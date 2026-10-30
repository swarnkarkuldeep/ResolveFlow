"""Turns ticket changes into SLA events and keeps the `ticket_sla` cache in step.

State is derived from the append-only `sla_events` stream, so any number can be reproduced by
hand and `ticket_sla` can always be rebuilt (see `recompute` / `backfill_events`).
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from resolveflow.context import ServiceCtx
from resolveflow.sla.defaults import DAYS, create_defaults
from resolveflow.sla.engine import Calendar, Pause, compute_due, threshold_instant

WARN_FRACTION = 0.75
DONE = ("resolved", "closed")


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass
class Config:
    enabled: bool
    business_hours_only: bool
    targets: dict[str, dict[str, int]]
    calendar: Calendar
    version: int

    @property
    def clock_calendar(self) -> Calendar | None:
        return self.calendar if self.business_hours_only else None


def _calendar(tz: str, weekly: dict[str, list[dict[str, str]]], holidays: list[date]) -> Calendar:
    def t(value: str) -> time:
        h, m = value.split(":")
        return time(int(h), int(m))

    return Calendar(
        ZoneInfo(tz),
        {
            i: [(t(r["start"]), t(r["end"])) for r in weekly.get(day, [])]
            for i, day in enumerate(DAYS)
        },
        frozenset(holidays),
    )


def load_config(ctx: ServiceCtx) -> Config:
    create_defaults(ctx.session, ctx.ws)  # no-op when present; heals legacy workspaces
    p = ctx.session.execute(
        text(
            "select enabled, business_hours_only, targets, version from sla_policies "
            "where workspace_id = :w"
        ),
        {"w": ctx.ws},
    ).one()
    c = ctx.session.execute(
        text("select timezone, weekly, holidays from business_calendars where workspace_id = :w"),
        {"w": ctx.ws},
    ).one()
    return Config(
        p.enabled,
        p.business_hours_only,
        p.targets,
        _calendar(c.timezone, c.weekly, c.holidays),
        p.version,
    )


def record_event(
    ctx: ServiceCtx,
    ticket_id: uuid.UUID,
    kind: str,
    detail: dict[str, Any] | None = None,
    at: datetime | None = None,
    dedupe_key: str | None = None,
) -> bool:
    """Append an event. False when `dedupe_key` was already recorded (idempotent callers)."""
    row = ctx.session.execute(
        text(
            "insert into sla_events (workspace_id, ticket_id, kind, detail, dedupe_key, at) "
            "values (:w, :t, :k, cast(:d as jsonb), :dk, :at) "
            "on conflict (workspace_id, dedupe_key) where dedupe_key is not null do nothing "
            "returning id"
        ),
        {
            "w": ctx.ws,
            "t": ticket_id,
            "k": kind,
            "d": json.dumps(detail) if detail is not None else None,
            "dk": dedupe_key,
            "at": at or utcnow(),
        },
    ).first()
    return row is not None


@dataclass
class Derived:
    start_at: datetime
    res_start: datetime
    pauses: list[Pause]
    fr_met_at: datetime | None
    res_met_at: datetime | None


def derive(events: list[Any], created_at: datetime) -> Derived:
    start_at = next((e.at for e in events if e.kind == "started"), created_at)
    res_start = start_at
    pauses: list[Pause] = []
    open_pause: datetime | None = None
    fr_met_at: datetime | None = None
    res_met_at: datetime | None = None
    for e in events:
        if e.kind == "paused" and open_pause is None:
            open_pause = e.at
        elif e.kind == "resumed" and open_pause is not None:
            pauses.append((open_pause, e.at))
            open_pause = None
        elif e.kind == "first_response" and fr_met_at is None:
            fr_met_at = e.at
        elif e.kind == "resolved":
            res_met_at = e.at
        elif e.kind == "reopened":
            res_met_at = None
            res_start = e.at
    if open_pause is not None:
        pauses.append((open_pause, None))
    return Derived(start_at, res_start, pauses, fr_met_at, res_met_at)


@dataclass
class Computed:
    cfg: Config
    d: Derived
    priority: str
    fr_target: int | None
    res_target: int | None
    fr_due: datetime | None
    res_due: datetime | None
    fr_warn: datetime | None
    res_warn: datetime | None
    paused_at: datetime | None


def compute(ctx: ServiceCtx, ticket_id: uuid.UUID) -> Computed:
    """Pure derivation of a ticket's clocks from its events and the workspace policy."""
    ticket = ctx.session.execute(
        text("select priority, created_at from tickets where id = :t and workspace_id = :w"),
        {"t": ticket_id, "w": ctx.ws},
    ).one()
    cfg = load_config(ctx)
    events = ctx.session.execute(
        text("select kind, at from sla_events where ticket_id = :t order by at, id"),
        {"t": ticket_id},
    ).all()
    d = derive(list(events), ticket.created_at)
    target = cfg.targets.get(ticket.priority) if cfg.enabled else None
    fr_target = target["first_response_minutes"] if target else None
    res_target = target["resolution_minutes"] if target else None
    cal = cfg.clock_calendar
    paused_at = d.pauses[-1][0] if d.pauses and d.pauses[-1][1] is None else None
    return Computed(
        cfg=cfg,
        d=d,
        priority=ticket.priority,
        fr_target=fr_target,
        res_target=res_target,
        fr_due=compute_due(d.start_at, fr_target, cal, d.pauses) if fr_target else None,
        res_due=compute_due(d.res_start, res_target, cal, d.pauses) if res_target else None,
        fr_warn=threshold_instant(d.start_at, fr_target, WARN_FRACTION, cal, d.pauses)
        if fr_target
        else None,
        res_warn=threshold_instant(d.res_start, res_target, WARN_FRACTION, cal, d.pauses)
        if res_target
        else None,
        paused_at=paused_at,
    )


def recompute(ctx: ServiceCtx, ticket_id: uuid.UUID, now: datetime | None = None) -> None:
    """Rebuild this ticket's `ticket_sla` row from its events (idempotent)."""
    now = now or utcnow()
    c = compute(ctx, ticket_id)
    d = c.d
    flags = ctx.session.execute(
        text(
            "select fr_warned_at, fr_breached_at, res_warned_at, res_breached_at "
            "from ticket_sla where ticket_id = :t"
        ),
        {"t": ticket_id},
    ).first()

    candidates: list[datetime | None] = []
    if c.paused_at is None:
        if c.fr_target and d.fr_met_at is None:
            if not (flags and flags.fr_warned_at):
                candidates.append(c.fr_warn)
            if not (flags and flags.fr_breached_at):
                candidates.append(c.fr_due)
        if c.res_target and d.res_met_at is None:
            if not (flags and flags.res_warned_at):
                candidates.append(c.res_warn)
            if not (flags and flags.res_breached_at):
                candidates.append(c.res_due)
    upcoming = [x for x in candidates if x is not None]

    ctx.session.execute(
        text(
            "insert into ticket_sla (ticket_id, workspace_id, policy_version, start_at, fr_target_min, "
            "res_target_min, fr_due_at, res_due_at, fr_met_at, res_met_at, paused_at, next_check_at, "
            "updated_at) values (:t, :w, :v, :s, :frt, :rst, :frd, :rsd, :frm, :rsm, :p, :n, :now) "
            "on conflict (ticket_id) do update set policy_version = excluded.policy_version, "
            "start_at = excluded.start_at, fr_target_min = excluded.fr_target_min, "
            "res_target_min = excluded.res_target_min, fr_due_at = excluded.fr_due_at, "
            "res_due_at = excluded.res_due_at, fr_met_at = excluded.fr_met_at, "
            "res_met_at = excluded.res_met_at, paused_at = excluded.paused_at, "
            "next_check_at = excluded.next_check_at, updated_at = excluded.updated_at"
        ),
        {
            "t": ticket_id,
            "w": ctx.ws,
            "v": c.cfg.version,
            "s": d.start_at,
            "frt": c.fr_target,
            "rst": c.res_target,
            "frd": c.fr_due,
            "rsd": c.res_due,
            "frm": d.fr_met_at,
            "rsm": d.res_met_at,
            "p": c.paused_at,
            "n": min(upcoming) if upcoming else None,
            "now": now,
        },
    )


# --- hooks called by the ticket services, inside their transactions -------------------------


def on_created(ctx: ServiceCtx, ticket_id: uuid.UUID) -> None:
    now = utcnow()
    record_event(ctx, ticket_id, "started", at=now)
    recompute(ctx, ticket_id, now)


def on_status_changed(ctx: ServiceCtx, ticket_id: uuid.UUID, old: str, new: str) -> None:
    if old == new:
        return
    now = utcnow()
    if old == "pending":
        record_event(ctx, ticket_id, "resumed", at=now)
    if new == "pending":
        record_event(ctx, ticket_id, "paused", at=now)
    if new in DONE and old not in DONE:
        record_event(ctx, ticket_id, "resolved", at=now)
    if old in DONE and new not in DONE:
        record_event(ctx, ticket_id, "reopened", at=now)
    recompute(ctx, ticket_id, now)


def on_priority_changed(ctx: ServiceCtx, ticket_id: uuid.UUID, old: str, new: str) -> None:
    if old == new:
        return
    now = utcnow()
    record_event(ctx, ticket_id, "priority_changed", {"from": old, "to": new}, at=now)
    recompute(ctx, ticket_id, now)


def on_agent_reply(ctx: ServiceCtx, ticket_id: uuid.UUID) -> None:
    now = utcnow()
    already = ctx.session.execute(
        text("select 1 from sla_events where ticket_id = :t and kind = 'first_response' limit 1"),
        {"t": ticket_id},
    ).first()
    if not already:
        record_event(ctx, ticket_id, "first_response", at=now)
    recompute(ctx, ticket_id, now)


def backfill_events(ctx: ServiceCtx, ticket_id: uuid.UUID) -> None:
    """Reconstruct the event stream for a ticket that predates SLA tracking (no-op if it has one)."""
    if ctx.session.execute(
        text("select 1 from sla_events where ticket_id = :t limit 1"), {"t": ticket_id}
    ).first():
        recompute(ctx, ticket_id)
        return
    t = ctx.session.execute(
        text(
            "select status, created_at, last_activity_at from tickets where id = :t and workspace_id = :w"
        ),
        {"t": ticket_id, "w": ctx.ws},
    ).one()
    record_event(ctx, ticket_id, "started", at=t.created_at)
    outbound = ctx.session.execute(
        text(
            "select min(created_at) as first, max(created_at) as last from messages "
            "where ticket_id = :t and direction = 'outbound' and kind = 'public'"
        ),
        {"t": ticket_id},
    ).one()
    if outbound.first:
        record_event(ctx, ticket_id, "first_response", at=outbound.first)
    if t.status in DONE:
        record_event(ctx, ticket_id, "resolved", at=t.last_activity_at)
    elif t.status == "pending":
        record_event(ctx, ticket_id, "paused", at=outbound.last or t.last_activity_at)
    recompute(ctx, ticket_id)

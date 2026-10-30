"""Restart-safe escalation sweep.

PostgreSQL holds every deadline and every escalation state; nothing is scheduled per ticket in a
queue. A sweep selects whatever is due with FOR UPDATE SKIP LOCKED, so concurrent sweepers never
touch the same ticket, records threshold events under a unique dedupe key, and always advances
`next_check_at`. After any downtime the next sweep simply finds the overdue rows and catches up.

Robustness rules (from review):
* each ticket runs in its own SAVEPOINT: one bad ticket is parked (retried in an hour) and logged,
  it can never stop the rest of the batch or other workspaces; a hard kill still rolls the whole
  batch back because nothing is committed until the batch ends;
* rows are locked `tickets` first (together with `ticket_sla`), the same order ticket writes use,
  so sweeps and user actions cannot deadlock;
* every phase loops until nothing is left or a time budget is used up.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from resolveflow import audit
from resolveflow.context import SystemContext
from resolveflow.rules import executor as rules_exec
from resolveflow.sla import service

log = logging.getLogger(__name__)

METRICS = (("first_response", "fr"), ("resolution", "res"))
PARK_FOR = timedelta(hours=1)


@dataclass
class SweepResult:
    thresholds: int = 0
    recomputed: int = 0
    backfilled: int = 0


def _process_ticket(ctx: SystemContext, ticket: Any, now: datetime) -> int:
    """Record every unrecorded threshold that has passed for one ticket, then reschedule it."""
    c = service.compute(ctx, ticket.ticket_id)
    recorded = 0
    for metric, prefix in METRICS:
        if getattr(c.d, f"{prefix}_met_at") is not None or c.paused_at is not None:
            continue
        due = getattr(c, f"{prefix}_due")
        target = getattr(c, f"{prefix}_target")
        if due is None or target is None:
            continue
        for level, instant, flag in (
            ("warning", getattr(c, f"{prefix}_warn"), f"{prefix}_warned_at"),
            ("breach", due, f"{prefix}_breached_at"),
        ):
            if instant is None or instant > now or getattr(ticket, flag) is not None:
                continue
            detail = {
                "metric": metric,
                "level": level,
                "due_at": due.isoformat(),
                "target_minutes": target,
            }
            key = f"{ticket.ticket_id}:{metric}:{level}:{due.isoformat()}"
            if service.record_event(
                ctx, ticket.ticket_id, "threshold", detail, at=instant, dedupe_key=key
            ):
                recorded += 1
                rules_exec.run_event(
                    ctx,
                    ticket.ticket_id,
                    "sla.threshold",
                    "warning" if level == "warning" else "breach",
                )
                audit.record(
                    ctx.session,
                    workspace_id=ctx.ws,
                    actor_type="system",
                    actor_id=None,
                    action="sla.warning" if level == "warning" else "sla.breached",
                    entity_type="ticket",
                    entity_id=ticket.ticket_id,
                    after={"metric": metric, "due_at": due.isoformat(), "target_minutes": target},
                )
            ctx.session.execute(
                text(f"update ticket_sla set {flag} = :at where ticket_id = :t"),  # noqa: S608 - fixed column names
                {"at": instant, "t": ticket.ticket_id},
            )
            setattr(ticket, flag, instant)
    service.recompute(ctx, ticket.ticket_id, now)
    return recorded


class _Row:
    """Mutable copy of the flag columns so a ticket's own earlier threshold is seen in-loop."""

    def __init__(self, row: Any) -> None:
        self.__dict__.update(row._mapping)


def _ctx(session: Session, workspace_id: uuid.UUID) -> SystemContext:
    session.execute(
        text("select set_config('app.workspace_id', :w, true)"), {"w": str(workspace_id)}
    )
    return SystemContext(session, workspace_id)


def _expired(deadline: float) -> bool:
    return time.monotonic() >= deadline


def _phase_due(
    engine: Engine, now: datetime, batch: int, ws: uuid.UUID | None, deadline: float
) -> int:
    """(a) tickets with a threshold that has passed."""
    total = 0
    while not _expired(deadline):
        with Session(engine) as s, s.begin():
            due = s.execute(
                text(
                    "select ts.ticket_id, ts.workspace_id, ts.fr_warned_at, ts.fr_breached_at, "
                    "ts.res_warned_at, ts.res_breached_at from ticket_sla ts "
                    "join tickets t on t.id = ts.ticket_id "
                    "where ts.next_check_at <= :now "
                    "and (cast(:ws as uuid) is null or ts.workspace_id = cast(:ws as uuid)) "
                    "order by ts.next_check_at limit :b for update of t, ts skip locked"
                ),
                {"now": now, "b": batch, "ws": ws},
            ).all()
            if not due:
                break
            for row in due:
                try:
                    with s.begin_nested():
                        total += _process_ticket(_ctx(s, row.workspace_id), _Row(row), now)
                except Exception:
                    log.exception("sla sweep failed for ticket %s; parking it", row.ticket_id)
                    s.execute(
                        text("update ticket_sla set next_check_at = :later where ticket_id = :t"),
                        {"later": now + PARK_FOR, "t": row.ticket_id},
                    )
        if len(due) < batch:
            break
    return total


def _phase_stale(
    engine: Engine, now: datetime, batch: int, ws: uuid.UUID | None, deadline: float
) -> int:
    """(b) tickets computed under an older policy/calendar version."""
    recomputed = 0
    with Session(engine) as s, s.begin():  # finished tickets just adopt the new version (set-based)
        s.execute(
            text(
                "update ticket_sla ts set policy_version = p.version "
                "from sla_policies p, tickets t where p.workspace_id = ts.workspace_id "
                "and t.id = ts.ticket_id and t.status in ('resolved', 'closed') "
                "and ts.policy_version <> p.version "
                "and (cast(:ws as uuid) is null or ts.workspace_id = cast(:ws as uuid))"
            ),
            {"ws": ws},
        )
    while not _expired(deadline):
        with Session(engine) as s, s.begin():
            stale = s.execute(
                text(
                    "select ts.ticket_id, ts.workspace_id, p.version from ticket_sla ts "
                    "join sla_policies p on p.workspace_id = ts.workspace_id "
                    "join tickets t on t.id = ts.ticket_id "
                    "where ts.policy_version <> p.version and t.status not in ('resolved', 'closed') "
                    "and (cast(:ws as uuid) is null or ts.workspace_id = cast(:ws as uuid)) "
                    "order by ts.ticket_id limit :b for update of t, ts skip locked"
                ),
                {"b": batch, "ws": ws},
            ).all()
            if not stale:
                break
            for row in stale:
                ctx = _ctx(s, row.workspace_id)
                try:
                    with s.begin_nested():
                        service.record_event(
                            ctx,
                            row.ticket_id,
                            "policy_changed",
                            {"version": row.version},
                            at=now,
                            dedupe_key=f"{row.ticket_id}:policy:{row.version}",
                        )
                        service.recompute(ctx, row.ticket_id, now)
                    recomputed += 1
                except Exception:
                    log.exception("sla recompute failed for ticket %s; parking it", row.ticket_id)
                    s.execute(
                        text(
                            "update ticket_sla set policy_version = :v, next_check_at = :later "
                            "where ticket_id = :t"
                        ),
                        {"v": row.version, "later": now + PARK_FOR, "t": row.ticket_id},
                    )
        if len(stale) < batch:
            break
    return recomputed


def _phase_missing(
    engine: Engine, now: datetime, batch: int, ws: uuid.UUID | None, deadline: float
) -> int:
    """(c) tickets that never got a clock (created before SLA tracking, or lost); open ones first."""
    backfilled = 0
    skipped: set[uuid.UUID] = set()
    while not _expired(deadline):
        with Session(engine) as s, s.begin():
            missing = s.execute(
                text(
                    "select t.id, t.workspace_id from tickets t "
                    "left join ticket_sla ts on ts.ticket_id = t.id "
                    "where ts.ticket_id is null and t.merged_into_id is null "
                    "and (cast(:ws as uuid) is null or t.workspace_id = cast(:ws as uuid)) "
                    "and t.id <> all(cast(:skip as uuid[])) "
                    "order by (t.status in ('resolved', 'closed')), t.created_at "
                    "limit :b for update of t skip locked"
                ),
                {"b": batch, "ws": ws, "skip": list(skipped)},
            ).all()
            if not missing:
                break
            for row in missing:
                try:
                    with s.begin_nested():
                        service.backfill_events(_ctx(s, row.workspace_id), row.id)
                    backfilled += 1
                except Exception:
                    log.exception("sla backfill failed for ticket %s", row.id)
                    skipped.add(row.id)
        if len(missing) < batch:
            break
    return backfilled


def sweep(
    engine: Engine,
    now: datetime | None = None,
    batch: int = 200,
    workspace_id: uuid.UUID | None = None,
    time_budget_s: float = 30.0,
) -> SweepResult:
    now = now or service.utcnow()
    deadline = time.monotonic() + time_budget_s
    result = SweepResult()
    result.thresholds += _phase_due(engine, now, batch, workspace_id, deadline)
    result.recomputed = _phase_stale(engine, now, batch, workspace_id, deadline)
    result.backfilled = _phase_missing(engine, now, batch, workspace_id, deadline)
    if result.recomputed or result.backfilled:
        # Recomputed or backfilled tickets may already be past a threshold: handle them this run.
        result.thresholds += _phase_due(engine, now, batch, workspace_id, deadline)
    return result

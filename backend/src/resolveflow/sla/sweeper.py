"""Restart-safe escalation sweep.

PostgreSQL holds every deadline and every escalation state; nothing is scheduled per ticket in a
queue. A sweep selects whatever is due with FOR UPDATE SKIP LOCKED, so concurrent sweepers never
touch the same ticket, records threshold events under a unique dedupe key, and always advances
`next_check_at`. After any downtime the next sweep simply finds the overdue rows and catches up.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from resolveflow import audit
from resolveflow.context import SystemContext
from resolveflow.sla import service

METRICS = (("first_response", "fr"), ("resolution", "res"))


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


def sweep(
    engine: Engine,
    now: datetime | None = None,
    batch: int = 200,
    workspace_id: uuid.UUID | None = None,
) -> SweepResult:
    now = now or service.utcnow()
    result = SweepResult()

    # (a) tickets with a threshold due
    while True:
        with Session(engine) as s, s.begin():
            due = s.execute(
                text(
                    "select ticket_id, workspace_id, fr_warned_at, fr_breached_at, res_warned_at, "
                    "res_breached_at from ticket_sla where next_check_at <= :now "
                    "and (cast(:ws as uuid) is null or workspace_id = cast(:ws as uuid)) "
                    "order by next_check_at limit :b for update skip locked"
                ),
                {"now": now, "b": batch, "ws": workspace_id},
            ).all()
            if not due:
                break
            for row in due:
                result.thresholds += _process_ticket(_ctx(s, row.workspace_id), _Row(row), now)
        if len(due) < batch:
            break

    # (b) tickets computed under an older policy/calendar version
    with Session(engine) as s, s.begin():
        stale = s.execute(
            text(
                "select ts.ticket_id, ts.workspace_id, p.version from ticket_sla ts "
                "join sla_policies p on p.workspace_id = ts.workspace_id "
                "where ts.policy_version <> p.version "
                "and (cast(:ws as uuid) is null or ts.workspace_id = cast(:ws as uuid)) "
                "order by ts.ticket_id limit :b for update of ts skip locked"
            ),
            {"b": batch, "ws": workspace_id},
        ).all()
        for row in stale:
            ctx = _ctx(s, row.workspace_id)
            service.record_event(
                ctx,
                row.ticket_id,
                "policy_changed",
                {"version": row.version},
                at=now,
                dedupe_key=f"{row.ticket_id}:policy:{row.version}",
            )
            service.recompute(ctx, row.ticket_id, now)
            result.recomputed += 1

    # (c) tickets that never got a clock (created before SLA tracking, or lost)
    with Session(engine) as s, s.begin():
        missing = s.execute(
            text(
                "select t.id, t.workspace_id from tickets t "
                "left join ticket_sla ts on ts.ticket_id = t.id "
                "where ts.ticket_id is null and t.merged_into_id is null "
                "and (cast(:ws as uuid) is null or t.workspace_id = cast(:ws as uuid)) "
                "order by t.created_at limit :b for update of t skip locked"
            ),
            {"b": batch, "ws": workspace_id},
        ).all()
        for row in missing:
            service.backfill_events(_ctx(s, row.workspace_id), row.id)
            result.backfilled += 1

    # Backfilled or recomputed tickets may already be past a threshold: process them in this run.
    if result.recomputed or result.backfilled:
        follow_up = sweep_due_only(engine, now, batch, workspace_id)
        result.thresholds += follow_up
    return result


def sweep_due_only(
    engine: Engine, now: datetime, batch: int, workspace_id: uuid.UUID | None = None
) -> int:
    total = 0
    while True:
        with Session(engine) as s, s.begin():
            due = s.execute(
                text(
                    "select ticket_id, workspace_id, fr_warned_at, fr_breached_at, res_warned_at, "
                    "res_breached_at from ticket_sla where next_check_at <= :now "
                    "and (cast(:ws as uuid) is null or workspace_id = cast(:ws as uuid)) "
                    "order by next_check_at limit :b for update skip locked"
                ),
                {"now": now, "b": batch, "ws": workspace_id},
            ).all()
            if not due:
                return total
            for row in due:
                total += _process_ticket(_ctx(s, row.workspace_id), _Row(row), now)
        if len(due) < batch:
            return total

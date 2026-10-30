"""Configurable data retention: old finished tickets are redacted, not just hidden.

A resolved or closed ticket untouched for `retention_days` loses its message text, subject and
notifications; a customer whose tickets are all redacted loses their name and email address. The
ticket shell (number, dates, status, priority, SLA outcome) stays so analytics and numbering keep
working. The append-only audit log is not rewritten.
"""

import uuid
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from resolveflow import audit
from resolveflow.context import ServiceCtx, SystemContext

REMOVED = "[Removed by the retention policy]"

_ELIGIBLE = (
    "from tickets where workspace_id = :w and redacted_at is null "
    "and status in ('resolved', 'closed') "
    "and last_activity_at < now() - make_interval(days => :d)"
)


def get_policy(ctx: ServiceCtx) -> dict[str, Any]:
    days = ctx.session.execute(
        text("select retention_days from workspaces where id = :w"), {"w": ctx.ws}
    ).scalar_one()
    eligible = 0
    if days:
        eligible = ctx.session.execute(
            text("select count(*) " + _ELIGIBLE), {"w": ctx.ws, "d": days}
        ).scalar_one()
    return {"retention_days": days, "eligible_tickets": int(eligible)}


def set_policy(ctx: ServiceCtx, days: int | None) -> dict[str, Any]:
    before = ctx.session.execute(
        text("select retention_days from workspaces where id = :w"), {"w": ctx.ws}
    ).scalar_one()
    ctx.session.execute(
        text("update workspaces set retention_days = :d where id = :w"), {"d": days, "w": ctx.ws}
    )
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type=ctx.actor_type,
        actor_id=ctx.actor_id,
        action="retention.policy_changed",
        entity_type="workspace",
        entity_id=ctx.ws,
        before={"retention_days": before},
        after={"retention_days": days},
        request_id=ctx.request_id,
    )
    return get_policy(ctx)


def apply(ctx: ServiceCtx) -> dict[str, int]:
    """Redact everything past the workspace's retention window. Idempotent."""
    s = ctx.session
    days = s.execute(
        text("select retention_days from workspaces where id = :w"), {"w": ctx.ws}
    ).scalar_one()
    if not days:
        return {"tickets": 0, "customers": 0}
    ids = [
        r.id
        for r in s.execute(text("select id " + _ELIGIBLE + " for update"), {"w": ctx.ws, "d": days})
    ]
    if not ids:
        return {"tickets": 0, "customers": 0}
    s.execute(
        text(
            "update messages set body = :r, message_id = null, in_reply_to = null "
            "where workspace_id = :w and ticket_id = any(:t)"
        ),
        {"r": REMOVED, "w": ctx.ws, "t": ids},
    )
    s.execute(
        text(
            "update tickets set subject = 'Ticket #' || number || ' (content removed)', "
            "redacted_at = now(), possible_duplicate_of = null "
            "where workspace_id = :w and id = any(:t)"
        ),
        {"w": ctx.ws, "t": ids},
    )
    s.execute(
        text("delete from notifications where workspace_id = :w and ticket_id = any(:t)"),
        {"w": ctx.ws, "t": ids},
    )
    customers = s.execute(
        text(
            "update customers c set email = 'removed-' || c.id || '@redacted.invalid', name = null "
            "where c.workspace_id = :w and c.email not like 'removed-%@redacted.invalid' "
            "and exists (select 1 from tickets t where t.requester_id = c.id "
            "and t.workspace_id = c.workspace_id) "
            "and not exists (select 1 from tickets t where t.requester_id = c.id "
            "and t.workspace_id = c.workspace_id and t.redacted_at is null) returning c.id"
        ),
        {"w": ctx.ws},
    ).all()
    audit.record(
        s,
        workspace_id=ctx.ws,
        actor_type=ctx.actor_type,
        actor_id=ctx.actor_id,
        action="retention.applied",
        entity_type="workspace",
        entity_id=ctx.ws,
        after={"tickets": len(ids), "customers": len(customers), "retention_days": days},
        request_id=ctx.request_id,
    )
    return {"tickets": len(ids), "customers": len(customers)}


def apply_all(engine: Engine) -> int:
    """Hourly job: every workspace with a policy. Cheap when nothing is due."""
    with Session(engine) as s, s.begin():
        workspaces: list[uuid.UUID] = [
            r.id
            for r in s.execute(text("select id from workspaces where retention_days is not null"))
        ]
    done = 0
    for ws in workspaces:
        with Session(engine) as s, s.begin():
            done += apply(SystemContext(s, ws))["tickets"]
    return done

"""Notification intents written by `notify` / `escalate` actions (delivery and display come in M4)."""

import uuid
from typing import Any

from sqlalchemy import text

from resolveflow.context import ServiceCtx
from resolveflow.errors import err


def recipients(ctx: ServiceCtx, ticket_id: uuid.UUID, params: dict[str, Any]) -> list[uuid.UUID]:
    target = params.get("target")
    s = ctx.session
    if target == "owners_admins":
        rows = s.execute(
            text(
                "select user_id from memberships where workspace_id = :w and active and role in ('owner', 'admin')"
            ),
            {"w": ctx.ws},
        )
    elif target == "assignee":
        assignee = s.execute(
            text("select assignee_id from tickets where id = :t and workspace_id = :w"),
            {"t": ticket_id, "w": ctx.ws},
        ).scalar()
        if assignee is None:
            raise err(422, "no_assignee", "The ticket has no assignee to notify.")
        rows = s.execute(
            text(
                "select user_id from memberships where workspace_id = :w and active and user_id = :u"
            ),
            {"w": ctx.ws, "u": assignee},
        )
    elif target == "user":
        rows = s.execute(
            text(
                "select user_id from memberships where workspace_id = :w and active and user_id = :u"
            ),
            {"w": ctx.ws, "u": uuid.UUID(params["user_id"])},
        )
    elif target == "team":
        rows = s.execute(
            text(
                "select tm.user_id from team_members tm join memberships m on m.user_id = tm.user_id "
                "and m.workspace_id = tm.workspace_id where tm.team_id = :t and tm.workspace_id = :w and m.active"
            ),
            {"t": uuid.UUID(params["team_id"]), "w": ctx.ws},
        )
    else:
        raise err(422, "bad_target", "Unknown notification target.")
    found = [r.user_id for r in rows]
    if not found:
        raise err(422, "nobody_to_notify", "There is nobody active to notify.")
    return found


def create_intents(
    ctx: ServiceCtx,
    ticket_id: uuid.UUID,
    params: dict[str, Any],
    rule_name: str,
    execution_id: uuid.UUID,
    escalated: bool,
) -> int:
    ticket = ctx.session.execute(
        text("select number, subject from tickets where id = :t and workspace_id = :w"),
        {"t": ticket_id, "w": ctx.ws},
    ).one()
    message = params.get("message")
    title = (
        f"Escalated: ticket #{ticket.number}"
        if escalated
        else f"{rule_name}: ticket #{ticket.number}"
    )
    body = f"{message} — {ticket.subject}" if message else ticket.subject
    created = 0
    for user_id in recipients(ctx, ticket_id, params):
        row = ctx.session.execute(
            text(
                "insert into notifications (workspace_id, user_id, kind, ticket_id, title, body, dedupe_key) "
                "values (:w, :u, :k, :t, :ti, :b, :d) on conflict (workspace_id, dedupe_key) "
                "where dedupe_key is not null do nothing returning id"
            ),
            {
                "w": ctx.ws,
                "u": user_id,
                "k": "escalation" if escalated else "rule",
                "t": ticket_id,
                "ti": title[:200],
                "b": body[:500],
                "d": f"exec:{execution_id}:{user_id}:{params.get('target')}",
            },
        ).first()
        created += 1 if row else 0
    return created

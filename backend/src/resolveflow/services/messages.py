import uuid
from typing import Any

from sqlalchemy import text

from resolveflow import audit
from resolveflow.config import get_settings
from resolveflow.context import ServiceCtx
from resolveflow.errors import err
from resolveflow.rules import executor as rules_exec
from resolveflow.sla import service as sla


def get_message(ctx: ServiceCtx, message_id: uuid.UUID) -> dict[str, Any]:
    m = ctx.session.execute(
        text(
            "select m.id, m.kind, m.direction, m.body, m.created_at, m.delivery_status, "
            "u.name as user_name, c.name as cust_name, c.email as cust_email "
            "from messages m left join users u on u.id = m.author_user_id "
            "left join customers c on c.id = m.author_customer_id "
            "where m.workspace_id = :w and m.id = :i"
        ),
        {"w": ctx.ws, "i": message_id},
    ).one()
    return {
        "id": str(m.id),
        "kind": m.kind,
        "direction": m.direction,
        "body": m.body,
        "created_at": m.created_at.isoformat(),
        "delivery_status": m.delivery_status,
        "author": (
            {"type": "user", "name": m.user_name}
            if m.user_name
            else {"type": "customer", "name": m.cust_name or m.cust_email}
        ),
    }


def add_message(
    ctx: ServiceCtx, ticket_id: uuid.UUID, *, body: str, kind: str, set_pending: bool = False
) -> dict[str, Any]:
    ticket = ctx.session.execute(
        text("select status from tickets where workspace_id = :w and id = :i for update"),
        {"w": ctx.ws, "i": ticket_id},
    ).first()
    if not ticket:
        raise err(404, "not_found", "Ticket not found.")
    if kind == "public":
        last_inbound = ctx.session.execute(
            text(
                "select message_id from messages where ticket_id = :t and direction = 'inbound' "
                "and message_id is not null order by created_at desc, id desc limit 1"
            ),
            {"t": ticket_id},
        ).scalar()
        message_id = f"<{uuid.uuid4().hex}@{get_settings().inbound_domain}>"
        message_pk = ctx.session.execute(
            text(
                "insert into messages (workspace_id, ticket_id, kind, direction, author_user_id, "
                "body, message_id, in_reply_to, delivery_status) "
                "values (:w, :t, 'public', 'outbound', :u, :b, :m, :r, 'queued') returning id"
            ),
            {
                "w": ctx.ws,
                "t": ticket_id,
                "u": ctx.actor_id,
                "b": body,
                "m": message_id,
                "r": last_inbound,
            },
        ).scalar_one()
    else:
        message_pk = ctx.session.execute(
            text(
                "insert into messages (workspace_id, ticket_id, kind, direction, author_user_id, "
                "body) values (:w, :t, 'note', 'internal', :u, :b) returning id"
            ),
            {"w": ctx.ws, "t": ticket_id, "u": ctx.actor_id, "b": body},
        ).scalar_one()

    new_status = ticket.status
    if new_status == "new":
        new_status = "open"
    if kind == "public" and set_pending and new_status in ("new", "open"):
        new_status = "pending"
    ctx.session.execute(
        text(
            "update tickets set status = :s, last_activity_at = now() "
            "where id = :i and workspace_id = :w"
        ),
        {"s": new_status, "i": ticket_id, "w": ctx.ws},
    )
    sla.on_status_changed(ctx, ticket_id, ticket.status, new_status)
    rules_exec.on_status_changed(ctx, ticket_id, ticket.status, new_status)
    if kind == "public":
        sla.on_agent_reply(ctx, ticket_id)
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type=ctx.actor_type,
        actor_id=ctx.actor_id,
        action="message.added",
        entity_type="ticket",
        entity_id=ticket_id,
        after={"kind": kind, "message_id": str(message_pk)},
        request_id=ctx.request_id,
    )
    return get_message(ctx, message_pk)

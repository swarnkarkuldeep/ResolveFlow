import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from resolveflow import audit
from resolveflow.context import SystemContext
from resolveflow.db import system_engine
from resolveflow.email.inbound import InboundMessage
from resolveflow.email.threading import match_ticket, parse_recipients
from resolveflow.rules import executor as rules_exec
from resolveflow.services import tickets as ticket_svc
from resolveflow.sla import service as sla

Status = Literal["created", "appended", "duplicate", "ignored"]


@dataclass
class IngestResult:
    status: Status
    ticket_id: uuid.UUID | None = None


def _body_with_footer(msg: InboundMessage) -> str:
    n = msg.attachments_dropped
    if not n:
        return msg.text
    noun = "attachment" if n == 1 else "attachments"
    return f"{msg.text}\n\n— {n} {noun} not stored."


def _resolve_workspace(s: Session, msg: InboundMessage) -> tuple[uuid.UUID, int | None] | None:
    for token, number in parse_recipients(msg.to_addresses):
        ws = s.execute(
            text("select id from workspaces where inbound_token = :t"), {"t": token}
        ).scalar()
        if ws:
            return ws, number
    return None


def _message_exists(s: Session, ws: uuid.UUID, message_id: str) -> bool:
    return bool(
        s.execute(
            text("select 1 from messages where workspace_id = :w and message_id = :m"),
            {"w": ws, "m": message_id},
        ).first()
    )


def ingest_inbound(msg: InboundMessage) -> IngestResult:
    """Create a ticket or append to one. Idempotent on (workspace, Message-ID).

    Runs as rf_system: the workspace is not known until the recipient address is resolved.
    """
    if "@" not in msg.from_email:
        return IngestResult("ignored")  # nobody to reply to
    try:
        with Session(system_engine()) as s, s.begin():
            resolved = _resolve_workspace(s, msg)
            if not resolved:
                return IngestResult("ignored")
            ws, plus_number = resolved
            s.execute(text("select set_config('app.workspace_id', :w, true)"), {"w": str(ws)})
            if _message_exists(s, ws, msg.message_id):
                return IngestResult("duplicate")
            ctx = SystemContext(s, ws)
            subject = (msg.subject or "(no subject)")[:300]
            ticket_id = match_ticket(s, ws, msg, plus_number)
            if ticket_id is None:
                created = ticket_svc.create_ticket(
                    ctx,
                    subject=subject,
                    body=_body_with_footer(msg),
                    requester_email=msg.from_email,
                    requester_name=msg.from_name,
                    channel="email",
                    message_id=msg.message_id,
                )
                return IngestResult("created", uuid.UUID(created["id"]))
            return _append(ctx, ticket_id, msg)
    except IntegrityError:
        # A concurrent delivery of the same Message-ID won the unique index; ours rolled back.
        with Session(system_engine()) as s, s.begin():
            resolved = _resolve_workspace(s, msg)
            if resolved and _message_exists(s, resolved[0], msg.message_id):
                return IngestResult("duplicate")
        raise


def _append(ctx: SystemContext, ticket_id: uuid.UUID, msg: InboundMessage) -> IngestResult:
    s = ctx.session
    row = s.execute(
        text("select merged_into_id from tickets where id = :i and workspace_id = :w for update"),
        {"i": ticket_id, "w": ctx.ws},
    ).first()
    if row and row.merged_into_id:
        ticket_id = row.merged_into_id  # replies to a merged ticket land on the surviving one
        s.execute(
            text("select 1 from tickets where id = :i and workspace_id = :w for update"),
            {"i": ticket_id, "w": ctx.ws},
        )
    customer_id = s.execute(
        text(
            "insert into customers (workspace_id, email, name) values (:w, :e, :n) "
            "on conflict (workspace_id, email) do update "
            "set name = coalesce(customers.name, excluded.name) returning id"
        ),
        {"w": ctx.ws, "e": msg.from_email, "n": msg.from_name},
    ).scalar_one()
    inserted = s.execute(
        text(
            "insert into messages (workspace_id, ticket_id, kind, direction, author_customer_id, "
            "body, message_id, in_reply_to) values (:w, :t, 'public', 'inbound', :c, :b, :m, :r) "
            "on conflict (workspace_id, message_id) where message_id is not null do nothing "
            "returning id"
        ),
        {
            "w": ctx.ws,
            "t": ticket_id,
            "c": customer_id,
            "b": _body_with_footer(msg),
            "m": msg.message_id,
            "r": msg.in_reply_to,
        },
    ).first()
    if not inserted:
        return IngestResult("duplicate")
    old_status = s.execute(
        text("select status from tickets where id = :t and workspace_id = :w for update"),
        {"t": ticket_id, "w": ctx.ws},
    ).scalar_one()
    s.execute(
        text(
            "update tickets set last_activity_at = now(), "
            "status = case when status in ('resolved', 'pending') then 'open' else status end "
            "where id = :t and workspace_id = :w"
        ),
        {"t": ticket_id, "w": ctx.ws},
    )
    new_status = "open" if old_status in ("resolved", "pending") else old_status
    sla.on_status_changed(ctx, ticket_id, old_status, new_status)
    rules_exec.on_status_changed(ctx, ticket_id, old_status, new_status)
    audit.record(
        s,
        workspace_id=ctx.ws,
        actor_type="system",
        actor_id=None,
        action="message.received",
        entity_type="ticket",
        entity_id=ticket_id,
        after={"from": msg.from_email, "message_id": msg.message_id},
    )
    rules_exec.run_event(ctx, ticket_id, "message.received")
    return IngestResult("appended", ticket_id)

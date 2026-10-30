import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator

from resolveflow.api.deps import RequestContext, require
from resolveflow.errors import err
from resolveflow.permissions import PERMS
from resolveflow.services import messages as msg_svc
from resolveflow.services import tickets as svc
from resolveflow.tasks.email import send_outbound_message
from resolveflow.types import EmailAddr

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

Status = Literal["new", "open", "pending", "resolved", "closed"]
Priority = Literal["low", "normal", "high", "urgent"]


class TicketIn(BaseModel):
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)
    requester_email: EmailAddr
    requester_name: str | None = Field(default=None, max_length=120)
    priority: Priority = "normal"


class TicketPatch(BaseModel):
    status: Status | None = None
    priority: Priority | None = None
    assignee_id: uuid.UUID | None = None
    tags: list[str] | None = Field(default=None, max_length=20)

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        cleaned = [t.strip() for t in v if t.strip()]
        if any(len(t) > 40 for t in cleaned):
            raise ValueError("Tags can be at most 40 characters.")
        return cleaned


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=20000)
    kind: Literal["public", "note"]
    set_pending: bool = False


class BulkIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    action: Literal["assign", "status", "priority", "add_tag"]
    value: str | None = None


class MergeIn(BaseModel):
    into_id: uuid.UUID


def _csv(value: str | None, allowed: tuple[str, ...], name: str) -> list[str] | None:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    bad = [p for p in parts if p not in allowed]
    if bad:
        raise err(422, f"bad_{name}", f"Unknown {name}: {', '.join(bad)}.")
    return parts


@router.get("/tickets")
def list_tickets(
    status: str | None = None,
    priority: str | None = None,
    assignee: str | None = None,
    tag: str | None = None,
    sla: Literal["at_risk", "breached"] | None = None,
    sort: Literal["activity", "created"] = "activity",
    order: Literal["asc", "desc"] = "desc",
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = None,
    ctx: RequestContext = Depends(require("ticket:read")),
) -> dict[str, Any]:
    return svc.list_tickets(
        ctx,
        me=ctx.user_id,
        statuses=_csv(status, svc.STATUSES, "status"),
        priorities=_csv(priority, svc.PRIORITIES, "priority"),
        assignee=assignee,
        tag=tag,
        sla=sla,
        sort=sort,
        order=order,
        limit=limit,
        cursor=cursor,
    )


@router.post("/tickets")
def create_ticket(
    body: TicketIn, ctx: RequestContext = Depends(require("ticket:create"))
) -> dict[str, Any]:
    out = svc.create_ticket(
        ctx,
        subject=body.subject.strip(),
        body=body.body,
        requester_email=body.requester_email,
        requester_name=body.requester_name,
        priority=body.priority,
        channel="manual",
    )
    ctx.commit()
    return out


@router.get("/tickets/{ticket_id}")
def get_ticket(
    ticket_id: uuid.UUID, ctx: RequestContext = Depends(require("ticket:read"))
) -> dict[str, Any]:
    return svc.get_ticket(ctx, ticket_id)


@router.patch("/tickets/{ticket_id}")
def patch_ticket(
    ticket_id: uuid.UUID, body: TicketPatch, ctx: RequestContext = Depends(require("ticket:update"))
) -> dict[str, Any]:
    fields = {k: getattr(body, k) for k in body.model_fields_set}
    if not fields:
        raise err(422, "empty_patch", "Provide at least one field to change.")
    if "assignee_id" in fields and "ticket:assign" not in PERMS.get(ctx.role or "", frozenset()):
        raise err(403, "forbidden", "You do not have permission to do that.")
    out = svc.update_ticket(ctx, ticket_id, fields)
    ctx.commit()
    return out


@router.get("/tickets/{ticket_id}/activity")
def activity(
    ticket_id: uuid.UUID, ctx: RequestContext = Depends(require("ticket:read"))
) -> list[dict[str, Any]]:
    return svc.ticket_activity(ctx, ticket_id)


@router.post("/tickets/{ticket_id}/messages")
def add_message(
    ticket_id: uuid.UUID, body: MessageIn, ctx: RequestContext = Depends(require("ticket:reply"))
) -> dict[str, Any]:
    out = msg_svc.add_message(
        ctx, ticket_id, body=body.body, kind=body.kind, set_pending=body.set_pending
    )
    ctx.commit()
    if body.kind == "public":
        try:
            send_outbound_message.delay(out["id"])
        except Exception:  # broker down: the row stays queued and the sweeper re-queues it
            log.warning("could not enqueue outbound email", exc_info=True)
    return out


@router.post("/tickets/bulk")
def bulk(body: BulkIn, ctx: RequestContext = Depends(require("ticket:bulk"))) -> dict[str, Any]:
    if body.action == "assign" and "ticket:assign" not in PERMS.get(ctx.role or "", frozenset()):
        raise err(403, "forbidden", "You do not have permission to do that.")
    out = svc.bulk_update(ctx, body.ids, action=body.action, value=body.value)
    ctx.commit()
    return out


@router.post("/tickets/{ticket_id}/merge")
def merge_ticket(
    ticket_id: uuid.UUID, body: MergeIn, ctx: RequestContext = Depends(require("ticket:merge"))
) -> dict[str, Any]:
    out = svc.merge(ctx, ticket_id, body.into_id)
    ctx.commit()
    return out

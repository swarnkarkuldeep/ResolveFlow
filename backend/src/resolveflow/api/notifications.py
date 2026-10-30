import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text

from resolveflow.api.deps import RequestContext, get_ctx
from resolveflow.errors import err
from resolveflow.notifications import service as svc

router = APIRouter(prefix="/api")

Kind = Literal["assigned", "customer_reply", "sla", "escalation", "rule"]


class PrefIn(BaseModel):
    kind: Kind
    in_app: bool
    email: bool


def _item(r: Any) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "kind": r.kind,
        "title": r.title,
        "body": r.body,
        "read": r.read_at is not None,
        "created_at": r.created_at.isoformat(),
        "ticket": {"id": str(r.ticket_id), "number": r.number} if r.ticket_id else None,
    }


@router.get("/notifications")
def list_notifications(
    unread: bool = False,
    limit: int = Query(30, ge=1, le=100),
    ctx: RequestContext = Depends(get_ctx),
) -> dict[str, Any]:
    rows = ctx.session.execute(
        text(
            "select n.id, n.kind, n.title, n.body, n.read_at, n.created_at, n.ticket_id, t.number "
            "from notifications n left join tickets t on t.id = n.ticket_id "
            "where n.workspace_id = :w and n.user_id = :u and n.in_app "
            "and (not :unread or n.read_at is null) "
            "order by n.created_at desc, n.id desc limit :lim"
        ),
        {"w": ctx.ws, "u": ctx.user_id, "unread": unread, "lim": limit},
    ).all()
    return {"items": [_item(r) for r in rows]}


@router.get("/notifications/unread-count")
def unread_count(ctx: RequestContext = Depends(get_ctx)) -> dict[str, int]:
    n = ctx.session.execute(
        text(
            "select count(*) from notifications where workspace_id = :w and user_id = :u "
            "and in_app and read_at is null"
        ),
        {"w": ctx.ws, "u": ctx.user_id},
    ).scalar_one()
    return {"count": int(n)}


@router.post("/notifications/read-all")
def read_all(ctx: RequestContext = Depends(get_ctx)) -> dict[str, bool]:
    ctx.session.execute(
        text(
            "update notifications set read_at = now() where workspace_id = :w and user_id = :u "
            "and in_app and read_at is null"
        ),
        {"w": ctx.ws, "u": ctx.user_id},
    )
    ctx.commit()
    return {"ok": True}


@router.post("/notifications/{notification_id}/read")
def mark_read(
    notification_id: uuid.UUID, ctx: RequestContext = Depends(get_ctx)
) -> dict[str, bool]:
    found = ctx.session.execute(
        text(
            "update notifications set read_at = coalesce(read_at, now()) "
            "where id = :i and workspace_id = :w and user_id = :u and in_app returning id"
        ),
        {"i": notification_id, "w": ctx.ws, "u": ctx.user_id},
    ).first()
    if not found:
        raise err(404, "not_found", "Notification not found.")
    ctx.commit()
    return {"ok": True}


@router.get("/notification-prefs")
def get_prefs(ctx: RequestContext = Depends(get_ctx)) -> list[dict[str, object]]:
    return svc.prefs_for(ctx, ctx.user_id)


@router.put("/notification-prefs")
def put_prefs(
    body: list[PrefIn], ctx: RequestContext = Depends(get_ctx)
) -> list[dict[str, object]]:
    svc.set_prefs(ctx, ctx.user_id, [b.model_dump() for b in body])
    ctx.commit()
    return svc.prefs_for(ctx, ctx.user_id)

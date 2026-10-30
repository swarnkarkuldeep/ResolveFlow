import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends
from sqlalchemy import text

from resolveflow import audit
from resolveflow.api.deps import RequestContext, require
from resolveflow.errors import err

router = APIRouter(prefix="/api")


@router.get("/notification-deliveries")
def list_deliveries(
    status: Literal["failing", "dead"] = "dead",
    ctx: RequestContext = Depends(require("notification:admin")),
) -> dict[str, Any]:
    rows = ctx.session.execute(
        text(
            "select n.id, n.title, n.kind, n.email_attempts, n.email_last_error, n.created_at, "
            "u.email, n.email_status "
            "from notifications n join users u on u.id = n.user_id "
            "where n.workspace_id = :w and "
            "((:dead and n.email_status = 'dead') or "
            "(not :dead and n.email_status = 'queued' and n.email_attempts > 0)) "
            "order by n.created_at desc limit 100"
        ),
        {"w": ctx.ws, "dead": status == "dead"},
    ).all()
    return {
        "items": [
            {
                "id": str(r.id),
                "title": r.title,
                "kind": r.kind,
                "recipient": r.email,
                "attempts": r.email_attempts,
                "error": r.email_last_error,
                "status": r.email_status,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/notification-deliveries/{notification_id}/retry")
def retry(
    notification_id: uuid.UUID, ctx: RequestContext = Depends(require("notification:admin"))
) -> dict[str, bool]:
    row = ctx.session.execute(
        text(
            "update notifications set email_status = 'queued', email_attempts = 0, "
            "email_next_at = now(), email_last_error = null "
            "where id = :i and workspace_id = :w and email_status = 'dead' returning id"
        ),
        {"i": notification_id, "w": ctx.ws},
    ).first()
    if not row:
        raise err(404, "not_found", "No failed email with that id.")
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type="user",
        actor_id=ctx.user_id,
        action="notification.email_retried",
        entity_type="notification",
        entity_id=notification_id,
        request_id=ctx.request_id,
    )
    ctx.commit()
    return {"ok": True}

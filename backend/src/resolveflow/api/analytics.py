import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text

from resolveflow.api.deps import RequestContext, require
from resolveflow.errors import err
from resolveflow.services import analytics as svc
from resolveflow.services import tickets as tk

router = APIRouter(prefix="/api")


@router.get("/analytics")
def analytics(
    days: int = 30, ctx: RequestContext = Depends(require("analytics:read"))
) -> dict[str, Any]:
    if days not in (7, 30, 90):
        raise err(422, "bad_range", "Choose 7, 30 or 90 days.")
    return svc.workspace_analytics(ctx, days)


@router.get("/customers/{customer_id}")
def customer_history(
    customer_id: uuid.UUID, ctx: RequestContext = Depends(require("ticket:read"))
) -> dict[str, Any]:
    c = ctx.session.execute(
        text(
            "select id, email, name, created_at from customers where id = :c and workspace_id = :w"
        ),
        {"c": customer_id, "w": ctx.ws},
    ).first()
    if not c:
        raise err(404, "not_found", "Customer not found.")
    rows = ctx.session.execute(
        text(
            tk._SELECT + " where t.workspace_id = :w and t.requester_id = :c "
            "order by t.created_at desc, t.id desc limit 200"
        ),
        {"w": ctx.ws, "c": customer_id},
    ).all()
    items = [tk._item(r) for r in rows]
    counts = ctx.session.execute(
        text(
            "select count(*) as total, count(*) filter (where status not in ('resolved', 'closed')) "
            "as open from tickets where workspace_id = :w and requester_id = :c"
        ),
        {"w": ctx.ws, "c": customer_id},
    ).one()
    return {
        "customer": {
            "id": str(c.id),
            "email": c.email,
            "name": c.name,
            "since": c.created_at.isoformat(),
        },
        "tickets": items,
        "stats": {
            "total": counts.total,
            "open": counts.open,
        },
    }

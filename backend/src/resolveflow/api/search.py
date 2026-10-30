from typing import Any

from fastapi import APIRouter, Depends, Query

from resolveflow.api.deps import RequestContext, require
from resolveflow.api.tickets import _csv
from resolveflow.services import search as svc
from resolveflow.services import tickets as tk

router = APIRouter(prefix="/api")


@router.get("/search")
def search(
    q: str = Query(max_length=500),
    status: str | None = None,
    priority: str | None = None,
    assignee: str | None = None,
    tag: str | None = None,
    limit: int = Query(25, ge=1, le=50),
    ctx: RequestContext = Depends(require("ticket:read")),
) -> dict[str, Any]:
    return {
        "items": svc.search_tickets(
            ctx,
            q,
            me=ctx.user_id,
            statuses=_csv(status, tk.STATUSES, "status"),
            priorities=_csv(priority, tk.PRIORITIES, "priority"),
            assignee=assignee,
            tag=tag,
            limit=limit,
        )
    }

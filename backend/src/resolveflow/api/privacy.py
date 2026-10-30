from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from resolveflow import retention
from resolveflow.api.deps import RequestContext, require

router = APIRouter(prefix="/api")


class PrivacyIn(BaseModel):
    retention_days: int | None = Field(default=None, ge=30, le=730)


@router.get("/settings/privacy")
def get_privacy(ctx: RequestContext = Depends(require("settings:read"))) -> dict[str, Any]:
    return retention.get_policy(ctx)


@router.put("/settings/privacy")
def put_privacy(
    body: PrivacyIn, ctx: RequestContext = Depends(require("settings:update"))
) -> dict[str, Any]:
    out = retention.set_policy(ctx, body.retention_days)
    ctx.commit()
    return out


@router.post("/settings/privacy/apply")
def apply_privacy(ctx: RequestContext = Depends(require("settings:update"))) -> dict[str, Any]:
    out = retention.apply(ctx)
    policy = retention.get_policy(ctx)
    ctx.commit()
    return {**out, **policy}

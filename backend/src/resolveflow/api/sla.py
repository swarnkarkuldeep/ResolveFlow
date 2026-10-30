from typing import Any

from fastapi import APIRouter, Depends

from resolveflow.api.deps import RequestContext, require
from resolveflow.sla.settings import SlaSettingsIn, read_settings, write_settings

router = APIRouter(prefix="/api")


@router.get("/settings/sla")
def get_sla_settings(ctx: RequestContext = Depends(require("settings:read"))) -> dict[str, Any]:
    out = read_settings(ctx)
    ctx.commit()  # read_settings heals a legacy workspace by inserting defaults
    return out


@router.put("/settings/sla")
def put_sla_settings(
    body: SlaSettingsIn, ctx: RequestContext = Depends(require("settings:update"))
) -> dict[str, Any]:
    out = write_settings(ctx, body)
    ctx.commit()
    return out

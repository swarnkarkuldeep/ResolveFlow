import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from resolveflow.api.deps import RequestContext, require
from resolveflow.rules import teams as svc

router = APIRouter(prefix="/api")


class TeamIn(BaseModel):
    name: str = Field(max_length=120)


class MembersIn(BaseModel):
    user_ids: list[uuid.UUID] = Field(max_length=100)


@router.get("/teams")
def list_teams(ctx: RequestContext = Depends(require("user:read"))) -> list[dict[str, Any]]:
    return svc.list_teams(ctx)


@router.post("/teams")
def create_team(
    body: TeamIn, ctx: RequestContext = Depends(require("team:manage"))
) -> dict[str, Any]:
    out = svc.create_team(ctx, body.name)
    ctx.commit()
    return out


@router.patch("/teams/{team_id}")
def rename_team(
    team_id: uuid.UUID, body: TeamIn, ctx: RequestContext = Depends(require("team:manage"))
) -> dict[str, Any]:
    out = svc.rename_team(ctx, team_id, body.name)
    ctx.commit()
    return out


@router.delete("/teams/{team_id}")
def delete_team(
    team_id: uuid.UUID, ctx: RequestContext = Depends(require("team:manage"))
) -> dict[str, str]:
    svc.delete_team(ctx, team_id)
    ctx.commit()
    return {"status": "ok"}


@router.put("/teams/{team_id}/members")
def set_members(
    team_id: uuid.UUID, body: MembersIn, ctx: RequestContext = Depends(require("team:manage"))
) -> dict[str, Any]:
    out = svc.set_members(ctx, team_id, body.user_ids)
    ctx.commit()
    return out

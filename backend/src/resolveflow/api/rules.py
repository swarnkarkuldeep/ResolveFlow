import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from resolveflow.api.deps import RequestContext, require
from resolveflow.rules import service as svc
from resolveflow.rules.schema import RuleDefinition

router = APIRouter(prefix="/api")


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    definition: RuleDefinition


class RuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    definition: RuleDefinition | None = None


class ActivateIn(BaseModel):
    version: int | None = Field(default=None, ge=1)


class ReorderIn(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=200)


@router.get("/rules")
def list_rules(ctx: RequestContext = Depends(require("rule:read"))) -> list[dict[str, Any]]:
    return svc.list_rules(ctx)


@router.post("/rules")
def create_rule(
    body: RuleIn, ctx: RequestContext = Depends(require("rule:manage"))
) -> dict[str, Any]:
    out = svc.create_rule(ctx, body.name, body.definition)
    ctx.commit()
    return out


@router.post("/rules/reorder")
def reorder(
    body: ReorderIn, ctx: RequestContext = Depends(require("rule:manage"))
) -> list[dict[str, Any]]:
    out = svc.reorder(ctx, body.ids)
    ctx.commit()
    return out


@router.get("/rules/{rule_id}")
def get_rule(
    rule_id: uuid.UUID, ctx: RequestContext = Depends(require("rule:read"))
) -> dict[str, Any]:
    return svc.get_rule(ctx, rule_id)


@router.put("/rules/{rule_id}")
def update_rule(
    rule_id: uuid.UUID, body: RuleUpdate, ctx: RequestContext = Depends(require("rule:manage"))
) -> dict[str, Any]:
    out = svc.update_rule(ctx, rule_id, body.name, body.definition)
    ctx.commit()
    return out


@router.post("/rules/{rule_id}/activate")
def activate(
    rule_id: uuid.UUID, body: ActivateIn, ctx: RequestContext = Depends(require("rule:manage"))
) -> dict[str, Any]:
    out = svc.activate(ctx, rule_id, body.version)
    ctx.commit()
    return out


@router.post("/rules/{rule_id}/archive")
def archive(
    rule_id: uuid.UUID, ctx: RequestContext = Depends(require("rule:manage"))
) -> dict[str, Any]:
    out = svc.set_archived(ctx, rule_id, True)
    ctx.commit()
    return out


@router.post("/rules/{rule_id}/restore")
def restore(
    rule_id: uuid.UUID, ctx: RequestContext = Depends(require("rule:manage"))
) -> dict[str, Any]:
    out = svc.set_archived(ctx, rule_id, False)
    ctx.commit()
    return out

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text

from resolveflow.api.auth import _set_cookie
from resolveflow.api.deps import RequestContext, require
from resolveflow.config import get_settings
from resolveflow.services import members as svc
from resolveflow.tasks.email import send_invitation
from resolveflow.types import EmailAddr

router = APIRouter(prefix="/api")

Role = Literal["owner", "admin", "agent", "viewer"]


class InviteIn(BaseModel):
    email: EmailAddr
    role: Role


class MemberPatch(BaseModel):
    role: Role | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def _something(self) -> "MemberPatch":
        if self.role is None and self.active is None:
            raise ValueError("Provide a role or an active flag.")
        return self


class AcceptIn(BaseModel):
    token: str = Field(max_length=200)
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=200)


@router.get("/members")
def members(ctx: RequestContext = Depends(require("user:read"))) -> list[dict[str, Any]]:
    return svc.list_members(ctx)


@router.patch("/members/{user_id}")
def patch_member(
    user_id: uuid.UUID, body: MemberPatch, ctx: RequestContext = Depends(require("user:manage"))
) -> dict[str, Any]:
    out = svc.update_member(ctx, user_id, body.role, body.active)
    ctx.commit()
    return out


@router.post("/invitations")
def invite(body: InviteIn, ctx: RequestContext = Depends(require("user:invite"))) -> dict[str, Any]:
    inv, raw = svc.create_invitation(ctx, body.email, body.role)
    workspace = ctx.session.execute(
        text("select name from workspaces where id = :w"), {"w": ctx.ws}
    ).scalar_one()
    ctx.commit()
    send_invitation.delay(body.email, workspace, ctx.user_name, raw)
    inv["link"] = f"{get_settings().public_base_url}/accept-invite?token={raw}"
    return inv


@router.get("/invitations")
def invitations(ctx: RequestContext = Depends(require("user:invite"))) -> list[dict[str, Any]]:
    return svc.list_invitations(ctx)


@router.delete("/invitations/{invitation_id}")
def revoke(
    invitation_id: uuid.UUID, ctx: RequestContext = Depends(require("user:invite"))
) -> dict[str, str]:
    svc.delete_invitation(ctx, invitation_id)
    ctx.commit()
    return {"status": "ok"}


@router.post("/auth/accept-invite")
def accept(body: AcceptIn, response: Response) -> dict[str, str]:
    s = svc.accept_invite(body.token, body.name.strip() or "Teammate", body.password)
    _set_cookie(response, s.raw_token)
    return {"csrf_token": s.csrf_token}

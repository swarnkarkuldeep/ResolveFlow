import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import text

from resolveflow.api.deps import COOKIE, RequestContext, get_ctx
from resolveflow.config import get_settings
from resolveflow.errors import err
from resolveflow.permissions import permissions_for
from resolveflow.services import auth as auth_service
from resolveflow.types import EmailAddr

router = APIRouter(prefix="/api")


class SignupIn(BaseModel):
    email: EmailAddr
    password: str = Field(min_length=10, max_length=200)
    name: str = Field(min_length=1, max_length=120)
    workspace_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: EmailAddr
    password: str = Field(max_length=200)


class SwitchIn(BaseModel):
    workspace_id: uuid.UUID


def _set_cookie(response: Response, raw: str) -> None:
    response.set_cookie(
        COOKIE,
        raw,
        max_age=auth_service.SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=get_settings().cookie_secure,
        path="/",
    )


def _me(ctx: RequestContext) -> dict[str, Any]:
    ws = ctx.session.execute(
        text(
            "select w.id, w.name, w.slug, m.role from memberships m "
            "join workspaces w on w.id = m.workspace_id "
            "where m.user_id = :u and m.active order by w.name"
        ),
        {"u": ctx.user_id},
    ).all()
    workspaces = [{"id": str(w.id), "name": w.name, "slug": w.slug, "role": w.role} for w in ws]
    active = next((w for w in workspaces if w["id"] == str(ctx.workspace_id)), None)
    return {
        "user": {"id": str(ctx.user_id), "email": ctx.user_email, "name": ctx.user_name},
        "workspaces": workspaces,
        "active_workspace": active,
        "role": ctx.role,
        "permissions": permissions_for(ctx.role),
        "csrf_token": ctx.csrf_token,
    }


@router.post("/auth/signup")
def signup(body: SignupIn, response: Response) -> dict[str, Any]:
    s = auth_service.signup(
        body.email, body.password, body.name.strip(), body.workspace_name.strip()
    )
    _set_cookie(response, s.raw_token)
    return {"csrf_token": s.csrf_token}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
    ip = request.client.host if request.client else "unknown"
    s = auth_service.login(body.email, body.password, ip)
    _set_cookie(response, s.raw_token)
    return {"csrf_token": s.csrf_token}


@router.post("/auth/logout")
def logout(response: Response, ctx: RequestContext = Depends(get_ctx)) -> dict[str, str]:
    ctx.session.execute(
        text("update sessions set revoked_at = now() where id = :i"), {"i": ctx.session_id}
    )
    ctx.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"status": "ok"}


@router.get("/auth/me")
def me(ctx: RequestContext = Depends(get_ctx)) -> dict[str, Any]:
    return _me(ctx)


@router.post("/workspaces/switch")
def switch(body: SwitchIn, ctx: RequestContext = Depends(get_ctx)) -> dict[str, str]:
    member = ctx.session.execute(
        text("select 1 from memberships where user_id = :u and workspace_id = :w and active"),
        {"u": ctx.user_id, "w": body.workspace_id},
    ).first()
    if not member:
        raise err(404, "not_found", "Workspace not found.")
    ctx.session.execute(
        text("update sessions set active_workspace_id = :w where id = :i"),
        {"w": body.workspace_id, "i": ctx.session_id},
    )
    ctx.commit()
    return {"status": "ok"}

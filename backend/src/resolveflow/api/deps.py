import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from resolveflow.db import app_engine
from resolveflow.errors import err
from resolveflow.permissions import PERMS
from resolveflow.security import hash_token

COOKIE = "rf_session"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class RequestContext:
    user_id: uuid.UUID
    user_email: str
    user_name: str
    workspace_id: uuid.UUID | None
    role: str | None
    csrf_token: str
    session_id: uuid.UUID
    session: Session
    request_id: str

    def commit(self) -> None:
        self.session.commit()

    @property
    def ws(self) -> uuid.UUID:
        if self.workspace_id is None:
            raise err(409, "no_workspace", "Choose a workspace first.")
        return self.workspace_id


def _unauth() -> HTTPException:
    return err(401, "unauthenticated", "Sign in to continue.")


def get_ctx(request: Request) -> Iterator[RequestContext]:
    token = request.cookies.get(COOKIE)
    if not token:
        raise _unauth()
    # Resolve the session first (sessions and users are not tenant tables).
    with Session(app_engine()) as lookup, lookup.begin():
        row = lookup.execute(
            text(
                "select s.id, s.user_id, s.active_workspace_id, s.csrf_token, s.expires_at, "
                "s.revoked_at, u.active, u.email, u.name from sessions s join users u "
                "on u.id = s.user_id where s.token_hash = :h"
            ),
            {"h": hash_token(token)},
        ).first()
    if not row or row.revoked_at or row.expires_at <= datetime.now(UTC) or not row.active:
        raise _unauth()
    if request.method in UNSAFE and request.headers.get("x-csrf-token") != row.csrf_token:
        raise err(403, "csrf", "Your session token is missing or stale. Reload the page.")

    session = Session(app_engine())
    try:
        session.execute(
            text(
                "select set_config('app.workspace_id', :w, true),"
                " set_config('app.user_id', :u, true)"
            ),
            {"w": str(row.active_workspace_id or ""), "u": str(row.user_id)},
        )
        role: str | None = None
        if row.active_workspace_id:
            m = session.execute(
                text(
                    "select role, active from memberships where workspace_id = :w and user_id = :u"
                ),
                {"w": row.active_workspace_id, "u": row.user_id},
            ).first()
            if not m or not m.active:
                raise _unauth()  # removed or deactivated: old cookies stop working immediately
            role = m.role
        yield RequestContext(
            user_id=row.user_id,
            user_email=row.email,
            user_name=row.name,
            workspace_id=row.active_workspace_id,
            role=role,
            csrf_token=row.csrf_token,
            session_id=row.id,
            session=session,
            request_id=request.headers.get("x-request-id", uuid.uuid4().hex),
        )
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def require(permission: str) -> Callable[[RequestContext], RequestContext]:
    def dep(ctx: RequestContext = Depends(get_ctx)) -> RequestContext:
        if permission not in PERMS.get(ctx.role or "", frozenset()):
            raise err(403, "forbidden", "You do not have permission to do that.")
        return ctx

    return dep

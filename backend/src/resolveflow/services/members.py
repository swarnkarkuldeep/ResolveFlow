import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from resolveflow import audit
from resolveflow.api.deps import RequestContext
from resolveflow.db import system_engine
from resolveflow.errors import err
from resolveflow.security import hash_password, hash_token, new_token, verify_password
from resolveflow.services.auth import NewSession, create_session

INVITE_DAYS = 7


def list_members(ctx: RequestContext) -> list[dict[str, Any]]:
    rows = ctx.session.execute(
        text(
            "select m.user_id, u.email, u.name, m.role, m.active from memberships m "
            "join users u on u.id = m.user_id where m.workspace_id = :w order by u.name"
        ),
        {"w": ctx.ws},
    ).all()
    return [
        {
            "user_id": str(r.user_id),
            "email": r.email,
            "name": r.name,
            "role": r.role,
            "active": r.active,
        }
        for r in rows
    ]


def create_invitation(ctx: RequestContext, email: str, role: str) -> tuple[dict[str, Any], str]:
    if role == "owner" and ctx.role != "owner":
        raise err(403, "forbidden", "Only an owner can invite another owner.")
    existing = ctx.session.execute(
        text(
            "select 1 from memberships m join users u on u.id = m.user_id "
            "where m.workspace_id = :w and u.email = :e and m.active"
        ),
        {"w": ctx.ws, "e": email},
    ).first()
    if existing:
        raise err(409, "already_member", "That person is already on this workspace.")
    raw, hashed = new_token()
    expires = datetime.now(UTC) + timedelta(days=INVITE_DAYS)
    inv_id = ctx.session.execute(
        text(
            "insert into invitations (workspace_id, email, role, token_hash, invited_by, expires_at) "
            "values (:w, :e, :r, :h, :u, :x) returning id"
        ),
        {"w": ctx.ws, "e": email, "r": role, "h": hashed, "u": ctx.user_id, "x": expires},
    ).scalar_one()
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type="user",
        actor_id=ctx.user_id,
        action="invitation.created",
        entity_type="invitation",
        entity_id=inv_id,
        after={"email": email, "role": role},
        request_id=ctx.request_id,
    )
    return {"id": str(inv_id), "email": email, "role": role, "expires_at": expires.isoformat()}, raw


def list_invitations(ctx: RequestContext) -> list[dict[str, Any]]:
    rows = ctx.session.execute(
        text(
            "select id, email, role, expires_at from invitations "
            "where accepted_at is null and expires_at > now() order by created_at desc"
        )
    ).all()
    return [
        {"id": str(r.id), "email": r.email, "role": r.role, "expires_at": r.expires_at.isoformat()}
        for r in rows
    ]


def delete_invitation(ctx: RequestContext, invitation_id: uuid.UUID) -> None:
    row = ctx.session.execute(
        text("delete from invitations where id = :i and accepted_at is null returning email, role"),
        {"i": invitation_id},
    ).first()
    if not row:
        raise err(404, "not_found", "Invitation not found.")
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type="user",
        actor_id=ctx.user_id,
        action="invitation.revoked",
        entity_type="invitation",
        entity_id=invitation_id,
        before={"email": row.email, "role": row.role},
        request_id=ctx.request_id,
    )


def update_member(
    ctx: RequestContext, user_id: uuid.UUID, role: str | None, active: bool | None
) -> dict[str, Any]:
    m = ctx.session.execute(
        text("select role, active from memberships where workspace_id = :w and user_id = :u"),
        {"w": ctx.ws, "u": user_id},
    ).first()
    if not m:
        raise err(404, "not_found", "Member not found.")
    if ctx.role != "owner" and (m.role == "owner" or role == "owner"):
        raise err(403, "forbidden", "Only an owner can change owners.")
    new_role = role or m.role
    new_active = m.active if active is None else active
    if m.role == "owner" and m.active and (new_role != "owner" or not new_active):
        # Lock every active owner row so two concurrent demotions cannot both see "2 owners".
        owners = len(
            ctx.session.execute(
                text(
                    "select user_id from memberships where workspace_id = :w and role = 'owner' "
                    "and active order by user_id for update"
                ),
                {"w": ctx.ws},
            ).all()
        )
        if owners <= 1:
            raise err(409, "last_owner", "A workspace needs at least one owner.")
    ctx.session.execute(
        text(
            "update memberships set role = :r, active = :a where workspace_id = :w and user_id = :u"
        ),
        {"r": new_role, "a": new_active, "w": ctx.ws, "u": user_id},
    )
    if not new_active:
        ctx.session.execute(
            text(
                "update sessions set revoked_at = now() "
                "where user_id = :u and active_workspace_id = :w and revoked_at is null"
            ),
            {"u": user_id, "w": ctx.ws},
        )
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type="user",
        actor_id=ctx.user_id,
        action="member.updated",
        entity_type="member",
        entity_id=user_id,
        before={"role": m.role, "active": m.active},
        after={"role": new_role, "active": new_active},
        request_id=ctx.request_id,
    )
    return {"user_id": str(user_id), "role": new_role, "active": new_active}


def accept_invite(token: str, name: str, password: str) -> NewSession:
    """Unauthenticated bootstrap flow, runs as rf_system."""
    with Session(system_engine()) as s, s.begin():
        inv = s.execute(
            text(
                "select id, workspace_id, email, role, expires_at, accepted_at, invited_by "
                "from invitations where token_hash = :h for update"
            ),
            {"h": hash_token(token)},
        ).first()
        if not inv:
            raise err(404, "invalid_invite", "This invitation link is not valid.")
        if inv.accepted_at or inv.expires_at <= datetime.now(UTC):
            raise err(410, "invite_used", "This invitation has expired or was already used.")
        user = s.execute(
            text("select id, password_hash from users where email = :e"), {"e": inv.email}
        ).first()
        if user:
            if not verify_password(password, user.password_hash):
                raise err(401, "invalid_credentials", "Email or password is incorrect.")
            user_id = user.id
        else:
            user_id = s.execute(
                text(
                    "insert into users (email, name, password_hash) values (:e, :n, :p) returning id"
                ),
                {"e": inv.email, "n": name, "p": hash_password(password)},
            ).scalar_one()
        s.execute(
            text(
                "insert into memberships (workspace_id, user_id, role) values (:w, :u, :r) "
                "on conflict (workspace_id, user_id) do update set role = :r, active = true"
            ),
            {"w": inv.workspace_id, "u": user_id, "r": inv.role},
        )
        s.execute(text("update invitations set accepted_at = now() where id = :i"), {"i": inv.id})
        audit.record(
            s,
            workspace_id=inv.workspace_id,
            actor_type="user",
            actor_id=user_id,
            action="invitation.accepted",
            entity_type="invitation",
            entity_id=inv.id,
            after={"email": inv.email, "role": inv.role},
        )
        return create_session(s, user_id, inv.workspace_id)

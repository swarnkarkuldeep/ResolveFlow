import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from resolveflow import audit, ratelimit
from resolveflow.db import system_engine
from resolveflow.errors import err
from resolveflow.security import DUMMY_HASH, hash_password, new_token, verify_password
from resolveflow.tenancy import tenant_session
from resolveflow.textutil import clean_line

SESSION_DAYS = 14
LOGIN_LIMIT = 10  # failures per (ip, email)
ACCOUNT_LOGIN_LIMIT = 30  # failures per account from anywhere, so a rotating IP cannot grind
LOGIN_WINDOW_S = 15 * 60


@dataclass
class NewSession:
    raw_token: str
    csrf_token: str
    user_id: uuid.UUID
    workspace_id: uuid.UUID | None


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:40] or "workspace"


def create_session(
    session: Session, user_id: uuid.UUID, workspace_id: uuid.UUID | None
) -> NewSession:
    raw, hashed = new_token()
    csrf = secrets.token_urlsafe(24)
    session.execute(
        text(
            "insert into sessions (token_hash, user_id, active_workspace_id, csrf_token, expires_at) "
            "values (:h, :u, :w, :c, :e)"
        ),
        {
            "h": hashed,
            "u": user_id,
            "w": workspace_id,
            "c": csrf,
            "e": datetime.now(UTC) + timedelta(days=SESSION_DAYS),
        },
    )
    return NewSession(raw, csrf, user_id, workspace_id)


def signup(email: str, password: str, name: str, workspace_name: str) -> NewSession:
    """Bootstrap flow (no tenant exists yet), so it runs as rf_system."""
    name, workspace_name = clean_line(name), clean_line(workspace_name)
    with Session(system_engine()) as s, s.begin():
        try:
            user_id = s.execute(
                text(
                    "insert into users (email, name, password_hash) values (:e, :n, :p) returning id"
                ),
                {"e": email, "n": name, "p": hash_password(password)},
            ).scalar_one()
        except IntegrityError:
            raise err(409, "email_taken", "An account with this email already exists.") from None
        base = _slugify(workspace_name)
        slug = base
        while s.execute(text("select 1 from workspaces where slug = :s"), {"s": slug}).first():
            slug = f"{base}-{secrets.token_hex(2)}"
        ws_id = s.execute(
            text(
                "insert into workspaces (slug, name, inbound_token) values (:s, :n, :t) returning id"
            ),
            {"s": slug, "n": workspace_name, "t": secrets.token_hex(8)},
        ).scalar_one()
        s.execute(
            text("insert into memberships (workspace_id, user_id, role) values (:w, :u, 'owner')"),
            {"w": ws_id, "u": user_id},
        )
        audit.record(
            s,
            workspace_id=ws_id,
            actor_type="user",
            actor_id=user_id,
            action="workspace.created",
            entity_type="workspace",
            entity_id=ws_id,
            after={"name": workspace_name, "slug": slug},
        )
        return create_session(s, user_id, ws_id)


def login(email: str, password: str, ip: str) -> NewSession:
    key = f"rl:login:{ip}:{email.lower()}"
    account_key = f"rl:login-account:{email.lower()}"
    if ratelimit.peek(key) >= LOGIN_LIMIT or ratelimit.peek(account_key) >= ACCOUNT_LOGIN_LIMIT:
        raise err(429, "rate_limited", "Too many sign-in attempts. Try again in 15 minutes.")
    with Session(system_engine()) as s, s.begin():  # rf_app cannot read password hashes
        row = s.execute(
            text("select id, password_hash, active from users where email = :e"), {"e": email}
        ).first()
    ok = verify_password(password, row.password_hash if row else DUMMY_HASH)
    if not (row and ok and row.active):
        ratelimit.count(key, LOGIN_WINDOW_S)
        ratelimit.count(account_key, LOGIN_WINDOW_S)
        raise err(401, "invalid_credentials", "Email or password is incorrect.")
    ratelimit.reset(key)
    with tenant_session(None, row.id) as s:
        ws = s.execute(
            text(
                "select workspace_id from memberships where user_id = :u and active "
                "order by created_at limit 1"
            ),
            {"u": row.id},
        ).scalar()
        return create_session(s, row.id, ws)

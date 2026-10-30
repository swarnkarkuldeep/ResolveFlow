import uuid

from fastapi.testclient import TestClient
from sqlalchemy import text

from resolveflow.db import engine_for


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:8]}@example.test"


def signup(client: TestClient, email: str | None = None, workspace: str = "Acme Plumbing") -> dict:
    r = client.post(
        "/api/auth/signup",
        json={
            "email": email or _email(),
            "password": "correct-horse-battery",
            "name": "Sam Owner",
            "workspace_name": workspace,
        },
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_signup_then_me(client: TestClient) -> None:
    body = signup(client)
    assert body["csrf_token"]
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    data = me.json()
    assert data["role"] == "owner"
    assert data["active_workspace"]["name"] == "Acme Plumbing"
    assert "ticket:read" in data["permissions"] and "user:manage" in data["permissions"]
    assert data["csrf_token"] == body["csrf_token"]


def test_password_is_argon2_and_session_token_not_stored_raw(
    client: TestClient, postgres_url: str
) -> None:
    email = _email()
    signup(client, email)
    cookie = client.cookies.get("rf_session")
    assert cookie
    with engine_for(postgres_url).connect() as conn:
        pw = conn.execute(
            text("select password_hash from users where email = :e"), {"e": email}
        ).scalar_one()
        hashes = conn.execute(text("select token_hash from sessions")).scalars().all()
    assert pw.startswith("$argon2id$")
    assert cookie not in hashes
    assert all(len(h) == 64 for h in hashes)


def test_login_failure_is_generic(client: TestClient) -> None:
    email = _email()
    signup(client, email)
    client.cookies.clear()
    wrong = client.post("/api/auth/login", json={"email": email, "password": "nope-nope-nope"})
    unknown = client.post("/api/auth/login", json={"email": _email(), "password": "nope-nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["detail"]["code"] == "invalid_credentials"


def test_login_rate_limited_after_ten_failures(client: TestClient) -> None:
    email = _email()
    signup(client, email)
    client.cookies.clear()
    codes = [
        client.post(
            "/api/auth/login", json={"email": email, "password": "bad-bad-bad-bad"}
        ).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429
    # even the right password is refused while limited
    ok = client.post("/api/auth/login", json={"email": email, "password": "correct-horse-battery"})
    assert ok.status_code == 429


def test_login_success_sets_session(client: TestClient) -> None:
    email = _email()
    signup(client, email)
    client.cookies.clear()
    r = client.post("/api/auth/login", json={"email": email, "password": "correct-horse-battery"})
    assert r.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_unsafe_request_requires_csrf_header(client: TestClient) -> None:
    body = signup(client)
    other = signup(client, workspace="Second Co")  # now logged in as a second user
    assert other["csrf_token"] != body["csrf_token"]
    ws = client.get("/api/auth/me").json()["active_workspace"]["id"]
    no_header = client.post("/api/workspaces/switch", json={"workspace_id": ws})
    assert no_header.status_code == 403
    with_header = client.post(
        "/api/workspaces/switch",
        json={"workspace_id": ws},
        headers={"X-CSRF-Token": other["csrf_token"]},
    )
    assert with_header.status_code == 200


def test_logout_kills_the_session(client: TestClient) -> None:
    body = signup(client)
    old_cookie = client.cookies.get("rf_session")
    r = client.post("/api/auth/logout", headers={"X-CSRF-Token": body["csrf_token"]})
    assert r.status_code == 200
    client.cookies.set("rf_session", old_cookie)
    assert client.get("/api/auth/me").status_code == 401


def test_deactivated_user_cookie_is_rejected(client: TestClient, postgres_url: str) -> None:
    email = _email()
    signup(client, email)
    with engine_for(postgres_url).begin() as conn:
        conn.execute(text("update users set active = false where email = :e"), {"e": email})
    assert client.get("/api/auth/me").status_code == 401


def test_switch_to_foreign_workspace_is_404(client: TestClient) -> None:
    first = signup(client, workspace="One Co")
    foreign_id = client.get("/api/auth/me").json()["active_workspace"]["id"]
    client.cookies.clear()
    second = signup(client, workspace="Two Co")
    r = client.post(
        "/api/workspaces/switch",
        json={"workspace_id": foreign_id},
        headers={"X-CSRF-Token": second["csrf_token"]},
    )
    assert r.status_code == 404
    assert first["csrf_token"] != second["csrf_token"]


def test_duplicate_email_signup_is_409(client: TestClient) -> None:
    email = _email()
    signup(client, email)
    client.cookies.clear()
    r = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": "correct-horse-battery",
            "name": "X",
            "workspace_name": "Y",
        },
    )
    assert r.status_code == 409


def test_short_password_is_422(client: TestClient) -> None:
    r = client.post(
        "/api/auth/signup",
        json={"email": _email(), "password": "short", "name": "X", "workspace_name": "Y"},
    )
    assert r.status_code == 422


def test_me_without_cookie_is_401(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401

import json
import uuid

import httpx
import pytest
from sqlalchemy import text
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from resolveflow.config import Settings
from resolveflow.db import engine_for
from resolveflow.email.outbound import MemoryProvider, PostmarkProvider, SmtpProvider
from tests.helpers import ClientFactory, invite_actor, make_owner, team, unique_email


def test_permission_matrix(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    target = t["agent"].user_id
    cases = [
        ("get", "/api/members", None, {"owner": 200, "admin": 200, "agent": 200, "viewer": 200}),
        (
            "get",
            "/api/invitations",
            None,
            {"owner": 200, "admin": 200, "agent": 403, "viewer": 403},
        ),
        (
            "post",
            "/api/invitations",
            lambda: {"email": unique_email("m"), "role": "agent"},
            {"owner": 200, "admin": 200, "agent": 403, "viewer": 403},
        ),
        (
            "patch",
            f"/api/members/{target}",
            {"role": "agent"},
            {"owner": 200, "admin": 200, "agent": 403, "viewer": 403},
        ),
    ]
    for method, path, body, expected in cases:
        for role, want in expected.items():
            payload = body() if callable(body) else body
            got = (
                getattr(t[role], method)(path, payload)
                if payload is not None
                else getattr(t[role], method)(path)
            )
            assert got.status_code == want, (method, path, role, got.status_code, got.text)


def test_invite_accept_flow_and_email(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    agent = invite_actor(owner, client_factory, "agent", name="Ana Agent")
    assert len(MemoryProvider.sent) == 1
    mail = MemoryProvider.sent[0]
    assert mail["to"] == agent.email
    assert "/accept-invite?token=" in mail["text"]
    me = agent.get("/api/auth/me").json()
    assert me["role"] == "agent"
    assert me["active_workspace"]["name"] == "Acme Plumbing"
    members = {m["email"]: m for m in owner.get("/api/members").json()}
    assert members[agent.email]["role"] == "agent" and members[agent.email]["active"] is True


def test_invite_token_is_single_use_and_expires(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    owner.post("/api/invitations", {"email": unique_email("a"), "role": "agent"})
    from tests.helpers import token_from_last_email

    token = token_from_last_email()
    c = client_factory()
    ok = c.post(
        "/api/auth/accept-invite",
        json={"token": token, "name": "N", "password": "correct-horse-battery"},
    )
    assert ok.status_code == 200
    again = client_factory().post(
        "/api/auth/accept-invite",
        json={"token": token, "name": "N", "password": "correct-horse-battery"},
    )
    assert again.status_code == 410
    owner.post("/api/invitations", {"email": unique_email("b"), "role": "agent"})
    expired = token_from_last_email()
    with engine_for(postgres_url).begin() as conn:
        conn.execute(text("update invitations set expires_at = now() - interval '1 day'"))
    r = client_factory().post(
        "/api/auth/accept-invite",
        json={"token": expired, "name": "N", "password": "correct-horse-battery"},
    )
    assert r.status_code == 410
    unknown = client_factory().post(
        "/api/auth/accept-invite",
        json={"token": "nope", "name": "N", "password": "correct-horse-battery"},
    )
    assert unknown.status_code == 404


def test_admin_cannot_grant_owner(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    r = t["admin"].post("/api/invitations", {"email": unique_email("x"), "role": "owner"})
    assert r.status_code == 403
    r2 = t["admin"].patch(f"/api/members/{t['agent'].user_id}", {"role": "owner"})
    assert r2.status_code == 403
    # ...and cannot touch an owner at all
    r3 = t["admin"].patch(f"/api/members/{t['owner'].user_id}", {"role": "agent"})
    assert r3.status_code == 403


def test_last_owner_cannot_be_demoted_or_deactivated(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    me = owner.user_id
    assert owner.patch(f"/api/members/{me}", {"role": "admin"}).status_code == 409
    assert owner.patch(f"/api/members/{me}", {"active": False}).status_code == 409
    assert (
        owner.patch(f"/api/members/{me}", {"active": False}).json()["detail"]["code"]
        == "last_owner"
    )


def test_deactivated_member_session_dies_immediately(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    assert t["agent"].get("/api/auth/me").status_code == 200
    r = t["owner"].patch(f"/api/members/{t['agent'].user_id}", {"active": False})
    assert r.status_code == 200
    assert t["agent"].get("/api/auth/me").status_code == 401


def test_cannot_manage_member_of_another_workspace(client_factory: ClientFactory) -> None:
    a = team(client_factory, "Workspace A")
    b = team(client_factory, "Workspace B")
    r = a["admin"].patch(f"/api/members/{b['agent'].user_id}", {"role": "viewer"})
    assert r.status_code == 404
    assert b["agent"].get("/api/auth/me").json()["role"] == "agent"


def test_cannot_invite_existing_member_and_list_revoke(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    dup = t["owner"].post("/api/invitations", {"email": t["agent"].email, "role": "agent"})
    assert dup.status_code == 409
    inv = t["owner"].post("/api/invitations", {"email": unique_email("p"), "role": "viewer"}).json()
    pending = t["owner"].get("/api/invitations").json()
    assert inv["id"] in [i["id"] for i in pending]
    assert t["owner"].delete(f"/api/invitations/{inv['id']}").status_code == 200
    assert inv["id"] not in [i["id"] for i in t["owner"].get("/api/invitations").json()]
    # foreign invitation id -> 404
    other = make_owner(client_factory, "Other Co")
    other_inv = other.post(
        "/api/invitations", {"email": unique_email("q"), "role": "viewer"}
    ).json()
    assert t["owner"].delete(f"/api/invitations/{other_inv['id']}").status_code == 404


def test_role_change_is_audited(client_factory: ClientFactory, postgres_url: str) -> None:
    t = team(client_factory)
    t["owner"].patch(f"/api/members/{t['agent'].user_id}", {"role": "viewer"})
    with engine_for(postgres_url).connect() as conn:
        row = conn.execute(
            text(
                "select before, after from audit_log where action = 'member.updated' "
                "and workspace_id = :w"
            ),
            {"w": uuid.UUID(t["owner"].workspace_id)},
        ).one()
    assert row.before["role"] == "agent" and row.after["role"] == "viewer"


def test_postmark_provider_builds_the_expected_request() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["token"] = request.headers["x-postmark-server-token"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ErrorCode": 0})

    p = PostmarkProvider("tok-123", "support@x.test", transport=httpx.MockTransport(handler))
    p.send(
        to="a@b.test",
        subject="Hi",
        text="Body",
        headers={"In-Reply-To": "<1@x>"},
        message_id="<2@x>",
    )
    assert seen["url"] == "https://api.postmarkapp.com/email"
    assert seen["token"] == "tok-123"
    assert seen["body"]["To"] == "a@b.test" and seen["body"]["TextBody"] == "Body"
    names = {h["Name"]: h["Value"] for h in seen["body"]["Headers"]}
    assert names["In-Reply-To"] == "<1@x>" and names["Message-ID"] == "<2@x>"

    def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"ErrorCode": 300, "Message": "bad"})

    bad = PostmarkProvider("tok", "s@x.test", transport=httpx.MockTransport(boom))
    with pytest.raises(RuntimeError):
        bad.send(to="a@b.test", subject="s", text="t")


def test_smtp_provider_delivers_to_real_mailpit() -> None:
    with DockerContainer("axllent/mailpit:v1.27").with_exposed_ports(1025, 8025) as mp:
        wait_for_logs(mp, "accessible via", timeout=60)
        host = mp.get_container_host_ip()
        smtp_port, ui_port = int(mp.get_exposed_port(1025)), int(mp.get_exposed_port(8025))
        s = Settings(  # type: ignore[call-arg]
            database_url="postgresql://x",
            redis_url="redis://x",
            smtp_host=host,
            smtp_port=smtp_port,
        )
        SmtpProvider(s).send(
            to="cust@example.test",
            subject="Re: Leaking tap",
            text="We will be there Tuesday.",
            headers={"In-Reply-To": "<abc@example.test>"},
            message_id="<m1@inbound.test>",
        )
        msgs = httpx.get(f"http://{host}:{ui_port}/api/v1/messages", timeout=10).json()
    assert msgs["total"] == 1
    assert msgs["messages"][0]["Subject"] == "Re: Leaking tap"
    assert msgs["messages"][0]["To"][0]["Address"] == "cust@example.test"

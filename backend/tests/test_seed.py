import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from resolveflow.db import engine_for, system_engine
from resolveflow.main import app
from resolveflow.seed import DEMO_PASSWORD, seed_demo, seed_if_empty
from tests.helpers import ClientFactory, make_owner


@pytest.fixture
def seeded(migrated_env: None, postgres_url: str):  # type: ignore[no-untyped-def]
    summary = seed_demo(system_engine())
    return summary, postgres_url


def _count(url: str, sql: str, **params: object) -> int:
    with engine_for(url).connect() as conn:
        return int(conn.execute(text(sql), params).scalar_one())


def test_seed_creates_a_realistic_workspace(seeded) -> None:  # type: ignore[no-untyped-def]
    summary, url = seeded
    ws = summary.workspace_id
    roles = {
        r[0]
        for r in engine_for(url)
        .connect()
        .execute(text("select role from memberships where workspace_id = :w"), {"w": ws})
    }
    assert roles == {"owner", "admin", "agent", "viewer"}
    assert 55 <= _count(url, "select count(*) from tickets where workspace_id = :w", w=ws) <= 65
    assert (
        _count(url, "select count(distinct status) from tickets where workspace_id = :w", w=ws) == 5
    )
    assert (
        _count(url, "select count(distinct priority) from tickets where workspace_id = :w", w=ws)
        == 4
    )
    assert (
        _count(url, "select count(distinct channel) from tickets where workspace_id = :w", w=ws)
        == 3
    )
    assert (
        _count(
            url,
            "select count(*) from tickets t where workspace_id = :w and merged_into_id is null "
            "and not exists (select 1 from messages m where m.ticket_id = t.id)",
            w=ws,
        )
        == 0
    )
    for label, sql in {
        "note": "select count(*) from messages where workspace_id = :w and kind = 'note'",
        "sent reply": "select count(*) from messages where workspace_id = :w and direction = 'outbound' and delivery_status = 'sent'",
        "merged": "select count(*) from tickets where workspace_id = :w and merged_into_id is not null",
        "duplicate": "select count(*) from tickets where workspace_id = :w and possible_duplicate_of is not null",
        "tagged": "select count(*) from ticket_tags where workspace_id = :w",
        "assigned": "select count(*) from tickets where workspace_id = :w and assignee_id is not null",
        "audit": "select count(*) from audit_log where workspace_id = :w",
        "sla clocks": "select count(*) from ticket_sla where workspace_id = :w and start_at is not null",
        "sla met": "select count(*) from ticket_sla where workspace_id = :w and fr_met_at is not null",
        "sla policy": "select count(*) from sla_policies where workspace_id = :w",
    }.items():
        assert _count(url, sql, w=ws) > 0, label


def test_seed_is_idempotent_and_if_empty_is_a_noop_when_data_exists(seeded) -> None:  # type: ignore[no-untyped-def]
    summary, url = seeded
    before = _count(url, "select count(*) from tickets")
    again = seed_demo(system_engine())
    assert again.workspace_id == summary.workspace_id
    assert _count(url, "select count(*) from tickets") == before
    assert seed_if_empty(system_engine()) is False  # workspaces already exist


def test_seeded_users_can_sign_in_and_see_only_their_workspace(
    seeded,
    client_factory: ClientFactory,  # type: ignore[no-untyped-def]
) -> None:
    summary, _ = seeded
    client = TestClient(app)
    r = client.post(
        "/api/auth/login", json={"email": summary.users["owner"], "password": DEMO_PASSWORD}
    )
    assert r.status_code == 200, r.text
    me = client.get("/api/auth/me").json()
    assert me["active_workspace"]["slug"] == "brightwork" and me["role"] == "owner"
    page = client.get("/api/tickets?limit=100").json()
    assert len(page["items"]) >= 50
    outsider = make_owner(client_factory, "Outsider Co")
    assert outsider.get("/api/tickets").json()["items"] == []
    viewer = TestClient(app)
    assert (
        viewer.post(
            "/api/auth/login", json={"email": summary.users["viewer"], "password": DEMO_PASSWORD}
        ).status_code
        == 200
    )
    assert viewer.get("/api/auth/me").json()["role"] == "viewer"

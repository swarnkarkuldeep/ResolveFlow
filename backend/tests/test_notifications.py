import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from resolveflow.db import engine_for, system_engine
from resolveflow.sla import service as sla_service
from resolveflow.sla import sweeper
from tests.helpers import Actor, ClientFactory, team
from tests.test_ingest import DOMAIN, payload, post, token_of
from tests.test_tickets import new_ticket


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, datetime]]:
    state = {"now": datetime(2026, 11, 2, 10, tzinfo=UTC)}
    monkeypatch.setattr(sla_service, "utcnow", lambda: state["now"])
    yield state


def inbox(actor: Actor, **params: Any) -> list[dict[str, Any]]:
    r = actor.get("/api/notifications", params=params)
    assert r.status_code == 200, r.text
    return list(r.json()["items"])


def rows(url: str, ws: str, kind: str | None = None) -> list[Any]:
    with engine_for(url).connect() as conn:
        return list(
            conn.execute(
                text(
                    "select user_id, kind, in_app, email_status from notifications "
                    "where workspace_id = :w and (cast(:k as text) is null or kind = :k)"
                ),
                {"w": uuid.UUID(ws), "k": kind},
            )
        )


def test_assigning_a_ticket_notifies_the_assignee_once_but_never_yourself(
    client_factory: ClientFactory,
) -> None:
    t = team(client_factory)
    owner, agent = t["owner"], t["agent"]
    tk = new_ticket(owner)
    owner.patch(f"/api/tickets/{tk['id']}", {"assignee_id": owner.user_id})
    assert inbox(owner) == []
    owner.patch(f"/api/tickets/{tk['id']}", {"assignee_id": agent.user_id})
    got = inbox(agent)
    assert len(got) == 1 and got[0]["kind"] == "assigned" and got[0]["read"] is False
    assert got[0]["ticket"]["id"] == tk["id"] and "#" in got[0]["title"]
    assert inbox(owner) == []


def test_unread_count_mark_read_and_read_all_only_touch_my_own(
    client_factory: ClientFactory,
) -> None:
    t = team(client_factory)
    owner, agent, admin = t["owner"], t["agent"], t["admin"]
    for _ in range(2):
        tk = new_ticket(owner)
        owner.patch(f"/api/tickets/{tk['id']}", {"assignee_id": agent.user_id})
        owner.patch(f"/api/tickets/{tk['id']}", {"assignee_id": admin.user_id})
    assert agent.get("/api/notifications/unread-count").json()["count"] == 2
    first = inbox(agent)[0]
    assert agent.post(f"/api/notifications/{first['id']}/read", {}).status_code == 200
    assert agent.get("/api/notifications/unread-count").json()["count"] == 1
    assert len(inbox(agent, unread="true")) == 1
    # somebody else's notification is not found, and cannot be marked read
    assert admin.post(f"/api/notifications/{first['id']}/read", {}).status_code == 404
    assert admin.get("/api/notifications/unread-count").json()["count"] == 2
    assert agent.post("/api/notifications/read-all", {}).status_code == 200
    assert agent.get("/api/notifications/unread-count").json()["count"] == 0
    assert admin.get("/api/notifications/unread-count").json()["count"] == 2


def test_a_customer_reply_notifies_the_assignee_and_a_replayed_email_does_not_repeat_it(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    t = team(client_factory)
    owner, agent = t["owner"], t["agent"]
    tk = new_ticket(owner)
    owner.patch(f"/api/tickets/{tk['id']}", {"assignee_id": agent.user_id})
    token = token_of(postgres_url, owner)
    to = f"support+{token}.{tk['number']}@{DOMAIN}"
    data = payload(to, sender=tk["requester"]["email"], message_id="<reply-1@customer.test>")
    for _ in range(2):
        assert post(client_factory(), data).status_code == 200
    replies = [n for n in inbox(agent) if n["kind"] == "customer_reply"]
    assert len(replies) == 1 and replies[0]["ticket"]["id"] == tk["id"]


def test_sla_thresholds_notify_the_assignee_or_the_admins_once_across_repeated_sweeps(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    t = team(client_factory)
    owner, agent = t["owner"], t["agent"]
    mine = new_ticket(owner, "Assigned one")
    owner.patch(f"/api/tickets/{mine['id']}", {"assignee_id": agent.user_id})
    new_ticket(owner, "Nobody has it")
    ws = uuid.UUID(owner.workspace_id)
    for hour in (16, 16, 17):
        sweeper.sweep(system_engine(), now=datetime(2026, 11, 2, hour, tzinfo=UTC), workspace_id=ws)
    sweeper.sweep(system_engine(), now=datetime(2026, 11, 3, 10, tzinfo=UTC), workspace_id=ws)
    sweeper.sweep(system_engine(), now=datetime(2026, 11, 3, 11, tzinfo=UTC), workspace_id=ws)
    agent_sla = [n for n in inbox(agent) if n["kind"] == "sla"]
    owner_sla = [n for n in inbox(owner) if n["kind"] == "sla"]
    assert len(agent_sla) == 2  # warning and breach, once each
    assert len(owner_sla) == 2 and all("Nobody" in (n["body"] or "") for n in owner_sla)
    assert {r.email_status for r in rows(postgres_url, owner.workspace_id, "sla")} == {"queued"}


def test_preferences_default_round_trip_and_reject_unknown_kinds(
    client_factory: ClientFactory,
) -> None:
    owner = team(client_factory)["owner"]
    prefs = {p["kind"]: p for p in owner.get("/api/notification-prefs").json()}
    assert prefs["assigned"] == {"kind": "assigned", "in_app": True, "email": False}
    assert prefs["sla"]["email"] is True and prefs["escalation"]["email"] is True
    r = owner.client.put(
        "/api/notification-prefs",
        json=[{"kind": "assigned", "in_app": False, "email": True}],
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert r.status_code == 200
    again = {p["kind"]: p for p in owner.get("/api/notification-prefs").json()}
    assert again["assigned"]["in_app"] is False and again["assigned"]["email"] is True
    bad = owner.client.put(
        "/api/notification-prefs",
        json=[{"kind": "nonsense", "in_app": True, "email": True}],
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert bad.status_code == 422


def test_turning_a_kind_off_creates_nothing_and_email_only_creates_a_hidden_row(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    t = team(client_factory)
    owner, agent = t["owner"], t["agent"]
    headers = {"X-CSRF-Token": agent.csrf}
    agent.client.put(
        "/api/notification-prefs",
        json=[{"kind": "assigned", "in_app": False, "email": False}],
        headers=headers,
    )
    tk = new_ticket(owner)
    owner.patch(f"/api/tickets/{tk['id']}", {"assignee_id": agent.user_id})
    assert rows(postgres_url, owner.workspace_id, "assigned") == []
    agent.client.put(
        "/api/notification-prefs",
        json=[{"kind": "assigned", "in_app": False, "email": True}],
        headers=headers,
    )
    tk2 = new_ticket(owner)
    owner.patch(f"/api/tickets/{tk2['id']}", {"assignee_id": agent.user_id})
    got = rows(postgres_url, owner.workspace_id, "assigned")
    assert len(got) == 1 and got[0].in_app is False and got[0].email_status == "queued"
    assert inbox(agent) == []  # not shown in the app
    assert agent.get("/api/notifications/unread-count").json()["count"] == 0


def test_rule_notifications_respect_preferences_and_dedupe(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    from tests.test_rules_exec import live, when

    t = team(client_factory)
    owner, admin = t["owner"], t["admin"]
    admin.client.put(
        "/api/notification-prefs",
        json=[{"kind": "rule", "in_app": False, "email": False}],
        headers={"X-CSRF-Token": admin.csrf},
    )
    live(
        owner,
        postgres_url,
        "Ping",
        when(
            "ticket.created",
            "subject",
            "contains",
            "ping",
            [{"type": "notify", "target": "owners_admins", "message": "look"}],
        ),
    )
    new_ticket(owner, "ping me")
    assert len([n for n in inbox(owner) if n["kind"] == "rule"]) == 1
    assert [n for n in inbox(admin) if n["kind"] == "rule"] == []

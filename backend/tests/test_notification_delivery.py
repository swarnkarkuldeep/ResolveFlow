import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from resolveflow.db import engine_for, system_engine
from resolveflow.email.outbound import MemoryProvider
from resolveflow.notifications import delivery
from tests.helpers import Actor, ClientFactory, team
from tests.test_tickets import new_ticket


def make_queued(client_factory: ClientFactory) -> tuple[dict[str, Actor], dict[str, Any]]:
    t = team(client_factory)
    owner, agent = t["owner"], t["agent"]
    agent.client.put(
        "/api/notification-prefs",
        json=[{"kind": "assigned", "in_app": True, "email": True}],
        headers={"X-CSRF-Token": agent.csrf},
    )
    tk = new_ticket(owner, "Boiler\r\nBcc: evil@example.test")
    owner.patch(f"/api/tickets/{tk['id']}", {"assignee_id": agent.user_id})
    return t, tk


def state(url: str, ws: str) -> Any:
    with engine_for(url).connect() as conn:
        return conn.execute(
            text(
                "select id, email_status, email_attempts, email_last_error, email_next_at "
                "from notifications where workspace_id = :w and email_status <> 'none'"
            ),
            {"w": uuid.UUID(ws)},
        ).one()


class Broken:
    calls = 0

    def send(self, **_: Any) -> None:
        Broken.calls += 1
        raise RuntimeError("provider is down")


def test_a_queued_notification_is_mailed_exactly_once_even_if_the_sweeper_runs_again(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    t, tk = make_queued(client_factory)
    ws = uuid.UUID(t["owner"].workspace_id)
    for _ in range(3):
        delivery.deliver_due(system_engine(), workspace_id=ws)
    sent = [
        m
        for m in MemoryProvider.sent
        if m["to"] == t["agent"].email and "Assigned to you" in str(m["subject"])
    ]
    assert len(sent) == 1
    assert "Bcc" not in str(sent[0]["subject"]) and "\n" not in str(sent[0]["subject"])
    assert str(tk["number"]) in str(sent[0]["subject"])
    assert f"/inbox/{tk['id']}" in str(sent[0]["text"])
    assert state(postgres_url, t["owner"].workspace_id).email_status == "sent"


def test_failures_back_off_then_dead_letter_and_an_admin_can_retry(
    client_factory: ClientFactory, postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, _ = make_queued(client_factory)
    owner, agent = t["owner"], t["agent"]
    ws = uuid.UUID(owner.workspace_id)
    monkeypatch.setattr(delivery, "get_provider", lambda: Broken())
    now = datetime.now(UTC) + timedelta(seconds=5)
    delivery.deliver_due(system_engine(), now=now, workspace_id=ws)
    s = state(postgres_url, owner.workspace_id)
    assert s.email_status == "queued" and s.email_attempts == 1
    assert "provider is down" in s.email_last_error
    assert s.email_next_at > now + timedelta(seconds=30)  # backed off
    calls = Broken.calls
    delivery.deliver_due(system_engine(), now=now, workspace_id=ws)  # not due yet
    assert Broken.calls == calls
    for _ in range(4):
        now += timedelta(hours=2)
        delivery.deliver_due(system_engine(), now=now, workspace_id=ws)
    s = state(postgres_url, owner.workspace_id)
    assert s.email_status == "dead" and s.email_attempts == 5

    listed = owner.get("/api/notification-deliveries", params={"status": "dead"}).json()["items"]
    assert len(listed) == 1 and listed[0]["recipient"] == agent.email
    assert "provider is down" in listed[0]["error"]
    assert agent.get("/api/notification-deliveries").status_code == 403
    assert (
        agent.post(f"/api/notification-deliveries/{listed[0]['id']}/retry", {}).status_code == 403
    )

    monkeypatch.setattr(delivery, "get_provider", lambda: MemoryProvider())
    assert (
        owner.post(f"/api/notification-deliveries/{listed[0]['id']}/retry", {}).status_code == 200
    )
    delivery.deliver_due(system_engine(), workspace_id=ws)
    assert state(postgres_url, owner.workspace_id).email_status == "sent"
    assert (
        owner.get("/api/notification-deliveries", params={"status": "dead"}).json()["items"] == []
    )


def test_a_deactivated_recipient_is_skipped_not_mailed(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    t, _ = make_queued(client_factory)
    owner, agent = t["owner"], t["agent"]
    with engine_for(postgres_url).begin() as conn:
        conn.execute(
            text("update memberships set active = false where user_id = :u"),
            {"u": uuid.UUID(agent.user_id)},
        )
    delivery.deliver_due(system_engine(), workspace_id=uuid.UUID(owner.workspace_id))
    assert [
        m
        for m in MemoryProvider.sent
        if m["to"] == agent.email and "Assigned to you" in str(m["subject"])
    ] == []
    assert state(postgres_url, owner.workspace_id).email_status == "skipped"


def test_deliveries_of_another_workspace_are_invisible_and_cannot_be_retried(
    client_factory: ClientFactory, postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    t, _ = make_queued(client_factory)
    other = team(client_factory, "Other Co")["owner"]
    monkeypatch.setattr(delivery, "get_provider", lambda: Broken())
    ws = uuid.UUID(t["owner"].workspace_id)
    now = datetime.now(UTC)
    for _ in range(5):
        now += timedelta(hours=2)
        delivery.deliver_due(system_engine(), now=now, workspace_id=ws)
    nid = (
        t["owner"]
        .get("/api/notification-deliveries", params={"status": "dead"})
        .json()["items"][0]["id"]
    )
    assert (
        other.get("/api/notification-deliveries", params={"status": "dead"}).json()["items"] == []
    )
    assert other.post(f"/api/notification-deliveries/{nid}/retry", {}).status_code == 404

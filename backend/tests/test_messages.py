import uuid

import pytest
from sqlalchemy import text

from resolveflow.celery_app import celery
from resolveflow.db import engine_for
from resolveflow.email.outbound import MemoryProvider
from resolveflow.tasks import email as email_tasks
from resolveflow.tasks.email import requeue_stuck_outbound, send_outbound_message
from tests.helpers import ClientFactory, make_owner, team
from tests.test_tickets import new_ticket


def _msg_row(url: str, message_id: str) -> object:
    with engine_for(url).connect() as conn:
        return conn.execute(
            text(
                "select delivery_status, delivery_attempts, message_id from messages where id = :i"
            ),
            {"i": uuid.UUID(message_id)},
        ).one()


def _reply(actor, ticket_id: str, body: str = "We will be there Tuesday.", **extra):  # type: ignore[no-untyped-def]
    return actor.post(
        f"/api/tickets/{ticket_id}/messages", {"body": body, "kind": "public", **extra}
    )


def test_reply_is_sent_with_threading_headers(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    tk = new_ticket(owner, "Leaking tap", requester_email="cora@customer.test")
    with engine_for(postgres_url).begin() as conn:
        conn.execute(
            text("update messages set message_id = '<orig@customer.test>' where ticket_id = :t"),
            {"t": uuid.UUID(tk["id"])},
        )
        token = conn.execute(text("select inbound_token from workspaces")).scalars().all()[-1]
    r = _reply(owner, tk["id"])
    assert r.status_code == 200, r.text
    assert r.json()["direction"] == "outbound" and r.json()["kind"] == "public"
    assert len(MemoryProvider.sent) == 1
    mail = MemoryProvider.sent[0]
    assert mail["to"] == "cora@customer.test"
    assert mail["subject"] == "Re: Leaking tap"
    assert mail["text"] == "We will be there Tuesday."
    headers = mail["headers"]
    assert headers["In-Reply-To"] == "<orig@customer.test>"
    assert headers["References"] == "<orig@customer.test>"
    assert headers["Reply-To"].startswith("support+") and f".{tk['number']}@" in headers["Reply-To"]
    assert mail["id"].startswith("<") and mail["id"].endswith(">")
    row = _msg_row(postgres_url, r.json()["id"])
    assert row.delivery_status == "sent"
    del token


def test_sending_twice_delivers_once(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    tk = new_ticket(owner)
    mid = _reply(owner, tk["id"]).json()["id"]
    send_outbound_message(mid)
    send_outbound_message(mid)
    assert len(MemoryProvider.sent) == 1


class FlakyProvider:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def send(self, **kwargs: object) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("smtp down")
        MemoryProvider().send(**kwargs)  # type: ignore[arg-type]


def _age_all(url: str) -> None:
    with engine_for(url).begin() as conn:
        conn.execute(
            text(
                "update messages set created_at = now() - interval '5 minutes' "
                "where delivery_status = 'queued'"
            )
        )


def test_transient_failure_is_retried_by_the_sweeper(
    client_factory: ClientFactory, postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = make_owner(client_factory)
    tk = new_ticket(owner)
    flaky = FlakyProvider(failures=1)
    monkeypatch.setattr(email_tasks, "get_provider", lambda: flaky)
    mid = _reply(owner, tk["id"]).json()["id"]
    row = _msg_row(postgres_url, mid)
    assert (row.delivery_status, row.delivery_attempts) == ("queued", 1)
    _age_all(postgres_url)
    assert requeue_stuck_outbound() == 1
    row = _msg_row(postgres_url, mid)
    assert (row.delivery_status, row.delivery_attempts) == ("sent", 2)
    assert flaky.calls == 2 and len(MemoryProvider.sent) == 1


def test_permanent_failure_is_marked_failed_and_visible(
    client_factory: ClientFactory, postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = make_owner(client_factory)
    tk = new_ticket(owner)
    monkeypatch.setattr(email_tasks, "get_provider", lambda: FlakyProvider(failures=99))
    mid = _reply(owner, tk["id"]).json()["id"]
    for _ in range(email_tasks.MAX_ATTEMPTS):
        _age_all(postgres_url)
        requeue_stuck_outbound()
    row = _msg_row(postgres_url, mid)
    assert (row.delivery_status, row.delivery_attempts) == ("failed", email_tasks.MAX_ATTEMPTS)
    assert requeue_stuck_outbound() == 0  # failed rows are not retried forever
    messages = owner.get(f"/api/tickets/{tk['id']}").json()["messages"]
    shown = next(m for m in messages if m["direction"] == "outbound")
    assert shown["delivery_status"] == "failed"


def test_stuck_queued_message_is_requeued_by_sweeper(
    client_factory: ClientFactory, postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = make_owner(client_factory)
    tk = new_ticket(owner)
    with monkeypatch.context() as m:  # simulate: the worker never picked the task up
        m.setattr(send_outbound_message, "delay", lambda *a, **k: None)
        mid = _reply(owner, tk["id"]).json()["id"]
    assert _msg_row(postgres_url, mid).delivery_status == "queued"
    assert requeue_stuck_outbound() == 0  # too fresh: the original task may still be in flight
    with engine_for(postgres_url).begin() as conn:
        conn.execute(
            text("update messages set created_at = now() - interval '5 minutes' where id = :i"),
            {"i": uuid.UUID(mid)},
        )
    assert requeue_stuck_outbound() == 1
    assert _msg_row(postgres_url, mid).delivery_status == "sent"
    assert len(MemoryProvider.sent) == 1


def test_beat_schedules_the_sweeper() -> None:
    entry = celery.conf.beat_schedule["requeue-stuck-outbound"]
    assert entry["task"] == "resolveflow.tasks.email.requeue_stuck_outbound"
    assert entry["schedule"] == 60.0


def test_internal_note_sends_nothing(client_factory: ClientFactory, postgres_url: str) -> None:
    owner = make_owner(client_factory)
    tk = new_ticket(owner)
    r = owner.post(
        f"/api/tickets/{tk['id']}/messages", {"body": "Call the supplier", "kind": "note"}
    )
    assert r.status_code == 200
    assert r.json()["direction"] == "internal" and r.json()["delivery_status"] == "none"
    assert MemoryProvider.sent == []


def test_reply_opens_new_ticket_and_can_set_pending(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    a, b = new_ticket(owner, "A"), new_ticket(owner, "B")
    _reply(owner, a["id"])
    assert owner.get(f"/api/tickets/{a['id']}").json()["status"] == "open"
    _reply(owner, b["id"], set_pending=True)
    assert owner.get(f"/api/tickets/{b['id']}").json()["status"] == "pending"


def test_validation_and_permissions(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    tk = new_ticket(t["owner"])
    assert _reply(t["owner"], tk["id"], body="").status_code == 422
    assert _reply(t["owner"], tk["id"], body="x" * 20001).status_code == 422
    assert (
        t["owner"]
        .post(f"/api/tickets/{tk['id']}/messages", {"body": "b", "kind": "sms"})
        .status_code
        == 422
    )
    assert _reply(t["viewer"], tk["id"]).status_code == 403
    assert _reply(t["agent"], tk["id"]).status_code == 200
    other = make_owner(client_factory, "Elsewhere")
    assert _reply(other, tk["id"]).status_code == 404


def test_message_is_audited(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    tk = new_ticket(owner)
    _reply(owner, tk["id"])
    actions = [a["action"] for a in owner.get(f"/api/tickets/{tk['id']}/activity").json()]
    assert "message.added" in actions

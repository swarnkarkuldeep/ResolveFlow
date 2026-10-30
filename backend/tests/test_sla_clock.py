import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from resolveflow.context import SystemContext
from resolveflow.db import engine_for, system_engine
from resolveflow.sla import service
from resolveflow.tenancy import tenant_session
from tests.helpers import Actor, ClientFactory, make_owner
from tests.test_ingest import DOMAIN, payload, post, token_of
from tests.test_tickets import new_ticket


def mon(hh: int, mm: int = 0, day: int = 2) -> datetime:
    """Mon 2026-11-02 by default (defaults are Mon-Fri 09:00-17:00 UTC, normal 8h/24h)."""
    return datetime(2026, 11, day, hh, mm, tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, datetime]]:
    state = {"now": mon(10)}
    monkeypatch.setattr(service, "utcnow", lambda: state["now"])
    yield state


def sla_row(url: str, ticket_id: str) -> Any:
    with engine_for(url).connect() as conn:
        return conn.execute(
            text("select * from ticket_sla where ticket_id = :t"), {"t": uuid.UUID(ticket_id)}
        ).one()


def kinds(url: str, ticket_id: str) -> list[str]:
    with engine_for(url).connect() as conn:
        return list(
            conn.execute(
                text("select kind from sla_events where ticket_id = :t order by at, id"),
                {"t": uuid.UUID(ticket_id)},
            ).scalars()
        )


def patch(actor: Actor, ticket_id: str, **fields: Any) -> None:
    r = actor.patch(f"/api/tickets/{ticket_id}", fields)
    assert r.status_code == 200, r.text


def reply(actor: Actor, ticket_id: str, kind: str = "public") -> None:
    r = actor.post(f"/api/tickets/{ticket_id}/messages", {"body": "Hello", "kind": kind})
    assert r.status_code == 200, r.text


def test_a_new_ticket_gets_business_hours_deadlines(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    row = sla_row(postgres_url, t["id"])
    assert row.start_at == mon(10)
    assert (row.fr_target_min, row.res_target_min) == (480, 1440)
    assert row.fr_due_at == mon(10, day=3)  # 8 business hours: 7h Monday + 1h Tuesday
    assert row.res_due_at == mon(10, day=5)  # 24 business hours: Mon 7h, Tue 8h, Wed 8h, Thu 1h
    assert row.paused_at is None and row.fr_met_at is None and row.res_met_at is None
    assert kinds(postgres_url, t["id"]) == ["started"]


def test_waiting_on_the_customer_pauses_and_resuming_pushes_the_deadline(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    clock["now"] = mon(12)
    patch(owner, t["id"], status="pending")
    paused = sla_row(postgres_url, t["id"])
    assert paused.paused_at == mon(12) and paused.fr_due_at is None and paused.next_check_at is None
    clock["now"] = mon(15)
    patch(owner, t["id"], status="open")
    resumed = sla_row(postgres_url, t["id"])
    assert resumed.paused_at is None
    assert resumed.fr_due_at == mon(13, day=3)  # three business hours of pause: Tue 10:00 -> 13:00
    assert kinds(postgres_url, t["id"]) == ["started", "paused", "resumed"]


def test_many_pause_cycles_accumulate(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    for start_h in (11, 13, 15):  # three one-hour pauses
        clock["now"] = mon(start_h)
        patch(owner, t["id"], status="pending")
        clock["now"] = mon(start_h + 1)
        patch(owner, t["id"], status="open")
    assert sla_row(postgres_url, t["id"]).fr_due_at == mon(13, day=3)


def test_first_agent_reply_meets_first_response_but_a_note_does_not(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    clock["now"] = mon(10, 30)
    reply(owner, t["id"], kind="note")
    assert sla_row(postgres_url, t["id"]).fr_met_at is None
    clock["now"] = mon(11)
    reply(owner, t["id"])
    row = sla_row(postgres_url, t["id"])
    assert row.fr_met_at == mon(11) and row.res_met_at is None
    clock["now"] = mon(11, 30)
    reply(owner, t["id"])
    assert sla_row(postgres_url, t["id"]).fr_met_at == mon(11)  # only the first counts
    assert kinds(postgres_url, t["id"]).count("first_response") == 1


def test_resolving_meets_resolution_and_reopening_restarts_that_clock(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    clock["now"] = mon(11)
    reply(owner, t["id"])
    clock["now"] = mon(13)
    patch(owner, t["id"], status="resolved")
    row = sla_row(postgres_url, t["id"])
    assert row.res_met_at == mon(13) and row.next_check_at is None
    clock["now"] = mon(9, day=3)  # Tuesday morning the customer comes back
    patch(owner, t["id"], status="open")
    row = sla_row(postgres_url, t["id"])
    assert row.res_met_at is None
    assert row.res_due_at == mon(
        17, day=5
    )  # 24 business hours from Tue 09:00: Tue 8h, Wed 8h, Thu 8h
    assert row.fr_met_at == mon(11)  # first response stays met
    assert kinds(postgres_url, t["id"]) == ["started", "first_response", "resolved", "reopened"]


def test_priority_change_recomputes_from_the_original_start_keeping_pauses(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    clock["now"] = mon(10, 30)
    patch(owner, t["id"], status="pending")
    clock["now"] = mon(11)
    patch(owner, t["id"], status="open")
    clock["now"] = mon(11, 5)
    patch(owner, t["id"], priority="urgent")  # urgent: first response 60, resolution 240
    row = sla_row(postgres_url, t["id"])
    assert (row.fr_target_min, row.res_target_min) == (60, 240)
    assert row.fr_due_at == mon(11, 30)  # 30 min before the pause + 30 min after it
    assert row.res_due_at == mon(14, 30)  # 240 business minutes + 30 min paused
    assert "priority_changed" in kinds(postgres_url, t["id"])


def test_a_customer_reply_to_a_waiting_ticket_resumes_the_clock(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    to = f"inbound-{token_of(postgres_url, owner)}@{DOMAIN}"
    created = post(client_factory(), payload(to, message_id="<c1@customer.test>")).json()
    tid = created["ticket_id"]
    clock["now"] = mon(12)
    patch(owner, tid, status="pending")
    assert sla_row(postgres_url, tid).paused_at == mon(12)
    clock["now"] = mon(14)
    r = post(
        client_factory(), payload(to, in_reply_to="<c1@customer.test>", subject="Re: Leaking tap")
    )
    assert r.json()["status"] == "appended"
    row = sla_row(postgres_url, tid)
    assert row.paused_at is None and row.fr_due_at is not None
    assert kinds(postgres_url, tid) == ["started", "paused", "resumed"]


def test_a_disabled_policy_means_no_deadlines(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    body = owner.get("/api/settings/sla").json()
    body.pop("version")
    body["enabled"] = False
    assert (
        owner.client.put(
            "/api/settings/sla", json=body, headers={"X-CSRF-Token": owner.csrf}
        ).status_code
        == 200
    )
    t = new_ticket(owner)
    row = sla_row(postgres_url, t["id"])
    assert row.fr_due_at is None and row.res_due_at is None and row.next_check_at is None


def test_merging_stops_the_source_clock(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    keep, dupe = new_ticket(owner, "Keep"), new_ticket(owner, "Dupe")
    clock["now"] = mon(11)
    assert (
        owner.post(f"/api/tickets/{dupe['id']}/merge", {"into_id": keep["id"]}).status_code == 200
    )
    assert sla_row(postgres_url, dupe["id"]).res_met_at == mon(11)
    assert sla_row(postgres_url, keep["id"]).res_met_at is None


def test_backfill_rebuilds_the_same_clock_from_history(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    tid = uuid.UUID(t["id"])
    with engine_for(
        postgres_url
    ).begin() as conn:  # make it look like a ticket from before SLA tracking
        conn.execute(text("delete from ticket_sla where ticket_id = :t"), {"t": tid})
        conn.execute(text("alter table sla_events disable trigger sla_events_no_change"))
        conn.execute(text("delete from sla_events where ticket_id = :t"), {"t": tid})
        conn.execute(text("alter table sla_events enable trigger sla_events_no_change"))
        conn.execute(
            text(
                "update tickets set created_at = :c, status = 'resolved', last_activity_at = :l where id = :t"
            ),
            {"c": mon(10), "l": mon(13), "t": tid},
        )
        conn.execute(
            text(
                "insert into messages (workspace_id, ticket_id, kind, direction, body, delivery_status, created_at) "
                "select workspace_id, id, 'public', 'outbound', 'We are on it', 'sent', :m from tickets where id = :t"
            ),
            {"m": mon(11), "t": tid},
        )
    with Session(system_engine()) as s, s.begin():
        ws = s.execute(
            text("select workspace_id from tickets where id = :t"), {"t": tid}
        ).scalar_one()
        service.backfill_events(SystemContext(s, ws), tid)
    row = sla_row(postgres_url, t["id"])
    assert row.start_at == mon(10) and row.fr_met_at == mon(11) and row.res_met_at == mon(13)
    assert row.fr_due_at == mon(10, day=3)
    assert kinds(postgres_url, t["id"]) == ["started", "first_response", "resolved"]


def test_the_event_stream_is_append_only_and_isolated(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    a = make_owner(client_factory, "Alpha")
    b = make_owner(client_factory, "Bravo")
    ta = new_ticket(a)
    with pytest.raises(DBAPIError), engine_for(postgres_url).begin() as conn:
        conn.execute(
            text("delete from sla_events where ticket_id = :t"), {"t": uuid.UUID(ta["id"])}
        )
    with pytest.raises(DBAPIError), engine_for(postgres_url).begin() as conn:
        conn.execute(
            text("update sla_events set kind = 'resolved' where ticket_id = :t"),
            {"t": uuid.UUID(ta["id"])},
        )
    with tenant_session(uuid.UUID(b.workspace_id), None) as s:
        assert s.execute(text("select count(*) from sla_events")).scalar_one() == 0
        assert s.execute(text("select count(*) from ticket_sla")).scalar_one() == 0

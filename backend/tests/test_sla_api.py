import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from resolveflow.db import system_engine
from resolveflow.sla import service, sweeper
from tests.helpers import Actor, ClientFactory, make_owner, team
from tests.test_tickets import new_ticket


def at(d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 11, d, hh, mm, tzinfo=UTC)  # day 2 is a Monday


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, datetime]]:
    state = {"now": at(2, 10)}
    monkeypatch.setattr(service, "utcnow", lambda: state["now"])
    yield state


def sweep(actor: Actor, now: datetime) -> None:
    sweeper.sweep(system_engine(), now=now, workspace_id=uuid.UUID(actor.workspace_id))


def sla_of(actor: Actor, ticket_id: str) -> dict:  # type: ignore[type-arg]
    return dict(actor.get(f"/api/tickets/{ticket_id}").json()["sla"])


def test_a_fresh_ticket_is_running_with_its_next_deadline(
    client_factory: ClientFactory, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    sla = sla_of(owner, t["id"])
    assert sla["state"] == "running"
    assert sla["first_response"] == {
        "due_at": at(3, 10).isoformat(),
        "met_at": None,
        "state": "running",
    }
    assert sla["resolution"]["due_at"] == at(5, 10).isoformat()
    assert sla["next_due_at"] == at(3, 10).isoformat()
    listed = owner.get("/api/tickets").json()["items"][0]["sla"]
    assert listed["state"] == "running" and listed["next_due_at"] == at(3, 10).isoformat()


def test_states_paused_met_at_risk_and_breached(
    client_factory: ClientFactory, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    paused, answered, risky, late = (
        new_ticket(owner, n) for n in ("Paused", "Answered", "Risky", "Late")
    )
    clock["now"] = at(2, 12)
    owner.patch(f"/api/tickets/{paused['id']}", {"status": "pending"})
    owner.post(f"/api/tickets/{answered['id']}/messages", {"body": "Hi", "kind": "public"})
    owner.patch(f"/api/tickets/{answered['id']}", {"status": "resolved"})
    assert sla_of(owner, paused["id"])["state"] == "paused"
    assert sla_of(owner, paused["id"])["next_due_at"] is None
    done = sla_of(owner, answered["id"])
    assert (
        done["state"] == "met"
        and done["first_response"]["state"] == "met"
        and done["resolution"]["state"] == "met"
    )
    sweep(owner, at(2, 16))  # 75% of the first-response target for the untouched tickets
    assert sla_of(owner, risky["id"])["state"] == "at_risk"
    assert sla_of(owner, risky["id"])["first_response"]["state"] == "at_risk"
    sweep(owner, at(3, 10))
    assert sla_of(owner, late["id"])["state"] == "breached"
    assert sla_of(owner, late["id"])["first_response"]["state"] == "breached"
    assert sla_of(owner, late["id"])["resolution"]["state"] == "running"


def test_queue_filters_for_at_risk_and_breached(
    client_factory: ClientFactory, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    risky = new_ticket(owner, "Risky")
    clock["now"] = at(2, 13)
    late = new_ticket(owner, "Late")  # started Mon 13:00, so it is not yet at risk at Mon 16:00
    healthy = new_ticket(owner, "Healthy")
    sweep(owner, at(2, 16))
    assert {i["id"] for i in owner.get("/api/tickets?sla=at_risk").json()["items"]} == {risky["id"]}
    sweep(
        owner, at(3, 10)
    )  # Risky breaches; Late and Healthy (started 13:00) pass 75% at Tue 11:00 not yet
    assert {i["id"] for i in owner.get("/api/tickets?sla=breached").json()["items"]} == {
        risky["id"]
    }
    assert owner.get("/api/tickets?sla=at_risk").json()["items"] == []
    sweep(owner, at(3, 11))
    assert {i["id"] for i in owner.get("/api/tickets?sla=at_risk").json()["items"]} == {
        late["id"],
        healthy["id"],
    }
    page = owner.get("/api/tickets?sla=at_risk&limit=1").json()
    assert len(page["items"]) == 1 and page["next_cursor"]
    # Re-prioritising starts a fresh cycle, so the ticket leaves the at-risk view.
    owner.patch(f"/api/tickets/{late['id']}", {"priority": "urgent"})
    assert {i["id"] for i in owner.get("/api/tickets?sla=at_risk").json()["items"]} == {
        healthy["id"]
    }
    assert owner.get("/api/tickets?sla=nonsense").status_code == 422


def test_resolved_tickets_are_never_in_the_risk_views(
    client_factory: ClientFactory, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    sweep(owner, at(3, 10))
    assert {i["id"] for i in owner.get("/api/tickets?sla=breached").json()["items"]} == {t["id"]}
    owner.patch(f"/api/tickets/{t['id']}", {"status": "resolved"})
    owner.post(f"/api/tickets/{t['id']}/messages", {"body": "Sorry for the wait", "kind": "public"})
    assert owner.get("/api/tickets?sla=breached").json()["items"] == []


def test_the_explainer_shows_the_numbers_behind_the_deadline(
    client_factory: ClientFactory, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    clock["now"] = at(2, 12)
    owner.patch(f"/api/tickets/{t['id']}", {"status": "pending"})
    clock["now"] = at(2, 15)
    owner.patch(f"/api/tickets/{t['id']}", {"status": "open"})
    clock["now"] = at(3, 11)
    r = owner.get(f"/api/tickets/{t['id']}/sla")
    assert r.status_code == 200, r.text
    x = r.json()
    assert x["policy"]["business_hours_only"] is True and x["policy"]["priority"] == "normal"
    assert x["policy"]["targets"] == {"first_response_minutes": 480, "resolution_minutes": 1440}
    assert (
        x["calendar"]["timezone"] == "UTC"
        and x["calendar"]["schedule_text"] == "Mon–Fri 09:00–17:00"
    )
    fr = next(m for m in x["metrics"] if m["key"] == "first_response")
    assert fr["target_minutes"] == 480 and fr["state"] == "running"
    assert (
        fr["due_at"] == at(3, 13).isoformat()
    )  # Tue 10:00 pushed three business hours by the pause
    # Mon 10-12 (120) + Mon 15-17 (120) + Tue 9-11 (120) of running time.
    assert fr["elapsed_minutes"] == pytest.approx(360)
    assert fr["paused_minutes"] == pytest.approx(180)
    texts = [e["text"] for e in x["events"]]
    assert (
        texts[0] == "Clock started"
        and "Paused: waiting on the customer" in texts
        and "Resumed" in texts
    )


def test_explainer_describes_threshold_events_in_plain_language(
    client_factory: ClientFactory, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    sweep(owner, at(2, 16))
    sweep(owner, at(3, 10))
    texts = [e["text"] for e in owner.get(f"/api/tickets/{t['id']}/sla").json()["events"]]
    assert "Warning: 75% of the first response target used" in texts
    assert "Breached: the first response target of 8 h was missed" in texts


def test_viewers_can_read_it_and_other_workspaces_cannot(
    client_factory: ClientFactory, clock: dict[str, datetime]
) -> None:
    t = team(client_factory)
    tk = new_ticket(t["owner"])
    assert t["viewer"].get(f"/api/tickets/{tk['id']}/sla").status_code == 200
    other = make_owner(client_factory, "Elsewhere")
    assert other.get(f"/api/tickets/{tk['id']}/sla").status_code == 404
    assert other.get(f"/api/tickets/{uuid.uuid4()}/sla").status_code == 404


def test_a_disabled_policy_reports_no_sla(
    client_factory: ClientFactory, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    body = owner.get("/api/settings/sla").json()
    body.pop("version")
    body["enabled"] = False
    owner.client.put("/api/settings/sla", json=body, headers={"X-CSRF-Token": owner.csrf})
    t = new_ticket(owner)
    sla = sla_of(owner, t["id"])
    assert sla["state"] == "none" and sla["next_due_at"] is None
    assert sla["first_response"]["state"] == "none"

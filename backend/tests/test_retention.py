import uuid
from typing import Any

from sqlalchemy import text

from resolveflow import retention
from resolveflow.db import engine_for, system_engine
from tests.helpers import ClientFactory, make_owner, team
from tests.test_tickets import new_ticket


def age(url: str, ticket_id: str, days: int, status: str = "resolved") -> None:
    with engine_for(url).begin() as conn:
        conn.execute(
            text(
                "update tickets set status = :s, last_activity_at = now() - make_interval(days => :d) "
                "where id = :t"
            ),
            {"s": status, "d": days, "t": uuid.UUID(ticket_id)},
        )


def put(actor: Any, days: int | None) -> Any:
    return actor.client.put(
        "/api/settings/privacy", json={"retention_days": days}, headers={"X-CSRF-Token": actor.csrf}
    )


def test_policy_is_validated_audited_and_limited_to_admins(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    owner = t["owner"]
    assert owner.get("/api/settings/privacy").json() == {
        "retention_days": None,
        "eligible_tickets": 0,
    }
    assert put(owner, 5).status_code == 422
    assert put(owner, 20000).status_code == 422
    assert put(owner, 90).json()["retention_days"] == 90
    assert put(t["agent"], 60).status_code == 403
    assert t["agent"].post("/api/settings/privacy/apply", {}).status_code == 403
    assert put(owner, None).json()["retention_days"] is None
    actions = [e["action"] for e in owner.get("/api/audit").json()["items"]]
    assert actions.count("retention.policy_changed") == 2


def test_old_finished_tickets_are_redacted_and_recent_or_open_ones_are_not(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    old = new_ticket(owner, "Secret boiler details")
    recent = new_ticket(owner, "Recent resolved")
    open_old = new_ticket(owner, "Still open but old")
    age(postgres_url, old["id"], 200)
    age(postgres_url, recent["id"], 5)
    age(postgres_url, open_old["id"], 200, status="open")
    put(owner, 90)
    assert owner.get("/api/settings/privacy").json()["eligible_tickets"] == 1
    out = owner.post("/api/settings/privacy/apply", {}).json()
    assert out["tickets"] == 1 and out["customers"] == 1 and out["eligible_tickets"] == 0

    got = owner.get(f"/api/tickets/{old['id']}").json()
    assert got["subject"].endswith("(content removed)") and got["subject"].startswith("Ticket #")
    assert all(m["body"] == retention.REMOVED for m in got["messages"])
    assert got["requester"]["name"] is None and got["requester"]["email"].endswith(
        "@redacted.invalid"
    )
    assert owner.get(f"/api/tickets/{recent['id']}").json()["subject"] == "Recent resolved"
    assert owner.get(f"/api/tickets/{open_old['id']}").json()["subject"] == "Still open but old"
    # the redacted text is gone from search too
    assert owner.get("/api/search", params={"q": "boiler"}).json()["items"] == []


def test_a_customer_with_a_live_ticket_keeps_their_identity_and_apply_is_idempotent(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    email = "repeat@customer.test"
    a = owner.post("/api/tickets", {"subject": "A", "body": "x", "requester_email": email}).json()
    owner.post("/api/tickets", {"subject": "B", "body": "y", "requester_email": email})
    age(postgres_url, a["id"], 400)
    put(owner, 30)
    first = owner.post("/api/settings/privacy/apply", {}).json()
    assert first["tickets"] == 1 and first["customers"] == 0
    assert owner.get(f"/api/tickets/{a['id']}").json()["requester"]["email"] == email
    second = owner.post("/api/settings/privacy/apply", {}).json()
    assert second["tickets"] == 0


def test_the_scheduled_job_applies_every_workspace_policy_and_only_those(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    with_policy = make_owner(client_factory, "Policy Co")
    without = make_owner(client_factory, "No Policy Co")
    a = new_ticket(with_policy, "Old A")
    b = new_ticket(without, "Old B")
    age(postgres_url, a["id"], 400)
    age(postgres_url, b["id"], 400)
    put(with_policy, 30)
    assert retention.apply_all(system_engine()) >= 1
    assert (
        with_policy.get(f"/api/tickets/{a['id']}").json()["subject"].endswith("(content removed)")
    )
    assert without.get(f"/api/tickets/{b['id']}").json()["subject"] == "Old B"

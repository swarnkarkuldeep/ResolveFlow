import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from resolveflow.db import engine_for
from tests.helpers import ClientFactory, make_owner, team
from tests.test_tickets import new_ticket


def sla_row(url: str, ticket_id: str, **cols: Any) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in cols)
    with engine_for(url).begin() as conn:
        conn.execute(
            text(f"update ticket_sla set {sets} where ticket_id = :t"),  # noqa: S608
            {**cols, "t": uuid.UUID(ticket_id)},
        )


def test_empty_workspace_returns_zeros_not_errors(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    data = owner.get("/api/analytics", params={"days": 30}).json()
    assert data["totals"] == {"created": 0, "resolved": 0, "open_now": 0}
    assert data["sla"]["first_response"] == {"measured": 0, "met": 0, "compliance_pct": None}
    assert data["averages"] == {"first_response_minutes": None, "resolution_minutes": None}
    assert len(data["by_day"]) == 30 and all(d["created"] == 0 for d in data["by_day"])
    assert data["by_priority"] == [] and data["by_channel"] == [] and data["by_agent"] == []


def test_counts_compliance_and_averages_are_exact(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    t = team(client_factory)
    owner, agent = t["owner"], t["agent"]
    now = datetime.now(UTC)
    a = new_ticket(owner, "A", priority="high")
    b = new_ticket(owner, "B")
    c = new_ticket(owner, "C")
    new_ticket(owner, "D")  # no SLA outcome yet
    owner.patch(f"/api/tickets/{a['id']}", {"assignee_id": agent.user_id})
    owner.patch(f"/api/tickets/{a['id']}", {"status": "resolved"})
    owner.patch(f"/api/tickets/{b['id']}", {"assignee_id": agent.user_id})
    start = now - timedelta(hours=5)
    # A: first response after 30 min (met), resolved after 120 min. B: first response missed. C: met after 90 min.
    sla_row(
        postgres_url,
        a["id"],
        start_at=start,
        fr_met_at=start + timedelta(minutes=30),
        res_met_at=start + timedelta(minutes=120),
    )
    sla_row(
        postgres_url,
        b["id"],
        start_at=start,
        fr_breached_at=start + timedelta(hours=1),
        fr_met_at=start + timedelta(hours=2),
    )
    sla_row(postgres_url, c["id"], start_at=start, fr_met_at=start + timedelta(minutes=90))

    data = owner.get("/api/analytics", params={"days": 7}).json()
    assert data["totals"]["created"] == 4 and data["totals"]["resolved"] == 1
    assert data["totals"]["open_now"] == 3
    fr = data["sla"]["first_response"]
    assert fr == {"measured": 3, "met": 2, "compliance_pct": 66.7}
    assert data["sla"]["breached"] == 1
    assert data["averages"]["first_response_minutes"] == 80.0  # (30 + 120 + 90) / 3
    assert data["averages"]["resolution_minutes"] == 120.0
    assert {p["priority"]: p["count"] for p in data["by_priority"]} == {"high": 1, "normal": 3}
    assert {c["channel"]: c["count"] for c in data["by_channel"]} == {"manual": 4}
    agents = {x["agent"]: x for x in data["by_agent"]}
    assert agents[agent.name]["assigned"] == 2 and agents[agent.name]["resolved"] == 1
    assert sum(d["created"] for d in data["by_day"]) == 4


def test_the_range_excludes_older_tickets_and_rejects_bad_ranges(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    old = new_ticket(owner, "Old")
    new_ticket(owner, "Recent")
    with engine_for(postgres_url).begin() as conn:
        conn.execute(
            text("update tickets set created_at = now() - interval '40 days' where id = :t"),
            {"t": uuid.UUID(old["id"])},
        )
    assert owner.get("/api/analytics", params={"days": 30}).json()["totals"]["created"] == 1
    assert owner.get("/api/analytics", params={"days": 90}).json()["totals"]["created"] == 2
    assert owner.get("/api/analytics", params={"days": 5}).status_code == 422


def test_analytics_is_for_owners_and_admins_and_never_counts_other_workspaces(
    client_factory: ClientFactory,
) -> None:
    t = team(client_factory)
    other = make_owner(client_factory, "Other Co")
    new_ticket(other, "Not mine")
    new_ticket(t["owner"], "Mine")
    assert t["admin"].get("/api/analytics").status_code == 200
    assert t["agent"].get("/api/analytics").status_code == 403
    assert t["viewer"].get("/api/analytics").status_code == 403
    assert t["owner"].get("/api/analytics").json()["totals"]["created"] == 1


def test_customer_history_lists_their_tickets_newest_first_and_stays_in_the_workspace(
    client_factory: ClientFactory,
) -> None:
    t = team(client_factory)
    owner = t["owner"]
    email = "repeat@customer.test"
    ids = []
    for subject in ("First", "Second"):
        r = owner.post(
            "/api/tickets",
            {
                "subject": subject,
                "body": "Hello there",
                "requester_email": email,
                "requester_name": "Rae Peat",
            },
        )
        ids.append(r.json())
    other_person = new_ticket(owner, "Someone else")
    cid = ids[0]["requester"]["id"]
    data = t["viewer"].get(f"/api/customers/{cid}").json()
    assert data["customer"]["email"] == email and data["customer"]["name"] == "Rae Peat"
    assert [x["subject"] for x in data["tickets"]] == ["Second", "First"]
    assert data["stats"] == {"total": 2, "open": 2}
    assert other_person["id"] not in [x["id"] for x in data["tickets"]]
    stranger = make_owner(client_factory, "Other Co")
    assert stranger.get(f"/api/customers/{cid}").status_code == 404

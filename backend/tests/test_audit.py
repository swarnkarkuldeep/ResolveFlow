import csv
import io
from datetime import UTC, datetime, timedelta

from tests.helpers import ClientFactory, invite_actor, make_owner, team
from tests.test_tickets import new_ticket


def test_audit_lists_newest_first_with_actor_names(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    tk = new_ticket(owner)
    owner.patch(f"/api/tickets/{tk['id']}", {"priority": "urgent"})
    page = owner.get("/api/audit").json()
    actions = [e["action"] for e in page["items"]]
    assert actions[:2] == ["ticket.updated", "ticket.created"] and "workspace.created" in actions
    top = page["items"][0]
    assert top["actor_name"] == "Olive Owner" and top["entity_type"] == "ticket"
    assert top["before"] == {"priority": "normal"} and top["after"] == {"priority": "urgent"}


def test_audit_filters_and_pagination(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    tk = new_ticket(t["agent"])
    t["agent"].patch(f"/api/tickets/{tk['id']}", {"status": "pending"})
    owner = t["owner"]
    only_tickets = owner.get("/api/audit?entity_type=ticket").json()["items"]
    assert only_tickets and all(e["entity_type"] == "ticket" for e in only_tickets)
    by_action = owner.get("/api/audit?action=ticket.updated").json()["items"]
    assert [e["action"] for e in by_action] == ["ticket.updated"]
    by_actor = owner.get(f"/api/audit?actor_id={t['agent'].user_id}").json()["items"]
    assert len(by_actor) == 3 and all(e["actor_name"] == "Agent Person" for e in by_actor)
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert owner.get("/api/audit", params={"from": future}).json()["items"] == []
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert owner.get("/api/audit", params={"from": past}).json()["items"]

    seen: list[str] = []
    cursor = None
    for _ in range(20):
        qs = "limit=2" + (f"&cursor={cursor}" if cursor else "")
        page = owner.get(f"/api/audit?{qs}").json()
        seen += [e["id"] for e in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    total = owner.get("/api/audit?limit=200").json()["items"]
    assert len(seen) == len(set(seen)) == len(total)


def test_only_owner_and_admin_can_read_audit(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    for role, want in {"owner": 200, "admin": 200, "agent": 403, "viewer": 403}.items():
        assert t[role].get("/api/audit").status_code == want
        assert t[role].get("/api/audit.csv").status_code == want


def test_audit_is_isolated_between_workspaces(client_factory: ClientFactory) -> None:
    a = make_owner(client_factory, "Alpha")
    b = make_owner(client_factory, "Bravo")
    new_ticket(a, "Secret subject")
    b_items = b.get("/api/audit?limit=200").json()["items"]
    assert all("Secret subject" not in str(e["after"]) for e in b_items)
    assert all(e["action"] == "workspace.created" for e in b_items)


def test_csv_export_has_header_and_neutralises_formulas(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    agent = invite_actor(owner, client_factory, "agent", name="=SUM(1+1)")
    new_ticket(agent, "Leaking tap")
    r = owner.get("/api/audit.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["time", "actor", "action", "entity_type", "entity_id", "before", "after"]
    created = next(row for row in rows if row[2] == "ticket.created")
    assert created[1] == "'=SUM(1+1)"
    assert all(not cell.startswith(("=", "+", "@")) for row in rows for cell in row)


def test_channel_settings(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    me = t["owner"].get("/api/auth/me").json()
    slug = me["active_workspace"]["slug"]
    s = t["owner"].get("/api/settings/channels").json()
    assert s["inbound_address"].startswith("inbound-") and s["inbound_address"].endswith(
        "@inbound.resolveflow.local"
    )
    assert s["form_url"] == f"http://localhost:3000/form/{slug}"
    assert s["form_url"] in s["form_snippet"] and s["form_snippet"].startswith("<iframe")
    assert s["simulate_enabled"] is True
    assert t["admin"].get("/api/settings/channels").status_code == 200
    assert t["agent"].get("/api/settings/channels").status_code == 403

import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import text

from resolveflow.db import engine_for
from resolveflow.main import app
from tests.helpers import Actor, ClientFactory, make_owner, team, unique_email


def new_ticket(actor: Actor, subject: str = "Leaking tap", **extra: object) -> dict:
    body = {
        "subject": subject,
        "body": "Water is dripping under the sink.",
        "requester_email": unique_email("cust"),
        "requester_name": "Cora Customer",
        **extra,
    }
    r = actor.post("/api/tickets", body)
    assert r.status_code == 200, r.text
    return r.json()


def test_numbers_are_per_workspace(client_factory: ClientFactory) -> None:
    a = make_owner(client_factory, "Alpha")
    b = make_owner(client_factory, "Bravo")
    assert [new_ticket(a)["number"], new_ticket(a)["number"]] == [1, 2]
    assert new_ticket(b)["number"] == 1


def test_concurrent_creates_get_unique_consecutive_numbers(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)

    def create(i: int) -> int:
        c = TestClient(app)
        c.cookies.set("rf_session", owner.client.cookies["rf_session"])
        r = c.post(
            "/api/tickets",
            json={"subject": f"T{i}", "body": "b", "requester_email": unique_email("c")},
            headers={"X-CSRF-Token": owner.csrf},
        )
        assert r.status_code == 200, r.text
        return int(r.json()["number"])

    with ThreadPoolExecutor(8) as pool:
        numbers = sorted(pool.map(create, range(8)))
    assert numbers == list(range(1, 9))


def test_created_ticket_shape_and_first_message(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner, priority="high")
    assert t["status"] == "new" and t["priority"] == "high" and t["channel"] == "manual"
    detail = owner.get(f"/api/tickets/{t['id']}").json()
    assert detail["requester"]["name"] == "Cora Customer"
    assert len(detail["messages"]) == 1
    m = detail["messages"][0]
    assert m["direction"] == "inbound" and m["kind"] == "public" and "dripping" in m["body"]


def test_list_filters(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    owner, agent = t["owner"], t["agent"]
    mine = new_ticket(owner, "Mine")
    unassigned = new_ticket(owner, "Unassigned")
    owner.patch(f"/api/tickets/{mine['id']}", {"assignee_id": owner.user_id, "tags": ["billing"]})
    owner.patch(f"/api/tickets/{unassigned['id']}", {"status": "resolved", "priority": "urgent"})

    def ids(qs: str, who: Actor = owner) -> set[str]:
        return {i["id"] for i in who.get(f"/api/tickets?{qs}").json()["items"]}

    assert ids("assignee=me") == {mine["id"]}
    assert ids("assignee=me", agent) == set()
    assert ids("assignee=none") == {unassigned["id"]}
    assert ids(f"assignee={owner.user_id}") == {mine["id"]}
    assert ids("status=resolved") == {unassigned["id"]}
    assert ids("status=new,open") == {mine["id"]}
    assert ids("priority=urgent") == {unassigned["id"]}
    assert ids("tag=billing") == {mine["id"]}
    item = next(i for i in owner.get("/api/tickets").json()["items"] if i["id"] == mine["id"])
    assert item["tags"] == ["billing"] and item["assignee"]["name"] == "Olive Owner"
    assert item["snippet"].startswith("Water is dripping")


def test_keyset_pagination_returns_each_ticket_once_newest_first(
    client_factory: ClientFactory,
) -> None:
    owner = make_owner(client_factory)
    created = [new_ticket(owner, f"T{i}")["id"] for i in range(7)]
    seen: list[str] = []
    cursor = None
    for _ in range(10):
        qs = "limit=3" + (f"&cursor={cursor}" if cursor else "")
        page = owner.get(f"/api/tickets?{qs}").json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert sorted(seen) == sorted(created) and len(seen) == len(set(seen))
    assert seen == list(reversed(created))  # newest activity first


def test_patch_is_audited_with_before_and_after(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    r = owner.patch(f"/api/tickets/{t['id']}", {"priority": "urgent", "status": "pending"})
    assert r.status_code == 200 and r.json()["priority"] == "urgent"
    activity = owner.get(f"/api/tickets/{t['id']}/activity").json()
    updated = next(a for a in activity if a["action"] == "ticket.updated")
    assert updated["before"] == {"priority": "normal", "status": "new"}
    assert updated["after"] == {"priority": "urgent", "status": "pending"}
    assert updated["actor_name"] == "Olive Owner"
    assert any(a["action"] == "ticket.created" for a in activity)


def test_assign_validations_and_auto_open(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    tk = new_ticket(t["owner"])
    outsider = make_owner(client_factory, "Elsewhere")
    assert (
        t["owner"].patch(f"/api/tickets/{tk['id']}", {"assignee_id": outsider.user_id}).status_code
        == 422
    )
    viewer_id = t["viewer"].user_id
    t["owner"].patch(f"/api/members/{viewer_id}", {"active": False})
    deactivated = t["owner"].patch(f"/api/tickets/{tk['id']}", {"assignee_id": viewer_id})
    assert deactivated.status_code == 422
    ok = t["owner"].patch(f"/api/tickets/{tk['id']}", {"assignee_id": t["agent"].user_id})
    assert ok.status_code == 200 and ok.json()["status"] == "open"
    cleared = t["owner"].patch(f"/api/tickets/{tk['id']}", {"assignee_id": None})
    assert cleared.json()["assignee"] is None


def test_tags_replace_set(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    tk = new_ticket(owner)
    owner.patch(f"/api/tickets/{tk['id']}", {"tags": ["vip", "billing"]})
    assert owner.get(f"/api/tickets/{tk['id']}").json()["tags"] == ["billing", "vip"]
    owner.patch(f"/api/tickets/{tk['id']}", {"tags": ["vip"]})
    assert owner.get(f"/api/tickets/{tk['id']}").json()["tags"] == ["vip"]


def test_role_permissions_on_tickets(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    tk = new_ticket(t["owner"])
    assert t["viewer"].get(f"/api/tickets/{tk['id']}").status_code == 200
    assert t["viewer"].patch(f"/api/tickets/{tk['id']}", {"priority": "low"}).status_code == 403
    assert (
        t["viewer"]
        .post("/api/tickets", {"subject": "s", "body": "b", "requester_email": "c@x.test"})
        .status_code
        == 403
    )
    assert t["agent"].patch(f"/api/tickets/{tk['id']}", {"priority": "low"}).status_code == 200


def test_foreign_ticket_ids_are_404(client_factory: ClientFactory) -> None:
    a = make_owner(client_factory, "Alpha")
    b = make_owner(client_factory, "Bravo")
    tk = new_ticket(a)
    assert b.get(f"/api/tickets/{tk['id']}").status_code == 404
    assert b.patch(f"/api/tickets/{tk['id']}", {"priority": "low"}).status_code == 404
    assert b.get(f"/api/tickets/{tk['id']}/activity").status_code == 404
    assert b.get(f"/api/tickets/{uuid.uuid4()}").status_code == 404


def test_validation_errors(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    tk = new_ticket(owner)
    assert owner.patch(f"/api/tickets/{tk['id']}", {"status": "bogus"}).status_code == 422
    assert owner.patch(f"/api/tickets/{tk['id']}", {"priority": "bogus"}).status_code == 422
    assert owner.patch(f"/api/tickets/{tk['id']}", {}).status_code == 422
    assert (
        owner.post(
            "/api/tickets", {"subject": "", "body": "b", "requester_email": "c@x.test"}
        ).status_code
        == 422
    )
    assert owner.get("/api/tickets?limit=1000").status_code == 422


def test_customer_is_reused_per_email(client_factory: ClientFactory, postgres_url: str) -> None:
    owner = make_owner(client_factory)
    for subject in ("One", "Two"):
        owner.post(
            "/api/tickets",
            {"subject": subject, "body": "b", "requester_email": "same@customer.test"},
        )
    with engine_for(postgres_url).connect() as conn:
        n = conn.execute(
            text("select count(*) from customers where email = 'same@customer.test'")
        ).scalar_one()
    assert n == 1

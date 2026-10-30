import uuid

from sqlalchemy import text

from resolveflow.db import engine_for
from tests.helpers import ClientFactory, make_owner, team, unique_email
from tests.test_tickets import new_ticket


def _audit_count(actor, ticket_id: str, action: str = "ticket.updated") -> int:  # type: ignore[no-untyped-def]
    return sum(
        1 for a in actor.get(f"/api/tickets/{ticket_id}/activity").json() if a["action"] == action
    )


def test_bulk_status_updates_all_with_one_audit_row_each(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    ids = [new_ticket(owner, f"T{i}")["id"] for i in range(3)]
    r = owner.post("/api/tickets/bulk", {"ids": ids, "action": "status", "value": "resolved"})
    assert r.status_code == 200, r.text
    assert sorted(r.json()["updated"]) == sorted(ids) and r.json()["skipped"] == []
    for i in ids:
        assert owner.get(f"/api/tickets/{i}").json()["status"] == "resolved"
        assert _audit_count(owner, i) == 1


def test_bulk_never_touches_foreign_tickets(client_factory: ClientFactory) -> None:
    a = make_owner(client_factory, "Alpha")
    b = make_owner(client_factory, "Bravo")
    mine, theirs = new_ticket(a)["id"], new_ticket(b)["id"]
    ghost = str(uuid.uuid4())
    r = a.post(
        "/api/tickets/bulk", {"ids": [mine, theirs, ghost], "action": "priority", "value": "urgent"}
    )
    assert r.status_code == 200
    assert r.json()["updated"] == [mine]
    assert sorted(r.json()["skipped"]) == sorted([theirs, ghost])
    assert b.get(f"/api/tickets/{theirs}").json()["priority"] == "normal"


def test_bulk_limits_and_validation(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    too_many = [str(uuid.uuid4()) for _ in range(201)]
    assert (
        owner.post(
            "/api/tickets/bulk", {"ids": too_many, "action": "status", "value": "open"}
        ).status_code
        == 422
    )
    one = new_ticket(owner)["id"]
    assert (
        owner.post(
            "/api/tickets/bulk", {"ids": [one], "action": "status", "value": "bogus"}
        ).status_code
        == 422
    )
    assert (
        owner.post(
            "/api/tickets/bulk", {"ids": [one], "action": "explode", "value": "x"}
        ).status_code
        == 422
    )
    assert (
        owner.post(
            "/api/tickets/bulk", {"ids": [], "action": "status", "value": "open"}
        ).status_code
        == 422
    )
    stranger = make_owner(client_factory, "Elsewhere")
    bad = owner.post(
        "/api/tickets/bulk", {"ids": [one], "action": "assign", "value": stranger.user_id}
    )
    assert bad.status_code == 422


def test_bulk_assign_and_add_tag_keep_existing_tags(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    tk = new_ticket(t["owner"])["id"]
    t["owner"].patch(f"/api/tickets/{tk}", {"tags": ["billing"]})
    t["agent"].post("/api/tickets/bulk", {"ids": [tk], "action": "add_tag", "value": "vip"})
    t["agent"].post(
        "/api/tickets/bulk", {"ids": [tk], "action": "assign", "value": t["agent"].user_id}
    )
    got = t["owner"].get(f"/api/tickets/{tk}").json()
    assert got["tags"] == ["billing", "vip"] and got["assignee"]["name"] == "Agent Person"


def test_viewer_cannot_bulk(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    tk = new_ticket(t["owner"])["id"]
    assert (
        t["viewer"]
        .post("/api/tickets/bulk", {"ids": [tk], "action": "status", "value": "open"})
        .status_code
        == 403
    )


def test_merge_moves_messages_and_closes_source(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    target = new_ticket(owner, "Original", requester_email="dup@customer.test")
    source = new_ticket(owner, "Same thing again", requester_email="dup@customer.test")
    owner.patch(f"/api/tickets/{source['id']}", {"tags": ["urgent-call"]})
    owner.post(f"/api/tickets/{source['id']}/messages", {"body": "Looking into it", "kind": "note"})
    r = owner.post(f"/api/tickets/{source['id']}/merge", {"into_id": target["id"]})
    assert r.status_code == 200, r.text
    merged_source = owner.get(f"/api/tickets/{source['id']}").json()
    assert merged_source["status"] == "closed" and merged_source["merged_into_id"] == target["id"]
    assert merged_source["messages"] == []
    detail = owner.get(f"/api/tickets/{target['id']}").json()
    bodies = [m["body"] for m in detail["messages"]]
    assert bodies[0].startswith("Water is dripping") and "Looking into it" in bodies
    assert any("Merged ticket" in b for b in bodies)  # explanatory internal note
    assert detail["tags"] == ["urgent-call"]
    assert _audit_count(owner, target["id"], "ticket.merged") == 1


def test_merge_rejects_self_chains_and_foreign(client_factory: ClientFactory) -> None:
    a = make_owner(client_factory, "Alpha")
    b = make_owner(client_factory, "Bravo")
    one, two, three = (new_ticket(a, s)["id"] for s in ("One", "Two", "Three"))
    foreign = new_ticket(b)["id"]
    assert a.post(f"/api/tickets/{one}/merge", {"into_id": one}).status_code == 422
    assert a.post(f"/api/tickets/{one}/merge", {"into_id": two}).status_code == 200
    assert (
        a.post(f"/api/tickets/{three}/merge", {"into_id": one}).status_code == 422
    )  # target already merged
    assert (
        a.post(f"/api/tickets/{one}/merge", {"into_id": three}).status_code == 422
    )  # source already merged
    assert a.post(f"/api/tickets/{three}/merge", {"into_id": foreign}).status_code == 404
    assert a.post(f"/api/tickets/{foreign}/merge", {"into_id": three}).status_code == 404


def test_viewer_cannot_merge(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    x, y = new_ticket(t["owner"])["id"], new_ticket(t["owner"])["id"]
    assert t["viewer"].post(f"/api/tickets/{x}/merge", {"into_id": y}).status_code == 403


def test_duplicate_flag_heuristic(client_factory: ClientFactory, postgres_url: str) -> None:
    owner = make_owner(client_factory)
    first = new_ticket(owner, "Invoice", requester_email="pat@customer.test")
    again = new_ticket(owner, "Re: Invoice", requester_email="pat@customer.test")
    assert again["possible_duplicate_of"] == first["id"]
    other_person = new_ticket(owner, "Invoice", requester_email=unique_email("someone"))
    assert other_person["possible_duplicate_of"] is None
    with engine_for(postgres_url).begin() as conn:
        conn.execute(
            text(
                "update tickets set created_at = now() - interval '3 days' where lower(subject) like '%invoice%'"
            )
        )
    later = new_ticket(owner, "FWD:  invoice ", requester_email="pat@customer.test")
    assert later["possible_duplicate_of"] is None
    assert (
        new_ticket(owner, "Something else", requester_email="pat@customer.test")[
            "possible_duplicate_of"
        ]
        is None
    )

import pytest

from tests.helpers import ClientFactory, make_owner, team
from tests.test_tickets import new_ticket


def search(actor, q: str, extra: str = "") -> list[dict]:
    r = actor.get("/api/search", params={"q": q})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_finds_by_subject_and_by_message_text_and_ranks_subject_first(
    client_factory: ClientFactory,
) -> None:
    owner = make_owner(client_factory)
    in_body = new_ticket(owner, "Unrelated title")  # body: "Water is dripping under the sink."
    in_subject = new_ticket(owner, "Dripping faucet in kitchen")
    hits = search(owner, "dripping")
    assert [h["id"] for h in hits][:2] == [in_subject["id"], in_body["id"]]
    assert hits[0]["match"] == "subject" and hits[1]["match"] == "message"
    assert "<mark>dripping</mark>" in hits[1]["snippet_html"].lower()


def test_snippet_escapes_html_from_customers(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    r = owner.post(
        "/api/tickets",
        {
            "subject": "Plain",
            "body": "<script>alert(1)</script> Fix the boiler & pipes today",
            "requester_email": "a@customer.test",
        },
    )
    assert r.status_code == 200
    hit = search(owner, "boiler")[0]
    assert "<script>" not in hit["snippet_html"]
    assert "boiler</mark> &amp; pipes" in hit["snippet_html"]
    assert "<mark>boiler</mark>" in hit["snippet_html"]


@pytest.mark.parametrize(
    "q", ['"unterminated', "a & b | !c", "((", "💥", "x" * 500, "-", "'; drop table tickets;--"]
)
def test_odd_queries_never_error(client_factory: ClientFactory, q: str) -> None:
    owner = make_owner(client_factory)
    new_ticket(owner)
    assert owner.get("/api/search", params={"q": q}).status_code == 200


def test_empty_query_is_rejected(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    assert owner.get("/api/search", params={"q": "   "}).status_code == 422
    assert owner.get("/api/search").status_code == 422


def test_filters_combine_with_search(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    a = new_ticket(owner, "Boiler broken", priority="urgent")
    new_ticket(owner, "Boiler noisy", priority="low")
    owner.patch(f"/api/tickets/{a['id']}", {"tags": ["gas"]})
    ids = [
        h["id"]
        for h in owner.get("/api/search", params={"q": "boiler", "priority": "urgent"}).json()[
            "items"
        ]
    ]
    assert ids == [a["id"]]
    ids = [
        h["id"]
        for h in owner.get("/api/search", params={"q": "boiler", "tag": "gas"}).json()["items"]
    ]
    assert ids == [a["id"]]
    assert search(owner, "boiler") and len(search(owner, "boiler")) == 2


def test_never_returns_another_workspaces_tickets_and_viewers_can_search(
    client_factory: ClientFactory,
) -> None:
    mine = team(client_factory)
    other = make_owner(client_factory, "Other Co")
    new_ticket(other, "Secret quokka problem")
    new_ticket(mine["owner"], "Visible quokka problem")
    for who in (mine["owner"], mine["viewer"]):
        assert [h["subject"] for h in search(who, "quokka")] == ["Visible quokka problem"]


def test_control_characters_in_the_query_or_tag_never_cause_a_server_error(
    client_factory: ClientFactory,
) -> None:
    owner = make_owner(client_factory)
    new_ticket(owner, "Boiler")
    assert owner.get("/api/search", params={"q": "boil\x00er"}).status_code == 200
    assert owner.get("/api/search", params={"q": "boiler", "tag": "a\x00b"}).status_code == 200

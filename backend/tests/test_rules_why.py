import uuid

from tests.helpers import ClientFactory, make_owner, team
from tests.test_rules_exec import live, refund_rule
from tests.test_tickets import new_ticket


def test_the_why_panel_lists_what_ran_and_what_happened(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    live(
        owner,
        postgres_url,
        "First",
        refund_rule(
            [{"type": "set_priority", "value": "urgent"}, {"type": "add_tag", "tag": "refund"}]
        ),
    )
    live(owner, postgres_url, "Second", refund_rule([{"type": "set_priority", "value": "low"}]))
    tk = new_ticket(owner, "Refund please")
    r = owner.get(f"/api/tickets/{tk['id']}/rules")
    assert r.status_code == 200
    items = {i["rule"]["name"]: i for i in r.json()}
    assert set(items) == {"First", "Second"}
    first = items["First"]
    assert (
        first["event"] == "ticket.created"
        and first["matched"] is True
        and first["rule"]["version"] == 1
    )
    assert [(a["text"], a["status"]) for a in first["actions"]] == [
        ("Set priority to urgent", "applied"),
        ("Add the tag “refund”", "applied"),
    ]
    second = items["Second"]["actions"][0]
    assert second["status"] == "skipped" and "First" in second["reason"]


def test_the_why_panel_is_empty_for_tickets_no_rule_touched_and_respects_isolation(
    client_factory: ClientFactory,
) -> None:
    t = team(client_factory)
    tk = new_ticket(t["owner"], "Nothing special")
    assert t["viewer"].get(f"/api/tickets/{tk['id']}/rules").json() == []
    other = make_owner(client_factory, "Elsewhere")
    assert other.get(f"/api/tickets/{tk['id']}/rules").status_code == 404
    assert other.get(f"/api/tickets/{uuid.uuid4()}/rules").status_code == 404

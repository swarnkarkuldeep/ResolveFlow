import uuid
from typing import Any

from sqlalchemy import text

from resolveflow.db import engine_for
from tests.helpers import Actor, ClientFactory, make_owner, team
from tests.test_rules_api import REFUND, create, put

FACTS = {
    "event": "ticket.created",
    "sender_email": "pat@acme-corp.test",
    "subject": "Refund for order 1042",
    "body": "I would like my money back.",
    "channel": "email",
    "priority": "normal",
    "status": "new",
    "tags": [],
    "assignee": {"kind": "none"},
}


def dry_run(
    actor: Actor, definition: dict[str, Any], facts: dict[str, Any] | None = None, **extra: Any
) -> Any:
    return actor.post(
        "/api/rules/test", {"definition": definition, "facts": facts or FACTS, **extra}
    )


def record(
    actor: Actor,
    rule_id: str,
    expectation: str,
    facts: dict[str, Any] | None = None,
    version: int | None = None,
) -> Any:
    body: dict[str, Any] = {"facts": facts or FACTS, "expectation": expectation}
    if version:
        body["version"] = version
    return actor.post(f"/api/rules/{rule_id}/tests", body)


def counts(url: str) -> dict[str, int]:
    tables = [
        "rules",
        "rule_versions",
        "rule_tests",
        "rule_executions",
        "audit_log",
        "tickets",
        "notifications",
    ]
    with engine_for(url).connect() as conn:
        return {
            t: int(conn.execute(text(f"select count(*) from {t}")).scalar_one()) for t in tables
        }  # noqa: S608


def test_a_dry_run_changes_nothing(client_factory: ClientFactory, postgres_url: str) -> None:
    owner = make_owner(client_factory)
    create(owner)
    before = counts(postgres_url)
    r = dry_run(owner, REFUND)
    assert r.status_code == 200 and r.json()["matched"] is True
    assert counts(postgres_url) == before


def test_the_result_shows_every_condition_with_the_value_that_was_checked(
    client_factory: ClientFactory,
) -> None:
    owner = make_owner(client_factory)
    definition = {
        **REFUND,
        "conditions": {
            "op": "and",
            "items": [
                {"field": "subject", "operator": "contains", "value": "refund"},
                {
                    "op": "or",
                    "items": [
                        {"field": "channel", "operator": "equals", "value": "form"},
                        {"field": "priority", "operator": "in", "value": ["high", "urgent"]},
                    ],
                },
            ],
        },
    }
    out = dry_run(owner, definition).json()
    assert out["matched"] is False
    tree = out["conditions"]
    assert tree["kind"] == "group" and tree["op"] == "and" and tree["passed"] is False
    first, group = tree["children"]
    assert first == {
        "kind": "condition",
        "field": "subject",
        "operator": "contains",
        "value": "refund",
        "actual": "Refund for order 1042",
        "passed": True,
    }
    assert group["kind"] == "group" and [c["passed"] for c in group["children"]] == [False, False]
    assert group["children"][0]["actual"] == "email"
    assert out["actions"] == []  # nothing is planned when the rule does not match


def test_actions_are_described_in_plain_language_with_real_names(
    client_factory: ClientFactory,
) -> None:
    t = team(client_factory)
    tm = t["owner"].post("/api/teams", {"name": "Support"}).json()
    definition = {
        **REFUND,
        "actions": [
            {"type": "assign", "target": "user", "user_id": t["agent"].user_id},
            {"type": "set_priority", "value": "urgent"},
            {"type": "set_status", "value": "open"},
            {"type": "add_tag", "tag": "refund"},
            {"type": "notify", "target": "team", "team_id": tm["id"]},
            {"type": "notify", "target": "owners_admins"},
            {
                "type": "escalate",
                "assign": {"target": "round_robin", "team_id": tm["id"]},
                "message": "Needs a manager",
            },
        ],
    }
    out = dry_run(t["owner"], definition).json()
    texts = [a["text"] for a in out["actions"]]
    assert texts == [
        "Assign to Agent Person",
        "Set priority to urgent",
        "Set status to open",
        "Add the tag “refund”",
        "Notify everyone in Support",
        "Notify the workspace owners and admins",
        "Escalate: assign to the next person in Support",
        "Escalate: notify the workspace owners and admins",
    ]
    statuses = {a["text"]: a["status"] for a in out["actions"]}
    assert (
        statuses["Escalate: assign to the next person in Support"] == "skipped"
    )  # the plain assign runs first
    assert (
        statuses["Escalate: notify the workspace owners and admins"] == "skipped"
    )  # same target already notified


def test_the_dry_run_can_show_how_it_would_interact_with_the_live_rules(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    live_def = {**REFUND, "actions": [{"type": "set_priority", "value": "urgent"}]}
    live = create(owner, "Live urgent", live_def)
    assert record(owner, live["id"], "match").json()["passed"] is True
    assert owner.post(f"/api/rules/{live['id']}/activate", {}).status_code == 200
    alone = dry_run(owner, REFUND).json()
    assert [a["status"] for a in alone["actions"]] == ["apply", "apply"]
    combined = dry_run(owner, REFUND, include_active_rules=True).json()
    prio = next(a for a in combined["actions"] if a["type"] == "set_priority")
    assert prio["status"] == "skipped" and "Live urgent" in prio["reason"]
    assert next(a for a in combined["actions"] if a["type"] == "add_tag")["status"] == "apply"


def test_a_recorded_test_is_bound_to_the_exact_version(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    r = create(owner)
    t1 = record(owner, r["id"], "match")
    assert (
        t1.status_code == 200
        and t1.json()["passed"] is True
        and t1.json()["matched"] is True
        and t1.json()["test_id"]
    )
    assert owner.get(f"/api/rules/{r['id']}").json()["versions"][0]["tested"] is True
    assert owner.post(f"/api/rules/{r['id']}/activate", {}).status_code == 200

    changed = {**REFUND, "actions": [{"type": "set_priority", "value": "urgent"}]}
    v2 = put(owner, r["id"], definition=changed).json()
    assert v2["current_version"] == 2 and v2["tested"] is False and v2["active_version"] == 1
    assert (
        owner.post(f"/api/rules/{r['id']}/activate", {}).status_code == 409
    )  # the v1 test does not count for v2
    assert (
        record(owner, r["id"], "match").json()["passed"] is True
    )  # tests v2 (the current version)
    assert owner.post(f"/api/rules/{r['id']}/activate", {}).json()["active_version"] == 2
    old = record(
        owner, r["id"], "match", version=1
    ).json()  # an explicit older version uses its own definition
    assert old["passed"] is True and any(
        a["text"] == "Set priority to high" for a in old["actions"]
    )


def test_expectations_decide_what_counts_as_passing(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    r = create(owner)
    wrong = record(owner, r["id"], "match", {**FACTS, "subject": "Hello"}).json()
    assert wrong["matched"] is False and wrong["passed"] is False
    assert owner.post(f"/api/rules/{r['id']}/activate", {}).status_code == 409
    negative = record(owner, r["id"], "no_match", {**FACTS, "subject": "Hello"}).json()
    assert negative["passed"] is True
    assert (
        owner.post(f"/api/rules/{r['id']}/activate", {}).status_code == 409
    )  # a passing negative test alone does not unlock
    detail = owner.get(f"/api/rules/{r['id']}").json()
    assert [(x["expectation"], x["passed"]) for x in detail["tests"]] == [
        ("no_match", True),
        ("match", False),
    ]
    assert record(owner, r["id"], "match").json()["passed"] is True
    assert owner.post(f"/api/rules/{r['id']}/activate", {}).status_code == 200


def test_the_stored_test_keeps_the_context_and_result(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    r = create(owner)
    tid = record(owner, r["id"], "match").json()["test_id"]
    with engine_for(postgres_url).connect() as conn:
        row = conn.execute(
            text("select context, result, content_hash from rule_tests where id = :i"),
            {"i": uuid.UUID(tid)},
        ).one()
    assert (
        row.context["subject"] == "Refund for order 1042"
        and row.result["matched"] is True
        and len(row.content_hash) == 64
    )


def test_malformed_facts_and_foreign_targets_are_rejected(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    other = make_owner(client_factory, "Elsewhere")
    assert dry_run(owner, REFUND, {**FACTS, "event": "ticket.exploded"}).status_code == 422
    assert dry_run(owner, REFUND, {**FACTS, "channel": "carrier-pigeon"}).status_code == 422
    assert dry_run(owner, REFUND, {**FACTS, "tags": [str(i) for i in range(21)]}).status_code == 422
    assert (
        dry_run(owner, REFUND, {**FACTS, "level": "breach"}).status_code == 422
    )  # level only for sla.threshold
    foreign = {
        **REFUND,
        "actions": [{"type": "assign", "target": "user", "user_id": other.user_id}],
    }
    assert dry_run(owner, foreign).status_code == 422
    assert owner.post("/api/rules/test", {"definition": REFUND}).status_code == 422


def test_testing_requires_rule_manage_and_stays_inside_the_workspace(
    client_factory: ClientFactory,
) -> None:
    t = team(client_factory)
    r = create(t["owner"])
    assert dry_run(t["agent"], REFUND).status_code == 403
    assert record(t["viewer"], r["id"], "match").status_code == 403
    other = make_owner(client_factory, "Elsewhere")
    assert record(other, r["id"], "match").status_code == 404
    assert dry_run(t["admin"], REFUND).status_code == 200

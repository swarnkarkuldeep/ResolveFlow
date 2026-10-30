import uuid
from typing import Any

import pytest
from pydantic import ValidationError

from resolveflow.rules.engine import RuleInput, TicketFacts, evaluate_group, plan
from resolveflow.rules.schema import FIELD_OPERATORS, RuleDefinition, canonical_hash

U1, U2, TEAM = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())


def facts(**kw: Any) -> TicketFacts:
    base = dict(
        event="ticket.created",
        level=None,
        sender_email="Pat.Jones@Acme-Corp.test",
        sender_domain="acme-corp.test",
        subject="Refund for order 1042",
        body="Hello, I would like my money back please.",
        channel="email",
        priority="normal",
        status="new",
        tags=frozenset({"vip"}),
        assignee_id=None,
    )
    base.update(kw)
    return TicketFacts(**base)  # type: ignore[arg-type]


def defn(
    conditions: dict[str, Any] | None = None,
    actions: list[dict[str, Any]] | None = None,
    event: str = "ticket.created",
    level: str | None = None,
) -> RuleDefinition:
    return RuleDefinition.model_validate(
        {
            "trigger": {"event": event, **({"level": level} if level else {})},
            "conditions": conditions or {"op": "and", "items": []},
            "actions": actions or [{"type": "set_priority", "value": "high"}],
        }
    )


def cond(field: str, operator: str, value: Any = None) -> dict[str, Any]:
    return {"field": field, "operator": operator, "value": value}


def passes(field: str, operator: str, value: Any, f: TicketFacts | None = None) -> bool:
    group = RuleDefinition.model_validate(
        {
            "trigger": {"event": "ticket.created"},
            "conditions": {"op": "and", "items": [cond(field, operator, value)]},
            "actions": [{"type": "add_tag", "tag": "x"}],
        }
    ).conditions
    return evaluate_group(group, f or facts()).passed


@pytest.mark.parametrize(
    ("field", "operator", "value", "expected"),
    [
        ("subject", "contains", "REFUND", True),
        ("subject", "contains", "invoice", False),
        ("subject", "not_contains", "invoice", True),
        ("subject", "equals", "refund for order 1042", True),
        ("subject", "not_equals", "refund for order 1042", False),
        ("subject", "starts_with", "refund", True),
        ("subject", "ends_with", "1042", True),
        ("subject", "contains_any", ["invoice", "refund"], True),
        ("subject", "contains_any", ["invoice", "quote"], False),
        ("body", "contains", "money back", True),
        ("sender_email", "ends_with", "@acme-corp.test", True),
        ("sender_email", "equals", "pat.jones@acme-corp.test", True),
        ("sender_domain", "equals", "ACME-CORP.test", True),
        ("sender_domain", "equals", "@acme-corp.test", True),
        ("sender_domain", "in", ["other.test", "acme-corp.test"], True),
        ("sender_domain", "not_equals", "other.test", True),
        ("channel", "equals", "email", True),
        ("channel", "in", ["form", "manual"], False),
        ("priority", "equals", "normal", True),
        ("priority", "in", ["high", "urgent"], False),
        ("status", "equals", "new", True),
        ("status", "not_equals", "new", False),
        ("tags", "contains", "VIP", True),
        ("tags", "not_contains", "refund", True),
        ("tags", "contains_any", ["refund", "vip"], True),
        ("tags", "is_not_empty", None, True),
        ("tags", "is_empty", None, False),
        ("assignee", "is_empty", None, True),
        ("assignee", "is_not_empty", None, False),
    ],
)
def test_operators(field: str, operator: str, value: Any, expected: bool) -> None:
    assert passes(field, operator, value) is expected


def test_assignee_and_empty_tags() -> None:
    assert passes("assignee", "is_not_empty", None, facts(assignee_id=U1)) is True
    assert passes("tags", "is_empty", None, facts(tags=frozenset())) is True


def test_nested_groups_follow_boolean_logic() -> None:
    tree = {
        "op": "and",
        "items": [
            cond("channel", "equals", "email"),
            {
                "op": "or",
                "items": [
                    cond("subject", "contains", "invoice"),
                    cond("subject", "contains", "refund"),
                ],
            },
        ],
    }
    d = defn(tree)
    assert evaluate_group(d.conditions, facts()).passed is True
    assert evaluate_group(d.conditions, facts(subject="Hello")).passed is False
    assert evaluate_group(d.conditions, facts(channel="form")).passed is False
    result = evaluate_group(d.conditions, facts())
    inner = result.children[1]
    assert inner.op == "or" and [c.passed for c in inner.children] == [False, True]  # type: ignore[union-attr]
    assert result.children[0].actual == "email"  # type: ignore[union-attr]


def test_empty_groups() -> None:
    assert evaluate_group(defn({"op": "and", "items": []}).conditions, facts()).passed is True
    assert evaluate_group(defn({"op": "or", "items": []}).conditions, facts()).passed is False


def rule(rid: str, position: int, d: RuleDefinition) -> RuleInput:
    return RuleInput(id=rid, name=f"Rule {rid}", position=position, definition=d)


def test_trigger_must_match() -> None:
    r = rule("a", 1, defn(event="message.received"))
    p = plan([r], facts(event="ticket.created"))
    assert p.results[0].matched is False and p.actions == []
    assert plan([r], facts(event="message.received")).results[0].matched is True


def test_sla_level_filter() -> None:
    breach = rule("b", 1, defn(event="sla.threshold", level="breach"))
    anylevel = rule("c", 2, defn(event="sla.threshold"))
    warn_facts = facts(event="sla.threshold", level="warning")
    p = plan([breach, anylevel], warn_facts)
    assert [r.matched for r in p.results] == [False, True]


def test_first_match_wins_per_exclusive_action_and_loser_is_explained() -> None:
    first = rule(
        "a",
        2,
        defn(
            actions=[
                {"type": "set_priority", "value": "urgent"},
                {"type": "assign", "target": "user", "user_id": U1},
            ]
        ),
    )
    second = rule(
        "b",
        1,
        defn(
            actions=[
                {"type": "set_priority", "value": "low"},
                {"type": "set_status", "value": "open"},
            ]
        ),
    )
    p = plan([first, second], facts())  # `second` has the lower position so it runs first
    by = {(a.rule_id, a.type): a for a in p.actions}
    assert by[("b", "set_priority")].status == "apply"
    assert by[("a", "set_priority")].status == "skipped" and "Rule b" in (
        by[("a", "set_priority")].reason or ""
    )
    assert by[("b", "set_status")].status == "apply" and by[("a", "assign")].status == "apply"
    assert [a.rule_id for a in p.actions if a.type == "set_priority"] == ["b", "a"]


def test_tags_are_additive_and_deduplicated() -> None:
    r1 = rule("a", 1, defn(actions=[{"type": "add_tag", "tag": "Refund"}]))
    r2 = rule(
        "b",
        2,
        defn(actions=[{"type": "add_tag", "tag": "refund"}, {"type": "add_tag", "tag": "billing"}]),
    )
    p = plan([r1, r2], facts())
    applied = [a.params["tag"] for a in p.actions if a.type == "add_tag" and a.status == "apply"]
    assert applied == ["Refund", "billing"]
    assert any(a.status == "skipped" and "already" in (a.reason or "") for a in p.actions)


def test_notifications_fire_for_every_rule_but_identical_targets_are_deduplicated() -> None:
    n = {"type": "notify", "target": "owners_admins"}
    p = plan(
        [
            rule("a", 1, defn(actions=[n])),
            rule("b", 2, defn(actions=[n, {"type": "notify", "target": "assignee"}])),
        ],
        facts(),
    )
    notes = [(a.params["target"], a.status) for a in p.actions if a.type == "notify"]
    assert notes == [
        ("owners_admins", "apply"),
        ("owners_admins", "skipped"),
        ("assignee", "apply"),
    ]


def test_escalate_expands_into_an_assignment_and_an_admin_notification() -> None:
    esc = rule(
        "a",
        1,
        defn(
            actions=[
                {
                    "type": "escalate",
                    "assign": {"target": "user", "user_id": U2},
                    "message": "Needs a manager",
                }
            ]
        ),
    )
    plain = rule("b", 2, defn(actions=[{"type": "assign", "target": "user", "user_id": U1}]))
    p = plan([esc, plain], facts())
    kinds = [(a.type, a.status, a.origin) for a in p.actions]
    assert ("assign", "apply", "escalate") in kinds and ("notify", "apply", "escalate") in kinds
    assert (
        "assign",
        "skipped",
        None,
    ) in kinds  # the later plain assignment loses to the escalation


def test_plan_is_deterministic_and_unmatched_rules_contribute_nothing() -> None:
    rules = [
        rule(
            "a",
            2,
            defn(cond_group := {"op": "and", "items": [cond("subject", "contains", "nope")]}),
        ),
        rule("b", 1, defn()),
    ]
    assert cond_group  # silence unused
    p1, p2 = plan(rules, facts()), plan(list(reversed(rules)), facts())
    assert [a.rule_id for a in p1.actions] == [a.rule_id for a in p2.actions] == ["b"]
    assert [r.rule_id for r in p1.results] == ["b", "a"]


@pytest.mark.parametrize(
    ("payload", "needle"),
    [
        (
            {"conditions": {"op": "and", "items": [cond("subject", "matches_regex", ".*")]}},
            "operator",
        ),
        ({"conditions": {"op": "and", "items": [cond("custom_field", "equals", "x")]}}, "field"),
        ({"conditions": {"op": "and", "items": [cond("assignee", "equals", "x")]}}, "operator"),
        (
            {"conditions": {"op": "and", "items": [cond("subject", "contains_any", "not-a-list")]}},
            "list",
        ),
        ({"conditions": {"op": "and", "items": [cond("priority", "equals", "huge")]}}, "priority"),
        ({"conditions": {"op": "and", "items": [cond("subject", "contains", "x" * 500)]}}, "200"),
        ({"actions": []}, "action"),
        ({"actions": [{"type": "send_reply", "body": "hi"}]}, "action"),
        ({"actions": [{"type": "assign", "target": "user"}]}, "user_id"),
        ({"actions": [{"type": "assign", "target": "round_robin"}]}, "team_id"),
        ({"actions": [{"type": "set_priority", "value": "mega"}]}, "priority"),
        ({"trigger": {"event": "ticket.exploded"}}, "event"),
        ({"trigger": {"event": "ticket.created", "level": "breach"}}, "level"),
    ],
)
def test_invalid_definitions_are_rejected_with_a_plain_reason(
    payload: dict[str, Any], needle: str
) -> None:
    base = {
        "trigger": {"event": "ticket.created"},
        "conditions": {"op": "and", "items": []},
        "actions": [{"type": "add_tag", "tag": "x"}],
    }
    with pytest.raises(ValidationError) as exc:
        RuleDefinition.model_validate({**base, **payload})
    assert needle in str(exc.value)


def test_depth_and_size_limits() -> None:
    deep: dict[str, Any] = {"op": "and", "items": [cond("subject", "contains", "x")]}
    for _ in range(4):
        deep = {"op": "and", "items": [deep]}
    with pytest.raises(ValidationError):
        defn(deep)
    wide = {"op": "and", "items": [cond("subject", "contains", str(i)) for i in range(21)]}
    with pytest.raises(ValidationError):
        defn(wide)
    with pytest.raises(ValidationError):
        defn(actions=[{"type": "add_tag", "tag": str(i)} for i in range(11)])


def test_canonical_hash_is_stable_and_sensitive() -> None:
    a = defn({"op": "and", "items": [cond("subject", "contains", "refund")]})
    b = RuleDefinition.model_validate(
        {
            "actions": [{"value": "high", "type": "set_priority"}],
            "conditions": {
                "items": [{"value": "refund", "operator": "contains", "field": "subject"}],
                "op": "and",
            },
            "trigger": {"event": "ticket.created"},
        }
    )
    assert canonical_hash(a) == canonical_hash(b)
    c = defn({"op": "and", "items": [cond("subject", "contains", "refunds")]})
    assert canonical_hash(c) != canonical_hash(a)
    d = defn({"op": "or", "items": [cond("subject", "contains", "refund")]})
    assert canonical_hash(d) != canonical_hash(a)


def test_every_field_has_operators() -> None:
    assert set(FIELD_OPERATORS) == {
        "sender_email",
        "sender_domain",
        "subject",
        "body",
        "channel",
        "priority",
        "status",
        "tags",
        "assignee",
    }

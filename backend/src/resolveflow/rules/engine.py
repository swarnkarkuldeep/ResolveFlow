"""Pure rule evaluation: no I/O. Turns (rules, ticket facts) into a conflict-resolved plan."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from resolveflow.rules.schema import (
    AddTagAction,
    AssignAction,
    Condition,
    EscalateAction,
    Group,
    NotifyAction,
    RuleDefinition,
    SetPriorityAction,
    SetStatusAction,
)


@dataclass(frozen=True)
class TicketFacts:
    event: str
    level: str | None
    sender_email: str
    sender_domain: str
    subject: str
    body: str
    channel: str
    priority: str
    status: str
    tags: frozenset[str]
    assignee_id: str | None


@dataclass
class ConditionResult:
    field: str
    operator: str
    value: Any
    actual: Any
    passed: bool


@dataclass
class GroupResult:
    op: str
    passed: bool
    children: list["ConditionResult | GroupResult"] = field(default_factory=list)


def _values(c: Condition) -> list[str]:
    raw = c.value if isinstance(c.value, list) else [c.value or ""]
    return [str(v).casefold() for v in raw]


def _fact(facts: TicketFacts, name: str) -> Any:
    if name == "assignee":
        return facts.assignee_id
    if name == "tags":
        return sorted(facts.tags)
    return getattr(facts, name)


def evaluate_condition(c: Condition, facts: TicketFacts) -> ConditionResult:
    actual = _fact(facts, c.field)
    op = c.operator
    vals = _values(c)
    if c.field == "tags":
        have = {t.casefold() for t in facts.tags}
        passed = {
            "contains": vals[0] in have if vals else False,
            "not_contains": vals[0] not in have if vals else False,
            "contains_any": any(v in have for v in vals),
            "is_empty": not have,
            "is_not_empty": bool(have),
        }[op]
    elif c.field == "assignee":
        passed = (actual is None) if op == "is_empty" else (actual is not None)
    else:
        text = str(actual).casefold()
        if c.field == "sender_domain":
            vals = [v.lstrip("@") for v in vals]
        passed = {
            "equals": text == vals[0],
            "not_equals": text != vals[0],
            "contains": vals[0] in text,
            "not_contains": vals[0] not in text,
            "contains_any": any(v in text for v in vals),
            "starts_with": text.startswith(vals[0]),
            "ends_with": text.endswith(vals[0]),
            "in": text in vals,
        }[op]
    return ConditionResult(c.field, op, c.value, actual, passed)


def evaluate_group(group: Group, facts: TicketFacts) -> GroupResult:
    children: list[ConditionResult | GroupResult] = [
        evaluate_group(i, facts) if isinstance(i, Group) else evaluate_condition(i, facts)
        for i in group.items
    ]
    if group.op == "and":
        passed = all(c.passed for c in children)  # an empty AND passes
    else:
        passed = any(c.passed for c in children)  # an empty OR does not
    return GroupResult(group.op, passed, children)


@dataclass(frozen=True)
class RuleInput:
    id: str
    name: str
    position: int
    definition: RuleDefinition
    version: int = 0


@dataclass
class RuleResult:
    rule_id: str
    name: str
    matched: bool
    trigger_matched: bool
    trace: GroupResult | None


@dataclass
class PlannedAction:
    rule_id: str
    rule_name: str
    type: str
    params: dict[str, Any]
    status: str = "apply"  # "apply" | "skipped"
    reason: str | None = None
    origin: str | None = None  # "escalate" when expanded from an escalation


@dataclass
class Plan:
    results: list[RuleResult]
    actions: list[PlannedAction]


def _trigger_matches(defn: RuleDefinition, facts: TicketFacts) -> bool:
    if defn.trigger.event != facts.event:
        return False
    return not (defn.trigger.level and defn.trigger.level != facts.level)


def _expand(rule: RuleInput) -> list[PlannedAction]:
    out: list[PlannedAction] = []
    for a in rule.definition.actions:
        base = {"rule_id": rule.id, "rule_name": rule.name}
        if isinstance(a, AssignAction):
            out.append(
                PlannedAction(
                    type="assign", params=a.model_dump(mode="json", exclude={"type"}), **base
                )
            )
        elif isinstance(a, SetPriorityAction):
            out.append(PlannedAction(type="set_priority", params={"value": a.value}, **base))
        elif isinstance(a, SetStatusAction):
            out.append(PlannedAction(type="set_status", params={"value": a.value}, **base))
        elif isinstance(a, AddTagAction):
            out.append(PlannedAction(type="add_tag", params={"tag": a.tag}, **base))
        elif isinstance(a, NotifyAction):
            out.append(
                PlannedAction(
                    type="notify", params=a.model_dump(mode="json", exclude={"type"}), **base
                )
            )
        elif isinstance(a, EscalateAction):
            out.append(
                PlannedAction(
                    type="assign",
                    params=a.assign.model_dump(mode="json"),
                    origin="escalate",
                    **base,
                )
            )
            out.append(
                PlannedAction(
                    type="notify",
                    params={
                        "target": "owners_admins",
                        "message": a.message or "Escalated by an automation rule",
                    },
                    origin="escalate",
                    **base,
                )
            )
    return out


EXCLUSIVE = ("assign", "set_priority", "set_status")


def _notify_key(p: dict[str, Any]) -> tuple[Any, ...]:
    return (p.get("target"), p.get("user_id"), p.get("team_id"))


def plan(rules: Sequence[RuleInput], facts: TicketFacts) -> Plan:
    ordered = sorted(rules, key=lambda r: (r.position, r.id))
    results: list[RuleResult] = []
    actions: list[PlannedAction] = []
    for rule in ordered:
        trigger_ok = _trigger_matches(rule.definition, facts)
        trace = evaluate_group(rule.definition.conditions, facts) if trigger_ok else None
        matched = bool(trigger_ok and trace and trace.passed)
        results.append(RuleResult(rule.id, rule.name, matched, trigger_ok, trace))
        if matched:
            actions.extend(_expand(rule))

    winners: dict[str, str] = {}
    seen_tags: dict[str, str] = {}
    seen_notes: dict[tuple[Any, ...], str] = {}
    for a in actions:
        if a.type in EXCLUSIVE:
            if a.type in winners:
                a.status, a.reason = (
                    "skipped",
                    f"Overridden by {winners[a.type]}, which runs first.",
                )
            else:
                winners[a.type] = a.rule_name
        elif a.type == "add_tag":
            key = a.params["tag"].casefold()
            if key in seen_tags:
                a.status, a.reason = "skipped", f"Tag already added by {seen_tags[key]}."
            else:
                seen_tags[key] = a.rule_name
        elif a.type == "notify":
            key = _notify_key(a.params)
            if key in seen_notes:
                a.status, a.reason = (
                    "skipped",
                    f"Already notifying this target for {seen_notes[key]}.",
                )
            else:
                seen_notes[key] = a.rule_name
    return Plan(results, actions)

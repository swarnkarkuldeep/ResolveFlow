"""Dry runs and recorded tests: the same pure engine as production, with no side effects."""

import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text

from resolveflow import audit
from resolveflow.context import ServiceCtx
from resolveflow.errors import err
from resolveflow.rules import service
from resolveflow.rules.engine import (
    ConditionResult,
    GroupResult,
    PlannedAction,
    RuleInput,
    TicketFacts,
    plan,
)
from resolveflow.rules.schema import (
    Channel,
    Event,
    Priority,
    RuleDefinition,
    Status,
    canonical_hash,
)

CANDIDATE_POSITION = 10**9


class AssigneeIn(BaseModel):
    kind: Literal["none", "user"] = "none"
    user_id: uuid.UUID | None = None


class FactsIn(BaseModel):
    event: Event
    level: Literal["warning", "breach"] | None = None
    sender_email: str = Field(max_length=254)
    subject: str = Field(max_length=300)
    body: str = Field(default="", max_length=20_000)
    channel: Channel
    priority: Priority
    status: Status
    tags: list[str] = Field(default_factory=list, max_length=20)
    assignee: AssigneeIn = Field(default_factory=AssigneeIn)

    @model_validator(mode="after")
    def _check(self) -> "FactsIn":
        if self.level and self.event != "sla.threshold":
            raise ValueError("A level only applies to the 'sla.threshold' event.")
        if any(len(t) > 40 for t in self.tags):
            raise ValueError("Tags can be at most 40 characters.")
        return self


def to_facts(f: FactsIn) -> TicketFacts:
    domain = f.sender_email.rsplit("@", 1)[-1].lower() if "@" in f.sender_email else ""
    return TicketFacts(
        event=f.event,
        level=f.level,
        sender_email=f.sender_email,
        sender_domain=domain,
        subject=f.subject,
        body=f.body,
        channel=f.channel,
        priority=f.priority,
        status=f.status,
        tags=frozenset(f.tags),
        assignee_id=str(f.assignee.user_id)
        if f.assignee.kind == "user" and f.assignee.user_id
        else ("unknown" if f.assignee.kind == "user" else None),
    )


def tree(node: ConditionResult | GroupResult) -> dict[str, Any]:
    if isinstance(node, GroupResult):
        return {
            "kind": "group",
            "op": node.op,
            "passed": node.passed,
            "children": [tree(c) for c in node.children],
        }
    return {
        "kind": "condition",
        "field": node.field,
        "operator": node.operator,
        "value": node.value,
        "actual": node.actual,
        "passed": node.passed,
    }


def _names(ctx: ServiceCtx, actions: list[PlannedAction]) -> tuple[dict[str, str], dict[str, str]]:
    users: set[str] = set()
    teams: set[str] = set()
    for a in actions:
        if a.params.get("user_id"):
            users.add(a.params["user_id"])
        if a.params.get("team_id"):
            teams.add(a.params["team_id"])
    user_names = (
        {
            str(r.id): r.name
            for r in ctx.session.execute(
                text("select id, name from users where id = any(cast(:ids as uuid[]))"),
                {"ids": list(users)},
            )
        }
        if users
        else {}
    )
    team_names = (
        {
            str(r.id): r.name
            for r in ctx.session.execute(
                text(
                    "select id, name from teams where workspace_id = :w and id = any(cast(:ids as uuid[]))"
                ),
                {"w": ctx.ws, "ids": list(teams)},
            )
        }
        if teams
        else {}
    )
    return user_names, team_names


def describe(a: PlannedAction, users: dict[str, str], teams: dict[str, str]) -> str:
    p = a.params
    if a.type == "assign":
        if p.get("target") == "round_robin":
            body = f"assign to the next person in {teams.get(p.get('team_id', ''), 'a team')}"
        else:
            body = f"assign to {users.get(p.get('user_id', ''), 'a teammate')}"
    elif a.type == "set_priority":
        body = f"set priority to {p['value']}"
    elif a.type == "set_status":
        body = f"set status to {p['value']}"
    elif a.type == "add_tag":
        return f"Add the tag “{p['tag']}”"
    else:
        target = p.get("target")
        body = {
            "assignee": "notify the assignee",
            "owners_admins": "notify the workspace owners and admins",
            "user": f"notify {users.get(p.get('user_id', ''), 'a teammate')}",
            "team": f"notify everyone in {teams.get(p.get('team_id', ''), 'a team')}",
        }.get(str(target), "notify")
    if a.origin == "escalate":
        return f"Escalate: {body}"
    return body[0].upper() + body[1:]


def run(
    ctx: ServiceCtx,
    candidate: RuleInput,
    facts: TicketFacts,
    include_active_rules: bool,
    exclude_rule: uuid.UUID | None = None,
) -> dict[str, Any]:
    others = service.load_active_rules(ctx, exclude_rule) if include_active_rules else []
    result = plan([*others, candidate], facts)
    mine = next(r for r in result.results if r.rule_id == candidate.id)
    actions = [a for a in result.actions if a.rule_id == candidate.id]
    users, teams = _names(ctx, actions)
    return {
        "matched": mine.matched,
        "trigger_matched": mine.trigger_matched,
        "conditions": tree(mine.trace) if mine.trace else None,
        "actions": [
            {
                "type": a.type,
                "params": a.params,
                "text": describe(a, users, teams),
                "status": a.status,
                "reason": a.reason,
            }
            for a in actions
        ],
    }


def dry_run(
    ctx: ServiceCtx, defn: RuleDefinition, facts_in: FactsIn, include_active_rules: bool
) -> dict[str, Any]:
    service.validate_targets(ctx, defn)
    candidate = RuleInput(
        id="candidate", name="This rule", position=CANDIDATE_POSITION, definition=defn
    )
    return run(ctx, candidate, to_facts(facts_in), include_active_rules)


def record_test(
    ctx: ServiceCtx,
    rule_id: uuid.UUID,
    version: int | None,
    facts_in: FactsIn,
    expectation: Literal["match", "no_match"],
    include_active_rules: bool = False,
) -> dict[str, Any]:
    rule = service.get_rule_row(ctx, rule_id)
    target = version if version is not None else rule["current_version"]
    stored = ctx.session.execute(
        text(
            "select definition, content_hash from rule_versions where rule_id = :r and version = :v"
        ),
        {"r": rule_id, "v": target},
    ).first()
    if not stored:
        raise err(404, "not_found", "That version does not exist.")
    defn = RuleDefinition.model_validate(stored.definition)
    service.validate_targets(ctx, defn)
    if canonical_hash(defn) != stored.content_hash:  # versions are immutable and hash-addressed
        raise RuntimeError("stored rule version does not match its content hash")
    candidate = RuleInput(
        id=str(rule_id), name=rule["name"], position=rule["position"], definition=defn
    )
    result = run(ctx, candidate, to_facts(facts_in), include_active_rules, exclude_rule=rule_id)
    passed = result["matched"] == (expectation == "match")
    test_id = ctx.session.execute(
        text(
            "insert into rule_tests (workspace_id, rule_id, version, content_hash, expectation, matched, "
            "passed, context, result, created_by) values (:w, :r, :v, :h, :e, :m, :p, cast(:c as jsonb), "
            "cast(:res as jsonb), :u) returning id"
        ),
        {
            "w": ctx.ws,
            "r": rule_id,
            "v": target,
            "h": stored.content_hash,
            "e": expectation,
            "m": result["matched"],
            "p": passed,
            "c": json.dumps(facts_in.model_dump(mode="json")),
            "res": json.dumps(result),
            "u": ctx.actor_id,
        },
    ).scalar_one()
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type=ctx.actor_type,
        actor_id=ctx.actor_id,
        action="rule.tested",
        entity_type="rule",
        entity_id=rule_id,
        after={
            "version": target,
            "expectation": expectation,
            "matched": result["matched"],
            "passed": passed,
        },
        request_id=ctx.request_id,
    )
    return {**result, "passed": passed, "test_id": str(test_id), "version": target}

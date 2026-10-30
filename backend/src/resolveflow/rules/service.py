"""Rule management: versioned definitions, test-gated activation, ordering."""

import json
import uuid
from typing import Any

from sqlalchemy import text

from resolveflow import audit
from resolveflow.context import ServiceCtx
from resolveflow.errors import err
from resolveflow.rules.engine import RuleInput
from resolveflow.rules.schema import (
    AssignAction,
    EscalateAction,
    NotifyAction,
    RuleDefinition,
    canonical_hash,
)
from resolveflow.textutil import clean_line

_LIST_SQL = """
select r.id, r.name, r.position, r.status, r.active_version, r.current_version, r.updated_at,
  v.definition, v.content_hash,
  exists (select 1 from rule_tests t where t.rule_id = r.id and t.content_hash = v.content_hash
          and t.passed and t.expectation = 'match' and t.matched) as tested
from rules r join rule_versions v on v.rule_id = r.id and v.version = r.current_version
where r.workspace_id = :w
"""


def _row(r: Any) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "name": r.name,
        "position": r.position,
        "status": r.status,
        "active_version": r.active_version,
        "current_version": r.current_version,
        "definition": r.definition,
        "tested": r.tested,
        "updated_at": r.updated_at.isoformat(),
    }


def validate_targets(ctx: ServiceCtx, defn: RuleDefinition) -> None:
    """Every person and team a rule points at must belong to this workspace (and be assignable)."""
    assignees: set[uuid.UUID] = set()
    notified: set[uuid.UUID] = set()
    teams: set[uuid.UUID] = set()
    for a in defn.actions:
        if isinstance(a, AssignAction | EscalateAction):
            spec = a if isinstance(a, AssignAction) else a.assign
            if spec.user_id:
                assignees.add(spec.user_id)
            if spec.team_id:
                teams.add(spec.team_id)
        elif isinstance(a, NotifyAction):
            if a.user_id:
                notified.add(a.user_id)
            if a.team_id:
                teams.add(a.team_id)
    if assignees:
        ok = {
            r.user_id
            for r in ctx.session.execute(
                text(
                    "select user_id from memberships where workspace_id = :w and active "
                    "and role <> 'viewer' and user_id = any(:ids)"
                ),
                {"w": ctx.ws, "ids": list(assignees)},
            )
        }
        if assignees - ok:
            raise err(
                422, "bad_assignee", "Assign only to active teammates who can work on tickets."
            )
    if notified:
        ok = {
            r.user_id
            for r in ctx.session.execute(
                text(
                    "select user_id from memberships where workspace_id = :w and active and user_id = any(:ids)"
                ),
                {"w": ctx.ws, "ids": list(notified)},
            )
        }
        if notified - ok:
            raise err(422, "bad_recipient", "Notify only active members of this workspace.")
    if teams:
        found = {
            r.id
            for r in ctx.session.execute(
                text("select id from teams where workspace_id = :w and id = any(:ids)"),
                {"w": ctx.ws, "ids": list(teams)},
            )
        }
        if teams - found:
            raise err(422, "bad_team", "That team does not exist in this workspace.")


def _clean_name(name: str) -> str:
    cleaned = clean_line(name)[:120]
    if not cleaned:
        raise err(422, "bad_name", "A rule needs a name.")
    return cleaned


def _add_version(ctx: ServiceCtx, rule_id: uuid.UUID, version: int, defn: RuleDefinition) -> str:
    h = canonical_hash(defn)
    ctx.session.execute(
        text(
            "insert into rule_versions (workspace_id, rule_id, version, definition, content_hash, created_by) "
            "values (:w, :r, :v, cast(:d as jsonb), :h, :u)"
        ),
        {
            "w": ctx.ws,
            "r": rule_id,
            "v": version,
            "d": json.dumps(defn.model_dump(mode="json")),
            "h": h,
            "u": ctx.actor_id,
        },
    )
    return h


def load_active_rules(ctx: ServiceCtx, exclude: uuid.UUID | None = None) -> list[RuleInput]:
    """Active rules at their active versions, in execution order."""
    rows = ctx.session.execute(
        text(
            "select r.id, r.name, r.position, r.active_version, v.definition from rules r "
            "join rule_versions v on v.rule_id = r.id and v.version = r.active_version "
            "where r.workspace_id = :w and r.status = 'active' "
            "and (cast(:ex as uuid) is null or r.id <> cast(:ex as uuid)) order by r.position, r.created_at"
        ),
        {"w": ctx.ws, "ex": exclude},
    ).all()
    return [
        RuleInput(
            id=str(r.id),
            name=r.name,
            position=r.position,
            definition=RuleDefinition.model_validate(r.definition),
            version=r.active_version,
        )
        for r in rows
    ]


def ticket_executions(ctx: ServiceCtx, ticket_id: uuid.UUID) -> list[dict[str, Any]]:
    """Which rules ran on this ticket, newest first: the data behind the ticket's 'why' panel."""
    exists = ctx.session.execute(
        text("select 1 from tickets where id = :t and workspace_id = :w"),
        {"t": ticket_id, "w": ctx.ws},
    ).first()
    if not exists:
        raise err(404, "not_found", "Ticket not found.")
    rows = ctx.session.execute(
        text(
            "select e.created_at, e.event, e.rule_id, e.rule_version, e.matched, e.actions, e.depth, r.name "
            "from rule_executions e join rules r on r.id = e.rule_id "
            "where e.ticket_id = :t and e.workspace_id = :w order by e.created_at desc, e.depth, e.id"
        ),
        {"t": ticket_id, "w": ctx.ws},
    ).all()
    return [
        {
            "at": r.created_at.isoformat(),
            "event": r.event,
            "rule": {"id": str(r.rule_id), "name": r.name, "version": r.rule_version},
            "matched": r.matched,
            "depth": r.depth,
            "actions": [
                {
                    "type": a["type"],
                    "text": a["text"],
                    "status": a["status"],
                    "reason": a.get("reason"),
                }
                for a in r.actions
            ],
        }
        for r in rows
    ]


def get_rule_row(ctx: ServiceCtx, rule_id: uuid.UUID) -> dict[str, Any]:
    r = ctx.session.execute(text(_LIST_SQL + " and r.id = :r"), {"w": ctx.ws, "r": rule_id}).first()
    if not r:
        raise err(404, "not_found", "Rule not found.")
    return _row(r)


def list_rules(ctx: ServiceCtx) -> list[dict[str, Any]]:
    rows = ctx.session.execute(
        text(_LIST_SQL + " order by (r.status = 'archived'), r.position, r.created_at"),
        {"w": ctx.ws},
    ).all()
    return [_row(r) for r in rows]


def get_rule(ctx: ServiceCtx, rule_id: uuid.UUID) -> dict[str, Any]:
    out = get_rule_row(ctx, rule_id)
    versions = ctx.session.execute(
        text(
            "select v.version, v.content_hash, v.created_at, u.name as author, "
            "exists (select 1 from rule_tests t where t.rule_id = v.rule_id and t.content_hash = v.content_hash "
            "and t.passed and t.expectation = 'match' and t.matched) as tested "
            "from rule_versions v left join users u on u.id = v.created_by "
            "where v.rule_id = :r order by v.version desc"
        ),
        {"r": rule_id},
    ).all()
    tests = ctx.session.execute(
        text(
            "select t.id, t.version, t.expectation, t.matched, t.passed, t.created_at, u.name as author "
            "from rule_tests t left join users u on u.id = t.created_by "
            "where t.rule_id = :r order by t.created_at desc limit 20"
        ),
        {"r": rule_id},
    ).all()
    out["versions"] = [
        {
            "version": v.version,
            "content_hash": v.content_hash,
            "created_at": v.created_at.isoformat(),
            "author": v.author,
            "tested": v.tested,
            "active": v.version == out["active_version"],
        }
        for v in versions
    ]
    out["tests"] = [
        {
            "id": str(t.id),
            "version": t.version,
            "expectation": t.expectation,
            "matched": t.matched,
            "passed": t.passed,
            "created_at": t.created_at.isoformat(),
            "author": t.author,
        }
        for t in tests
    ]
    return out


def create_rule(ctx: ServiceCtx, name: str, defn: RuleDefinition) -> dict[str, Any]:
    name = _clean_name(name)
    validate_targets(ctx, defn)
    position = ctx.session.execute(
        text("select coalesce(max(position), 0) + 1 from rules where workspace_id = :w"),
        {"w": ctx.ws},
    ).scalar_one()
    rule_id = ctx.session.execute(
        text("insert into rules (workspace_id, name, position) values (:w, :n, :p) returning id"),
        {"w": ctx.ws, "n": name, "p": position},
    ).scalar_one()
    h = _add_version(ctx, rule_id, 1, defn)
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type=ctx.actor_type,
        actor_id=ctx.actor_id,
        action="rule.created",
        entity_type="rule",
        entity_id=rule_id,
        after={"name": name, "version": 1, "content_hash": h},
        request_id=ctx.request_id,
    )
    return get_rule_row(ctx, rule_id)


def update_rule(
    ctx: ServiceCtx, rule_id: uuid.UUID, name: str | None, defn: RuleDefinition | None
) -> dict[str, Any]:
    ctx.session.execute(
        text("select 1 from rules where id = :r and workspace_id = :w for update"),
        {"r": rule_id, "w": ctx.ws},
    )  # serialise concurrent edits so two writers never claim the same version number
    before = get_rule_row(ctx, rule_id)
    new_name = _clean_name(name) if name is not None else before["name"]
    version = before["current_version"]
    new_hash = None
    if defn is not None:
        validate_targets(ctx, defn)
        current_hash = ctx.session.execute(
            text("select content_hash from rule_versions where rule_id = :r and version = :v"),
            {"r": rule_id, "v": version},
        ).scalar_one()
        if canonical_hash(defn) != current_hash:
            version += 1
            new_hash = _add_version(ctx, rule_id, version, defn)
    if new_name == before["name"] and version == before["current_version"]:
        return before
    ctx.session.execute(
        text(
            "update rules set name = :n, current_version = :v, updated_at = now() "
            "where id = :r and workspace_id = :w"
        ),
        {"n": new_name, "v": version, "r": rule_id, "w": ctx.ws},
    )
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type=ctx.actor_type,
        actor_id=ctx.actor_id,
        action="rule.updated",
        entity_type="rule",
        entity_id=rule_id,
        before={"name": before["name"], "version": before["current_version"]},
        after={
            "name": new_name,
            "version": version,
            **({"content_hash": new_hash} if new_hash else {}),
        },
        request_id=ctx.request_id,
    )
    return get_rule_row(ctx, rule_id)


def activate(ctx: ServiceCtx, rule_id: uuid.UUID, version: int | None) -> dict[str, Any]:
    rule = get_rule_row(ctx, rule_id)
    if rule["status"] == "archived":
        raise err(409, "archived", "Restore this automation before making it live.")
    target = version if version is not None else rule["current_version"]
    v = ctx.session.execute(
        text(
            "select content_hash, definition from rule_versions where rule_id = :r and version = :v"
        ),
        {"r": rule_id, "v": target},
    ).first()
    if not v:
        raise err(404, "not_found", "That version does not exist.")
    validate_targets(ctx, RuleDefinition.model_validate(v.definition))
    tested = ctx.session.execute(
        text(
            "select 1 from rule_tests where rule_id = :r and content_hash = :h and passed "
            "and expectation = 'match' and matched limit 1"
        ),
        {"r": rule_id, "h": v.content_hash},
    ).first()
    if not tested:
        raise err(
            409,
            "needs_passing_test",
            "This version has not passed a test yet. Run a test that is expected to match and passes, then activate.",
        )
    ctx.session.execute(
        text(
            "update rules set status = 'active', active_version = :v, updated_at = now() where id = :r and workspace_id = :w"
        ),
        {"v": target, "r": rule_id, "w": ctx.ws},
    )
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type=ctx.actor_type,
        actor_id=ctx.actor_id,
        action="rule.activated",
        entity_type="rule",
        entity_id=rule_id,
        before={"active_version": rule["active_version"]},
        after={"active_version": target},
        request_id=ctx.request_id,
    )
    return get_rule_row(ctx, rule_id)


def set_archived(ctx: ServiceCtx, rule_id: uuid.UUID, archived: bool) -> dict[str, Any]:
    rule = get_rule_row(ctx, rule_id)
    if archived:
        ctx.session.execute(
            text(
                "update rules set status = 'archived', active_version = null, updated_at = now() where id = :r and workspace_id = :w"
            ),
            {"r": rule_id, "w": ctx.ws},
        )
    else:
        ctx.session.execute(
            text(
                "update rules set status = 'draft', updated_at = now() where id = :r and workspace_id = :w"
            ),
            {"r": rule_id, "w": ctx.ws},
        )
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type=ctx.actor_type,
        actor_id=ctx.actor_id,
        action="rule.archived" if archived else "rule.restored",
        entity_type="rule",
        entity_id=rule_id,
        before={"status": rule["status"]},
        request_id=ctx.request_id,
    )
    return get_rule_row(ctx, rule_id)


def reorder(ctx: ServiceCtx, ids: list[uuid.UUID]) -> list[dict[str, Any]]:
    current = [
        r.id
        for r in ctx.session.execute(
            text(
                "select id from rules where workspace_id = :w and status <> 'archived' order by position"
            ),
            {"w": ctx.ws},
        )
    ]
    if sorted(map(str, ids)) != sorted(map(str, current)) or len(set(ids)) != len(ids):
        raise err(422, "bad_order", "List every active and draft rule exactly once.")
    for position, rule_id in enumerate(ids, start=1):
        ctx.session.execute(
            text("update rules set position = :p where id = :r and workspace_id = :w"),
            {"p": position, "r": rule_id, "w": ctx.ws},
        )
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type=ctx.actor_type,
        actor_id=ctx.actor_id,
        action="rule.reordered",
        entity_type="rule",
        entity_id=None,
        before={"order": [str(i) for i in current]},
        after={"order": [str(i) for i in ids]},
        request_id=ctx.request_id,
    )
    return list_rules(ctx)

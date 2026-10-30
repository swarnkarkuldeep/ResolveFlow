import uuid
from typing import Any

from sqlalchemy import text

from resolveflow.db import engine_for
from resolveflow.rules.schema import RuleDefinition, canonical_hash
from tests.helpers import Actor, ClientFactory, make_owner, team

REFUND = {
    "trigger": {"event": "ticket.created"},
    "conditions": {
        "op": "and",
        "items": [{"field": "subject", "operator": "contains", "value": "refund"}],
    },
    "actions": [{"type": "set_priority", "value": "high"}, {"type": "add_tag", "tag": "refund"}],
}


def create(
    actor: Actor, name: str = "Refund requests", definition: dict[str, Any] | None = None
) -> dict[str, Any]:
    r = actor.post("/api/rules", {"name": name, "definition": definition or REFUND})
    assert r.status_code == 200, r.text
    return dict(r.json())


def put(actor: Actor, rule_id: str, **body: Any) -> Any:
    return actor.client.put(
        f"/api/rules/{rule_id}", json=body, headers={"X-CSRF-Token": actor.csrf}
    )


def passing_test(
    url: str, workspace_id: str, rule_id: str, version: int, definition: dict[str, Any]
) -> None:
    """Records a passing positive test the way the tester would (the tester itself is covered in T4)."""
    h = canonical_hash(RuleDefinition.model_validate(definition))
    with engine_for(url).begin() as conn:
        conn.execute(
            text(
                "insert into rule_tests (workspace_id, rule_id, version, content_hash, expectation, matched, "
                "passed, context, result) values (:w, :r, :v, :h, 'match', true, true, '{}', '{}')"
            ),
            {"w": uuid.UUID(workspace_id), "r": uuid.UUID(rule_id), "v": version, "h": h},
        )


def test_create_list_and_get(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    a = create(owner, "First")
    b = create(owner, "Second")
    assert (
        a["status"] == "draft"
        and a["current_version"] == 1
        and a["active_version"] is None
        and a["tested"] is False
    )
    assert (a["position"], b["position"]) == (1, 2)
    listed = owner.get("/api/rules").json()
    assert [r["name"] for r in listed] == ["First", "Second"]
    assert listed[0]["definition"]["trigger"]["event"] == "ticket.created"
    detail = owner.get(f"/api/rules/{a['id']}").json()
    assert [v["version"] for v in detail["versions"]] == [1] and detail["versions"][0][
        "tested"
    ] is False


def test_editing_the_definition_makes_a_new_version_but_a_rename_does_not(
    client_factory: ClientFactory,
) -> None:
    owner = make_owner(client_factory)
    r = create(owner)
    renamed = put(owner, r["id"], name="Refunds").json()
    assert renamed["name"] == "Refunds" and renamed["current_version"] == 1
    changed = {**REFUND, "actions": [{"type": "set_priority", "value": "urgent"}]}
    v2 = put(owner, r["id"], definition=changed).json()
    assert v2["current_version"] == 2 and v2["tested"] is False
    same = put(owner, r["id"], definition=changed).json()
    assert same["current_version"] == 2  # an identical definition is not a new version
    assert [v["version"] for v in owner.get(f"/api/rules/{r['id']}").json()["versions"]] == [2, 1]


def test_activation_needs_a_passing_test_of_that_exact_version(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    r = create(owner)
    blocked = owner.post(f"/api/rules/{r['id']}/activate", {})
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "needs_passing_test"
    passing_test(postgres_url, owner.workspace_id, r["id"], 1, REFUND)
    ok = owner.post(f"/api/rules/{r['id']}/activate", {})
    assert (
        ok.status_code == 200
        and ok.json()["status"] == "active"
        and ok.json()["active_version"] == 1
    )

    # Edit after testing: v2 is untested, v1 keeps running, v2 cannot be activated yet.
    changed = {**REFUND, "actions": [{"type": "set_priority", "value": "urgent"}]}
    v2 = put(owner, r["id"], definition=changed).json()
    assert v2["current_version"] == 2 and v2["active_version"] == 1 and v2["status"] == "active"
    assert owner.post(f"/api/rules/{r['id']}/activate", {}).status_code == 409
    passing_test(postgres_url, owner.workspace_id, r["id"], 2, changed)
    assert owner.post(f"/api/rules/{r['id']}/activate", {}).json()["active_version"] == 2
    # Rolling back to the older, tested version is allowed.
    back = owner.post(f"/api/rules/{r['id']}/activate", {"version": 1})
    assert back.status_code == 200 and back.json()["active_version"] == 1


def test_a_test_does_not_unlock_a_different_definition(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    r = create(owner)
    passing_test(postgres_url, owner.workspace_id, r["id"], 1, REFUND)
    reordered = {
        **REFUND,
        "actions": list(reversed(REFUND["actions"])),
    }  # same content, different order => new hash
    v2 = put(owner, r["id"], definition=reordered).json()
    assert v2["current_version"] == 2 and v2["tested"] is False
    assert owner.post(f"/api/rules/{r['id']}/activate", {}).status_code == 409
    assert owner.post(f"/api/rules/{r['id']}/activate", {"version": 9}).status_code == 404


def test_only_positive_passing_tests_unlock_activation(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    r = create(owner)
    h = canonical_hash(RuleDefinition.model_validate(REFUND))
    with engine_for(postgres_url).begin() as conn:
        for expectation, matched, passed in (("no_match", False, True), ("match", False, False)):
            conn.execute(
                text(
                    "insert into rule_tests (workspace_id, rule_id, version, content_hash, expectation, matched, passed, context, result) "
                    "values (:w, :r, 1, :h, :e, :m, :p, '{}', '{}')"
                ),
                {
                    "w": uuid.UUID(owner.workspace_id),
                    "r": uuid.UUID(r["id"]),
                    "h": h,
                    "e": expectation,
                    "m": matched,
                    "p": passed,
                },
            )
    assert owner.post(f"/api/rules/{r['id']}/activate", {}).status_code == 409


def test_archive_restore_and_reorder(client_factory: ClientFactory, postgres_url: str) -> None:
    owner = make_owner(client_factory)
    a, b, c = create(owner, "A"), create(owner, "B"), create(owner, "C")
    passing_test(postgres_url, owner.workspace_id, a["id"], 1, REFUND)
    owner.post(f"/api/rules/{a['id']}/activate", {})
    archived = owner.post(f"/api/rules/{a['id']}/archive", {}).json()
    assert archived["status"] == "archived" and archived["active_version"] is None
    assert owner.post(f"/api/rules/{a['id']}/restore", {}).json()["status"] == "draft"
    assert owner.post("/api/rules/reorder", {"ids": [c["id"], a["id"], b["id"]]}).status_code == 200
    assert [r["name"] for r in owner.get("/api/rules").json()] == ["C", "A", "B"]
    assert (
        owner.post("/api/rules/reorder", {"ids": [a["id"], b["id"]]}).status_code == 422
    )  # must list every rule
    assert (
        owner.post(
            "/api/rules/reorder", {"ids": [a["id"], b["id"], c["id"], str(uuid.uuid4())]}
        ).status_code
        == 422
    )


def test_definitions_may_only_point_at_people_and_teams_of_this_workspace(
    client_factory: ClientFactory,
) -> None:
    t = team(client_factory)
    other = make_owner(client_factory, "Elsewhere")
    foreign_team = other.post("/api/teams", {"name": "Theirs"}).json()["id"]

    def with_actions(actions: list[dict[str, Any]]) -> dict[str, Any]:
        return {**REFUND, "actions": actions}

    bad = [
        [{"type": "assign", "target": "user", "user_id": other.user_id}],
        [{"type": "assign", "target": "round_robin", "team_id": foreign_team}],
        [{"type": "notify", "target": "team", "team_id": foreign_team}],
        [{"type": "assign", "target": "user", "user_id": t["viewer"].user_id}],
        [{"type": "escalate", "assign": {"target": "user", "user_id": str(uuid.uuid4())}}],
    ]
    for actions in bad:
        r = t["owner"].post("/api/rules", {"name": "Bad", "definition": with_actions(actions)})
        assert r.status_code == 422, (actions, r.text)
    ok = t["owner"].post(
        "/api/rules",
        {
            "name": "Fine",
            "definition": with_actions(
                [{"type": "assign", "target": "user", "user_id": t["agent"].user_id}]
            ),
        },
    )
    assert ok.status_code == 200


def test_permissions_and_isolation(client_factory: ClientFactory) -> None:
    t = team(client_factory)
    r = create(t["owner"])
    for role, want in {"owner": 200, "admin": 200, "agent": 403, "viewer": 403}.items():
        assert t[role].get("/api/rules").status_code == want, role
    assert t["agent"].post("/api/rules", {"name": "x", "definition": REFUND}).status_code == 403
    assert t["admin"].post(f"/api/rules/{r['id']}/archive", {}).status_code == 200
    other = make_owner(client_factory, "Elsewhere")
    assert other.get(f"/api/rules/{r['id']}").status_code == 404
    assert put(other, r["id"], name="x").status_code == 404
    assert other.post(f"/api/rules/{r['id']}/activate", {}).status_code == 404
    assert other.get("/api/rules").json() == []


def test_invalid_definitions_return_a_plain_422(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    bad = {
        **REFUND,
        "conditions": {
            "op": "and",
            "items": [{"field": "subject", "operator": "matches_regex", "value": ".*"}],
        },
    }
    r = owner.post("/api/rules", {"name": "Regex", "definition": bad})
    assert r.status_code == 422 and "operator" in r.text
    assert owner.post("/api/rules", {"name": "", "definition": REFUND}).status_code == 422


def test_rule_lifecycle_is_audited(client_factory: ClientFactory, postgres_url: str) -> None:
    owner = make_owner(client_factory)
    r = create(owner)
    passing_test(postgres_url, owner.workspace_id, r["id"], 1, REFUND)
    owner.post(f"/api/rules/{r['id']}/activate", {})
    put(
        owner, r["id"], definition={**REFUND, "actions": [{"type": "set_priority", "value": "low"}]}
    )
    owner.post(f"/api/rules/{r['id']}/archive", {})
    with engine_for(postgres_url).connect() as conn:
        actions = list(
            conn.execute(
                text(
                    "select action from audit_log where workspace_id = :w and entity_type = 'rule' order by created_at, id"
                ),
                {"w": uuid.UUID(owner.workspace_id)},
            ).scalars()
        )
    assert actions == ["rule.created", "rule.activated", "rule.updated", "rule.archived"]


def test_a_team_used_by_a_rule_cannot_be_deleted_until_the_rule_is_archived(
    client_factory: ClientFactory,
) -> None:
    t = team(client_factory)
    tm = t["owner"].post("/api/teams", {"name": "Support"}).json()
    r = create(
        t["owner"],
        "Uses team",
        {**REFUND, "actions": [{"type": "assign", "target": "round_robin", "team_id": tm["id"]}]},
    )
    blocked = t["owner"].delete(f"/api/teams/{tm['id']}")
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "team_in_use"
    t["owner"].post(f"/api/rules/{r['id']}/archive", {})
    assert t["owner"].delete(f"/api/teams/{tm['id']}").status_code == 200

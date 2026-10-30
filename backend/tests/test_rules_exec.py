import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import event, text

from resolveflow.db import app_engine, engine_for, system_engine
from resolveflow.sla import service as sla_service
from resolveflow.sla import sweeper
from tests.helpers import Actor, ClientFactory, invite_actor, make_owner, team
from tests.test_ingest import DOMAIN, payload, post, token_of
from tests.test_rules_api import passing_test
from tests.test_tickets import new_ticket


def when(
    event_name: str,
    field: str,
    operator: str,
    value: Any,
    actions: list[dict[str, Any]],
    level: str | None = None,
) -> dict[str, Any]:
    return {
        "trigger": {"event": event_name, **({"level": level} if level else {})},
        "conditions": {
            "op": "and",
            "items": [{"field": field, "operator": operator, "value": value}],
        },
        "actions": actions,
    }


def refund_rule(actions: list[dict[str, Any]]) -> dict[str, Any]:
    return when("ticket.created", "subject", "contains", "refund", actions)


def live(actor: Actor, url: str, name: str, definition: dict[str, Any]) -> str:
    r = actor.post("/api/rules", {"name": name, "definition": definition})
    assert r.status_code == 200, r.text
    rid = str(r.json()["id"])
    passing_test(url, actor.workspace_id, rid, 1, definition)
    assert actor.post(f"/api/rules/{rid}/activate", {}).status_code == 200
    return rid


def executions(url: str, ticket_id: str) -> list[Any]:
    with engine_for(url).connect() as conn:
        return list(
            conn.execute(
                text(
                    "select e.rule_id, e.rule_version, e.event, e.matched, e.actions, e.depth, r.name "
                    "from rule_executions e join rules r on r.id = e.rule_id "
                    "where e.ticket_id = :t order by e.created_at, e.id"
                ),
                {"t": uuid.UUID(ticket_id)},
            )
        )


def ticket_of(actor: Actor, ticket_id: str) -> dict[str, Any]:
    return dict(actor.get(f"/api/tickets/{ticket_id}").json())


def test_every_action_is_applied_audited_as_a_rule_and_recorded(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    t = team(client_factory)
    rid = live(
        t["owner"],
        postgres_url,
        "Refunds",
        refund_rule(
            [
                {"type": "set_priority", "value": "high"},
                {"type": "add_tag", "tag": "refund"},
                {"type": "set_status", "value": "open"},
                {"type": "assign", "target": "user", "user_id": t["agent"].user_id},
                {"type": "notify", "target": "owners_admins", "message": "Refund request arrived"},
            ]
        ),
    )
    tk = new_ticket(t["owner"], "Refund for order 1042")
    got = ticket_of(t["owner"], tk["id"])
    assert got["priority"] == "high" and got["tags"] == ["refund"] and got["status"] == "open"
    assert got["assignee"]["name"] == "Agent Person"
    (ex,) = executions(postgres_url, tk["id"])
    assert (
        str(ex.rule_id) == rid
        and ex.matched is True
        and ex.event == "ticket.created"
        and ex.rule_version == 1
    )
    assert [a["status"] for a in ex.actions] == ["applied"] * 5
    with engine_for(postgres_url).connect() as conn:
        audit_actors = conn.execute(
            text(
                "select distinct actor_type, actor_id from audit_log where entity_id = :t and action = 'ticket.updated'"
            ),
            {"t": uuid.UUID(tk["id"])},
        ).all()
        recipients = {
            str(r.user_id)
            for r in conn.execute(
                text("select user_id from notifications where ticket_id = :t"),
                {"t": uuid.UUID(tk["id"])},
            )
        }
    assert {(a.actor_type, str(a.actor_id)) for a in audit_actors} == {("rule", rid)}
    assert recipients == {t["owner"].user_id, t["admin"].user_id}


def test_round_robin_rotates_across_new_tickets(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    agents = [invite_actor(owner, client_factory, "agent", f"Agent {i}") for i in range(3)]
    tm = owner.post("/api/teams", {"name": "Support"}).json()
    owner.client.put(
        f"/api/teams/{tm['id']}/members",
        json={"user_ids": [a.user_id for a in agents]},
        headers={"X-CSRF-Token": owner.csrf},
    )
    live(
        owner,
        postgres_url,
        "Rotate",
        when(
            "ticket.created",
            "channel",
            "equals",
            "manual",
            [{"type": "assign", "target": "round_robin", "team_id": tm["id"]}],
        ),
    )
    assignees = [
        ticket_of(owner, new_ticket(owner, f"T{i}")["id"])["assignee"]["id"] for i in range(6)
    ]
    assert set(assignees) == {a.user_id for a in agents}
    assert assignees[:3] == assignees[3:]


def test_escalate_assigns_and_notifies_owners_and_admins(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    t = team(client_factory)
    live(
        t["owner"],
        postgres_url,
        "Escalate refunds",
        refund_rule(
            [
                {
                    "type": "escalate",
                    "assign": {"target": "user", "user_id": t["admin"].user_id},
                    "message": "Needs a manager",
                }
            ]
        ),
    )
    tk = new_ticket(t["owner"], "Refund disaster")
    assert ticket_of(t["owner"], tk["id"])["assignee"]["name"] == "Admin Person"
    with engine_for(postgres_url).connect() as conn:
        rows = conn.execute(
            text("select user_id, body from notifications where ticket_id = :t"),
            {"t": uuid.UUID(tk["id"])},
        ).all()
    assert {str(r.user_id) for r in rows} == {t["owner"].user_id, t["admin"].user_id}
    assert all("Needs a manager" in (r.body or "") or "Needs a manager" in str(r) for r in rows)


def test_message_received_and_status_changed_triggers(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    live(
        owner,
        postgres_url,
        "Chasers",
        when(
            "message.received",
            "body",
            "contains",
            "urgent",
            [{"type": "set_priority", "value": "urgent"}],
        ),
    )
    live(
        owner,
        postgres_url,
        "On resolve",
        when(
            "status.changed", "status", "equals", "resolved", [{"type": "add_tag", "tag": "done"}]
        ),
    )
    to = f"inbound-{token_of(postgres_url, owner)}@{DOMAIN}"
    anon = client_factory()
    tid = post(anon, payload(to, message_id="<m1@customer.test>", body="Hello there")).json()[
        "ticket_id"
    ]
    assert ticket_of(owner, tid)["priority"] == "normal"  # creation is not a follow-up message
    post(
        anon,
        payload(to, in_reply_to="<m1@customer.test>", subject="Re: x", body="This is urgent!!"),
    )
    assert ticket_of(owner, tid)["priority"] == "urgent"
    owner.patch(f"/api/tickets/{tid}", {"status": "resolved"})
    assert "done" in ticket_of(owner, tid)["tags"]


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, datetime]]:
    state = {"now": datetime(2026, 11, 2, 10, tzinfo=UTC)}
    monkeypatch.setattr(sla_service, "utcnow", lambda: state["now"])
    yield state


def test_sla_threshold_rules_react_to_the_level(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    always = {"field": "channel", "operator": "equals", "value": "manual"}
    warn = {
        "trigger": {"event": "sla.threshold", "level": "warning"},
        "conditions": {"op": "and", "items": [always]},
        "actions": [{"type": "add_tag", "tag": "at-risk"}],
    }
    breach = {
        "trigger": {"event": "sla.threshold", "level": "breach"},
        "conditions": {"op": "and", "items": [always]},
        "actions": [{"type": "set_priority", "value": "urgent"}],
    }
    live(owner, postgres_url, "Warn", warn)
    live(owner, postgres_url, "Breach", breach)
    tk = new_ticket(owner)
    sweeper.sweep(
        system_engine(),
        now=datetime(2026, 11, 2, 16, tzinfo=UTC),
        workspace_id=uuid.UUID(owner.workspace_id),
    )
    got = ticket_of(owner, tk["id"])
    assert "at-risk" in got["tags"] and got["priority"] == "normal"  # warning only so far
    sweeper.sweep(
        system_engine(),
        now=datetime(2026, 11, 3, 10, tzinfo=UTC),
        workspace_id=uuid.UUID(owner.workspace_id),
    )
    assert ticket_of(owner, tk["id"])["priority"] == "urgent"


def test_only_the_active_version_runs(client_factory: ClientFactory, postgres_url: str) -> None:
    owner = make_owner(client_factory)
    definition = refund_rule([{"type": "set_priority", "value": "high"}])
    rid = live(owner, postgres_url, "Refunds", definition)
    v2 = {**definition, "actions": [{"type": "set_priority", "value": "urgent"}]}
    assert (
        owner.client.put(
            f"/api/rules/{rid}", json={"definition": v2}, headers={"X-CSRF-Token": owner.csrf}
        ).status_code
        == 200
    )
    tk = new_ticket(owner, "Refund please")
    assert ticket_of(owner, tk["id"])["priority"] == "high"  # the untested draft v2 does not run
    assert executions(postgres_url, tk["id"])[0].rule_version == 1


def test_draft_and_archived_rules_do_not_run(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    owner.post(
        "/api/rules",
        {"name": "Draft", "definition": refund_rule([{"type": "set_priority", "value": "urgent"}])},
    )
    rid = live(owner, postgres_url, "Soon archived", refund_rule([{"type": "add_tag", "tag": "x"}]))
    owner.post(f"/api/rules/{rid}/archive", {})
    tk = new_ticket(owner, "Refund me")
    got = ticket_of(owner, tk["id"])
    assert got["priority"] == "normal" and got["tags"] == []
    assert executions(postgres_url, tk["id"]) == []


def test_conflicts_first_rule_wins_and_the_loser_is_recorded(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    live(
        owner,
        postgres_url,
        "First",
        refund_rule([{"type": "set_priority", "value": "urgent"}, {"type": "add_tag", "tag": "a"}]),
    )
    live(
        owner,
        postgres_url,
        "Second",
        refund_rule([{"type": "set_priority", "value": "low"}, {"type": "add_tag", "tag": "b"}]),
    )
    tk = new_ticket(owner, "Refund conflict")
    got = ticket_of(owner, tk["id"])
    assert got["priority"] == "urgent" and got["tags"] == ["a", "b"]
    by_name = {e.name: e for e in executions(postgres_url, tk["id"])}
    first, second = by_name["First"], by_name["Second"]
    assert second.actions[0]["status"] == "skipped" and "First" in second.actions[0]["reason"]
    assert first.actions[0]["status"] == "applied"


def test_a_loop_between_two_rules_stops_and_each_fires_once(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    live(
        owner,
        postgres_url,
        "A",
        when(
            "status.changed",
            "status",
            "equals",
            "open",
            [{"type": "set_status", "value": "pending"}],
        ),
    )
    live(
        owner,
        postgres_url,
        "B",
        when(
            "status.changed",
            "status",
            "equals",
            "pending",
            [{"type": "set_status", "value": "open"}],
        ),
    )
    tk = new_ticket(owner, "Loop")
    owner.patch(f"/api/tickets/{tk['id']}", {"status": "open"})
    names = [e.name for e in executions(postgres_url, tk["id"])]
    assert names.count("A") == 1 and names.count("B") == 1
    assert ticket_of(owner, tk["id"])["status"] == "open"  # the chain ended after B set it back


def test_chains_stop_at_depth_three(client_factory: ClientFactory, postgres_url: str) -> None:
    owner = make_owner(client_factory)
    steps = [
        ("ticket.created", "channel", "equals", "manual", "open"),
        ("status.changed", "status", "equals", "open", "pending"),
        ("status.changed", "status", "equals", "pending", "resolved"),
        ("status.changed", "status", "equals", "resolved", "closed"),
    ]
    for i, (ev, f, op, val, to) in enumerate(steps):
        live(
            owner,
            postgres_url,
            f"R{i + 1}",
            when(ev, f, op, val, [{"type": "set_status", "value": to}]),
        )
    tk = new_ticket(owner, "Deep chain")
    assert ticket_of(owner, tk["id"])["status"] == "resolved"  # R4 would be a fourth level
    depths = sorted(e.depth for e in executions(postgres_url, tk["id"]))
    assert depths == [1, 2, 3]


def test_a_rule_that_cannot_act_records_a_failure_but_never_blocks_the_change(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    t = team(client_factory)
    live(
        t["owner"],
        postgres_url,
        "Assign agent",
        refund_rule(
            [
                {"type": "assign", "target": "user", "user_id": t["agent"].user_id},
                {"type": "set_priority", "value": "high"},
            ]
        ),
    )
    t["owner"].patch(f"/api/members/{t['agent'].user_id}", {"active": False})
    tk = new_ticket(t["owner"], "Refund after the agent left")  # must still succeed
    got = ticket_of(t["owner"], tk["id"])
    assert got["assignee"] is None and got["priority"] == "high"
    (ex,) = executions(postgres_url, tk["id"])
    assert [a["status"] for a in ex.actions] == ["failed", "applied"] and ex.actions[0]["reason"]


def test_rules_never_touch_other_workspaces(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    a, b = make_owner(client_factory, "Alpha"), make_owner(client_factory, "Bravo")
    live(
        a, postgres_url, "Alpha refunds", refund_rule([{"type": "set_priority", "value": "urgent"}])
    )
    tb = new_ticket(b, "Refund in the other workspace")
    assert (
        ticket_of(b, tb["id"])["priority"] == "normal" and executions(postgres_url, tb["id"]) == []
    )


def test_loading_rules_costs_one_query_per_event(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    for i in range(3):
        live(
            owner,
            postgres_url,
            f"R{i}",
            when(
                "ticket.created",
                "subject",
                "contains",
                f"never-{i}",
                [{"type": "add_tag", "tag": "x"}],
            ),
        )
    seen: list[str] = []

    def spy(conn: Any, cursor: Any, statement: str, *args: Any) -> None:
        if " from rules " in statement.lower() and "rule_versions" in statement.lower():
            seen.append(statement)

    event.listen(app_engine(), "before_cursor_execute", spy)
    try:
        new_ticket(owner, "Nothing matches here")
    finally:
        event.remove(app_engine(), "before_cursor_execute", spy)
    assert len(seen) <= 1

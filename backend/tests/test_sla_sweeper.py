import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text

from resolveflow.celery_app import celery
from resolveflow.db import engine_for, system_engine
from resolveflow.sla import service, sweeper
from resolveflow.tasks import sla as sla_tasks
from tests.helpers import Actor, ClientFactory, make_owner
from tests.test_tickets import new_ticket


def day(d: int, hh: int, mm: int = 0) -> datetime:
    """November 2026: day 2 is a Monday. Defaults: Mon-Fri 09:00-17:00 UTC, normal 8h / 24h."""
    return datetime(2026, 11, d, hh, mm, tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, datetime]]:
    state = {"now": day(2, 10)}
    monkeypatch.setattr(service, "utcnow", lambda: state["now"])
    yield state


def threshold_events(url: str, ticket_id: str) -> list[tuple[str, str]]:
    with engine_for(url).connect() as conn:
        rows = conn.execute(
            text(
                "select detail->>'metric', detail->>'level' from sla_events "
                "where ticket_id = :t and kind = 'threshold' order by at, id"
            ),
            {"t": uuid.UUID(ticket_id)},
        ).all()
    return [(r[0], r[1]) for r in rows]


def row(url: str, ticket_id: str) -> Any:
    with engine_for(url).connect() as conn:
        return conn.execute(
            text("select * from ticket_sla where ticket_id = :t"), {"t": uuid.UUID(ticket_id)}
        ).one()


def run(now: datetime, *actors: Actor) -> sweeper.SweepResult:
    """Sweep only these actors' workspaces: the shared test database also holds other tests' data."""
    total = sweeper.SweepResult()
    for a in actors:
        r = sweeper.sweep(system_engine(), now=now, workspace_id=uuid.UUID(a.workspace_id))
        total.thresholds += r.thresholds
        total.recomputed += r.recomputed
        total.backfilled += r.backfilled
    return total


def test_a_warning_then_a_breach_are_recorded_once_each(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    assert run(day(2, 15, 59), owner).thresholds == 0  # 75% of 8 business hours is Mon 16:00
    assert run(day(2, 16), owner).thresholds == 1
    assert threshold_events(postgres_url, t["id"]) == [("first_response", "warning")]
    r = row(postgres_url, t["id"])
    assert r.fr_warned_at == day(2, 16) and r.fr_breached_at is None
    assert r.next_check_at == day(3, 10)  # the breach moment is next
    assert run(day(3, 10), owner).thresholds == 1
    assert threshold_events(postgres_url, t["id"]) == [
        ("first_response", "warning"),
        ("first_response", "breach"),
    ]
    assert row(postgres_url, t["id"]).fr_breached_at == day(3, 10)
    assert (
        run(day(3, 11), owner).thresholds == 0
    )  # nothing new until the resolution warning (Wed 12:00)
    actions = [a["action"] for a in owner.get("/api/audit?limit=50").json()["items"]]
    assert actions.count("sla.warning") == 1 and actions.count("sla.breached") == 1


def test_running_twice_or_concurrently_never_duplicates(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    tickets = [new_ticket(owner, f"T{i}") for i in range(4)]
    now = day(3, 12)  # first response warned and breached; resolution not yet at 75%
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda _: run(now, owner).thresholds, range(6)))
    assert sum(results) == 4 * 2
    for t in tickets:
        assert threshold_events(postgres_url, t["id"]) == [
            ("first_response", "warning"),
            ("first_response", "breach"),
        ]
    assert run(now, owner).thresholds == 0


def test_waiting_on_the_customer_is_never_warned_and_met_metrics_stay_quiet(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    waiting, answered = new_ticket(owner, "Waiting"), new_ticket(owner, "Answered")
    clock["now"] = day(2, 12)
    assert owner.patch(f"/api/tickets/{waiting['id']}", {"status": "pending"}).status_code == 200
    clock["now"] = day(2, 11)
    owner.post(f"/api/tickets/{answered['id']}/messages", {"body": "Hi", "kind": "public"})
    run(day(2, 20), owner)
    assert threshold_events(postgres_url, waiting["id"]) == []
    assert (
        threshold_events(postgres_url, answered["id"]) == []
    )  # first response met, resolution not at 75% yet


def test_cold_start_after_downtime_catches_up_everything_overdue_in_order(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    tickets = [new_ticket(owner, f"Old {i}") for i in range(3)]
    # The scheduler was down; four days later the first sweep finds every deadline long gone.
    result = run(day(6, 12), owner)
    assert result.thresholds == 3 * 4
    for t in tickets:
        assert threshold_events(postgres_url, t["id"]) == [
            ("first_response", "warning"),
            ("first_response", "breach"),
            ("resolution", "warning"),
            ("resolution", "breach"),
        ]
        assert row(postgres_url, t["id"]).next_check_at is None
    assert run(day(6, 13), owner).thresholds == 0


def test_a_crash_mid_batch_leaves_no_partial_state_and_the_next_sweep_finishes(
    client_factory: ClientFactory,
    postgres_url: str,
    clock: dict[str, datetime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = make_owner(client_factory)
    tickets = [new_ticket(owner, f"Crash {i}") for i in range(3)]
    real = sweeper._process_ticket
    calls = {"n": 0}

    def flaky(ctx: Any, ticket: Any, now: datetime) -> int:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("worker killed")
        return real(ctx, ticket, now)

    with monkeypatch.context() as m:
        m.setattr(sweeper, "_process_ticket", flaky)
        with pytest.raises(RuntimeError):
            run(day(3, 12), owner)
    for t in tickets:
        assert threshold_events(postgres_url, t["id"]) == []  # the whole batch rolled back
    assert run(day(3, 12), owner).thresholds == 3 * 2


def test_editing_the_policy_reschedules_open_tickets_and_keeps_recorded_breaches(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    breached, fresh = new_ticket(owner, "Breached"), None
    run(day(3, 10), owner)  # warning and breach for the first ticket are on record
    assert row(postgres_url, breached["id"]).fr_breached_at == day(3, 10)
    clock["now"] = day(3, 10, 30)
    fresh = new_ticket(owner, "Fresh")  # starts Tue 10:30 under the old policy
    body = owner.get("/api/settings/sla").json()
    body.pop("version")
    body["targets"]["normal"] = {"first_response_minutes": 120, "resolution_minutes": 1440}
    assert (
        owner.client.put(
            "/api/settings/sla", json=body, headers={"X-CSRF-Token": owner.csrf}
        ).status_code
        == 200
    )
    run(day(3, 11), owner)
    again = row(postgres_url, fresh["id"])
    assert again.fr_target_min == 120 and again.fr_due_at == day(
        3, 12, 30
    )  # two business hours from 10:30
    assert row(postgres_url, breached["id"]).fr_breached_at == day(3, 10)  # history is kept
    assert threshold_events(postgres_url, breached["id"]).count(("first_response", "breach")) == 1
    run(day(3, 11), owner)  # a second pass must not record the policy change again
    with engine_for(postgres_url).connect() as conn:
        n = conn.execute(
            text(
                "select count(*) from sla_events where ticket_id = :t and kind = 'policy_changed'"
            ),
            {"t": uuid.UUID(fresh["id"])},
        ).scalar_one()
    assert n == 1
    run(day(3, 12, 30), owner)
    assert threshold_events(postgres_url, fresh["id"]) == [
        ("first_response", "warning"),
        ("first_response", "breach"),
    ]


def test_tickets_without_a_clock_row_are_backfilled(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    with engine_for(postgres_url).begin() as conn:
        conn.execute(text("delete from ticket_sla where ticket_id = :t"), {"t": uuid.UUID(t["id"])})
    result = run(day(2, 11), owner)
    assert result.backfilled >= 1
    assert row(postgres_url, t["id"]).fr_due_at is not None


def test_a_sweep_only_acts_on_what_is_due_in_each_workspace(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    a, b = make_owner(client_factory, "Alpha"), make_owner(client_factory, "Bravo")
    body = b.get("/api/settings/sla").json()
    body.pop("version")
    body["targets"]["normal"] = {"first_response_minutes": 2400, "resolution_minutes": 4800}
    assert (
        b.client.put("/api/settings/sla", json=body, headers={"X-CSRF-Token": b.csrf}).status_code
        == 200
    )
    ta, tb = new_ticket(a), new_ticket(b)
    run(day(2, 16), a, b)
    assert threshold_events(postgres_url, ta["id"]) == [("first_response", "warning")]
    assert threshold_events(postgres_url, tb["id"]) == []


def test_the_sweep_is_scheduled_by_beat_and_runs_as_a_task(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    entry = celery.conf.beat_schedule["sla-sweep"]
    assert entry["task"] == "resolveflow.tasks.sla.sweep" and entry["schedule"] == 60.0
    assert celery.conf.task_acks_late is True
    owner = make_owner(client_factory)
    new_ticket(owner)
    out = sla_tasks.sweep(now=day(3, 12).isoformat())
    assert out["thresholds"] >= 2
    assert isinstance(owner, Actor)

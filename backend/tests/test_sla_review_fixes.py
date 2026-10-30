"""Regression tests for the findings of the M2 whole-branch review."""

import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from datetime import time as dtime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from resolveflow.context import SystemContext
from resolveflow.db import engine_for, system_engine
from resolveflow.services import tickets as ticket_svc
from resolveflow.sla import service, sweeper
from resolveflow.sla.engine import Calendar, compute_due
from tests.helpers import Actor, ClientFactory, make_owner
from tests.test_ingest import DOMAIN, payload, post, token_of
from tests.test_tickets import new_ticket


def at(d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(2026, 11, d, hh, mm, tzinfo=UTC)  # day 2 is a Monday


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, datetime]]:
    state = {"now": at(2, 10)}
    monkeypatch.setattr(service, "utcnow", lambda: state["now"])
    yield state


def put(actor: Actor, mutate: Any) -> Any:
    body = actor.get("/api/settings/sla").json()
    body.pop("version")
    mutate(body)
    return actor.client.put("/api/settings/sla", json=body, headers={"X-CSRF-Token": actor.csrf})


def run(now: datetime, *actors: Actor) -> sweeper.SweepResult:
    total = sweeper.SweepResult()
    for a in actors:
        r = sweeper.sweep(system_engine(), now=now, workspace_id=uuid.UUID(a.workspace_id))
        total.thresholds += r.thresholds
        total.recomputed += r.recomputed
        total.backfilled += r.backfilled
    return total


def row(url: str, ticket_id: str) -> Any:
    with engine_for(url).connect() as conn:
        return conn.execute(
            text("select * from ticket_sla where ticket_id = :t"), {"t": uuid.UUID(ticket_id)}
        ).one()


def sla(actor: Actor, ticket_id: str) -> dict[str, Any]:
    return dict(actor.get(f"/api/tickets/{ticket_id}").json()["sla"])


# --- C1: a bad calendar must never break ticket writes or the shared sweeper --------------------


def test_settings_that_cannot_produce_deadlines_are_rejected(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    closed = put(
        owner,
        lambda b: b.update(
            schedule={d: [] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}
        ),
    )
    assert closed.status_code == 422 and "opening hours" in closed.text
    ok_24x7 = put(
        owner,
        lambda b: b.update(
            business_hours_only=False,
            schedule={d: [] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")},
        ),
    )
    assert ok_24x7.status_code == 200  # no calendar is needed when every hour counts
    tiny = {"mon": [{"start": "09:00", "end": "09:15"}]}
    long_target = put(
        owner,
        lambda b: b.update(
            schedule={**{d: [] for d in ("tue", "wed", "thu", "fri", "sat", "sun")}, **tiny},
            targets={
                p: {"first_response_minutes": 10, "resolution_minutes": 525_000}
                for p in ("low", "normal", "high", "urgent")
            },
            business_hours_only=True,
        ),
    )
    assert long_target.status_code == 422 and "business hours" in long_target.text


def test_ticket_writes_survive_a_legacy_calendar_with_no_opening_hours(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    with engine_for(postgres_url).begin() as conn:  # a config that predates the validation
        conn.execute(
            text(
                "update business_calendars set weekly = cast(:w as jsonb) where workspace_id = :ws"
            ),
            {
                "w": '{"mon":[],"tue":[],"wed":[],"thu":[],"fri":[],"sat":[],"sun":[]}',
                "ws": uuid.UUID(owner.workspace_id),
            },
        )
    t = new_ticket(owner)  # must not 500
    assert (
        owner.post(f"/api/tickets/{t['id']}/messages", {"body": "Hi", "kind": "public"}).status_code
        == 200
    )
    assert owner.patch(f"/api/tickets/{t['id']}", {"status": "resolved"}).status_code == 200
    r = row(postgres_url, t["id"])
    assert r.fr_due_at is None and r.next_check_at is None


def test_one_poisoned_ticket_cannot_block_other_workspaces(
    client_factory: ClientFactory,
    postgres_url: str,
    clock: dict[str, datetime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b = make_owner(client_factory, "Poison"), make_owner(client_factory, "Healthy")
    ta, tb = new_ticket(a), new_ticket(b)
    real = sweeper._process_ticket

    def poisoned(ctx: Any, ticket: Any, now: datetime) -> int:
        if str(ticket.ticket_id) == ta["id"]:
            raise ValueError("calendar has no working hours")
        return real(ctx, ticket, now)

    monkeypatch.setattr(sweeper, "_process_ticket", poisoned)
    sweeper.sweep(system_engine(), now=at(3, 12))  # the global path, as beat runs it
    with engine_for(postgres_url).connect() as conn:
        healthy = conn.execute(
            text("select count(*) from sla_events where ticket_id = :t and kind = 'threshold'"),
            {"t": uuid.UUID(tb["id"])},
        ).scalar_one()
    assert healthy == 2
    assert row(postgres_url, ta["id"]).next_check_at > at(
        3, 12
    )  # parked, not retried in a tight loop


def test_a_killed_sweep_still_rolls_back_the_whole_batch(
    client_factory: ClientFactory,
    postgres_url: str,
    clock: dict[str, datetime],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = make_owner(client_factory)
    tickets = [new_ticket(owner, f"Kill {i}") for i in range(3)]
    real = sweeper._process_ticket
    calls = {"n": 0}

    def killed(ctx: Any, ticket: Any, now: datetime) -> int:
        calls["n"] += 1
        if calls["n"] == 2:
            raise SystemExit(
                "worker killed"
            )  # a BaseException: not swallowed by per-ticket isolation
        return real(ctx, ticket, now)

    with monkeypatch.context() as m:
        m.setattr(sweeper, "_process_ticket", killed)
        with pytest.raises(SystemExit):
            run(at(3, 12), owner)
    with engine_for(postgres_url).connect() as conn:
        n = conn.execute(
            text(
                "select count(*) from sla_events where kind = 'threshold' and ticket_id = any(:ids)"
            ),
            {"ids": [uuid.UUID(t["id"]) for t in tickets]},
        ).scalar_one()
    assert n == 0
    assert run(at(3, 12), owner).thresholds == 3 * 2


# --- C2: reopening or re-prioritising starts a fresh escalation cycle ----------------------------


def test_reopening_clears_the_old_breach_and_the_new_cycle_is_escalated_again(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    run(at(6, 12), owner)  # long overdue: first response and resolution warned and breached
    assert row(postgres_url, t["id"]).res_breached_at is not None
    clock["now"] = at(6, 12)
    owner.post(
        f"/api/tickets/{t['id']}/messages", {"body": "Sorry for the wait", "kind": "public"}
    )  # a late first response
    owner.patch(f"/api/tickets/{t['id']}", {"status": "resolved"})
    clock["now"] = at(9, 9)  # next Monday the customer returns
    owner.patch(f"/api/tickets/{t['id']}", {"status": "open"})
    r = row(postgres_url, t["id"])
    assert r.res_breached_at is None and r.res_warned_at is None
    assert sla(owner, t["id"])["resolution"]["state"] == "running"
    assert t["id"] not in {i["id"] for i in owner.get("/api/tickets?sla=breached").json()["items"]}
    run(at(11, 11), owner)  # Wed 11:00: 75% of 24 business hours since Mon 09:00
    r = row(postgres_url, t["id"])
    assert r.res_warned_at == at(11, 11) and r.res_breached_at is None
    run(at(11, 17), owner)
    assert row(postgres_url, t["id"]).res_breached_at == at(11, 17)


def test_changing_priority_after_a_warning_starts_over(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    run(at(2, 16), owner)
    assert sla(owner, t["id"])["first_response"]["state"] == "at_risk"
    clock["now"] = at(2, 16, 5)
    owner.patch(
        f"/api/tickets/{t['id']}", {"priority": "low"}
    )  # low: first response 24 business hours
    assert sla(owner, t["id"])["first_response"]["state"] == "running"
    assert row(postgres_url, t["id"]).fr_warned_at is None


def test_a_policy_edit_keeps_the_breach_that_was_already_recorded(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    t = new_ticket(owner)
    run(at(3, 10), owner)
    assert row(postgres_url, t["id"]).fr_breached_at == at(3, 10)
    put(
        owner,
        lambda b: b["targets"].update(
            normal={"first_response_minutes": 120, "resolution_minutes": 1440}
        ),
    )
    run(at(3, 11), owner)
    assert row(postgres_url, t["id"]).fr_breached_at == at(
        3, 10
    )  # history survives a policy change


# --- I1: opening ranges may arrive in any order ----------------------------------------------


def test_unsorted_opening_ranges_give_the_same_answer_as_sorted_ones() -> None:
    utc = ZoneInfo("UTC")
    sorted_cal = Calendar(utc, {0: [(dtime(9), dtime(12)), (dtime(13), dtime(17))]}, frozenset())
    mixed_cal = Calendar(utc, {0: [(dtime(13), dtime(17)), (dtime(9), dtime(12))]}, frozenset())
    start = at(2, 8)
    assert (
        compute_due(start, 300, mixed_cal, [])
        == compute_due(start, 300, sorted_cal, [])
        == at(2, 15)  # 3 h morning + 2 h after lunch
    )


def test_saved_schedules_are_stored_sorted(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    r = put(
        owner,
        lambda b: b["schedule"].update(
            mon=[{"start": "13:00", "end": "17:00"}, {"start": "09:00", "end": "12:00"}]
        ),
    )
    assert r.status_code == 200
    assert owner.get("/api/settings/sla").json()["schedule"]["mon"] == [
        {"start": "09:00", "end": "12:00"},
        {"start": "13:00", "end": "17:00"},
    ]


# --- I2: sweeper and ticket writes must not deadlock -------------------------------------------


def test_sweeping_while_tickets_change_never_deadlocks(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    tickets = [new_ticket(owner, f"Busy {i}") for i in range(6)]
    errors: list[BaseException] = []
    stop = threading.Event()

    def sweeper_loop() -> None:
        try:
            while not stop.is_set():
                run(at(6, 12), owner)
        except BaseException as exc:  # noqa: BLE001 - collect any failure from the thread
            errors.append(exc)

    th = threading.Thread(target=sweeper_loop)
    th.start()
    try:
        for i in range(30):
            t = tickets[i % len(tickets)]
            owner.patch(f"/api/tickets/{t['id']}", {"status": "pending" if i % 2 == 0 else "open"})
            owner.post(f"/api/tickets/{t['id']}/messages", {"body": "x", "kind": "note"})
    finally:
        stop.set()
        th.join(timeout=30)
    assert errors == []


# --- I3: an inbound reply must not race an agent's status change ---------------------------------


def test_an_inbound_reply_waits_for_a_concurrent_status_change_and_resumes_the_clock(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    to = f"inbound-{token_of(postgres_url, owner)}@{DOMAIN}"
    tid = post(client_factory(), payload(to, message_id="<race1@customer.test>")).json()[
        "ticket_id"
    ]
    ws = uuid.UUID(owner.workspace_id)
    result: dict[str, Any] = {}

    def inbound() -> None:
        result["r"] = post(
            client_factory(), payload(to, in_reply_to="<race1@customer.test>", subject="Re: x")
        ).json()

    with Session(system_engine()) as s, s.begin():
        clock["now"] = at(2, 12)
        ticket_svc.update_ticket(
            SystemContext(s, ws), uuid.UUID(tid), {"status": "pending"}
        )  # holds the row lock
        th = threading.Thread(target=inbound)
        th.start()
        time.sleep(0.8)  # the reply is now waiting on the agent's transaction
    th.join(timeout=20)
    assert result["r"]["status"] == "appended"
    r = row(postgres_url, tid)
    assert r.paused_at is None
    with engine_for(postgres_url).connect() as conn:
        status = conn.execute(
            text("select status from tickets where id = :t"), {"t": uuid.UUID(tid)}
        ).scalar_one()
    assert status == "open"


# --- I4: ordering and reconciliation of pause state ----------------------------------------------


def test_events_with_identical_timestamps_pair_up_in_insertion_order(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    for i in range(12):
        t = new_ticket(owner, f"Same instant {i}")
        tid = uuid.UUID(t["id"])
        with Session(system_engine()) as s, s.begin():
            ctx = SystemContext(s, uuid.UUID(owner.workspace_id))
            service.record_event(ctx, tid, "paused", at=at(2, 12))
            service.record_event(ctx, tid, "resumed", at=at(2, 12))
            s.execute(text("update tickets set status = 'open' where id = :t"), {"t": tid})
            service.recompute(ctx, tid)
        assert row(postgres_url, t["id"]).paused_at is None


def test_pause_state_is_reconciled_with_the_ticket_status(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    skewed, missing = new_ticket(owner, "Skewed clock"), new_ticket(owner, "Lost pause")
    ws = uuid.UUID(owner.workspace_id)
    with Session(system_engine()) as s, s.begin():
        ctx = SystemContext(s, ws)
        # A worker whose clock ran slow: the resume sorts before the pause it belongs to.
        service.record_event(ctx, uuid.UUID(skewed["id"]), "resumed", at=at(2, 10, 59))
        service.record_event(ctx, uuid.UUID(skewed["id"]), "paused", at=at(2, 11))
        s.execute(
            text("update tickets set status = 'open' where id = :t"), {"t": uuid.UUID(skewed["id"])}
        )
        service.recompute(ctx, uuid.UUID(skewed["id"]))
        # The reverse: the ticket is pending but no pause event was ever recorded.
        s.execute(
            text("update tickets set status = 'pending' where id = :t"),
            {"t": uuid.UUID(missing["id"])},
        )
        service.recompute(ctx, uuid.UUID(missing["id"]))
    assert row(postgres_url, skewed["id"]).paused_at is None
    assert row(postgres_url, missing["id"]).paused_at is not None


# --- I5: a policy change reaches every open ticket without waiting for many ticks ----------------


def test_one_sweep_reschedules_every_stale_ticket_even_across_batches(
    client_factory: ClientFactory, postgres_url: str, clock: dict[str, datetime]
) -> None:
    owner = make_owner(client_factory)
    tickets = [new_ticket(owner, f"Stale {i}") for i in range(5)]
    done = new_ticket(owner, "Already resolved")
    owner.patch(f"/api/tickets/{done['id']}", {"status": "resolved"})
    put(
        owner,
        lambda b: b["targets"].update(
            normal={"first_response_minutes": 120, "resolution_minutes": 1440}
        ),
    )
    result = sweeper.sweep(
        system_engine(), now=at(2, 11), batch=2, workspace_id=uuid.UUID(owner.workspace_id)
    )
    assert result.recomputed >= 5
    for t in tickets:
        assert row(postgres_url, t["id"]).fr_target_min == 120
    with engine_for(postgres_url).connect() as conn:
        stale = conn.execute(
            text(
                "select count(*) from ticket_sla ts join sla_policies p on p.workspace_id = ts.workspace_id "
                "where ts.workspace_id = :w and ts.policy_version <> p.version"
            ),
            {"w": uuid.UUID(owner.workspace_id)},
        ).scalar_one()
    assert stale == 0  # resolved tickets are version-bumped too, so nothing is selected forever

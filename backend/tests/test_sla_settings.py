import copy
import uuid

import pytest
from sqlalchemy import text

from resolveflow.db import engine_for
from resolveflow.sla.defaults import backfill_defaults, default_settings
from tests.helpers import Actor, ClientFactory, make_owner, team


def get_settings(actor: Actor) -> dict:  # type: ignore[type-arg]
    r = actor.get("/api/settings/sla")
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_new_workspaces_start_with_sensible_defaults(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    s = get_settings(owner)
    expected = default_settings()
    assert s["enabled"] is True and s["business_hours_only"] is True and s["version"] == 1
    assert s["targets"] == expected["targets"]
    assert s["timezone"] == "UTC"
    assert s["schedule"]["mon"] == [{"start": "09:00", "end": "17:00"}]
    assert s["schedule"]["sat"] == [] and s["holidays"] == []
    assert s["targets"]["urgent"] == {"first_response_minutes": 60, "resolution_minutes": 240}


def test_put_round_trips_bumps_the_version_and_is_audited(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    body = get_settings(owner)
    body.pop("version")
    body["business_hours_only"] = False
    body["timezone"] = "Europe/London"
    body["targets"]["high"] = {"first_response_minutes": 30, "resolution_minutes": 120}
    body["schedule"]["sat"] = [{"start": "10:00", "end": "14:00"}]
    body["holidays"] = ["2026-12-25", "2026-12-26"]
    r = owner.client.put("/api/settings/sla", json=body, headers={"X-CSRF-Token": owner.csrf})
    assert r.status_code == 200, r.text
    after = get_settings(owner)
    assert after["version"] == 2
    assert after["business_hours_only"] is False and after["timezone"] == "Europe/London"
    assert after["targets"]["high"] == {"first_response_minutes": 30, "resolution_minutes": 120}
    assert after["schedule"]["sat"] == [{"start": "10:00", "end": "14:00"}]
    assert after["holidays"] == ["2026-12-25", "2026-12-26"]
    with engine_for(postgres_url).connect() as conn:
        row = conn.execute(
            text(
                "select before, after from audit_log where action = 'settings.sla_updated' "
                "and workspace_id = :w"
            ),
            {"w": uuid.UUID(owner.workspace_id)},
        ).one()
    assert row.before["business_hours_only"] is True and row.after["business_hours_only"] is False


def _valid(owner: Actor) -> dict:  # type: ignore[type-arg]
    body = get_settings(owner)
    body.pop("version")
    return body


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda b: b["targets"]["low"].update(first_response_minutes=0), "first_response_minutes"),
        (lambda b: b["targets"]["low"].update(resolution_minutes=600_000), "resolution_minutes"),
        (
            lambda b: b["targets"]["urgent"].update(
                first_response_minutes=500, resolution_minutes=100
            ),
            "resolution",
        ),
        (lambda b: b.update(timezone="Mars/Olympus_Mons"), "timezone"),
        (lambda b: b["schedule"].update(mon=[{"start": "17:00", "end": "09:00"}]), "start"),
        (
            lambda b: b["schedule"].update(
                mon=[{"start": "09:00", "end": "12:00"}, {"start": "11:00", "end": "14:00"}]
            ),
            "overlap",
        ),
        (lambda b: b["schedule"].update(mon=[{"start": "9am", "end": "5pm"}]), "start"),
        (
            lambda b: b["schedule"].update(
                mon=[{"start": f"0{i}:00", "end": f"0{i}:30"} for i in range(5)]
            ),
            "mon",
        ),
        (lambda b: b.update(holidays=["2026-02-30"]), "holidays"),
        (
            lambda b: b.update(holidays=[f"2027-01-{(i % 28) + 1:02d}" for i in range(101)]),
            "holidays",
        ),
        (lambda b: b["targets"].pop("normal"), "normal"),
    ],
)
def test_validation_rejects_bad_settings_with_a_plain_message(
    client_factory: ClientFactory,
    mutate,
    needle: str,  # type: ignore[no-untyped-def]
) -> None:
    owner = make_owner(client_factory)
    body = copy.deepcopy(_valid(owner))
    mutate(body)
    r = owner.client.put("/api/settings/sla", json=body, headers={"X-CSRF-Token": owner.csrf})
    assert r.status_code == 422, r.text
    assert needle in r.text
    assert get_settings(owner)["version"] == 1  # nothing was saved


def test_only_owner_and_admin_can_view_or_change_service_levels(
    client_factory: ClientFactory,
) -> None:
    t = team(client_factory)
    body = _valid(t["owner"])
    for role, want in {"owner": 200, "admin": 200, "agent": 403, "viewer": 403}.items():
        assert t[role].get("/api/settings/sla").status_code == want, role
        got = t[role].client.put(
            "/api/settings/sla", json=body, headers={"X-CSRF-Token": t[role].csrf}
        )
        assert got.status_code == want, role


def test_settings_are_per_workspace(client_factory: ClientFactory) -> None:
    a = make_owner(client_factory, "Alpha")
    b = make_owner(client_factory, "Bravo")
    body = _valid(a)
    body["business_hours_only"] = False
    assert (
        a.client.put("/api/settings/sla", json=body, headers={"X-CSRF-Token": a.csrf}).status_code
        == 200
    )
    assert get_settings(b)["business_hours_only"] is True and get_settings(b)["version"] == 1


def test_backfill_creates_defaults_for_existing_workspaces_and_is_idempotent(
    migrated_env: None, postgres_url: str
) -> None:
    with engine_for(postgres_url).begin() as conn:
        ws = conn.execute(
            text(
                "insert into workspaces (slug, name, inbound_token) values (:s, 'Legacy', :t) returning id"
            ),
            {"s": f"legacy-{uuid.uuid4().hex[:6]}", "t": uuid.uuid4().hex[:16]},
        ).scalar_one()
        backfill_defaults(conn)
        backfill_defaults(conn)
        policies = conn.execute(
            text("select count(*) from sla_policies where workspace_id = :w"), {"w": ws}
        ).scalar_one()
        calendars = conn.execute(
            text("select count(*) from business_calendars where workspace_id = :w"), {"w": ws}
        ).scalar_one()
    assert (policies, calendars) == (1, 1)


def test_a_legacy_workspace_without_rows_still_reads_defaults(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    with engine_for(postgres_url).begin() as conn:
        conn.execute(
            text("delete from sla_policies where workspace_id = :w"),
            {"w": uuid.UUID(owner.workspace_id)},
        )
        conn.execute(
            text("delete from business_calendars where workspace_id = :w"),
            {"w": uuid.UUID(owner.workspace_id)},
        )
    assert get_settings(owner)["targets"] == default_settings()["targets"]

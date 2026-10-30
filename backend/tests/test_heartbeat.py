import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from resolveflow.celery_app import celery
from resolveflow.db import engine_for
from resolveflow.health import check_scheduler
from resolveflow.tasks.system import heartbeat


def _set_beat_age(url: str, seconds: int) -> None:
    with engine_for(url).begin() as conn:
        conn.execute(text("DELETE FROM system_heartbeat"))
        conn.execute(
            text(
                "INSERT INTO system_heartbeat (id, beat_at) "
                "VALUES (1, now() - make_interval(secs => :s))"
            ),
            {"s": seconds},
        )


def test_heartbeat_upserts_single_row(migrated_env: None, postgres_url: str) -> None:
    heartbeat()
    with engine_for(postgres_url).connect() as conn:
        first = conn.execute(text("SELECT beat_at FROM system_heartbeat")).scalar_one()
    time.sleep(0.05)
    heartbeat()
    with engine_for(postgres_url).connect() as conn:
        rows = conn.execute(text("SELECT beat_at FROM system_heartbeat")).all()
    assert len(rows) == 1
    assert rows[0][0] > first


def test_scheduler_check_states(migrated_env: None, postgres_url: str) -> None:
    eng = engine_for(postgres_url)
    r = check_scheduler(eng)
    assert (r.ok, r.detail) == (False, "no heartbeat yet")
    _set_beat_age(postgres_url, 5)
    assert check_scheduler(eng).ok is True
    _set_beat_age(postgres_url, 300)
    r = check_scheduler(eng)
    assert r.ok is False
    assert r.detail.startswith("stale")


def test_system_endpoint_reports_stale_scheduler(
    migrated_env: None, postgres_url: str, client: TestClient
) -> None:
    _set_beat_age(postgres_url, 300)
    r = client.get("/api/health/system")
    assert r.status_code == 200
    checks = {c["name"]: c for c in r.json()["checks"]}
    assert set(checks) == {"db", "redis", "scheduler"}
    assert checks["scheduler"]["ok"] is False


def test_system_endpoint_is_200_when_db_is_down(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from resolveflow.config import get_settings

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1:1/db")
    get_settings.cache_clear()
    r = client.get("/api/health/system")
    assert r.status_code == 200
    checks = {c["name"]: c for c in r.json()["checks"]}
    assert checks["db"]["ok"] is False and checks["scheduler"]["ok"] is False


def test_celery_reliability_settings_and_schedule() -> None:
    assert celery.conf.task_acks_late is True
    assert celery.conf.task_reject_on_worker_lost is True
    assert celery.conf.broker_connection_retry_on_startup is True
    entry = celery.conf.beat_schedule["heartbeat"]
    assert entry["task"] == "resolveflow.tasks.system.heartbeat"
    assert entry["schedule"] == 30.0

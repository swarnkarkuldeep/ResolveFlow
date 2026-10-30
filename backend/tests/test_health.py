import pytest
from fastapi.testclient import TestClient

from resolveflow.config import get_settings
from resolveflow.db import app_engine
from resolveflow.main import app


def test_live_returns_ok() -> None:
    r = TestClient(app).get("/api/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_ok(client: TestClient) -> None:
    r = client.get("/api/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert {c["name"]: c["ok"] for c in body["checks"]} == {"db": True, "redis": True}


def test_ready_503_when_redis_down(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    get_settings.cache_clear()
    r = client.get("/api/health/ready")
    assert r.status_code == 503
    body = r.json()
    checks = {c["name"]: c for c in body["checks"]}
    assert checks["redis"]["ok"] is False
    assert checks["db"]["ok"] is True
    assert "Traceback" not in r.text


def test_ready_503_when_db_down(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("DATABASE_URL", "APP_DATABASE_URL"):
        monkeypatch.setenv(var, "postgresql+psycopg://u:p@127.0.0.1:1/db")
    get_settings.cache_clear()
    app_engine.cache_clear()
    r = client.get("/api/health/ready")
    assert r.status_code == 503
    checks = {c["name"]: c for c in r.json()["checks"]}
    assert checks["db"]["ok"] is False
    assert checks["redis"]["ok"] is True
    assert "Traceback" not in r.text and "u:p" not in r.text

from fastapi.testclient import TestClient

from resolveflow.main import app


def test_live_returns_ok() -> None:
    r = TestClient(app).get("/api/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

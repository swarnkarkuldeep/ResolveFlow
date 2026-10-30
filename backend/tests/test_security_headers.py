from fastapi.testclient import TestClient

from resolveflow.main import app


def test_api_responses_carry_hardening_headers_and_are_not_cacheable() -> None:
    r = TestClient(app).get("/api/health/live")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"


def test_error_responses_carry_them_too() -> None:
    r = TestClient(app).get("/api/tickets")  # unauthenticated
    assert r.status_code == 401
    assert r.headers["x-content-type-options"] == "nosniff"

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from alembic import command
from resolveflow.config import get_settings
from resolveflow.db import app_engine, engine_for, system_engine
from resolveflow.main import app

# Import-time defaults so modules that read settings at import (celery_app) can be collected;
# fixtures below override these with real container URLs.
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://x:x@127.0.0.1:1/x")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:1/0")


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """Real Postgres: CI service container via TEST_DATABASE_URL, else testcontainers."""
    if url := os.environ.get("TEST_DATABASE_URL"):
        yield url
        return
    with PostgresContainer("postgres:16", driver="psycopg") as pg:
        yield pg.get_connection_url()


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    if url := os.environ.get("TEST_REDIS_URL"):
        yield url
        return
    with RedisContainer("redis:7") as r:
        yield f"redis://{r.get_container_host_ip()}:{r.get_exposed_port(6379)}/0"


def _reset() -> None:
    get_settings.cache_clear()
    engine_for.cache_clear()
    app_engine.cache_clear()
    system_engine.cache_clear()


def _as_role(url: str, role: str, password: str) -> str:
    return make_url(url).set(username=role, password=password).render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def app_url(postgres_url: str) -> str:
    return _as_role(postgres_url, "rf_app", "rf_app_dev")


@pytest.fixture(scope="session")
def system_url(postgres_url: str) -> str:
    return _as_role(postgres_url, "rf_system", "rf_system_dev")


@pytest.fixture
def env(
    monkeypatch: pytest.MonkeyPatch,
    postgres_url: str,
    redis_url: str,
    app_url: str,
    system_url: str,
) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("APP_DATABASE_URL", app_url)
    monkeypatch.setenv("SYSTEM_DATABASE_URL", system_url)
    monkeypatch.setenv("REDIS_URL", redis_url)
    _reset()
    yield
    _reset()


@pytest.fixture
def client(migrated_env: None) -> TestClient:
    return TestClient(app)


@pytest.fixture
def migrated_env(env: None, postgres_url: str) -> Iterator[None]:
    """DB at head with an empty heartbeat table."""
    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "alembic"))
    cfg.set_main_option("sqlalchemy.url", postgres_url.replace("%", "%%"))
    command.upgrade(cfg, "head")
    with engine_for(postgres_url).begin() as conn:
        conn.execute(text("DELETE FROM system_heartbeat"))
    yield

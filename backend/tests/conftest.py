import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from alembic import command
from resolveflow.config import get_settings
from resolveflow.db import engine_for
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


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, postgres_url: str, redis_url: str) -> Iterator[None]:
    monkeypatch.setenv("DATABASE_URL", postgres_url)
    monkeypatch.setenv("REDIS_URL", redis_url)
    get_settings.cache_clear()
    engine_for.cache_clear()
    yield
    get_settings.cache_clear()
    engine_for.cache_clear()


@pytest.fixture
def client(env: None) -> TestClient:
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

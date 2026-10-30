import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer

from resolveflow.config import get_settings
from resolveflow.db import engine_for
from resolveflow.main import app


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

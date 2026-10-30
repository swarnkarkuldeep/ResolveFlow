from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from alembic import command

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def scratch_db_url(postgres_url: str) -> Iterator[str]:
    """A throwaway database so up/down migrations don't disturb other tests."""
    url = make_url(postgres_url)
    admin_dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS migtest")
        conn.execute("CREATE DATABASE migtest")
    yield url.set(database="migtest").render_as_string(hide_password=False)
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS migtest WITH (FORCE)")


def _cfg(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def _tables(url: str) -> set[str]:
    eng = create_engine(url)
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


def test_upgrade_head_then_downgrade_base(scratch_db_url: str) -> None:
    cfg = _cfg(scratch_db_url)
    command.upgrade(cfg, "head")
    assert "system_heartbeat" in _tables(scratch_db_url)
    command.downgrade(cfg, "base")
    assert "system_heartbeat" not in _tables(scratch_db_url)


def test_upgrade_is_idempotent(scratch_db_url: str) -> None:
    cfg = _cfg(scratch_db_url)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")
    assert "system_heartbeat" in _tables(scratch_db_url)

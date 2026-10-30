import pytest
from pydantic import ValidationError

from resolveflow.config import Settings, get_settings


def test_settings_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h/db")
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/0")
    get_settings.cache_clear()
    s = get_settings()
    assert s.database_url == "postgresql+psycopg://u:p@h/db"
    assert s.redis_url == "redis://h:6379/0"
    get_settings.cache_clear()


def test_missing_database_url_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/0")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from resolveflow.config import get_settings


@lru_cache
def engine_for(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 2})


@lru_cache
def app_engine() -> Engine:
    s = get_settings()
    return engine_for(s.app_database_url or s.database_url)


@lru_cache
def system_engine() -> Engine:
    s = get_settings()
    return engine_for(s.system_database_url or s.database_url)


def get_session() -> Iterator[Session]:
    with sessionmaker(engine_for(get_settings().database_url))() as session:
        yield session

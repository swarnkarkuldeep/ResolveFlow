from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str
    redis_url: str
    smtp_host: str = "mailpit"
    smtp_port: int = 1025


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

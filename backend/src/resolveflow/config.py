from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"
    database_url: str
    redis_url: str
    smtp_host: str = "mailpit"
    smtp_port: int = 1025

    # Connection roles: `database_url` is the owner (migrations); the API/worker use the
    # non-superuser `rf_app` (RLS enforced); sweepers use `rf_system` (BYPASSRLS).
    app_database_url: str | None = None
    system_database_url: str | None = None
    app_db_password: str = "rf_app_dev"  # noqa: S105 - dev default, overridden in prod
    system_db_password: str = "rf_system_dev"  # noqa: S105

    public_base_url: str = "http://localhost:3000"
    inbound_domain: str = "inbound.resolveflow.local"
    email_provider: Literal["smtp", "postmark", "memory"] = "smtp"
    mail_from: str = "support@resolveflow.local"
    postmark_server_token: str | None = None
    postmark_webhook_secret: str | None = None
    seed_demo: bool = False
    simulate_inbound_enabled: bool = False
    cookie_secure: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

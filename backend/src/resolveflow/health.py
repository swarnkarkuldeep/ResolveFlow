from dataclasses import asdict, dataclass

import redis
from sqlalchemy import Engine, text


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, str | bool]:
        return asdict(self)


def check_db(engine: Engine) -> CheckResult:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return CheckResult("db", True, "ok")
    except Exception as exc:  # report, never raise; class name only so no URL/credentials leak
        return CheckResult("db", False, f"unreachable ({type(exc).__name__})")


def check_redis(url: str) -> CheckResult:
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        return CheckResult("redis", True, "ok")
    except Exception as exc:
        return CheckResult("redis", False, f"unreachable ({type(exc).__name__})")

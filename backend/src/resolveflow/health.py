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


def check_scheduler(engine: Engine, max_age_s: int = 90) -> CheckResult:
    try:
        with engine.connect() as conn:
            age = conn.execute(
                text(
                    "SELECT extract(epoch FROM now() - beat_at) FROM system_heartbeat WHERE id = 1"
                )
            ).scalar()
    except Exception as exc:
        return CheckResult("scheduler", False, f"unknown ({type(exc).__name__})")
    if age is None:
        return CheckResult("scheduler", False, "no heartbeat yet")
    if age > max_age_s:
        return CheckResult("scheduler", False, f"stale: {int(age)}s")
    return CheckResult("scheduler", True, f"last beat {int(age)}s ago")

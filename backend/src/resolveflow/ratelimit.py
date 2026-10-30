import logging

import redis

from resolveflow.config import get_settings

log = logging.getLogger(__name__)


def _client() -> redis.Redis:
    return redis.Redis.from_url(
        get_settings().redis_url, socket_connect_timeout=1, socket_timeout=1
    )


def count(key: str, window_s: int) -> int:
    """Increment and return the counter for `key`; the window starts at the first hit.

    Fails open (returns 0) if Redis is unreachable: availability over lockout, and logged.
    """
    try:
        c = _client()
        n = int(c.incr(key))  # type: ignore[arg-type]
        if n == 1:
            c.expire(key, window_s)
        return n
    except redis.RedisError:
        log.warning("rate limiter unavailable; failing open", exc_info=True)
        return 0


def peek(key: str) -> int:
    try:
        v = _client().get(key)
        return int(v) if v else 0  # type: ignore[arg-type]
    except redis.RedisError:
        return 0


def reset(key: str) -> None:
    try:
        _client().delete(key)
    except redis.RedisError:
        log.warning("rate limiter reset failed", exc_info=True)

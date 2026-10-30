"""Email delivery for notifications: DB-driven, idempotent, with backoff and a dead-letter state."""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from resolveflow.config import get_settings
from resolveflow.email.outbound import get_provider
from resolveflow.textutil import clean_line

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BACKOFF = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15), timedelta(hours=1))


def _compose(r: object) -> tuple[str, str]:
    subject = clean_line(str(r.title))  # type: ignore[attr-defined]
    lines = [subject]
    if r.body:  # type: ignore[attr-defined]
        lines.append(clean_line(str(r.body)))  # type: ignore[attr-defined]
    if r.ticket_id:  # type: ignore[attr-defined]
        lines += ["", f"{get_settings().public_base_url}/inbox/{r.ticket_id}"]  # type: ignore[attr-defined]
    lines += ["", "You get this because of your notification settings in ResolveFlow."]
    return subject, "\n".join(lines)


LEASE = timedelta(minutes=5)


def _claim(engine: Engine, now: datetime, limit: int, workspace_id: uuid.UUID | None) -> list[Any]:
    """Short transaction: lease due rows ('sending') so no other worker takes them, then release locks."""
    with Session(engine) as s, s.begin():
        return list(
            s.execute(
                text(
                    "with due as (select id from notifications "
                    "where email_status in ('queued', 'sending') and email_next_at <= :now "
                    "and (cast(:w as uuid) is null or workspace_id = :w) "
                    "order by email_next_at limit :lim for update skip locked) "
                    "update notifications n set email_status = 'sending', email_next_at = :lease "
                    "from due, users u where n.id = due.id and u.id = n.user_id "
                    "returning n.id, n.title, n.body, n.ticket_id, n.email_attempts, u.email, "
                    "coalesce((select m.active from memberships m where m.user_id = n.user_id "
                    "and m.workspace_id = n.workspace_id), false) as active"
                ),
                {"now": now, "w": workspace_id, "lim": limit, "lease": now + LEASE},
            ).all()
        )


def _finish(engine: Engine, sql: str, params: dict[str, Any]) -> None:
    with Session(engine) as s, s.begin():
        s.execute(text(sql), params)


def deliver_due(
    engine: Engine,
    now: datetime | None = None,
    limit: int = 100,
    workspace_id: uuid.UUID | None = None,
) -> int:
    """Send every queued notification email that is due.

    Rows are leased in one short transaction, mailed with no transaction open, and each outcome is
    committed on its own. A crash mid-batch re-sends at most the one row in flight (once its lease
    expires), never the rows already mailed.
    """
    now = now or datetime.now(UTC)
    sent = 0
    for r in _claim(engine, now, limit, workspace_id):
        if not r.active:
            _finish(
                engine,
                "update notifications set email_status = 'skipped', email_next_at = null where id = :i",
                {"i": r.id},
            )
            continue
        attempts = r.email_attempts + 1
        try:
            subject, body = _compose(r)
            get_provider().send(to=r.email, subject=subject, text=body)
        except Exception as exc:
            log.warning("notification email attempt %s failed", attempts, exc_info=True)
            dead = attempts >= MAX_ATTEMPTS
            _finish(
                engine,
                "update notifications set email_attempts = :a, email_last_error = :e, "
                "email_status = :st, email_next_at = :nx where id = :i",
                {
                    "a": attempts,
                    "e": str(exc)[:300] or exc.__class__.__name__,
                    "st": "dead" if dead else "queued",
                    "nx": None if dead else now + BACKOFF[min(attempts, len(BACKOFF)) - 1],
                    "i": r.id,
                },
            )
            continue
        _finish(
            engine,
            "update notifications set email_status = 'sent', email_attempts = :a, "
            "email_sent_at = :now, email_next_at = null, email_last_error = null where id = :i",
            {"a": attempts, "now": now, "i": r.id},
        )
        sent += 1
    return sent

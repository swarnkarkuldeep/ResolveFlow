"""Email delivery for notifications: DB-driven, idempotent, with backoff and a dead-letter state."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

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


def deliver_due(
    engine: Engine,
    now: datetime | None = None,
    limit: int = 100,
    workspace_id: uuid.UUID | None = None,
) -> int:
    """Send every queued notification email that is due. Safe to run concurrently and repeatedly."""
    now = now or datetime.now(UTC)
    sent = 0
    with Session(engine) as s, s.begin():
        rows = s.execute(
            text(
                "select n.id, n.title, n.body, n.ticket_id, n.email_attempts, u.email, "
                "coalesce(m.active, false) as active "
                "from notifications n join users u on u.id = n.user_id "
                "left join memberships m on m.user_id = n.user_id and m.workspace_id = n.workspace_id "
                "where n.email_status = 'queued' and n.email_next_at <= :now "
                "and (cast(:w as uuid) is null or n.workspace_id = :w) "
                "order by n.email_next_at limit :lim for update of n skip locked"
            ),
            {"now": now, "w": workspace_id, "lim": limit},
        ).all()
        for r in rows:
            if not r.active:
                s.execute(
                    text("update notifications set email_status = 'skipped' where id = :i"),
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
                s.execute(
                    text(
                        "update notifications set email_attempts = :a, email_last_error = :e, "
                        "email_status = :st, email_next_at = :nx where id = :i"
                    ),
                    {
                        "a": attempts,
                        "e": str(exc)[:300] or exc.__class__.__name__,
                        "st": "dead" if dead else "queued",
                        "nx": None if dead else now + BACKOFF[min(attempts, len(BACKOFF)) - 1],
                        "i": r.id,
                    },
                )
                continue
            s.execute(
                text(
                    "update notifications set email_status = 'sent', email_attempts = :a, "
                    "email_sent_at = :now, email_next_at = null, email_last_error = null "
                    "where id = :i"
                ),
                {"a": attempts, "now": now, "i": r.id},
            )
            sent += 1
    return sent

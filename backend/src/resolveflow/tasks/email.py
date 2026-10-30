import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

from resolveflow.celery_app import celery
from resolveflow.config import get_settings
from resolveflow.db import system_engine
from resolveflow.email.outbound import get_provider
from resolveflow.textutil import clean_line

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
STUCK_AFTER_SECONDS = 60


@celery.task(
    name="resolveflow.tasks.email.send_invitation",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=5,
)
def send_invitation(to: str, workspace_name: str, inviter_name: str, token: str) -> None:
    link = f"{get_settings().public_base_url}/accept-invite?token={token}"
    workspace_name, inviter_name = clean_line(workspace_name), clean_line(inviter_name)
    get_provider().send(
        to=to,
        subject=f"{inviter_name} invited you to {workspace_name} on ResolveFlow",
        text=(
            f"{inviter_name} invited you to join {workspace_name} on ResolveFlow.\n\n"
            f"Accept the invitation and set your password:\n{link}\n\n"
            "The link works once and expires in 7 days."
        ),
    )


@celery.task(name="resolveflow.tasks.email.send_outbound_message")
def send_outbound_message(message_id: str) -> None:
    """Deliver one queued reply. Idempotent: only a `queued` row is ever sent.

    A failed attempt leaves the row `queued` (attempt counted); `requeue_stuck_outbound` retries
    it, so retries are driven by the database and survive worker or broker restarts.
    """
    with Session(system_engine()) as s, s.begin():
        row = s.execute(
            text(
                "select m.id, m.body, m.message_id, m.in_reply_to, m.delivery_status, "
                "m.delivery_attempts, t.subject, t.number, c.email as to_email, w.inbound_token "
                "from messages m join tickets t on t.id = m.ticket_id "
                "join customers c on c.id = t.requester_id "
                "join workspaces w on w.id = m.workspace_id "
                "where m.id = :i for update of m"
            ),
            {"i": message_id},
        ).first()
        if not row or row.delivery_status != "queued":
            return
        attempts = row.delivery_attempts + 1
        headers = {
            "Reply-To": f"support+{row.inbound_token}.{row.number}@{get_settings().inbound_domain}"
        }
        if row.in_reply_to:
            headers["In-Reply-To"] = row.in_reply_to
            headers["References"] = row.in_reply_to
        clean_subject = clean_line(row.subject)
        subject = (
            clean_subject if clean_subject.lower().startswith("re:") else f"Re: {clean_subject}"
        )
        try:
            get_provider().send(
                to=row.to_email,
                subject=subject,
                text=row.body,
                headers=headers,
                message_id=row.message_id,
            )
            status = "sent"
        except Exception:
            log.warning("outbound email attempt %s failed", attempts, exc_info=True)
            status = "failed" if attempts >= MAX_ATTEMPTS else "queued"
        s.execute(
            text("update messages set delivery_status = :s, delivery_attempts = :a where id = :i"),
            {"s": status, "a": attempts, "i": row.id},
        )


@celery.task(name="resolveflow.tasks.email.requeue_stuck_outbound")
def requeue_stuck_outbound() -> int:
    """Recover replies whose task was lost (worker crash, broker flush, cold start)."""
    with Session(system_engine()) as s, s.begin():
        ids = (
            s.execute(
                text(
                    "select id from messages where delivery_status = 'queued' "
                    "and created_at < now() - make_interval(secs => :n) "
                    "order by created_at limit 200"
                ),
                {"n": STUCK_AFTER_SECONDS},
            )
            .scalars()
            .all()
        )
    for message_id in ids:
        send_outbound_message.delay(str(message_id))
    return len(ids)

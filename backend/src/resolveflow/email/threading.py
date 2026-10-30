import re
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from resolveflow.email.inbound import InboundMessage

_ADDRESS = re.compile(r"(?:inbound-|support\+)([a-f0-9]{16})(?:\.(\d+))?@", re.IGNORECASE)


def parse_recipients(addresses: list[str]) -> list[tuple[str, int | None]]:
    """(workspace inbound token, ticket number if present) for every addressed mailbox."""
    found: list[tuple[str, int | None]] = []
    for addr in addresses:
        m = _ADDRESS.search(addr)
        if m:
            found.append((m.group(1).lower(), int(m.group(2)) if m.group(2) else None))
    return found


def match_ticket(
    session: Session, workspace_id: uuid.UUID, msg: InboundMessage, plus_number: int | None
) -> uuid.UUID | None:
    """Find the ticket this message belongs to: reply headers first, then plus-address number."""
    ids = [i for i in [msg.in_reply_to, *msg.references] if i]
    if ids:
        found: uuid.UUID | None = session.execute(
            text(
                "select ticket_id from messages where workspace_id = :w "
                "and message_id = any(:ids) order by created_at desc limit 1"
            ),
            {"w": workspace_id, "ids": ids},
        ).scalar()
        if found:
            return found
    if plus_number is not None:
        # The token is in every Reply-To header, so a number alone is not proof of belonging:
        # only the requester (or someone who already wrote in) may thread into that ticket.
        by_number: uuid.UUID | None = session.execute(
            text(
                "select t.id from tickets t join customers c on c.id = t.requester_id "
                "where t.workspace_id = :w and t.number = :n and (c.email = :e or exists ("
                "select 1 from messages m join customers mc on mc.id = m.author_customer_id "
                "where m.ticket_id = t.id and mc.email = :e))"
            ),
            {"w": workspace_id, "n": plus_number, "e": msg.from_email},
        ).scalar()
        return by_number
    return None

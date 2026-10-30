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
        by_number: uuid.UUID | None = session.execute(
            text("select id from tickets where workspace_id = :w and number = :n"),
            {"w": workspace_id, "n": plus_number},
        ).scalar()
        return by_number
    return None

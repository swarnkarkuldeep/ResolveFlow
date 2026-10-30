from dataclasses import dataclass, field
from typing import Any, Protocol

MAX_BODY_CHARS = 50_000


@dataclass
class InboundMessage:
    message_id: str
    from_email: str
    from_name: str | None
    to_addresses: list[str]
    subject: str
    text: str
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    attachments_dropped: int = 0


class InboundEmailProvider(Protocol):
    """Turns one provider's webhook payload into the provider-neutral InboundMessage."""

    def parse(self, payload: dict[str, Any]) -> InboundMessage: ...

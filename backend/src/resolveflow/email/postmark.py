import re
from html.parser import HTMLParser
from typing import Any

from resolveflow.email.inbound import MAX_BODY_CHARS, InboundMessage

_BLOCKS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


class PostmarkInbound:
    def parse(self, payload: dict[str, Any]) -> InboundMessage:
        headers = {
            str(h.get("Name", "")).lower(): str(h.get("Value", ""))
            for h in payload.get("Headers") or []
            if isinstance(h, dict)
        }
        sender = payload.get("FromFull") or {}
        from_email = str(sender.get("Email") or payload.get("From") or "").strip().lower()
        recipients = [
            str(r.get("Email", "")).lower()
            for r in payload.get("ToFull") or []
            if isinstance(r, dict)
        ]
        if payload.get("OriginalRecipient"):
            recipients.append(str(payload["OriginalRecipient"]).lower())
        body = str(payload.get("TextBody") or "")
        if not body.strip():
            body = html_to_text(str(payload.get("HtmlBody") or ""))
        message_id = headers.get("message-id") or f"<pm-{payload.get('MessageID', '')}@postmark>"
        refs = headers.get("references", "").split()
        return InboundMessage(
            message_id=message_id.strip(),
            from_email=from_email,
            from_name=(sender.get("Name") or payload.get("FromName") or None),
            to_addresses=recipients,
            subject=str(payload.get("Subject") or "").strip(),
            text=body[:MAX_BODY_CHARS],
            in_reply_to=headers.get("in-reply-to", "").strip() or None,
            references=refs,
            attachments_dropped=len(payload.get("Attachments") or []),
        )

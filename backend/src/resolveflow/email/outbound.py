import smtplib
from email.message import EmailMessage
from typing import ClassVar, Protocol

import httpx

from resolveflow.config import Settings, get_settings


class OutboundEmailProvider(Protocol):
    def send(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        headers: dict[str, str] | None = None,
        message_id: str | None = None,
    ) -> None: ...


class SmtpProvider:
    """Plain SMTP; in local dev this is Mailpit, which captures mail for inspection."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    def send(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        headers: dict[str, str] | None = None,
        message_id: str | None = None,
    ) -> None:
        msg = EmailMessage()
        msg["From"] = self._s.mail_from
        msg["To"] = to
        msg["Subject"] = subject
        if message_id:
            msg["Message-ID"] = message_id
        for k, v in (headers or {}).items():
            msg[k] = v
        msg.set_content(text)
        with smtplib.SMTP(self._s.smtp_host, self._s.smtp_port, timeout=10) as smtp:
            smtp.send_message(msg)


class PostmarkProvider:
    URL = "https://api.postmarkapp.com/email"

    def __init__(
        self, token: str, from_addr: str, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._token, self._from, self._transport = token, from_addr, transport

    def send(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        headers: dict[str, str] | None = None,
        message_id: str | None = None,
    ) -> None:
        all_headers = dict(headers or {})
        if message_id:
            all_headers["Message-ID"] = message_id
        body = {
            "From": self._from,
            "To": to,
            "Subject": subject,
            "TextBody": text,
            "MessageStream": "outbound",
            "Headers": [{"Name": k, "Value": v} for k, v in all_headers.items()],
        }
        with httpx.Client(transport=self._transport, timeout=10) as client:
            resp = client.post(
                self.URL, json=body, headers={"X-Postmark-Server-Token": self._token}
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"postmark rejected the message ({resp.status_code})")


class MemoryProvider:
    """Test double that records messages instead of sending them."""

    sent: ClassVar[list[dict[str, object]]] = []

    def send(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        headers: dict[str, str] | None = None,
        message_id: str | None = None,
    ) -> None:
        self.sent.append(
            {"to": to, "subject": subject, "text": text, "headers": headers or {}, "id": message_id}
        )


def get_provider() -> OutboundEmailProvider:
    s = get_settings()
    if s.email_provider == "postmark":
        if not s.postmark_server_token:
            raise RuntimeError("POSTMARK_SERVER_TOKEN is required when EMAIL_PROVIDER=postmark")
        return PostmarkProvider(s.postmark_server_token, s.mail_from)
    if s.email_provider == "memory":
        return MemoryProvider()
    return SmtpProvider(s)

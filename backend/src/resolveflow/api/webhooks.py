import base64
import binascii
import hmac
import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy import text

from resolveflow.api.deps import RequestContext, require
from resolveflow.config import get_settings
from resolveflow.email.postmark import PostmarkInbound
from resolveflow.errors import err
from resolveflow.services.ingest import ingest_inbound
from resolveflow.types import EmailAddr

router = APIRouter(prefix="/api")


def handle_postmark_payload(data: dict[str, Any]) -> dict[str, Any]:
    """The single ingestion entry point, shared by the real webhook and the simulate button."""
    result = ingest_inbound(PostmarkInbound().parse(data))
    return {
        "status": result.status,
        "ticket_id": str(result.ticket_id) if result.ticket_id else None,
    }


def _verify_basic(authorization: str | None = Header(default=None)) -> None:
    secret = get_settings().postmark_webhook_secret
    password = ""
    if authorization and authorization.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(authorization[6:].strip()).decode()
            password = decoded.partition(":")[2]
        except (binascii.Error, UnicodeDecodeError):
            password = ""
    if not secret or not hmac.compare_digest(password.encode(), secret.encode()):
        raise err(401, "unauthorized", "Invalid webhook credentials.")


@router.post("/webhooks/email/postmark", dependencies=[Depends(_verify_basic)])
def postmark_webhook(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return handle_postmark_payload(payload)


class SimulateIn(BaseModel):
    from_email: EmailAddr
    from_name: str | None = Field(default=None, max_length=120)
    subject: str = Field(default="Question about my order", max_length=300)
    text: str = Field(min_length=1, max_length=20000)
    in_reply_to: str | None = Field(default=None, max_length=300)


@router.post("/dev/simulate-inbound")
def simulate_inbound(
    body: SimulateIn, ctx: RequestContext = Depends(require("settings:update"))
) -> dict[str, Any]:
    """Feeds a provider-shaped payload through the same handler as the real webhook."""
    settings = get_settings()
    if not settings.simulate_inbound_enabled:
        raise err(404, "not_found", "Not found.")
    token = ctx.session.execute(
        text("select inbound_token from workspaces where id = :w"), {"w": ctx.ws}
    ).scalar_one()
    address = f"inbound-{token}@{settings.inbound_domain}"
    headers = [{"Name": "Message-ID", "Value": f"<sim-{uuid.uuid4().hex}@simulated.local>"}]
    if body.in_reply_to:
        headers += [
            {"Name": "In-Reply-To", "Value": body.in_reply_to},
            {"Name": "References", "Value": body.in_reply_to},
        ]
    data = {
        "MessageID": str(uuid.uuid4()),
        "FromFull": {"Email": body.from_email, "Name": body.from_name or ""},
        "ToFull": [{"Email": address, "Name": ""}],
        "OriginalRecipient": address,
        "Subject": body.subject,
        "TextBody": body.text,
        "Headers": headers,
        "Attachments": [],
    }
    return handle_postmark_payload(data)

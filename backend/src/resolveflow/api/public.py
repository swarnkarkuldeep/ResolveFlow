from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from resolveflow import ratelimit
from resolveflow.context import SystemContext
from resolveflow.db import system_engine
from resolveflow.errors import err
from resolveflow.services import tickets as ticket_svc
from resolveflow.types import EmailAddr

router = APIRouter(prefix="/api/public")

FORM_LIMIT = 5
FORM_WINDOW_S = 3600


class FormIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    email: EmailAddr
    subject: str = Field(min_length=1, max_length=300)
    message: str = Field(min_length=1, max_length=10_000)
    website: str = Field(default="", max_length=500)  # honeypot: real people leave it empty


@router.get("/forms/{slug}")
def form_info(slug: str) -> dict[str, str]:
    with Session(system_engine()) as s, s.begin():
        name = s.execute(text("select name from workspaces where slug = :s"), {"s": slug}).scalar()
    if not name:
        raise err(404, "not_found", "This form does not exist.")
    return {"workspace_name": name}


@router.post("/forms/{slug}")
def submit_form(slug: str, body: FormIn, request: Request) -> dict[str, Any]:
    with Session(system_engine()) as s, s.begin():
        ws = s.execute(text("select id from workspaces where slug = :s"), {"s": slug}).scalar()
        if not ws:
            raise err(404, "not_found", "This form does not exist.")
        if body.website.strip():
            return {"reference": None}  # looks like success to a bot, creates nothing
        ip = request.client.host if request.client else "unknown"
        if ratelimit.count(f"rl:form:{ip}:{slug}", FORM_WINDOW_S) > FORM_LIMIT:
            raise err(429, "rate_limited", "Too many messages from this address. Try again later.")
        s.execute(text("select set_config('app.workspace_id', :w, true)"), {"w": str(ws)})
        ticket = ticket_svc.create_ticket(
            SystemContext(s, ws),
            subject=body.subject.strip(),
            body=body.message,
            requester_email=body.email,
            requester_name=body.name,
            channel="form",
        )
        return {"reference": f"#{ticket['number']}"}

import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from resolveflow.db import engine_for
from resolveflow.email.outbound import MemoryProvider
from resolveflow.main import app
from tests.helpers import Actor, ClientFactory, make_owner, team

DOMAIN = "inbound.resolveflow.local"
SECRET = "whsec-test"


def token_of(url: str, actor: Actor) -> str:
    with engine_for(url).connect() as conn:
        return str(
            conn.execute(
                text("select inbound_token from workspaces where id = :w"),
                {"w": uuid.UUID(actor.workspace_id)},
            ).scalar_one()
        )


def payload(
    to: str,
    *,
    subject: str | None = "Leaking tap",
    body: str = "My tap has been leaking since Monday.",
    message_id: str | None = None,
    in_reply_to: str | None = None,
    sender: str = "cora@customer.test",
    html: str | None = None,
    attachments: int = 0,
    plus_only: bool = False,
) -> dict[str, Any]:
    mid = message_id or f"<{uuid.uuid4().hex}@customer.test>"
    headers = [{"Name": "Message-ID", "Value": mid}]
    if in_reply_to:
        headers += [
            {"Name": "In-Reply-To", "Value": in_reply_to},
            {"Name": "References", "Value": in_reply_to},
        ]
    data: dict[str, Any] = {
        "MessageID": str(uuid.uuid4()),
        "FromFull": {"Email": sender, "Name": "Cora Customer"},
        "ToFull": [{"Email": to, "Name": ""}],
        "OriginalRecipient": to,
        "TextBody": body,
        "HtmlBody": html or "",
        "Headers": headers,
        "Attachments": [{"Name": f"f{i}.pdf"} for i in range(attachments)],
    }
    if subject is not None:
        data["Subject"] = subject
    return data


def post(
    client: TestClient, data: dict[str, Any], auth: tuple[str, str] | None = ("pm", SECRET)
) -> Any:
    return client.post("/api/webhooks/email/postmark", json=data, auth=auth)


def tickets(owner: Actor) -> list[dict[str, Any]]:
    return owner.get("/api/tickets").json()["items"]


def test_new_email_creates_a_ticket(client_factory: ClientFactory, postgres_url: str) -> None:
    owner = make_owner(client_factory)
    to = f"inbound-{token_of(postgres_url, owner)}@{DOMAIN}"
    mid = "<abc123@customer.test>"
    r = post(client_factory(), payload(to, message_id=mid))
    assert r.status_code == 200 and r.json()["status"] == "created"
    (t,) = tickets(owner)
    assert t["channel"] == "email" and t["subject"] == "Leaking tap" and t["status"] == "new"
    assert t["requester"] == {
        "id": t["requester"]["id"],
        "email": "cora@customer.test",
        "name": "Cora Customer",
    }
    detail = owner.get(f"/api/tickets/{t['id']}").json()
    assert detail["messages"][0]["body"] == "My tap has been leaking since Monday."
    actions = [a["action"] for a in owner.get(f"/api/tickets/{t['id']}/activity").json()]
    assert "ticket.created" in actions
    assert owner.get(f"/api/tickets/{t['id']}/activity").json()[0]["actor_name"] == "System"


def test_reply_threads_by_in_reply_to_and_reopens(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    to = f"inbound-{token_of(postgres_url, owner)}@{DOMAIN}"
    anon = client_factory()
    first = post(anon, payload(to, message_id="<m1@customer.test>")).json()
    tid = first["ticket_id"]
    owner.post(
        f"/api/tickets/{tid}/messages",
        {"body": "On our way", "kind": "public", "set_pending": True},
    )
    assert owner.get(f"/api/tickets/{tid}").json()["status"] == "pending"
    our_id = MemoryProvider.sent[-1]["id"]
    r = post(anon, payload(to, subject="Re: Leaking tap", body="Thanks!", in_reply_to=our_id))
    assert r.json() == {"status": "appended", "ticket_id": tid}
    detail = owner.get(f"/api/tickets/{tid}").json()
    assert detail["status"] == "open" and [m["body"] for m in detail["messages"]][-1] == "Thanks!"
    assert len(tickets(owner)) == 1


def test_plus_address_fallback_matches_ticket_number(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    token = token_of(postgres_url, owner)
    anon = client_factory()
    tid = post(anon, payload(f"inbound-{token}@{DOMAIN}")).json()["ticket_id"]
    number = owner.get(f"/api/tickets/{tid}").json()["number"]
    r = post(
        anon, payload(f"support+{token}.{number}@{DOMAIN}", subject="totally different subject")
    )
    assert r.json() == {"status": "appended", "ticket_id": tid}
    assert len(tickets(owner)) == 1


def test_reply_to_merged_ticket_lands_on_the_target(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    to = f"inbound-{token_of(postgres_url, owner)}@{DOMAIN}"
    anon = client_factory()
    a = post(anon, payload(to, message_id="<a@customer.test>", subject="First")).json()["ticket_id"]
    b = post(anon, payload(to, message_id="<b@customer.test>", subject="Second")).json()[
        "ticket_id"
    ]
    owner.post(f"/api/tickets/{a}/merge", {"into_id": b})
    r = post(anon, payload(to, in_reply_to="<a@customer.test>", body="More info"))
    assert r.json() == {"status": "appended", "ticket_id": b}


def test_duplicate_delivery_creates_one_message_even_concurrently(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    to = f"inbound-{token_of(postgres_url, owner)}@{DOMAIN}"
    data = payload(to, message_id="<same@customer.test>")
    assert post(client_factory(), data).json()["status"] == "created"
    assert post(client_factory(), data).json()["status"] == "duplicate"

    racing = payload(to, message_id="<race@customer.test>", subject="Race")
    with ThreadPoolExecutor(8) as pool:
        statuses = sorted(
            pool.map(lambda _: post(TestClient(app), racing).json()["status"], range(8))
        )
    assert statuses.count("created") == 1 and statuses.count("duplicate") == 7
    assert len(tickets(owner)) == 2
    with engine_for(postgres_url).connect() as conn:
        n = conn.execute(
            text("select count(*) from messages where message_id = '<race@customer.test>'")
        ).scalar_one()
    assert n == 1


def test_unknown_recipient_token_is_ignored_with_200(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    r = post(client_factory(), payload(f"inbound-deadbeefdeadbeef@{DOMAIN}"))
    assert r.status_code == 200 and r.json() == {"status": "ignored", "ticket_id": None}
    assert tickets(owner) == []


def test_webhook_requires_the_shared_secret(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    data = payload(f"inbound-{token_of(postgres_url, owner)}@{DOMAIN}")
    c = client_factory()
    assert post(c, data, auth=None).status_code == 401
    assert post(c, data, auth=("pm", "wrong")).status_code == 401
    assert tickets(owner) == []


def test_webhook_rejects_non_json_and_non_object(client_factory: ClientFactory) -> None:
    c = client_factory()
    bad = c.post(
        "/api/webhooks/email/postmark",
        content=b"not json",
        auth=("pm", SECRET),
        headers={"content-type": "application/json"},
    )
    assert bad.status_code == 422
    assert (
        c.post("/api/webhooks/email/postmark", json=[1, 2], auth=("pm", SECRET)).status_code == 422
    )


def test_odd_payloads(client_factory: ClientFactory, postgres_url: str) -> None:
    owner = make_owner(client_factory)
    to = f"inbound-{token_of(postgres_url, owner)}@{DOMAIN}"
    anon = client_factory()
    post(anon, payload(to, subject=None, body="No subject here"))
    html = "<html><style>p{color:red}</style><body><p>Hello <b>there</b></p><script>alert(1)</script></body></html>"
    post(anon, payload(to, subject="Html only", body="", html=html))
    post(anon, payload(to, subject="Big", body="x" * 100_000))
    post(anon, payload(to, subject="Script", body="<script>alert('x')</script> hi"))
    post(anon, payload(to, subject="Files", body="see attached", attachments=3))
    by_subject = {t["subject"]: t for t in tickets(owner)}
    assert "(no subject)" in by_subject

    def body_of(subject: str) -> str:
        return str(
            owner.get(f"/api/tickets/{by_subject[subject]['id']}").json()["messages"][0]["body"]
        )

    assert body_of("Html only").strip() == "Hello there"
    assert len(body_of("Big")) == 50_000
    assert body_of("Script") == "<script>alert('x')</script> hi"
    assert body_of("Files").endswith("3 attachments not stored.")


def test_simulate_uses_the_same_ingestion_path(
    client_factory: ClientFactory, postgres_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = team(client_factory)
    sim = {
        "from_email": "walkin@customer.test",
        "from_name": "Walt",
        "subject": "Hello",
        "text": "Anyone there?",
    }
    r = t["owner"].post("/api/dev/simulate-inbound", sim)
    assert r.status_code == 200 and r.json()["status"] == "created"
    (ticket,) = tickets(t["owner"])
    assert ticket["channel"] == "email" and ticket["requester"]["name"] == "Walt"
    reply = t["owner"].post(
        "/api/dev/simulate-inbound", {**sim, "text": "Following up", "in_reply_to": None}
    )
    assert reply.json()["status"] == "created"  # no threading info -> a new ticket, like real mail

    seen: list[dict[str, Any]] = []
    from resolveflow.api import webhooks

    real = webhooks.handle_postmark_payload

    def spy(data: dict[str, Any]) -> Any:
        seen.append(data)
        return real(data)

    monkeypatch.setattr(webhooks, "handle_postmark_payload", spy)
    t["owner"].post("/api/dev/simulate-inbound", {**sim, "subject": "Spy one"})
    post(
        client_factory(),
        payload(f"inbound-{token_of(postgres_url, t['owner'])}@{DOMAIN}", subject="Spy two"),
    )
    assert len(seen) == 2 and all("ToFull" in d and "Headers" in d for d in seen)


def test_simulate_is_gated(client_factory: ClientFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    t = team(client_factory)
    body = {"from_email": "w@customer.test", "subject": "s", "text": "t"}
    assert t["agent"].post("/api/dev/simulate-inbound", body).status_code == 403
    from resolveflow.config import get_settings

    monkeypatch.setenv("SIMULATE_INBOUND_ENABLED", "0")
    get_settings.cache_clear()
    assert t["owner"].post("/api/dev/simulate-inbound", body).status_code == 404


def test_message_without_a_sender_address_is_ignored(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    to = f"inbound-{token_of(postgres_url, owner)}@{DOMAIN}"
    r = post(client_factory(), payload(to, sender="not-an-address"))
    assert r.status_code == 200 and r.json()["status"] == "ignored"
    assert tickets(owner) == []

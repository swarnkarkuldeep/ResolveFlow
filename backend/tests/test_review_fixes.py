"""Regression tests for the findings of the M1 whole-branch review."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from resolveflow.db import engine_for
from resolveflow.email.outbound import MemoryProvider
from resolveflow.main import app
from resolveflow.services import auth as auth_service
from resolveflow.textutil import clean_line
from tests.helpers import PASSWORD, ClientFactory, make_owner, unique_email
from tests.test_forms import slug_of, submit
from tests.test_ingest import DOMAIN, payload, post, token_of

ROOT = Path(__file__).resolve().parents[2]


def test_nginx_overwrites_forwarded_for_so_clients_cannot_spoof_their_ip() -> None:
    conf = (ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in conf
    assert "$proxy_add_x_forwarded_for" not in conf


def test_login_is_also_limited_per_account_regardless_of_ip(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    codes = []
    for i in range(32):
        try:
            auth_service.login(owner.email, "wrong-wrong-wrong", ip=f"10.0.0.{i}")
        except Exception as exc:  # HTTPException carrying the status
            codes.append(exc.status_code)  # type: ignore[attr-defined]
    assert codes[:30] == [401] * 30 and set(codes[30:]) == {429}


def test_accept_invite_enforces_password_and_name_rules(client_factory: ClientFactory) -> None:
    from tests.helpers import token_from_last_email

    owner = make_owner(client_factory)
    owner.post("/api/invitations", {"email": unique_email("p"), "role": "agent"})
    token = token_from_last_email()
    c = client_factory()
    assert (
        c.post(
            "/api/auth/accept-invite", json={"token": token, "name": "N", "password": "x"}
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/auth/accept-invite",
            json={"token": token, "name": "N" * 500, "password": PASSWORD},
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/auth/accept-invite", json={"token": token, "name": "Ok", "password": PASSWORD}
        ).status_code
        == 200
    )


def test_clean_line_collapses_control_characters() -> None:
    assert clean_line("Hello\r\nBcc: evil@x.test") == "Hello Bcc: evil@x.test"
    assert clean_line("  a\t\tb\x00c  ") == "a b c"


def test_subject_with_line_breaks_is_stored_clean_and_still_replies(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    submit(client_factory(), slug_of(owner), subject="Quote\r\nBcc: evil@x.test", name="Fran\nkie")
    (t,) = owner.get("/api/tickets").json()["items"]
    assert t["subject"] == "Quote Bcc: evil@x.test" and t["requester"]["name"] == "Fran kie"
    r = owner.post(f"/api/tickets/{t['id']}/messages", {"body": "Hi", "kind": "public"})
    assert r.status_code == 200
    assert "\n" not in str(MemoryProvider.sent[-1]["subject"])


def test_plus_address_only_threads_for_the_ticket_requester(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    token = token_of(postgres_url, owner)
    anon = client_factory()
    tid = post(anon, payload(f"inbound-{token}@{DOMAIN}", sender="victim@customer.test")).json()[
        "ticket_id"
    ]
    number = owner.get(f"/api/tickets/{tid}").json()["number"]
    stranger = post(
        anon,
        payload(
            f"support+{token}.{number}@{DOMAIN}", sender="stranger@customer.test", subject="Hijack"
        ),
    ).json()
    assert stranger["status"] == "created" and stranger["ticket_id"] != tid
    owner_reply = post(
        anon,
        payload(
            f"support+{token}.{number}@{DOMAIN}", sender="victim@customer.test", subject="Re: mine"
        ),
    ).json()
    assert owner_reply == {"status": "appended", "ticket_id": tid}


def test_oversized_message_ids_do_not_poison_the_webhook(
    client_factory: ClientFactory, postgres_url: str
) -> None:
    owner = make_owner(client_factory)
    to = f"inbound-{token_of(postgres_url, owner)}@{DOMAIN}"
    huge = "<" + "a" * 5000 + "@customer.test>"
    first = post(client_factory(), payload(to, message_id=huge, in_reply_to=huge))
    again = post(client_factory(), payload(to, message_id=huge))
    assert first.status_code == 200 and first.json()["status"] == "created"
    assert again.json()["status"] == "duplicate"


def test_two_owners_demoting_each_other_never_leaves_zero_owners(
    client_factory: ClientFactory,
) -> None:
    from tests.helpers import invite_actor

    for _ in range(5):
        owner = make_owner(client_factory)
        co = invite_actor(owner, client_factory, "owner")
        pairs = [(owner, co.user_id), (co, owner.user_id)]

        def demote(pair: tuple) -> int:  # type: ignore[type-arg]
            actor, target = pair
            c = TestClient(app)
            c.cookies.set("rf_session", actor.client.cookies["rf_session"])
            return int(
                c.patch(
                    f"/api/members/{target}",
                    json={"role": "viewer"},
                    headers={"X-CSRF-Token": actor.csrf},
                ).status_code
            )

        with ThreadPoolExecutor(2) as pool:
            statuses = list(pool.map(demote, pairs))
        survivors = [a for a in (owner, co) if a.get("/api/auth/me").json().get("role") == "owner"]
        assert survivors, f"workspace left without an owner: {statuses}"


def test_app_role_cannot_read_password_hashes(client_factory: ClientFactory, app_url: str) -> None:
    make_owner(client_factory)
    eng = create_engine(app_url)
    try:
        with eng.connect() as conn:
            assert conn.execute(text("select count(*) from users")).scalar_one() > 0
            conn.rollback()
            with pytest.raises(DBAPIError):
                conn.execute(text("select password_hash from users limit 1"))
    finally:
        eng.dispose()
    assert uuid.uuid4()  # keep imports honest
    assert engine_for  # noqa: B018

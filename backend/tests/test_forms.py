from typing import Any

from fastapi.testclient import TestClient

from tests.helpers import Actor, ClientFactory, make_owner


def slug_of(owner: Actor) -> str:
    return str(owner.get("/api/auth/me").json()["active_workspace"]["slug"])


def submit(client: TestClient, slug: str, **overrides: Any) -> Any:
    body = {
        "name": "Frankie Form",
        "email": "frankie@customer.test",
        "subject": "Quote for a bathroom refit",
        "message": "Could someone call me about a quote?",
        "website": "",
        **overrides,
    }
    return client.post(f"/api/public/forms/{slug}", json=body)


def test_public_form_info_exposes_only_the_workspace_name(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory, "Brightwork Studio")
    r = client_factory().get(f"/api/public/forms/{slug_of(owner)}")
    assert r.status_code == 200 and r.json() == {"workspace_name": "Brightwork Studio"}


def test_valid_submission_creates_a_form_ticket(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    r = submit(client_factory(), slug_of(owner))
    assert r.status_code == 200 and r.json() == {"reference": "#1"}
    (t,) = owner.get("/api/tickets").json()["items"]
    assert t["channel"] == "form" and t["subject"] == "Quote for a bathroom refit"
    assert (
        t["requester"]["email"] == "frankie@customer.test"
        and t["requester"]["name"] == "Frankie Form"
    )
    detail = owner.get(f"/api/tickets/{t['id']}").json()
    assert detail["messages"][0]["body"] == "Could someone call me about a quote?"
    assert owner.get(f"/api/tickets/{t['id']}/activity").json()[0]["actor_name"] == "System"


def test_honeypot_is_silently_accepted_and_creates_nothing(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    r = submit(client_factory(), slug_of(owner), website="http://spam.example")
    assert r.status_code == 200
    assert owner.get("/api/tickets").json()["items"] == []


def test_sixth_submission_in_an_hour_is_rate_limited(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    slug, c = slug_of(owner), client_factory()
    assert [submit(c, slug).status_code for _ in range(5)] == [200] * 5
    limited = submit(c, slug)
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "rate_limited"
    assert len(owner.get("/api/tickets").json()["items"]) == 5


def test_unknown_workspace_is_404(client_factory: ClientFactory) -> None:
    c = client_factory()
    assert c.get("/api/public/forms/nope-nope").status_code == 404
    assert submit(c, "nope-nope").status_code == 404


def test_invalid_input_is_422(client_factory: ClientFactory) -> None:
    owner = make_owner(client_factory)
    slug, c = slug_of(owner), client_factory()
    assert submit(c, slug, email="not-an-email").status_code == 422
    assert submit(c, slug, message="").status_code == 422
    assert submit(c, slug, message="x" * 10_001).status_code == 422
    assert submit(c, slug, subject="").status_code == 422


def test_submissions_stay_in_their_own_workspace(client_factory: ClientFactory) -> None:
    a = make_owner(client_factory, "Alpha")
    b = make_owner(client_factory, "Bravo")
    submit(client_factory(), slug_of(a))
    assert len(a.get("/api/tickets").json()["items"]) == 1
    assert b.get("/api/tickets").json()["items"] == []

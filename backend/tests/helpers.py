import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi.testclient import TestClient

from resolveflow.email.outbound import MemoryProvider

PASSWORD = "correct-horse-battery"


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@example.test"


@dataclass
class Actor:
    client: TestClient
    csrf: str
    email: str
    role: str
    name: str = "Test User"

    @property
    def _h(self) -> dict[str, str]:
        return {"X-CSRF-Token": self.csrf}

    def get(self, path: str, **kw: Any) -> Any:
        return self.client.get(path, **kw)

    def post(self, path: str, json: Any = None, **kw: Any) -> Any:
        return self.client.post(path, json=json, headers=self._h, **kw)

    def patch(self, path: str, json: Any = None) -> Any:
        return self.client.patch(path, json=json, headers=self._h)

    def delete(self, path: str) -> Any:
        return self.client.delete(path, headers=self._h)

    @property
    def user_id(self) -> str:
        return str(self.get("/api/auth/me").json()["user"]["id"])

    @property
    def workspace_id(self) -> str:
        return str(self.get("/api/auth/me").json()["active_workspace"]["id"])


ClientFactory = Callable[[], TestClient]


def make_owner(factory: ClientFactory, workspace: str = "Acme Plumbing") -> Actor:
    client = factory()
    email = unique_email("owner")
    r = client.post(
        "/api/auth/signup",
        json={
            "email": email,
            "password": PASSWORD,
            "name": "Olive Owner",
            "workspace_name": workspace,
        },
    )
    assert r.status_code == 200, r.text
    return Actor(client, r.json()["csrf_token"], email, "owner", "Olive Owner")


def token_from_last_email() -> str:
    body = MemoryProvider.sent[-1]["text"]
    m = re.search(r"token=([A-Za-z0-9_\-]+)", body)
    assert m, body
    return m.group(1)


def invite_actor(owner: Actor, factory: ClientFactory, role: str, name: str | None = None) -> Actor:
    email = unique_email(role)
    r = owner.post("/api/invitations", {"email": email, "role": role})
    assert r.status_code == 200, r.text
    token = token_from_last_email()
    client = factory()
    name = name or f"{role.title()} Person"
    acc = client.post(
        "/api/auth/accept-invite", json={"token": token, "name": name, "password": PASSWORD}
    )
    assert acc.status_code == 200, acc.text
    return Actor(client, acc.json()["csrf_token"], email, role, name)


def team(factory: ClientFactory, workspace: str = "Acme Plumbing") -> dict[str, Actor]:
    owner = make_owner(factory, workspace)
    return {
        "owner": owner,
        "admin": invite_actor(owner, factory, "admin"),
        "agent": invite_actor(owner, factory, "agent"),
        "viewer": invite_actor(owner, factory, "viewer"),
    }

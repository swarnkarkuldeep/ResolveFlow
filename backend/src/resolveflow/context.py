import uuid
from dataclasses import dataclass
from typing import Literal, Protocol

from sqlalchemy.orm import Session


class ServiceCtx(Protocol):
    """What the service layer needs from a caller: a tenant-scoped session and an actor."""

    session: Session
    request_id: str | None

    @property
    def ws(self) -> uuid.UUID: ...

    @property
    def actor_type(self) -> Literal["user", "system", "rule"]: ...

    @property
    def actor_id(self) -> uuid.UUID | None: ...


@dataclass
class SystemContext:
    """Used by non-interactive flows (inbound email, web form, tasks). Not a user."""

    session: Session
    workspace_id: uuid.UUID
    request_id: str | None = None

    @property
    def ws(self) -> uuid.UUID:
        return self.workspace_id

    @property
    def actor_type(self) -> Literal["system"]:
        return "system"

    @property
    def actor_id(self) -> None:
        return None


@dataclass
class RuleContext:
    """Used while a rule applies its actions: changes are audited as the rule, not a person."""

    session: Session
    workspace_id: uuid.UUID
    rule_id: uuid.UUID
    request_id: str | None = None

    @property
    def ws(self) -> uuid.UUID:
        return self.workspace_id

    @property
    def actor_type(self) -> Literal["rule"]:
        return "rule"

    @property
    def actor_id(self) -> uuid.UUID:
        return self.rule_id

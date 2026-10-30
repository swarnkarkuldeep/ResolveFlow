"""Rule definitions: a small, closed vocabulary validated up front (no regex, no custom fields)."""

import hashlib
import json
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Event = Literal["ticket.created", "message.received", "status.changed", "sla.threshold"]
Priority = Literal["low", "normal", "high", "urgent"]
Status = Literal["new", "open", "pending", "resolved", "closed"]
Channel = Literal["email", "form", "manual"]

TEXT_OPS = {
    "equals",
    "not_equals",
    "contains",
    "not_contains",
    "contains_any",
    "starts_with",
    "ends_with",
}
ENUM_OPS = {"equals", "not_equals", "in"}

FIELD_OPERATORS: dict[str, set[str]] = {
    "sender_email": TEXT_OPS,
    "sender_domain": ENUM_OPS,
    "subject": TEXT_OPS,
    "body": TEXT_OPS,
    "channel": ENUM_OPS,
    "priority": ENUM_OPS,
    "status": ENUM_OPS,
    "tags": {"contains", "not_contains", "contains_any", "is_empty", "is_not_empty"},
    "assignee": {"is_empty", "is_not_empty"},
}
ENUM_VALUES: dict[str, set[str]] = {
    "channel": {"email", "form", "manual"},
    "priority": {"low", "normal", "high", "urgent"},
    "status": {"new", "open", "pending", "resolved", "closed"},
}
LIST_OPS = {"contains_any", "in"}
NO_VALUE_OPS = {"is_empty", "is_not_empty"}

MAX_DEPTH = 3
MAX_CONDITIONS = 20
MAX_ACTIONS = 10
MAX_TEXT = 200


class Condition(BaseModel):
    field: Literal[
        "sender_email",
        "sender_domain",
        "subject",
        "body",
        "channel",
        "priority",
        "status",
        "tags",
        "assignee",
    ]
    operator: str
    value: str | list[str] | None = None

    @model_validator(mode="after")
    def _check(self) -> "Condition":
        if self.operator not in FIELD_OPERATORS[self.field]:
            allowed = ", ".join(sorted(FIELD_OPERATORS[self.field]))
            raise ValueError(
                f"The operator '{self.operator}' does not work with {self.field}. Use one of: {allowed}."
            )
        if self.operator in NO_VALUE_OPS:
            if self.value not in (None, "", []):
                raise ValueError(f"'{self.operator}' takes no value.")
            return self
        if self.operator in LIST_OPS:
            if not isinstance(self.value, list) or not self.value:
                raise ValueError(f"'{self.operator}' needs a list of values.")
            values = self.value
        else:
            if not isinstance(self.value, str) or not self.value.strip():
                raise ValueError(f"'{self.operator}' needs a value.")
            values = [self.value]
        for v in values:
            if not isinstance(v, str) or not v.strip():
                raise ValueError("Values cannot be empty.")
            if len(v) > MAX_TEXT:
                raise ValueError(f"Values can be at most {MAX_TEXT} characters.")
        if len(values) > 20:
            raise ValueError("A list can hold at most 20 values.")
        if self.field in ENUM_VALUES:
            bad = [v for v in values if v not in ENUM_VALUES[self.field]]
            if bad:
                raise ValueError(f"Unknown {self.field}: {', '.join(bad)}.")
        return self


class Group(BaseModel):
    op: Literal["and", "or"]
    items: list["Condition | Group"] = Field(default_factory=list)

    @field_validator("items", mode="before")
    @classmethod
    def _route(cls, v: Any) -> Any:
        if not isinstance(v, list):
            return v
        out: list[Any] = []
        for item in v:
            if isinstance(item, dict) and "field" in item:
                out.append(Condition.model_validate(item))
            elif isinstance(item, dict):
                out.append(Group.model_validate(item))
            else:
                out.append(item)
        return out


Group.model_rebuild()


def _measure(group: Group, depth: int = 1) -> tuple[int, int]:
    """(max depth, number of conditions)."""
    max_depth, count = depth, 0
    for item in group.items:
        if isinstance(item, Group):
            d, c = _measure(item, depth + 1)
            max_depth, count = max(max_depth, d), count + c
        else:
            count += 1
    return max_depth, count


class Trigger(BaseModel):
    event: Event
    level: Literal["warning", "breach"] | None = None

    @model_validator(mode="after")
    def _level(self) -> "Trigger":
        if self.level and self.event != "sla.threshold":
            raise ValueError("A level only applies to the 'sla.threshold' event.")
        return self


class AssignSpec(BaseModel):
    target: Literal["user", "round_robin"]
    user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _ids(self) -> "AssignSpec":
        if self.target == "user" and not self.user_id:
            raise ValueError("Choose who to assign to (user_id).")
        if self.target == "round_robin" and not self.team_id:
            raise ValueError("Choose the team to rotate through (team_id).")
        return self


class AssignAction(AssignSpec):
    type: Literal["assign"]


class SetPriorityAction(BaseModel):
    type: Literal["set_priority"]
    value: Priority


class SetStatusAction(BaseModel):
    type: Literal["set_status"]
    value: Status


class AddTagAction(BaseModel):
    type: Literal["add_tag"]
    tag: str = Field(min_length=1, max_length=40)

    @field_validator("tag")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("A tag cannot be empty.")
        return v


class NotifyAction(BaseModel):
    type: Literal["notify"]
    target: Literal["user", "team", "assignee", "owners_admins"]
    user_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    message: str | None = Field(default=None, max_length=MAX_TEXT)

    @model_validator(mode="after")
    def _ids(self) -> "NotifyAction":
        if self.target == "user" and not self.user_id:
            raise ValueError("Choose who to notify (user_id).")
        if self.target == "team" and not self.team_id:
            raise ValueError("Choose the team to notify (team_id).")
        return self


class EscalateAction(BaseModel):
    type: Literal["escalate"]
    assign: AssignSpec
    message: str | None = Field(default=None, max_length=MAX_TEXT)


Action = Annotated[
    AssignAction
    | SetPriorityAction
    | SetStatusAction
    | AddTagAction
    | NotifyAction
    | EscalateAction,
    Field(discriminator="type"),
]


class RuleDefinition(BaseModel):
    trigger: Trigger
    conditions: Group
    actions: list[Action] = Field(min_length=1, max_length=MAX_ACTIONS)

    @model_validator(mode="after")
    def _size(self) -> "RuleDefinition":
        depth, count = _measure(self.conditions)
        if depth > MAX_DEPTH:
            raise ValueError(f"Conditions can be nested at most {MAX_DEPTH} levels deep.")
        if count > MAX_CONDITIONS:
            raise ValueError(f"A rule can have at most {MAX_CONDITIONS} conditions.")
        return self


def canonical_hash(defn: RuleDefinition) -> str:
    """Content hash of the normalised definition: tests are bound to it, any edit changes it."""
    blob = json.dumps(defn.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()

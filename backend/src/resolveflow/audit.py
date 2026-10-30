import json
import uuid
from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session


def record(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    actor_type: Literal["user", "system", "rule"],
    actor_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> None:
    """Append an audit row inside the caller's transaction (so it cannot be missed)."""
    session.execute(
        text(
            "insert into audit_log (workspace_id, actor_type, actor_id, action, entity_type, "
            "entity_id, before, after, request_id) values (:w, :at, :ai, :a, :et, :ei, "
            "cast(:b as jsonb), cast(:af as jsonb), :r)"
        ),
        {
            "w": workspace_id,
            "at": actor_type,
            "ai": actor_id,
            "a": action,
            "et": entity_type,
            "ei": entity_id,
            "b": json.dumps(before, default=str) if before is not None else None,
            "af": json.dumps(after, default=str) if after is not None else None,
            "r": request_id,
        },
    )

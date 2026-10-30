import json
import uuid
from typing import Any

from sqlalchemy import Connection, text
from sqlalchemy.orm import Session

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
PRIORITIES = ("low", "normal", "high", "urgent")


def default_settings() -> dict[str, Any]:
    """Editable starting point: one business day to first reply on normal tickets, Mon-Fri 9-17 UTC."""
    return {
        "enabled": True,
        "business_hours_only": True,
        "targets": {
            "urgent": {"first_response_minutes": 60, "resolution_minutes": 240},
            "high": {"first_response_minutes": 240, "resolution_minutes": 480},
            "normal": {"first_response_minutes": 480, "resolution_minutes": 1440},
            "low": {"first_response_minutes": 1440, "resolution_minutes": 4320},
        },
        "timezone": "UTC",
        "schedule": {
            d: ([{"start": "09:00", "end": "17:00"}] if d in DAYS[:5] else []) for d in DAYS
        },
        "holidays": [],
    }


_POLICY_SQL = (
    "insert into sla_policies (workspace_id, name, enabled, business_hours_only, targets) "
    "select {w}, 'Default', :enabled, :bho, cast(:targets as jsonb) {frm} "
    "on conflict (workspace_id) do nothing"
)
_CALENDAR_SQL = (
    "insert into business_calendars (workspace_id, timezone, weekly) "
    "select {w}, :tz, cast(:weekly as jsonb) {frm} on conflict (workspace_id) do nothing"
)


def _params() -> dict[str, Any]:
    d = default_settings()
    return {
        "enabled": d["enabled"],
        "bho": d["business_hours_only"],
        "targets": json.dumps(d["targets"]),
        "tz": d["timezone"],
        "weekly": json.dumps(d["schedule"]),
    }


def backfill_defaults(conn: Connection) -> None:
    """Give every workspace without one a default policy and calendar (idempotent)."""
    conn.execute(text(_POLICY_SQL.format(w="w.id", frm="from workspaces w")), _params())
    conn.execute(text(_CALENDAR_SQL.format(w="w.id", frm="from workspaces w")), _params())


def create_defaults(session: Session, workspace_id: uuid.UUID) -> None:
    session.execute(text(_POLICY_SQL.format(w=":ws", frm="")), {**_params(), "ws": workspace_id})
    session.execute(text(_CALENDAR_SQL.format(w=":ws", frm="")), {**_params(), "ws": workspace_id})

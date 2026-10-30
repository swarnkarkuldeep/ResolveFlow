import base64
import csv
import io
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text

from resolveflow.api.deps import RequestContext, require
from resolveflow.config import get_settings
from resolveflow.errors import err

router = APIRouter(prefix="/api")

CSV_MAX_ROWS = 10_000
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

_BASE = (
    "select a.id, a.created_at, a.actor_type, a.actor_id, u.name as actor_name, a.action, "
    "a.entity_type, a.entity_id, a.before, a.after from audit_log a "
    "left join users u on u.id = a.actor_id where a.workspace_id = :w"
)


def _filters(
    entity_type: str | None,
    actor_id: uuid.UUID | None,
    action: str | None,
    from_: datetime | None,
    to: datetime | None,
) -> tuple[str, dict[str, Any]]:
    sql = ""
    params: dict[str, Any] = {}
    if entity_type:
        sql += " and a.entity_type = :et"
        params["et"] = entity_type
    if actor_id:
        sql += " and a.actor_id = :ai"
        params["ai"] = actor_id
    if action:
        sql += " and a.action = :ac"
        params["ac"] = action
    if from_:
        sql += " and a.created_at >= :from_"
        params["from_"] = from_
    if to:
        sql += " and a.created_at <= :to"
        params["to"] = to
    return sql, params


def _row(r: Any) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "created_at": r.created_at.isoformat(),
        "actor_type": r.actor_type,
        "actor_id": str(r.actor_id) if r.actor_id else None,
        "actor_name": r.actor_name or ("System" if r.actor_type == "system" else None),
        "action": r.action,
        "entity_type": r.entity_type,
        "entity_id": str(r.entity_id) if r.entity_id else None,
        "before": r.before,
        "after": r.after,
    }


@router.get("/audit")
def list_audit(
    entity_type: str | None = None,
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = None,
    ctx: RequestContext = Depends(require("audit:read")),
) -> dict[str, Any]:
    where, params = _filters(entity_type, actor_id, action, from_, to)
    params.update(w=ctx.ws, lim=limit + 1)
    if cursor:
        try:
            data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            params.update(ct=data["t"], ci=str(uuid.UUID(data["i"])))
        except Exception:
            raise err(422, "bad_cursor", "That page marker is not valid.") from None
        where += " and (a.created_at, a.id) < (cast(:ct as timestamptz), cast(:ci as uuid))"
    rows = ctx.session.execute(
        text(_BASE + where + " order by a.created_at desc, a.id desc limit :lim"), params
    ).all()
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = page[-1]
        raw = json.dumps({"t": last.created_at.isoformat(), "i": str(last.id)})
        next_cursor = base64.urlsafe_b64encode(raw.encode()).decode()
    return {"items": [_row(r) for r in page], "next_cursor": next_cursor}


def _safe(value: object) -> str:
    cell = "" if value is None else str(value)
    return "'" + cell if cell.startswith(_FORMULA_PREFIXES) else cell


@router.get("/audit.csv")
def export_csv(
    entity_type: str | None = None,
    actor_id: uuid.UUID | None = None,
    action: str | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = None,
    ctx: RequestContext = Depends(require("audit:read")),
) -> Response:
    where, params = _filters(entity_type, actor_id, action, from_, to)
    params.update(w=ctx.ws, lim=CSV_MAX_ROWS)
    rows = ctx.session.execute(
        text(_BASE + where + " order by a.created_at desc, a.id desc limit :lim"), params
    ).all()
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["time", "actor", "action", "entity_type", "entity_id", "before", "after"])
    for r in rows:
        item = _row(r)
        writer.writerow(
            [
                _safe(item["created_at"]),
                _safe(item["actor_name"]),
                _safe(item["action"]),
                _safe(item["entity_type"]),
                _safe(item["entity_id"]),
                _safe(json.dumps(item["before"]) if item["before"] is not None else ""),
                _safe(json.dumps(item["after"]) if item["after"] is not None else ""),
            ]
        )
    return Response(
        out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit-log.csv"'},
    )


@router.get("/settings/channels")
def channel_settings(ctx: RequestContext = Depends(require("settings:read"))) -> dict[str, Any]:
    s = get_settings()
    ws = ctx.session.execute(
        text("select slug, inbound_token from workspaces where id = :w"), {"w": ctx.ws}
    ).one()
    form_url = f"{s.public_base_url}/form/{ws.slug}"
    return {
        "inbound_address": f"inbound-{ws.inbound_token}@{s.inbound_domain}",
        "form_url": form_url,
        "form_snippet": (
            f'<iframe src="{form_url}" title="Contact us" width="100%" height="560" '
            'style="border:0"></iframe>'
        ),
        "simulate_enabled": s.simulate_inbound_enabled,
    }

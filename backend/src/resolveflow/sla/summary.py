"""Read-side SLA views: the per-ticket summary for lists and the full explainer."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text

from resolveflow.context import ServiceCtx
from resolveflow.errors import err
from resolveflow.sla import service
from resolveflow.sla.defaults import DAYS
from resolveflow.sla.engine import elapsed_minutes

_ORDER = {"breached": 3, "at_risk": 2, "paused": 1, "running": 0}
DAY_LABEL = {d: d.capitalize() for d in DAYS}

SLA_COLUMNS = (
    "ts.fr_due_at, ts.res_due_at, ts.fr_met_at, ts.res_met_at, ts.fr_warned_at, ts.fr_breached_at, "
    "ts.res_warned_at, ts.res_breached_at, ts.paused_at, ts.fr_target_min, ts.res_target_min"
)

BREACHED_SQL = (
    "((ts.fr_breached_at is not null and ts.fr_met_at is null) "
    "or (ts.res_breached_at is not null and ts.res_met_at is null))"
)
AT_RISK_SQL = (
    "((ts.fr_warned_at is not null and ts.fr_met_at is null) "
    "or (ts.res_warned_at is not null and ts.res_met_at is null))"
)


def metric_state(target: int | None, met: Any, warned: Any, breached: Any, paused: Any) -> str:
    if target is None:
        return "none"
    if met is not None:
        return "met"
    if breached is not None:
        return "breached"
    if paused is not None:
        return "paused"
    if warned is not None:
        return "at_risk"
    return "running"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def summarize(row: Any) -> dict[str, Any]:
    """The `sla` object attached to ticket list items and details."""
    fr = metric_state(
        row.fr_target_min, row.fr_met_at, row.fr_warned_at, row.fr_breached_at, row.paused_at
    )
    res = metric_state(
        row.res_target_min, row.res_met_at, row.res_warned_at, row.res_breached_at, row.paused_at
    )
    unmet = [s for s in (fr, res) if s not in ("none", "met")]
    if unmet:
        overall = max(unmet, key=lambda s: _ORDER[s])
    elif fr == "none" and res == "none":
        overall = "none"
    else:
        overall = "met"
    due_candidates = [
        due
        for state, due in ((fr, row.fr_due_at), (res, row.res_due_at))
        if state in ("running", "at_risk", "breached") and due is not None
    ]
    return {
        "state": overall,
        "next_due_at": _iso(min(due_candidates)) if due_candidates else None,
        "first_response": {
            "due_at": _iso(row.fr_due_at),
            "met_at": _iso(row.fr_met_at),
            "state": fr,
        },
        "resolution": {
            "due_at": _iso(row.res_due_at),
            "met_at": _iso(row.res_met_at),
            "state": res,
        },
    }


def fmt_minutes(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} h {m} min"
    return f"{h} h" if h else f"{m} min"


def schedule_text(weekly: dict[str, list[dict[str, str]]]) -> str:
    def label(day: str) -> str:
        return ", ".join(f"{r['start']}–{r['end']}" for r in weekly.get(day, []))

    groups: list[tuple[list[str], str]] = []
    for day in DAYS:
        hours = label(day)
        if not hours:
            continue
        if (
            groups
            and groups[-1][1] == hours
            and DAYS.index(groups[-1][0][-1]) == DAYS.index(day) - 1
        ):
            groups[-1][0].append(day)
        else:
            groups.append(([day], hours))
    if not groups:
        return "Never open"
    parts = []
    for days, hours in groups:
        name = (
            DAY_LABEL[days[0]] if len(days) == 1 else f"{DAY_LABEL[days[0]]}–{DAY_LABEL[days[-1]]}"
        )
        parts.append(f"{name} {hours}")
    return "; ".join(parts)


def _event_text(kind: str, detail: dict[str, Any] | None) -> str:
    d = detail or {}
    if kind == "threshold":
        name = str(d.get("metric", "")).replace("_", " ")
        if d.get("level") == "warning":
            return f"Warning: 75% of the {name} target used"
        return f"Breached: the {name} target of {fmt_minutes(int(d.get('target_minutes', 0)))} was missed"
    return {
        "started": "Clock started",
        "paused": "Paused: waiting on the customer",
        "resumed": "Resumed",
        "first_response": "First response sent",
        "resolved": "Resolved",
        "reopened": "Reopened: the resolution clock restarted",
        "priority_changed": f"Priority changed from {d.get('from')} to {d.get('to')}; deadlines recalculated",
        "policy_changed": "Service levels changed; deadlines recalculated",
    }.get(kind, kind)


def explain(ctx: ServiceCtx, ticket_id: uuid.UUID, now: datetime | None = None) -> dict[str, Any]:
    now = now or service.utcnow()
    exists = ctx.session.execute(
        text("select 1 from tickets where id = :t and workspace_id = :w"),
        {"t": ticket_id, "w": ctx.ws},
    ).first()
    if not exists:
        raise err(404, "not_found", "Ticket not found.")
    c = service.compute(ctx, ticket_id)
    row = ctx.session.execute(
        text(f"select {SLA_COLUMNS} from ticket_sla ts where ts.ticket_id = :t"),  # noqa: S608 - constant columns
        {"t": ticket_id},
    ).first()
    summary = summarize(row) if row else None
    cal = c.cfg.clock_calendar

    def metric(key: str, name: str, prefix: str, start: datetime) -> dict[str, Any]:
        target = getattr(c, f"{prefix}_target")
        met = getattr(c.d, f"{prefix}_met_at")
        end = met or now
        paused = sum(
            (
                ((b or now) - max(a, start)).total_seconds() / 60
                for a, b in c.d.pauses
                if (b or now) > start
            ),
            0.0,
        )
        return {
            "key": key,
            "name": name,
            "target_minutes": target,
            "due_at": _iso(getattr(c, f"{prefix}_due")),
            "met_at": _iso(met),
            "state": summary[key]["state"] if summary else "none",
            "elapsed_minutes": round(elapsed_minutes(start, end, cal, c.d.pauses), 1)
            if target
            else None,
            "paused_minutes": round(paused, 1),
        }

    events = ctx.session.execute(
        text("select kind, detail, at from sla_events where ticket_id = :t order by at, id"),
        {"t": ticket_id},
    ).all()
    return {
        "policy": {
            "enabled": c.cfg.enabled,
            "business_hours_only": c.cfg.business_hours_only,
            "priority": c.priority,
            "targets": c.cfg.targets.get(c.priority),
        },
        "calendar": {
            "timezone": str(c.cfg.calendar.tz),
            "schedule_text": schedule_text(_weekly_json(c)),
            "holidays": len(c.cfg.calendar.holidays),
        },
        "state": summary["state"] if summary else "none",
        "metrics": [
            metric("first_response", "First response", "fr", c.d.start_at),
            metric("resolution", "Resolution", "res", c.d.res_start),
        ],
        "events": [
            {"at": e.at.isoformat(), "kind": e.kind, "text": _event_text(e.kind, e.detail)}
            for e in events
        ],
    }


def _weekly_json(c: service.Computed) -> dict[str, list[dict[str, str]]]:
    cal = c.cfg.calendar
    return {
        day: [
            {"start": s.strftime("%H:%M"), "end": e.strftime("%H:%M")}
            for s, e in cal.weekly.get(i, [])
        ]
        for i, day in enumerate(DAYS)
    }

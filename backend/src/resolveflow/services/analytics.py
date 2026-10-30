# ruff: noqa: S608  (the only concatenated SQL is a module constant; every value is bound)
"""Basic workspace analytics: plain SQL aggregates, all tenant-scoped, day buckets in UTC."""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from resolveflow.context import ServiceCtx

_RESOLVED_CTE = """
resolved as (
  select distinct on (a.entity_id) a.entity_id as ticket_id, a.created_at
  from audit_log a join tickets t on t.id = a.entity_id and t.workspace_id = a.workspace_id
  where a.workspace_id = :w and a.entity_type = 'ticket' and a.action = 'ticket.updated'
    and a.after ->> 'status' in ('resolved', 'closed') and a.created_at >= :since
    and t.status in ('resolved', 'closed')
  order by a.entity_id, a.created_at desc)
"""


def _pct(met: int, measured: int) -> float | None:
    return round(100.0 * met / measured, 1) if measured else None


def _avg(value: object) -> float | None:
    return round(float(value), 1) if value is not None else None  # type: ignore[arg-type]


def workspace_analytics(ctx: ServiceCtx, days: int) -> dict[str, Any]:
    s = ctx.session
    since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=days - 1
    )
    p = {"w": ctx.ws, "days": days, "since": since}

    totals = s.execute(
        text(
            "with "
            + _RESOLVED_CTE
            + "select (select count(*) from tickets where workspace_id = :w and created_at >= :since) as created, "
            "(select count(*) from resolved) as resolved, "
            "(select count(*) from tickets where workspace_id = :w and status not in ('resolved', 'closed')) as open_now"
        ),
        p,
    ).one()

    sla = s.execute(
        text(
            "select "
            "count(*) filter (where fr_target_min is not null and (fr_met_at is not null or fr_breached_at is not null)) as fr_measured, "
            "count(*) filter (where fr_target_min is not null and fr_met_at is not null and fr_breached_at is null) as fr_met, "
            "count(*) filter (where res_target_min is not null and (res_met_at is not null or res_breached_at is not null)) as res_measured, "
            "count(*) filter (where res_target_min is not null and res_met_at is not null and res_breached_at is null) as res_met, "
            "count(*) filter (where fr_breached_at is not null or res_breached_at is not null) as breached, "
            "avg(extract(epoch from (fr_met_at - start_at)) / 60) as avg_fr, "
            "avg(extract(epoch from (res_met_at - start_at)) / 60) as avg_res "
            "from ticket_sla s join tickets t on t.id = s.ticket_id "
            "where t.workspace_id = :w and t.created_at >= :since"
        ),
        p,
    ).one()

    by_day = s.execute(
        text(
            "select d::date as day, "
            "(select count(*) from tickets t where t.workspace_id = :w and "
            "  (t.created_at at time zone 'utc')::date = d::date) as created, "
            "(select count(*) from audit_log a join tickets t on t.id = a.entity_id and t.workspace_id = a.workspace_id "
            "  where a.workspace_id = :w and a.entity_type = 'ticket' and a.action = 'ticket.updated' "
            "  and a.after ->> 'status' in ('resolved', 'closed') and t.status in ('resolved', 'closed') "
            "  and (a.created_at at time zone 'utc')::date = d::date) as resolved "
            "from generate_series(cast(:since as date), cast(:since as date) + (:days - 1), interval '1 day') d order by d"
        ),
        p,
    ).all()

    def counts(column: str) -> list[Any]:
        sql = {
            "priority": "select priority as k, count(*) as n from tickets where workspace_id = :w "
            "and created_at >= :since group by priority order by n desc, k",
            "channel": "select channel as k, count(*) as n from tickets where workspace_id = :w "
            "and created_at >= :since group by channel order by n desc, k",
        }[column]
        return list(s.execute(text(sql), p).all())

    agents = s.execute(
        text(
            "with "
            + _RESOLVED_CTE
            + ", mine as (select assignee_id, id from tickets where workspace_id = :w and assignee_id is not null "
            "  and created_at >= :since) "
            "select u.name, count(m.id) as assigned, count(r.ticket_id) as resolved "
            "from mine m join users u on u.id = m.assignee_id "
            "left join resolved r on r.ticket_id = m.id group by u.name order by assigned desc, u.name"
        ),
        p,
    ).all()

    return {
        "range": {"days": days, "since": since.date().isoformat(), "timezone": "UTC"},
        "totals": {
            "created": totals.created,
            "resolved": totals.resolved,
            "open_now": totals.open_now,
        },
        "sla": {
            "first_response": {
                "measured": sla.fr_measured,
                "met": sla.fr_met,
                "compliance_pct": _pct(sla.fr_met, sla.fr_measured),
            },
            "resolution": {
                "measured": sla.res_measured,
                "met": sla.res_met,
                "compliance_pct": _pct(sla.res_met, sla.res_measured),
            },
            "breached": sla.breached,
        },
        "averages": {
            "first_response_minutes": _avg(sla.avg_fr),
            "resolution_minutes": _avg(sla.avg_res),
        },
        "by_day": [
            {"date": r.day.isoformat(), "created": r.created, "resolved": r.resolved}
            for r in by_day
        ],
        "by_priority": [{"priority": r.k, "count": r.n} for r in counts("priority")],
        "by_channel": [{"channel": r.k, "count": r.n} for r in counts("channel")],
        "by_agent": [
            {"agent": r.name, "assigned": r.assigned, "resolved": r.resolved} for r in agents
        ],
    }

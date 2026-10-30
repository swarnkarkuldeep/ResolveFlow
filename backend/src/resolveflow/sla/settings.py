import json
from datetime import date, time
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import text

from resolveflow import audit
from resolveflow.context import ServiceCtx
from resolveflow.sla.defaults import DAYS, PRIORITIES, create_defaults

Priority = Literal["low", "normal", "high", "urgent"]
Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
Clock = Annotated[str, Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]
MAX_MINUTES = 525_600  # one year


class Target(BaseModel):
    first_response_minutes: int = Field(ge=1, le=MAX_MINUTES)
    resolution_minutes: int = Field(ge=1, le=MAX_MINUTES)

    @model_validator(mode="after")
    def _order(self) -> "Target":
        if self.resolution_minutes < self.first_response_minutes:
            raise ValueError(
                "The resolution target cannot be shorter than the first response target."
            )
        return self


class Range(BaseModel):
    start: Clock
    end: Clock


class SlaSettingsIn(BaseModel):
    enabled: bool
    business_hours_only: bool
    targets: dict[Priority, Target]
    timezone: str = Field(max_length=64)
    schedule: dict[Day, list[Range]]
    holidays: list[date] = Field(max_length=100)

    @field_validator("targets")
    @classmethod
    def _all_priorities(cls, v: dict[str, Target]) -> dict[str, Target]:
        missing = [p for p in PRIORITIES if p not in v]
        if missing:
            raise ValueError(
                f"Targets are required for every priority; missing {', '.join(missing)}."
            )
        return v

    @field_validator("timezone")
    @classmethod
    def _zone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise ValueError("Unknown timezone. Use an IANA name such as Europe/London.") from None
        return v

    @field_validator("schedule")
    @classmethod
    def _ranges(cls, v: dict[str, list[Range]]) -> dict[str, list[Range]]:
        for day, ranges in v.items():
            if len(ranges) > 4:
                raise ValueError(f"{day}: at most 4 opening ranges per day.")
            parsed = sorted((_t(r.start), _t(r.end)) for r in ranges)
            for start, end in parsed:
                if start >= end:
                    raise ValueError(f"{day}: each range must start before it ends.")
            for (_, e1), (s2, _) in zip(parsed, parsed[1:], strict=False):
                if s2 < e1:
                    raise ValueError(f"{day}: opening ranges overlap.")
        return v


def _t(value: str) -> time:
    h, m = value.split(":")
    return time(int(h), int(m))


def normalized(body: SlaSettingsIn) -> dict[str, Any]:
    sched: dict[str, list[Range]] = {str(k): v for k, v in body.schedule.items()}
    return {
        "enabled": body.enabled,
        "business_hours_only": body.business_hours_only,
        "targets": {p: body.targets[p].model_dump() for p in PRIORITIES},
        "timezone": body.timezone,
        "schedule": {d: [r.model_dump() for r in sched.get(d, [])] for d in DAYS},
        "holidays": sorted({h.isoformat() for h in body.holidays}),
    }


def read_settings(ctx: ServiceCtx) -> dict[str, Any]:
    create_defaults(ctx.session, ctx.ws)  # no-op when rows exist; heals legacy workspaces
    p = ctx.session.execute(
        text(
            "select enabled, business_hours_only, targets, version from sla_policies "
            "where workspace_id = :w"
        ),
        {"w": ctx.ws},
    ).one()
    c = ctx.session.execute(
        text("select timezone, weekly, holidays from business_calendars where workspace_id = :w"),
        {"w": ctx.ws},
    ).one()
    return {
        "enabled": p.enabled,
        "business_hours_only": p.business_hours_only,
        "targets": p.targets,
        "timezone": c.timezone,
        "schedule": c.weekly,
        "holidays": [h.isoformat() for h in c.holidays],
        "version": p.version,
    }


def write_settings(ctx: ServiceCtx, body: SlaSettingsIn) -> dict[str, Any]:
    before = read_settings(ctx)
    new = normalized(body)
    ctx.session.execute(
        text(
            "update sla_policies set enabled = :e, business_hours_only = :b, "
            "targets = cast(:t as jsonb), version = version + 1, updated_at = now() "
            "where workspace_id = :w"
        ),
        {
            "e": new["enabled"],
            "b": new["business_hours_only"],
            "t": json.dumps(new["targets"]),
            "w": ctx.ws,
        },
    )
    ctx.session.execute(
        text(
            "update business_calendars set timezone = :z, weekly = cast(:s as jsonb), "
            "holidays = cast(:h as date[]), updated_at = now() where workspace_id = :w"
        ),
        {"z": new["timezone"], "s": json.dumps(new["schedule"]), "h": new["holidays"], "w": ctx.ws},
    )
    audit.record(
        ctx.session,
        workspace_id=ctx.ws,
        actor_type=ctx.actor_type,
        actor_id=ctx.actor_id,
        action="settings.sla_updated",
        entity_type="workspace",
        entity_id=ctx.ws,
        before={k: v for k, v in before.items() if k != "version"},
        after=new,
        request_id=ctx.request_id,
    )
    return read_settings(ctx)

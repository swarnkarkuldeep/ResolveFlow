"""Pure SLA arithmetic: no I/O, no clock reads. Every instant is passed in.

A deadline is the instant when `target_minutes` of *running* time have elapsed since `start`,
where running time excludes paused intervals and, when a calendar is given, is limited to its
opening hours (with holidays closed). All results are timezone-aware UTC.
"""

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

Pause = tuple[datetime, datetime | None]
Interval = tuple[datetime, datetime | None]

_MAX_DAYS = 366 * 3


@dataclass(frozen=True)
class Calendar:
    tz: ZoneInfo
    weekly: dict[int, list[tuple[time, time]]]  # weekday 0 = Monday; missing or empty = closed
    holidays: frozenset[date]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetimes must be timezone-aware")
    return value.astimezone(UTC)


def _merge_pauses(start: datetime, pauses: Sequence[Pause]) -> list[Pause]:
    """Clip to `start`, drop empties, merge overlaps. `None` as an end means 'still paused'."""
    items: list[tuple[datetime, datetime | None]] = []
    for a, b in pauses:
        a_utc, b_utc = _utc(a), (_utc(b) if b is not None else None)
        if b_utc is not None and b_utc <= start:
            continue
        a_utc = max(a_utc, start)
        if b_utc is not None and b_utc <= a_utc:
            continue
        items.append((a_utc, b_utc))
    items.sort(key=lambda p: p[0])
    merged: list[tuple[datetime, datetime | None]] = []
    for a, b in items:
        if merged:
            last_a, last_b = merged[-1]
            if last_b is None:
                continue
            if a <= last_b:
                merged[-1] = (last_a, None if b is None else max(last_b, b))
                continue
        merged.append((a, b))
    return merged


def _segments(start: datetime, merged: list[Pause]) -> list[Interval]:
    out: list[Interval] = []
    cursor = start
    for a, b in merged:
        if a > cursor:
            out.append((cursor, a))
        if b is None:
            return out
        cursor = max(cursor, b)
    out.append((cursor, None))
    return out


def _open_intervals(
    start: datetime, cal: Calendar, stop_at: datetime | None
) -> Iterator[tuple[datetime, datetime]]:
    if not any(cal.weekly.get(d) for d in range(7)):
        raise ValueError("calendar has no working hours")
    day = start.astimezone(cal.tz).date()
    for _ in range(_MAX_DAYS):
        if day not in cal.holidays:
            for open_t, close_t in cal.weekly.get(day.weekday(), []):
                a = datetime.combine(day, open_t, tzinfo=cal.tz).astimezone(UTC)
                b = datetime.combine(day, close_t, tzinfo=cal.tz).astimezone(UTC)
                if b <= start:
                    continue
                a = max(a, start)
                if stop_at is not None and a >= stop_at:
                    return
                yield a, b
        day += timedelta(days=1)
        if (
            stop_at is not None
            and datetime.combine(day, time(0), tzinfo=cal.tz).astimezone(UTC) >= stop_at
        ):
            return
    raise ValueError("no working time found within the planning horizon")


def _running(
    start: datetime, cal: Calendar | None, pauses: Sequence[Pause], until: datetime | None
) -> Iterator[Interval]:
    merged = _merge_pauses(start, pauses)
    segments = _segments(start, merged)
    # With an open pause, nothing after its start can ever run.
    open_pause_start = merged[-1][0] if merged and merged[-1][1] is None else None
    stop = min([x for x in (until, open_pause_start) if x is not None], default=None)

    if cal is None:
        for a, b in segments:
            end = b
            if stop is not None and (end is None or end > stop):
                end = stop
            if end is not None and end <= a:
                continue
            if stop is not None and a >= stop:
                return
            yield a, end
        return

    for oa, ob in _open_intervals(start, cal, stop):
        for sa, sb in segments:
            a = max(oa, sa)
            b = ob if sb is None else min(ob, sb)
            if stop is not None:
                b = min(b, stop)
            if b > a:
                yield a, b


def compute_due(
    start: datetime, target_minutes: int, calendar: Calendar | None, pauses: Sequence[Pause]
) -> datetime | None:
    """When the target is reached, or None while the clock is stopped by an open pause."""
    if target_minutes <= 0:
        raise ValueError("target_minutes must be positive")
    start = _utc(start)
    remaining = timedelta(minutes=target_minutes)
    for a, b in _running(start, calendar, pauses, until=None):
        if b is None:
            return a + remaining
        length = b - a
        if length >= remaining:
            return a + remaining
        remaining -= length
    return None


def elapsed_minutes(
    start: datetime, now: datetime, calendar: Calendar | None, pauses: Sequence[Pause]
) -> float:
    """Running minutes consumed between `start` and `now`."""
    start, now = _utc(start), _utc(now)
    if now <= start:
        return 0.0
    total = timedelta(0)
    for a, b in _running(start, calendar, pauses, until=now):
        total += (b if b is not None else now) - a
    return total.total_seconds() / 60


def threshold_instant(
    start: datetime,
    target_minutes: int,
    fraction: float,
    calendar: Calendar | None,
    pauses: Sequence[Pause],
) -> datetime | None:
    """The instant `fraction` of the target has been consumed (rounded up to a whole minute)."""
    return compute_due(start, max(1, math.ceil(target_minutes * fraction)), calendar, pauses)

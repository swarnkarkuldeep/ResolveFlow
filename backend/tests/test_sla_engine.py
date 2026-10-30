from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from resolveflow.sla.engine import Calendar, compute_due, elapsed_minutes, threshold_instant

UTC_TZ = ZoneInfo("UTC")
WEEKDAYS = {d: [(time(9), time(17))] for d in range(5)}
WORK_WEEK = Calendar(UTC_TZ, WEEKDAYS, frozenset())


def at(day: int, hh: int, mm: int = 0, month: int = 11) -> datetime:
    return datetime(2026, month, day, hh, mm, tzinfo=UTC)


def test_calendar_fixture_dates_are_what_the_tests_assume() -> None:
    assert date(2026, 11, 2).weekday() == 0  # Monday
    assert date(2026, 11, 6).weekday() == 4  # Friday
    assert date(2026, 11, 7).weekday() == 5  # Saturday


def test_24x7_is_plain_addition() -> None:
    assert compute_due(at(2, 10), 90, None, []) == at(2, 11, 30)


def test_24x7_skips_pauses() -> None:
    assert compute_due(at(2, 10), 90, None, [(at(2, 10, 30), at(2, 11))]) == at(2, 12)


def test_overlapping_pauses_count_once() -> None:
    pauses = [(at(2, 10, 30), at(2, 11)), (at(2, 10, 45), at(2, 11, 15))]
    assert compute_due(at(2, 10), 90, None, pauses) == at(2, 12, 15)


def test_open_pause_stops_the_clock() -> None:
    assert compute_due(at(2, 10), 90, None, [(at(2, 10, 30), None)]) is None


def test_business_hours_roll_over_a_weekend() -> None:
    # Fri 16:30 + 120 min: 30 min Friday, 90 min Monday morning.
    assert compute_due(at(6, 16, 30), 120, WORK_WEEK, []) == at(9, 10, 30)


def test_created_on_a_saturday_starts_counting_monday() -> None:
    assert compute_due(at(7, 12), 60, WORK_WEEK, []) == at(9, 10)


def test_created_before_opening_waits_for_opening() -> None:
    assert compute_due(at(2, 8), 30, WORK_WEEK, []) == at(2, 9, 30)


def test_split_day_skips_lunch() -> None:
    lunch = Calendar(UTC_TZ, {0: [(time(9), time(12)), (time(13), time(17))]}, frozenset())
    assert compute_due(at(2, 11, 30), 120, lunch, []) == at(2, 14, 30)


def test_holiday_is_skipped() -> None:
    cal = Calendar(UTC_TZ, WEEKDAYS, frozenset({date(2026, 11, 9)}))
    assert compute_due(at(6, 16, 30), 120, cal, []) == at(10, 10, 30)


def test_pause_across_the_weekend() -> None:
    # 105 running minutes Fri 15:00-16:45, paused until Mon 10:00, 15 minutes left.
    pauses = [(at(6, 16, 45), at(9, 10))]
    assert compute_due(at(6, 15), 120, WORK_WEEK, pauses) == at(9, 10, 15)


def test_open_pause_in_business_hours_returns_none() -> None:
    assert compute_due(at(6, 15), 120, WORK_WEEK, [(at(6, 16), None)]) is None


def test_dst_spring_forward_counts_real_elapsed_business_time() -> None:
    ny = ZoneInfo("America/New_York")
    nightly = Calendar(ny, {d: [(time(1), time(5))] for d in range(7)}, frozenset())
    start = datetime(2026, 3, 8, 6, 0, tzinfo=UTC)  # 01:00 EST, the night clocks jump to 03:00 EDT
    # The 01:00-05:00 window is only 3 real hours that night (06:00-09:00 UTC).
    assert compute_due(start, 180, nightly, []) == datetime(2026, 3, 8, 9, 0, tzinfo=UTC)
    # One minute more spills into the next night's window, which opens 05:00 UTC (01:00 EDT).
    assert compute_due(start, 181, nightly, []) == datetime(2026, 3, 9, 5, 1, tzinfo=UTC)


def test_timezone_without_dst_and_half_hour_offset() -> None:
    ist = Calendar(ZoneInfo("Asia/Kolkata"), WEEKDAYS, frozenset())  # open 03:30-11:30 UTC
    # Mon 11:00 UTC = 16:30 IST: 30 min left today, 30 min tomorrow from 03:30 UTC.
    assert compute_due(at(2, 11), 60, ist, []) == at(3, 4)


def test_elapsed_matches_the_target_at_the_due_instant() -> None:
    cases = [
        (at(6, 16, 30), 120, WORK_WEEK, []),
        (at(6, 15), 120, WORK_WEEK, [(at(6, 16, 45), at(9, 10))]),
        (at(2, 10), 90, None, [(at(2, 10, 30), at(2, 11))]),
    ]
    for start, target, cal, pauses in cases:
        due = compute_due(start, target, cal, pauses)
        assert due is not None
        assert elapsed_minutes(start, due, cal, pauses) == pytest.approx(target)
        assert elapsed_minutes(start, start, cal, pauses) == 0


def test_elapsed_exact_value_across_pause() -> None:
    # Fri 15:00-16:45 runs (105), paused to Mon 10:00, Mon 10:00-12:00 runs (120).
    value = elapsed_minutes(at(6, 15), at(9, 12), WORK_WEEK, [(at(6, 16, 45), at(9, 10))])
    assert value == pytest.approx(225)


def test_threshold_instant_uses_the_rounded_up_fraction() -> None:
    # 75% of 480 business minutes = 360, i.e. Mon 10:00 + 6h = Mon 16:00.
    assert threshold_instant(at(2, 10), 480, 0.75, WORK_WEEK, []) == at(2, 16)
    # 75% of 61 minutes rounds up to 46.
    assert threshold_instant(at(2, 10), 61, 0.75, None, []) == at(2, 10, 46)


def test_invalid_inputs_raise() -> None:
    with pytest.raises(ValueError):
        compute_due(at(2, 10), 0, None, [])
    with pytest.raises(ValueError):
        compute_due(at(2, 10), -5, None, [])
    with pytest.raises(ValueError):
        compute_due(datetime(2026, 11, 2, 10), 30, None, [])  # naive
    with pytest.raises(ValueError):
        compute_due(at(2, 10), 30, Calendar(UTC_TZ, {}, frozenset()), [])  # never open


def test_results_are_utc_even_for_non_utc_input() -> None:
    start = datetime(2026, 11, 2, 11, 0, tzinfo=ZoneInfo("Asia/Tokyo"))  # 02:00 UTC
    due = compute_due(start, 60, None, [])
    assert due == datetime(2026, 11, 2, 3, 0, tzinfo=UTC) and due.utcoffset() == timedelta(0)

"""Holiday windows, and the controller events that cover them. Pure date logic.

The controller's own yearly repeat rules are unreliable for a holiday that moves, or for a
window that starts before the holiday and ends after it. So each holiday is kept as ONE
ordinary event that holds the *next* occurrence's real dates (daily, until the last night). When
that window has passed, the same event is updated in place to the following year's dates
(see holiday_manager.py). The controller then only ever plays a plain dated event.

A holiday's window is one of:
  week   the Monday-Sunday week containing the holiday's date
  range  a fixed start and end date (may cross New Year)
  day    the single date
each widened (or, with negative numbers, narrowed) by `before` / `after` days.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

EVENT_PREFIX = "Holiday: "
MAX_ADJUST = 14  # extra days before / after, either way

# A date rule is ("fixed", month, day), ("nth", month, weekday, n) with Monday = 0, or
# ("easter", offset_days).
Rule = tuple


@dataclass(frozen=True)
class Holiday:
    id: str
    name: str
    kind: str                      # week | range | day
    start: Rule                    # the holiday's date, or a range's first day
    end: Rule | None = None        # a range's last day
    priority: int = 3
    # Start and end of each night. Nights run from sunset to midnight (a holiday applies by
    # calendar date); the controller's own schedule takes over after that.
    times: tuple[str, str] = ("sunset", "00:00")
    overnight: bool = True         # each night ends on the next date
    info: str = ""
    custom: bool = False


CATALOG: tuple[Holiday, ...] = (
    Holiday("new_year", "New Year fireworks", "day", ("fixed", 1, 1), priority=4,
            times=("00:00", "00:15"), overnight=False, info="Jan 1, midnight to 00:15"),
    Holiday("december", "December", "range", ("fixed", 12, 1), ("fixed", 12, 31), info="Dec 1 – 31"),
    Holiday("st_patricks", "St. Patrick's Day", "week", ("fixed", 3, 17), info="The week of Mar 17"),
    Holiday("easter", "Easter Monday", "week", ("easter", 1), info="The week of Easter Monday"),
    Holiday("canada_day", "Canada Day", "week", ("fixed", 7, 1), info="The week of Jul 1"),
    Holiday("truth_reconciliation", "Truth and Reconciliation", "week", ("fixed", 9, 30), info="The week of Sep 30"),
    Holiday("thanksgiving", "Canadian Thanksgiving", "week", ("nth", 10, 0, 2), info="The week of the 2nd Monday of October"),
    Holiday("halloween", "Halloween", "range", ("fixed", 10, 25), ("fixed", 10, 31), info="Oct 25 – 31"),
    Holiday("remembrance", "Remembrance Day", "week", ("fixed", 11, 11), info="The week of Nov 11"),
)
BY_ID = {h.id: h for h in CATALOG}


def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (the anonymous Gregorian computus)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def rule_date(rule: Rule, year: int) -> date:
    kind = rule[0]
    if kind == "fixed":
        try:
            return date(year, rule[1], rule[2])
        except ValueError:  # Feb 29 in a year without one
            return date(year, rule[1], rule[2] - 1)
    if kind == "nth":
        _, month, weekday, n = rule
        first = date(year, month, 1)
        return first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (n - 1))
    if kind == "easter":
        return easter_sunday(year) + timedelta(days=rule[1])
    raise ValueError(f"unknown date rule {rule!r}")


def window(holiday: Holiday, year: int, before: int = 0, after: int = 0) -> tuple[date, date]:
    """First and last night of the holiday that belongs to `year` (a range may end the next year)."""
    first = rule_date(holiday.start, year)
    if holiday.kind == "week":
        start = first - timedelta(days=first.weekday())
        end = start + timedelta(days=6)
    elif holiday.kind == "range":
        end = rule_date(holiday.end, year)
        if end < first:
            end = rule_date(holiday.end, year + 1)
        start = first
    else:
        start = end = first
    start, end = start - timedelta(days=before), end + timedelta(days=after)
    if end < start:  # narrowed past nothing: keep one night
        end = start
    return start, end


def next_window(holiday: Holiday, today: date, before: int = 0, after: int = 0) -> tuple[date, date]:
    """The occurrence in progress today, or else the next one."""
    candidates = sorted(window(holiday, y, before, after) for y in (today.year - 1, today.year, today.year + 1))
    return next(w for w in candidates if w[1] >= today)


def event_name(holiday: Holiday) -> str:
    return f"{EVENT_PREFIX}{holiday.name}"


def event_fields(
    holiday: Holiday,
    span: tuple[date, date],
    scene_uuid: str | None,
    enabled: bool = True,
    playlist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The event as create_event / update_event fields: nightly until the last night.

    It shows a scene, or a playlist (`{"uuid", "seconds", "shuffle"}`) instead.
    """
    start, end = span
    fields = {
        "name": event_name(holiday),
        "start_date": start.isoformat(),
        # A night that ends at midnight (or at sunrise) ends on the next date.
        "end_date": (start + timedelta(days=1) if holiday.overnight else start).isoformat(),
        "start_time": holiday.times[0],
        "end_time": holiday.times[1],
        "priority": holiday.priority,
        "frequency": 1,
        "interval": 1,
        "repeat_until": end.isoformat(),
        "enabled": enabled,
    }
    if playlist:
        fields.update(playlist=playlist["uuid"], seconds_per_scene=playlist["seconds"], shuffle=playlist["shuffle"])
    else:
        fields["scene"] = scene_uuid
    return fields


# ---- custom holidays --------------------------------------------------------

_MMDD = re.compile(r"^(\d{1,2})-(\d{1,2})$")


def parse_month_day(text: Any) -> tuple[int, int] | None:
    """'10-25' -> (10, 25) if that is a real date (Feb 29 allowed), else None."""
    m = _MMDD.match(text) if isinstance(text, str) else None
    if not m:
        return None
    month, day = int(m.group(1)), int(m.group(2))
    try:
        date(2024, month, day)  # a leap year, so 02-29 passes
    except ValueError:
        return None
    return month, day


def custom_holiday(spec: dict[str, Any]) -> Holiday | None:
    """A user's holiday ({id, name, start: 'MM-DD', end: 'MM-DD'}) as a Holiday, or None if invalid."""
    start, end = parse_month_day(spec.get("start")), parse_month_day(spec.get("end"))
    name = str(spec.get("name") or "").strip()
    if not (start and end and name and spec.get("id")):
        return None
    return Holiday(str(spec["id"]), name[:60], "range", ("fixed", *start), ("fixed", *end), custom=True,
                   info=f"{spec['start']} – {spec['end']}")


def clamp_adjust(value: Any) -> int:
    try:
        return max(-MAX_ADJUST, min(MAX_ADJUST, int(value)))
    except (TypeError, ValueError):
        return 0

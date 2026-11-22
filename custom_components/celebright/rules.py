"""Lighting rules: "show this scene while something is true, then go back to the schedule".

Pure logic (no Home Assistant imports): validating a rule as the card submits it, and deciding
whether it is true right now. rule_engine.py watches Home Assistant and acts on the result.

A rule is true when its condition holds AND every optional limit is met:
  when        a sensor is above / below a number, or an entity is in a state (default "on")
  only_dark   the sun is below the horizon
  dates       today is inside a yearly month/day range (may cross New Year)
  times       the time of day is inside a window (may cross midnight)
Rules are kept in priority order (first wins). `max_hours` is handled by the engine.
"""
from __future__ import annotations

import re
import uuid as _uuid
from datetime import date, datetime, time
from typing import Any, Callable

from .holidays import parse_month_day

RULE_TYPES = ("sensor_above", "sensor_below", "entity_state")
MAX_RULES = 20
_ENTITY = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
_CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
_UNKNOWN = ("unknown", "unavailable", "none", "")

# What the card offers as a starting point. The aurora rule has no entity: the card fills in
# a sensor with "aurora" in its name when it finds one.
PRESETS: tuple[dict[str, Any], ...] = (
    {"id": "aurora", "name": "Aurora alert", "when": {"type": "sensor_above", "value": 75}, "only_dark": True},
    {"id": "switch", "name": "While a switch is on", "when": {"type": "entity_state", "value": "on"}},
    {"id": "sensor", "name": "Sensor rule", "when": {"type": "sensor_above", "value": 50}},
)


def _clock(value: Any) -> str | None:
    m = _CLOCK.match(value.strip()) if isinstance(value, str) else None
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def validate_rule(raw: dict[str, Any]) -> dict[str, Any]:
    """The rule in its stored form, or ValueError with a message for the user."""
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("Give the rule a name.")
    if not raw.get("scene"):
        raise ValueError("Choose a scene.")

    when_raw = raw.get("when") or {}
    kind = when_raw.get("type")
    if kind not in RULE_TYPES:
        raise ValueError("Choose what the rule waits for.")
    entity_id = str(when_raw.get("entity_id") or "").strip().lower()
    if not _ENTITY.match(entity_id):
        raise ValueError("Choose an entity (for example sensor.aurora_visibility).")
    if kind == "entity_state":
        value: Any = str(when_raw.get("value") if when_raw.get("value") not in (None, "") else "on").strip()
    else:
        try:
            value = float(when_raw.get("value"))
        except (TypeError, ValueError):
            raise ValueError("Enter the number to compare against.") from None

    rule: dict[str, Any] = {
        "id": str(raw.get("id") or _uuid.uuid4().hex[:8]),
        "name": name[:60],
        "enabled": bool(raw.get("enabled", True)),
        "scene": str(raw["scene"]),
        "when": {"type": kind, "entity_id": entity_id, "value": value},
        "only_dark": bool(raw.get("only_dark")),
        "dates": None,
        "times": None,
        "max_hours": None,
    }

    dates = raw.get("dates")
    if dates:
        start, end = parse_month_day(dates.get("start")), parse_month_day(dates.get("end"))
        if not (start and end):
            raise ValueError("Enter valid start and end dates.")
        rule["dates"] = {"start": f"{start[0]:02d}-{start[1]:02d}", "end": f"{end[0]:02d}-{end[1]:02d}"}

    times = raw.get("times")
    if times:
        start, end = _clock(times.get("start")), _clock(times.get("end"))
        if not (start and end) or start == end:
            raise ValueError("Enter a start and an end time that differ.")
        rule["times"] = {"start": start, "end": end}

    if raw.get("max_hours") not in (None, "", 0):
        try:
            hours = float(raw["max_hours"])
        except (TypeError, ValueError):
            raise ValueError("Enter the hours as a number.") from None
        if not 0.25 <= hours <= 48:
            raise ValueError("Stop after between 0.25 and 48 hours.")
        rule["max_hours"] = hours
    return rule


def condition_met(when: dict[str, Any], read: Callable[[str], str | None]) -> bool:
    state = read(when["entity_id"])
    if state is None or state.strip().lower() in _UNKNOWN:
        return False
    if when["type"] == "entity_state":
        return state.strip().lower() == str(when["value"]).strip().lower()
    try:
        number = float(state)
    except ValueError:
        return False
    return number > when["value"] if when["type"] == "sensor_above" else number < when["value"]


def in_dates(dates: dict[str, str] | None, today: date) -> bool:
    if not dates:
        return True
    start, end = parse_month_day(dates["start"]), parse_month_day(dates["end"])
    here = (today.month, today.day)
    return (start <= here <= end) if start <= end else (here >= start or here <= end)


def in_times(times: dict[str, str] | None, now: time) -> bool:
    if not times:
        return True
    here = now.strftime("%H:%M")
    start, end = times["start"], times["end"]
    return (start <= here < end) if start < end else (here >= start or here < end)


def is_met(rule: dict[str, Any], read: Callable[[str], str | None], now: datetime, dark: bool) -> bool:
    """Whether the rule is true right now (an enabled rule; the engine skips disabled ones)."""
    return (
        condition_met(rule["when"], read)
        and (dark or not rule["only_dark"])
        and in_dates(rule["dates"], now.date())
        and in_times(rule["times"], now.time())
    )


def describe(rule: dict[str, Any]) -> str:
    """One line for the card, e.g. "sensor.aurora above 75, only after dark"."""
    when = rule["when"]
    parts = [{"sensor_above": "{e} above {v:g}", "sensor_below": "{e} below {v:g}"}.get(when["type"], "{e} is {v}").format(
        e=when["entity_id"], v=when["value"])]
    if rule["only_dark"]:
        parts.append("only after dark")
    if rule["dates"]:
        parts.append(f"{rule['dates']['start']} to {rule['dates']['end']}")
    if rule["times"]:
        parts.append(f"{rule['times']['start']}-{rule['times']['end']}")
    if rule["max_hours"]:
        parts.append(f"for at most {rule['max_hours']:g} h")
    return ", ".join(parts)

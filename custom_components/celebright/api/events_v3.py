"""Schedule events for v3 (firmware 3.x) controllers. Pure functions, no I/O.

Event format as the Celebright app sends it (`saveEvent {"event": {...}}`): dates are
"YYYY-MM-DD"; start/end anchors are sunrise | sunset | fixed_time (then *_time is
"HH:MM:SS"); offsets apply only to sunrise/sunset anchors; `recurrence_rule` is an
RRULE or null (once). The md5 recipe reproduces the server checksum of an app-created event.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from .base import EventInfo

ANCHORS = ("fixed_time", "sunrise", "sunset")

_MONTHS = ["", "January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]
_SHORT_MONTHS = [m[:3] for m in _MONTHS]
_WEEKDAYS = {"SU": "Sunday", "MO": "Monday", "TU": "Tuesday", "WE": "Wednesday",
             "TH": "Thursday", "FR": "Friday", "SA": "Saturday"}
_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", -1: "last"}


def utc_now_str() -> str:
    """last_modified_utc format used by the app: 2026-10-26T17:58:10Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- Building ---

def code_to_anchor(code: int) -> tuple[str, str | None]:
    """Legacy time code -> (anchor, "HH:MM:SS"|None): -2 sunset, -1 sunrise, n >= 0 seconds."""
    if code == -2:
        return "sunset", None
    if code == -1:
        return "sunrise", None
    code = max(0, code)
    return "fixed_time", f"{code // 3600:02d}:{code % 3600 // 60:02d}:{code % 60:02d}"


def format_until(epoch: int) -> str:
    """RRULE UNTIL value: 20251030T060000Z."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_rrule(
    *,
    frequency: int,
    interval: int = 1,
    by_day: str | None = None,
    by_month: int | None = None,
    by_month_day: int | None = None,
    by_set_pos: int | None = None,
    until_epoch: int | None = None,
) -> str | None:
    """RRULE for frequency 0 = once (none), 1 = daily (until `until_epoch` or forever), 4 = yearly.

    Part order follows the rules the app stores.
    """
    parts: list[str] = []
    if frequency == 4:
        parts.append("FREQ=YEARLY")
    elif frequency == 1:
        parts.append("FREQ=DAILY")
    else:
        return None
    if interval and interval > 1:
        parts.append(f"INTERVAL={interval}")
    if frequency == 4:
        if by_month_day:
            parts.append(f"BYMONTHDAY={by_month_day}")
        if by_day:
            parts.append(f"BYDAY={by_day}")
        if by_month:
            parts.append(f"BYMONTH={by_month}")
        if by_set_pos:
            parts.append(f"BYSETPOS={by_set_pos}")
    if until_epoch is not None:
        parts.append(f"UNTIL={format_until(until_epoch)}")
    return ";".join(parts)


def compute_event_md5_v3(ev: dict[str, Any]) -> str:
    """The app's checksum: md5 of the concatenated fields (null -> ""), in this order."""
    def s(x: Any) -> str:
        return "" if x is None else str(x)

    def b01(x: Any) -> str:
        return "" if x is None else ("1" if x else "0")

    def anchor(x: Any) -> str:
        return x if x in ("sunrise", "sunset") else "fixed_time"

    parts = [
        ev["uuid"], ev["event_name"],
        s(ev.get("saved_scene_uuid")), s(ev.get("event_look_uuid")), s(ev.get("playlist_uuid")),
        s(ev.get("playlist_scene_display_duration_seconds")),
        b01(ev.get("playlist_randomize")), b01(ev.get("playlist_once_per_event")),
        s(ev.get("group_uuid")), s(ev.get("subscribed_event_series_uuid")),
        s(ev["priority"] if ev.get("priority") is not None else 3),
        s(ev.get("start_date")), anchor(ev.get("start_anchor_type")),
        s(ev.get("start_time")), s(ev.get("start_offset_minutes")),
        s(ev.get("end_date")), anchor(ev.get("end_anchor_type")),
        s(ev.get("end_time")), s(ev.get("end_offset_minutes")),
        s(ev.get("recurrence_rule")),
        "1" if ev.get("recurrence_every_year") else "0",
        "1" if ev.get("enabled", True) else "0",
        s(ev.get("event_looks_playlist_uuid")),
    ]
    return hashlib.md5("".join(parts).encode("utf-8")).hexdigest()


def build_event(
    *,
    uuid: str,
    name: str,
    scene_uuid: str,
    start_date: str,
    end_date: str,
    start_anchor: str,
    start_time: str | None,
    end_anchor: str,
    end_time: str | None,
    priority: int = 3,
    start_offset_minutes: int | None = None,
    end_offset_minutes: int | None = None,
    rrule: str | None = None,
    enabled: bool = True,
    last_modified_utc: str | None = None,
) -> dict[str, Any]:
    """A complete v3 event dict, checksum included, ready for `saveEvent`."""
    ev: dict[str, Any] = {
        "uuid": uuid,
        "md5": "",
        "event_name": name,
        "priority": priority,
        "start_date": start_date,
        "start_anchor_type": start_anchor,
        "start_time": start_time if start_anchor == "fixed_time" else None,
        "end_date": end_date,
        "end_anchor_type": end_anchor,
        "end_time": end_time if end_anchor == "fixed_time" else None,
        "recurrence_rule": rrule,
        "recurrence_every_year": False,
        "enabled": enabled,
        "last_modified_utc": last_modified_utc or utc_now_str(),
        "saved_scene_uuid": scene_uuid,
    }
    # The app only sends offsets for sunrise/sunset anchors (0 when unset).
    if start_anchor != "fixed_time":
        ev["start_offset_minutes"] = start_offset_minutes or 0
    if end_anchor != "fixed_time":
        ev["end_offset_minutes"] = end_offset_minutes or 0
    ev["md5"] = compute_event_md5_v3(ev)
    return ev


# --- Decoding (for the Scheduled Events sensor) ---

def parse_rrule(rule: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (rule or "").split(";"):
        key, _, value = part.partition("=")
        if key:
            out[key.upper()] = value
    return out


def _fmt_date(value: str | None) -> str:
    """'2026-11-01' (or an UNTIL '20261114T070000Z') -> 'Nov 1'."""
    if not value:
        return "?"
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", value)
    if not m:
        return value
    month, day = int(m.group(2)), int(m.group(3))
    return f"{_SHORT_MONTHS[month]} {day}" if 1 <= month <= 12 else value


def describe_when(ev: dict[str, Any]) -> str:
    rule = parse_rrule(ev.get("recurrence_rule"))
    start, end = ev.get("start_date"), ev.get("end_date")
    freq = rule.get("FREQ")
    until = rule.get("UNTIL")

    if freq == "YEARLY":
        try:
            month = int(rule["BYMONTH"]) if "BYMONTH" in rule else None
            day = int(rule["BYMONTHDAY"]) if "BYMONTHDAY" in rule else None
            pos = int(rule["BYSETPOS"]) if "BYSETPOS" in rule else None
        except ValueError:
            month = day = pos = None
        weekday = rule.get("BYDAY")
        if month and day:
            text = f"Every {_MONTHS[month]} {day}"
        elif month and weekday and pos:
            text = f"{_ORDINALS.get(pos, str(pos))} {_WEEKDAYS.get(weekday, weekday)} of {_MONTHS[month]}"
        else:
            text = "Every year"
        if until:
            text += f" (until {_fmt_date(until)})"
    elif freq == "DAILY":
        text = f"{_fmt_date(start)} – {_fmt_date(until)} (seasonal)" if until else f"Daily from {_fmt_date(start)}"
    elif freq == "WEEKLY":
        days = ", ".join(_WEEKDAYS.get(d, d)[:3] for d in rule.get("BYDAY", "").split(",") if d)
        text = f"Weekly on {days}" if days else "Weekly"
    else:
        text = _fmt_date(start) if not end or end == start else f"{_fmt_date(start)} – {_fmt_date(end)}"
    return text


def _anchor_text(anchor: str | None, clock: str | None, offset: int | None) -> str:
    if anchor in ("sunrise", "sunset"):
        label = anchor.capitalize()
        return f"{label} {offset:+d} min" if offset else label
    if not clock:
        return "?"
    hhmm = clock[:5]
    return "Midnight" if hhmm == "00:00" else hhmm


def describe_time(ev: dict[str, Any]) -> str:
    start = _anchor_text(ev.get("start_anchor_type"), ev.get("start_time"), ev.get("start_offset_minutes"))
    end = _anchor_text(ev.get("end_anchor_type"), ev.get("end_time"), ev.get("end_offset_minutes"))
    return f"{start} – {end}"


def is_v3_event_list(raw_events: list[Any]) -> bool:
    """True when the REST list uses the v3 event format (vs the legacy one)."""
    return any(isinstance(e, dict) and "start_anchor_type" in e for e in raw_events)


def parse_events(raw_events: list[dict[str, Any]]) -> list[EventInfo]:
    events: list[EventInfo] = []
    for e in raw_events:
        if not isinstance(e, dict):
            continue
        enabled = bool(e.get("enabled", True))
        when = describe_when(e)
        events.append(
            EventInfo(
                uuid=e.get("uuid", ""),
                name=e.get("event_name", "Event"),
                scene_uuid=e.get("saved_scene_uuid") or "",
                priority=e.get("priority") if isinstance(e.get("priority"), int) else 0,
                when_text=when if enabled else f"{when} — disabled",
                time_text=describe_time(e),
                raw=e,
                enabled=enabled,
            )
        )
    events.sort(key=lambda ev: (-ev.priority, ev.name.lower()))
    return events

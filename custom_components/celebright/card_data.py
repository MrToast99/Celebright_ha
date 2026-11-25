"""Data for the Celebright card: each controller's entities, scenes and schedule events.

Pure functions (no Home Assistant imports), so they can be tested on their own.
An event comes with a `form`: its fields in the shape the create_event / update_event
services take, so the card can edit it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from .api.base import uses_v3_firmware
from .api.events_v3 import is_v3_event_list, parse_rrule

# role -> (domain, unique-id suffix). "" is the bare device id (the light).
_ENTITY_ROLES: dict[str, tuple[str, str]] = {
    "light": ("light", ""),
    "scene_select": ("select", "scene"),
    "schedule": ("binary_sensor", "schedule_enabled"),
    "schedule_switch": ("switch", "schedule_switch"),
    "refresh": ("button", "refresh_scenes"),
    **{
        key: ("sensor", key)
        for key in (
            "current_display", "active_event", "next_event_start", "active_source",
            "scheduled_events", "model", "firmware", "hw_version", "led_count",
            "bulb_type", "color_order", "location",
        )
    },
}

_LocalDate = Callable[[int], str]


def _clock(seconds: int) -> str:
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


def _legacy_time(code: Any) -> str:
    """Legacy time code -> the services' time text."""
    if code == -2:
        return "sunset"
    if code == -1:
        return "sunrise"
    return _clock(code) if isinstance(code, int) and code > 0 else "00:00"


def _until_date(until: str | None, local_date: _LocalDate) -> str | None:
    """RRULE UNTIL (20251031T060000Z) -> local 'YYYY-MM-DD'."""
    if not until:
        return None
    try:
        moment = datetime.strptime(until, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        try:
            moment = datetime.strptime(until[:8], "%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return local_date(int(moment.timestamp()))


def _v3_time(anchor: str | None, clock: str | None) -> str:
    if anchor in ("sunrise", "sunset"):
        return anchor
    return clock[:5] if clock else "00:00"


def _v3_form(raw: dict[str, Any], local_date: _LocalDate) -> dict[str, Any]:
    rule = parse_rrule(raw.get("recurrence_rule"))
    freq = {"YEARLY": 4, "DAILY": 1}.get(rule.get("FREQ", ""), 0)
    form: dict[str, Any] = {
        "start_date": raw.get("start_date"),
        "end_date": raw.get("end_date") or raw.get("start_date"),
        "start_time": _v3_time(raw.get("start_anchor_type"), raw.get("start_time")),
        "end_time": _v3_time(raw.get("end_anchor_type"), raw.get("end_time")),
        "frequency": freq,
        "enabled": bool(raw.get("enabled", True)),
    }
    for key in ("start_offset_minutes", "end_offset_minutes"):
        if raw.get(key):
            form[key] = raw[key]
    if rule.get("INTERVAL", "").isdigit():
        form["interval"] = int(rule["INTERVAL"])
    for key, field in (("BYMONTH", "by_month"), ("BYMONTHDAY", "by_month_day"), ("BYSETPOS", "by_set_pos")):
        try:
            form[field] = int(rule[key])
        except (KeyError, ValueError):
            pass
    if rule.get("BYDAY"):
        form["by_day"] = rule["BYDAY"]
    until = _until_date(rule.get("UNTIL"), local_date)
    if until:
        form["repeat_until"] = until
    return form


def _legacy_form(raw: dict[str, Any], local_date: _LocalDate) -> dict[str, Any]:
    start, end = raw.get("startDate"), raw.get("endDate")
    form: dict[str, Any] = {
        "start_date": local_date(start) if start else None,
        "end_date": local_date(end) if end else (local_date(start) if start else None),
        "start_time": _legacy_time(raw.get("startTime")),
        "end_time": _legacy_time(raw.get("endTime")),
        "frequency": raw.get("frequency") if raw.get("frequency") in (1, 4) else 1,
        "enabled": True,
    }
    if raw.get("interval"):
        form["interval"] = raw["interval"]
    if raw.get("repeatUntil"):
        form["repeat_until"] = local_date(raw["repeatUntil"])
    for key, field in (("byMonth", "by_month"), ("byMonthDay", "by_month_day"), ("bySetPos", "by_set_pos")):
        if raw.get(key) is not None:
            form[field] = raw[key]
    if raw.get("byDay"):
        form["by_day"] = raw["byDay"]
    return form


def event_form(raw: dict[str, Any] | None, local_date: _LocalDate) -> dict[str, Any] | None:
    """The event as create_event / update_event fields (without name, scene and priority)."""
    if not isinstance(raw, dict):
        return None
    form = _v3_form(raw, local_date) if is_v3_event_list([raw]) else _legacy_form(raw, local_date)
    return form if form.get("start_date") else None


def _device_payload(coord: Any, device_id: str, lookup, ha_device, local_date: _LocalDate) -> dict[str, Any]:
    info = coord.device_infos[device_id]
    v3 = uses_v3_firmware(info)

    entities = {}
    for role, (domain, suffix) in _ENTITY_ROLES.items():
        entity_id = lookup(domain, f"{device_id}_{suffix}" if suffix else device_id)
        if entity_id:
            entities[role] = entity_id

    scenes = [
        {
            "uuid": scene.uuid,
            "name": scene.name,
            "entity_id": lookup("scene", f"{device_id}_scene_{scene.uuid}"),
            "preview": scene.preview,
        }
        for scene in coord.scenes.get(device_id, [])
    ]

    by_uuid = {scene.uuid: scene for scene in coord.scenes.get(device_id, [])}
    playlists = [
        {
            "uuid": playlist.uuid,
            "name": playlist.name,
            "description": playlist.description,
            # A scene that was deleted since keeps its slot with no name, so the card can say so.
            "scenes": [
                {
                    "uuid": uuid,
                    "name": by_uuid[uuid].name if uuid in by_uuid else None,
                    "preview": by_uuid[uuid].preview if uuid in by_uuid else None,
                }
                for uuid in playlist.scene_uuids
            ],
        }
        for playlist in getattr(coord, "playlists", {}).get(device_id, [])
    ]

    events = []
    for ev in info.events:
        raw = ev.raw if isinstance(ev.raw, dict) else {}
        playlist = None
        if raw.get("playlist_uuid"):
            playlist = {
                "uuid": raw["playlist_uuid"],
                "name": coord.playlist_name_for_uuid(device_id, raw["playlist_uuid"]) if hasattr(coord, "playlist_name_for_uuid") else None,
                "seconds": raw.get("playlist_scene_display_duration_seconds") or 30,
                "shuffle": bool(raw.get("playlist_randomize")),
                "once": bool(raw.get("playlist_once_per_event")),
            }
        form = event_form(ev.raw, local_date)
        if form:
            form.update(name=ev.name, scene=ev.scene_uuid, priority=ev.priority)
        events.append(
            {
                "uuid": ev.uuid,
                "name": ev.name,
                "scene_uuid": ev.scene_uuid,
                "scene": coord.scene_name_for_uuid(device_id, ev.scene_uuid),
                "playlist": playlist,
                "when": ev.when_text,
                "time": ev.time_text,
                "priority": ev.priority,
                "enabled": ev.enabled,
                "form": form,
            }
        )

    return {
        "device_id": device_id,
        "ha_device_id": ha_device(device_id),
        "name": info.name,
        "v3": v3,
        "entities": entities,
        "scenes": scenes,
        "playlists": playlists,
        "events": events,
    }


def build_card_info(
    coordinators: list[Any],
    lookup: Callable[[str, str], str | None],
    ha_device: Callable[[str], str | None],
    local_date: _LocalDate,
) -> dict[str, Any]:
    """Every controller the card can show.

    lookup(domain, unique_id) -> entity id or None; ha_device(device_id) -> the registry
    device id or None; local_date(epoch) -> 'YYYY-MM-DD' in the server's time zone.
    """
    return {
        "devices": [
            _device_payload(coord, device_id, lookup, ha_device, local_date)
            for coord in coordinators
            for device_id in coord.device_infos
        ]
    }


"""Home Assistant services for Celebright (schedule writing)."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .api import CelebrightError
from .api.playlists import DEFAULT_SECONDS, MAX_SECONDS, MAX_SLEEP_MINUTES, MIN_SECONDS
from .api.base import uses_v3_firmware
from .api.events_v3 import build_rrule, code_to_anchor
from .const import DOMAIN
from .coordinator import CelebrightCoordinator
from .dashboard import build_dashboard

_LOGGER = logging.getLogger(__name__)

SERVICE_CREATE_EVENT = "create_event"
SERVICE_UPDATE_EVENT = "update_event"
SERVICE_DELETE_EVENT = "delete_event"
SERVICE_SET_EVENT_ENABLED = "set_event_enabled"
SERVICE_REFRESH_SCENES = "refresh_scenes"
SERVICE_GENERATE_DASHBOARD = "generate_dashboard"
SERVICE_PLAY_PLAYLIST = "play_playlist"

# Weekday codes accepted for by_day.
_WEEKDAYS = {"MO", "TU", "WE", "TH", "FR", "SA", "SU"}

# Shared field block for create / update
_EVENT_FIELDS = {
    vol.Optional("device_id"): cv.string,
    vol.Required("name"): cv.string,
    # A scene, or (firmware 3.x) a playlist: exactly one of them.
    vol.Exclusive("scene", "event_content"): cv.string,  # scene name or UUID
    vol.Exclusive("playlist", "event_content"): cv.string,  # playlist name or UUID
    vol.Optional("seconds_per_scene", default=DEFAULT_SECONDS): vol.All(
        vol.Coerce(int), vol.Range(min=MIN_SECONDS, max=MAX_SECONDS)
    ),
    vol.Optional("shuffle", default=False): cv.boolean,
    vol.Optional("play_once", default=False): cv.boolean,
    vol.Required("start_date"): cv.string,  # "YYYY-MM-DD" or epoch int (as str)
    vol.Required("end_date"): cv.string,
    vol.Required("start_time"): cv.string,  # sunset|sunrise|midnight|HH:MM
    vol.Required("end_time"): cv.string,
    vol.Optional("priority", default=3): vol.All(vol.Coerce(int), vol.Range(min=1, max=4)),
    # The GUI select submits "0"/"1"/"4" as strings; Coerce accepts those and YAML ints.
    # 0 = once (v3 only), 1 = daily (until repeat_until, or forever), 4 = yearly.
    # No default: omitted = once (or daily until repeat_until) on v3, daily on older firmware.
    vol.Optional("frequency"): vol.All(vol.Coerce(int), vol.In([0, 1, 4])),
    vol.Optional("interval", default=1): cv.positive_int,
    vol.Optional("repeat_until"): cv.string,
    vol.Optional("by_day"): cv.string,
    vol.Optional("by_month"): vol.All(vol.Coerce(int), vol.Range(min=1, max=12)),
    vol.Optional("by_month_day"): vol.All(vol.Coerce(int), vol.Range(min=1, max=31)),
    vol.Optional("by_set_pos"): vol.All(vol.Coerce(int), vol.Range(min=-1, max=5)),
    # v3 controllers only (ignored on older firmware):
    vol.Optional("start_offset_minutes"): vol.All(vol.Coerce(int), vol.Range(min=-720, max=720)),
    vol.Optional("end_offset_minutes"): vol.All(vol.Coerce(int), vol.Range(min=-720, max=720)),
    vol.Optional("enabled"): cv.boolean,
}

CREATE_EVENT_SCHEMA = vol.Schema(_EVENT_FIELDS)

# Update requires identifying the existing event (by uuid, or by current name)
UPDATE_EVENT_SCHEMA = vol.Schema(
    {
        **_EVENT_FIELDS,
        vol.Exclusive("event_uuid", "event_id"): cv.string,
        vol.Exclusive("event_name", "event_id"): cv.string,
    }
)

GENERATE_DASHBOARD_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
        vol.Optional("filename", default="celebright_dashboard.yaml"): vol.All(
            cv.string, vol.Match(r"^[A-Za-z0-9_.-]+\.ya?ml$")
        ),
    }
)

PLAY_PLAYLIST_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
        vol.Required("playlist"): cv.string,   # playlist name or UUID
        vol.Optional("seconds_per_scene", default=DEFAULT_SECONDS): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_SECONDS, max=MAX_SECONDS)
        ),
        vol.Optional("shuffle", default=False): cv.boolean,
        vol.Optional("sleep_timer_minutes"): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_SLEEP_MINUTES)),
    }
)

SET_EVENT_ENABLED_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
        vol.Exclusive("event_uuid", "event_id"): cv.string,
        vol.Exclusive("event_name", "event_id"): cv.string,
        vol.Required("enabled"): cv.boolean,
    }
)

DELETE_EVENT_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): cv.string,
        vol.Exclusive("event_uuid", "event_id"): cv.string,
        vol.Exclusive("event_name", "event_id"): cv.string,
    }
)


def _parse_time(value: str) -> int:
    """sunset → -2, sunrise → -1, midnight → 0, 'HH:MM' → seconds since midnight."""
    v = value.strip().lower()
    if v in ("sunset", "dusk"):
        return -2
    if v in ("sunrise", "dawn"):
        return -1
    if v == "midnight":
        return 0
    if ":" in v:
        try:
            h, m = v.split(":")
            return int(h) * 3600 + int(m) * 60
        except ValueError as err:
            raise ServiceValidationError(f"Invalid time '{value}' (use HH:MM, sunset, sunrise, midnight)") from err
    # Allow raw seconds
    if v.lstrip("-").isdigit():
        return int(v)
    raise ServiceValidationError(f"Invalid time '{value}' (use HH:MM, sunset, sunrise, or midnight)")


def _parse_date(hass: HomeAssistant, value: str) -> int:
    """'YYYY-MM-DD' → epoch at local midnight; or pass through an integer epoch string."""
    v = value.strip()
    if v.isdigit():
        return int(v)
    try:
        d = datetime.strptime(v, "%Y-%m-%d")
    except ValueError as err:
        raise ServiceValidationError(f"Invalid date '{value}' (use YYYY-MM-DD)") from err
    local = dt_util.start_of_local_day(d)
    return int(local.timestamp())


def _find_coordinator(hass: HomeAssistant, device_id: str | None) -> tuple[CelebrightCoordinator, str]:
    """Resolve which coordinator + Celebright device_id to act on."""
    entries = hass.config_entries.async_entries(DOMAIN)
    coordinators: list[CelebrightCoordinator] = [
        e.runtime_data for e in entries if getattr(e, "runtime_data", None)
    ]
    if not coordinators:
        raise ServiceValidationError("No Celebright integration is loaded")

    if device_id:
        for coord in coordinators:
            if device_id in coord.device_infos:
                return coord, device_id
        raise ServiceValidationError(f"Unknown Celebright device_id '{device_id}'")

    # No device specified — only valid if there is exactly one device total
    all_pairs = [(c, d) for c in coordinators for d in c.device_infos]
    if len(all_pairs) == 1:
        return all_pairs[0]
    raise ServiceValidationError(
        "Multiple Celebright devices found; specify 'device_id' "
        f"(one of: {[d for _, d in all_pairs]})"
    )


def _resolve_scene_uuid(coord: CelebrightCoordinator, device_id: str, scene: str) -> str:
    scene_uuid = coord.uuid_for_scene_name(device_id, scene)
    if not scene_uuid and scene in {s.uuid for s in coord.scenes.get(device_id, [])}:
        scene_uuid = scene
    if not scene_uuid:
        names = [s.name for s in coord.scenes.get(device_id, [])]
        raise ServiceValidationError(
            f"Scene '{scene}' not found for device {device_id}. Available: {names}"
        )
    return scene_uuid


def _resolve_playlist_uuid(coord: CelebrightCoordinator, device_id: str, playlist: str) -> str:
    if not uses_v3_firmware(coord.device_infos.get(device_id)):
        raise ServiceValidationError("Playlists need a controller on firmware 3.x.")
    playlist_uuid = coord.playlist_uuid_for(device_id, playlist)
    if not playlist_uuid:
        names = [p.name for p in coord.playlists.get(device_id, [])]
        raise ServiceValidationError(
            f"Playlist '{playlist}' not found for device {device_id}. Available: {names}"
        )
    return playlist_uuid


def _build_event_kwargs(hass: HomeAssistant, coord, device_id: str, data: dict) -> dict:
    by_day = data.get("by_day")
    if by_day and by_day.upper() not in _WEEKDAYS:
        raise ServiceValidationError(f"by_day must be one of {sorted(_WEEKDAYS)}")
    repeat_until = data.get("repeat_until")
    if bool(data.get("scene")) == bool(data.get("playlist")):
        raise ServiceValidationError("Give the event either a scene or a playlist")
    playlist_uuid = _resolve_playlist_uuid(coord, device_id, data["playlist"]) if data.get("playlist") else None
    scene_uuid = None if playlist_uuid else _resolve_scene_uuid(coord, device_id, data["scene"])
    start_date = _parse_date(hass, data["start_date"])
    end_date = _parse_date(hass, data["end_date"])
    start_time = _parse_time(data["start_time"])
    end_time = _parse_time(data["end_time"])
    until = _parse_date(hass, repeat_until) if repeat_until else None
    by_day = by_day.upper() if by_day else None
    freq = data.get("frequency")
    legacy_freq = 1 if freq is None else freq
    v3_freq = (0 if until is None else 1) if freq is None else freq

    start_anchor, start_clock = code_to_anchor(start_time)
    end_anchor, end_clock = code_to_anchor(end_time)
    return {
        "name": data["name"],
        "scene_uuid": scene_uuid or "",
        "start_date": start_date,
        "end_date": end_date,
        "start_time": start_time,
        "end_time": end_time,
        "priority": data["priority"],
        "frequency": legacy_freq,
        "interval": data["interval"],
        "repeat_until": until,
        "by_day": by_day,
        "by_month": data.get("by_month"),
        "by_month_day": data.get("by_month_day"),
        "by_set_pos": data.get("by_set_pos"),
        # The same event in v3 format: local date strings, sunrise/sunset anchors, RRULE.
        "v3_event": {
            "name": data["name"],
            "scene_uuid": scene_uuid,
            "playlist_uuid": playlist_uuid,
            "playlist_seconds": data.get("seconds_per_scene", DEFAULT_SECONDS) if playlist_uuid else None,
            "playlist_shuffle": bool(data.get("shuffle")) if playlist_uuid else False,
            "playlist_once": bool(data.get("play_once")) if playlist_uuid else False,
            "start_date": _epoch_to_local_date(start_date),
            "end_date": _epoch_to_local_date(end_date),
            "start_anchor": start_anchor,
            "start_time": start_clock,
            "end_anchor": end_anchor,
            "end_time": end_clock,
            "priority": data["priority"],
            "start_offset_minutes": data.get("start_offset_minutes"),
            "end_offset_minutes": data.get("end_offset_minutes"),
            "rrule": build_rrule(
                frequency=v3_freq,
                interval=data["interval"],
                by_day=by_day,
                by_month=data.get("by_month"),
                by_month_day=data.get("by_month_day"),
                by_set_pos=data.get("by_set_pos"),
                until_epoch=until,
            ),
            "enabled": data.get("enabled", True),
        },
    }


def _epoch_to_local_date(epoch: int) -> str:
    """Epoch seconds -> 'YYYY-MM-DD' in the HA time zone."""
    return dt_util.as_local(dt_util.utc_from_timestamp(epoch)).strftime("%Y-%m-%d")


def _resolve_event_uuid(coord, device_id: str, data: dict) -> str:
    """Find the target event UUID from an explicit uuid or a current event name."""
    if data.get("event_uuid"):
        return data["event_uuid"]
    name = data.get("event_name")
    if name:
        uuid = coord.event_uuid_for_name(device_id, name)
        if not uuid:
            info = coord.device_infos.get(device_id)
            existing = [e.name for e in info.events] if info else []
            raise ServiceValidationError(
                f"No event named '{name}' on device {device_id}. Existing: {existing}"
            )
        return uuid
    raise ServiceValidationError("Provide either 'event_uuid' or 'event_name'")


def _read_dashboard_template() -> str:
    return Path(__file__).with_name("dashboard.yaml").read_text(encoding="utf-8")


def _write_text(path: str, text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


async def _run(coro):
    """Await a Celebright call, surfacing API errors as clean HA service errors."""
    try:
        return await coro
    except CelebrightError as err:
        raise HomeAssistantError(str(err)) from err


def async_register_services(hass: HomeAssistant) -> None:
    """Register Celebright services. Called once from async_setup, so they exist even while no entry is loaded."""
    if hass.services.has_service(DOMAIN, SERVICE_CREATE_EVENT):
        return

    async def _handle_create_event(call: ServiceCall) -> ServiceResponse:
        coord, device_id = _find_coordinator(hass, call.data.get("device_id"))
        kwargs = _build_event_kwargs(hass, coord, device_id, call.data)
        ack = await _run(coord.async_create_event(device_id, **kwargs))
        return {"created": ack}

    async def _handle_update_event(call: ServiceCall) -> ServiceResponse:
        coord, device_id = _find_coordinator(hass, call.data.get("device_id"))
        event_uuid = _resolve_event_uuid(coord, device_id, call.data)
        data = dict(call.data)
        if "enabled" not in data:
            # Don't silently re-enable an event that is switched off.
            info = coord.device_infos.get(device_id)
            existing = next((e for e in (info.events if info else []) if e.uuid == event_uuid), None)
            data["enabled"] = existing.enabled if existing else True
        kwargs = _build_event_kwargs(hass, coord, device_id, data)
        # Reusing the same uuid turns saveEvent into an in-place update.
        ack = await _run(coord.async_create_event(device_id, event_uuid=event_uuid, **kwargs))
        return {"updated": ack}

    async def _handle_delete_event(call: ServiceCall) -> ServiceResponse:
        coord, device_id = _find_coordinator(hass, call.data.get("device_id"))
        event_uuid = _resolve_event_uuid(coord, device_id, call.data)
        ack = await _run(coord.async_delete_event(device_id, event_uuid))
        return {"deleted": ack}

    async def _handle_set_event_enabled(call: ServiceCall) -> ServiceResponse:
        coord, device_id = _find_coordinator(hass, call.data.get("device_id"))
        event_uuid = _resolve_event_uuid(coord, device_id, call.data)
        ack = await _run(coord.async_set_event_enabled(device_id, event_uuid, call.data["enabled"]))
        return {"event": ack}

    async def _handle_generate_dashboard(call: ServiceCall) -> ServiceResponse:
        coord, device_id = _find_coordinator(hass, call.data.get("device_id"))
        info = coord.device_infos.get(device_id)
        registry = er.async_get(hass)
        template = await hass.async_add_executor_job(_read_dashboard_template)
        text, missing = build_dashboard(
            template,
            info.name if info else device_id,
            device_id,
            lambda domain, unique_id: registry.async_get_entity_id(domain, DOMAIN, unique_id),
            playlists=uses_v3_firmware(info),
        )
        path = hass.config.path(call.data["filename"])
        await hass.async_add_executor_job(_write_text, path, text)
        return {"file": path, "missing_entities": missing, "yaml": text}

    async def _handle_play_playlist(call: ServiceCall) -> None:
        coord, device_id = _find_coordinator(hass, call.data.get("device_id"))
        playlist_uuid = coord.playlist_uuid_for(device_id, call.data["playlist"])
        if not playlist_uuid:
            names = [p.name for p in coord.playlists.get(device_id, [])]
            raise ServiceValidationError(
                f"Playlist '{call.data['playlist']}' not found for device {device_id}. Available: {names}"
            )
        await _run(
            coord.async_play_playlist(
                device_id, playlist_uuid, seconds=call.data["seconds_per_scene"],
                shuffle=call.data["shuffle"], sleep_minutes=call.data.get("sleep_timer_minutes"),
            )
        )

    async def _handle_refresh_scenes(call: ServiceCall) -> None:
        # Refresh every loaded Celebright coordinator (no target needed).
        seen: set[int] = set()
        for entry in hass.config_entries.async_entries(DOMAIN):
            coord = getattr(entry, "runtime_data", None)
            if isinstance(coord, CelebrightCoordinator) and id(coord) not in seen:
                seen.add(id(coord))
                await coord.async_refresh_scenes()

    hass.services.async_register(
        DOMAIN, SERVICE_CREATE_EVENT, _handle_create_event,
        schema=CREATE_EVENT_SCHEMA, supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_EVENT, _handle_update_event,
        schema=UPDATE_EVENT_SCHEMA, supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_EVENT, _handle_delete_event,
        schema=DELETE_EVENT_SCHEMA, supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SET_EVENT_ENABLED, _handle_set_event_enabled,
        schema=SET_EVENT_ENABLED_SCHEMA, supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_PLAY_PLAYLIST, _handle_play_playlist, schema=PLAY_PLAYLIST_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REFRESH_SCENES, _handle_refresh_scenes,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_GENERATE_DASHBOARD, _handle_generate_dashboard,
        schema=GENERATE_DASHBOARD_SCHEMA, supports_response=SupportsResponse.OPTIONAL,
    )


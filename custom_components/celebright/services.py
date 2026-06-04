"""Home Assistant services for Celebright (schedule writing)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import CelebrightCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_CREATE_EVENT = "create_event"
SERVICE_UPDATE_EVENT = "update_event"
SERVICE_DELETE_EVENT = "delete_event"

# Recurrence frequency: 1 = one-time / seasonal range, 4 = yearly (matches the app)
_WEEKDAYS = {"MO", "TU", "WE", "TH", "FR", "SA", "SU"}

# Shared field block for create / update
_EVENT_FIELDS = {
    vol.Optional("device_id"): cv.string,
    vol.Required("name"): cv.string,
    vol.Required("scene"): cv.string,  # scene name or UUID
    vol.Required("start_date"): cv.string,  # "YYYY-MM-DD" or epoch int (as str)
    vol.Required("end_date"): cv.string,
    vol.Required("start_time"): cv.string,  # sunset|sunrise|midnight|HH:MM
    vol.Required("end_time"): cv.string,
    vol.Optional("priority", default=3): vol.All(int, vol.Range(min=1, max=4)),
    vol.Optional("frequency", default=1): vol.In([1, 4]),
    vol.Optional("interval", default=1): cv.positive_int,
    vol.Optional("repeat_until"): cv.string,
    vol.Optional("by_day"): cv.string,
    vol.Optional("by_month"): vol.All(int, vol.Range(min=1, max=12)),
    vol.Optional("by_month_day"): vol.All(int, vol.Range(min=1, max=31)),
    vol.Optional("by_set_pos"): vol.All(int, vol.Range(min=-1, max=5)),
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
            raise HomeAssistantError(f"Invalid time '{value}' (use HH:MM, sunset, sunrise, midnight)") from err
    # Allow raw seconds
    if v.lstrip("-").isdigit():
        return int(v)
    raise HomeAssistantError(f"Invalid time '{value}' (use HH:MM, sunset, sunrise, or midnight)")


def _parse_date(hass: HomeAssistant, value: str) -> int:
    """'YYYY-MM-DD' → epoch at local midnight; or pass through an integer epoch string."""
    v = value.strip()
    if v.isdigit():
        return int(v)
    try:
        d = datetime.strptime(v, "%Y-%m-%d")
    except ValueError as err:
        raise HomeAssistantError(f"Invalid date '{value}' (use YYYY-MM-DD)") from err
    local = dt_util.start_of_local_day(d)
    return int(local.timestamp())


def _find_coordinator(hass: HomeAssistant, device_id: str | None) -> tuple[CelebrightCoordinator, str]:
    """Resolve which coordinator + Celebright device_id to act on."""
    entries = hass.config_entries.async_entries(DOMAIN)
    coordinators: list[CelebrightCoordinator] = [
        e.runtime_data for e in entries if getattr(e, "runtime_data", None)
    ]
    if not coordinators:
        raise HomeAssistantError("No Celebright integration is loaded")

    if device_id:
        for coord in coordinators:
            if device_id in coord.device_infos:
                return coord, device_id
        raise HomeAssistantError(f"Unknown Celebright device_id '{device_id}'")

    # No device specified — only valid if there is exactly one device total
    all_pairs = [(c, d) for c in coordinators for d in c.device_infos]
    if len(all_pairs) == 1:
        return all_pairs[0]
    raise HomeAssistantError(
        "Multiple Celebright devices found; specify 'device_id' "
        f"(one of: {[d for _, d in all_pairs]})"
    )


def _resolve_scene_uuid(coord: CelebrightCoordinator, device_id: str, scene: str) -> str:
    scene_uuid = coord.uuid_for_scene_name(device_id, scene)
    if not scene_uuid and scene in {s.uuid for s in coord.scenes.get(device_id, [])}:
        scene_uuid = scene
    if not scene_uuid:
        names = [s.name for s in coord.scenes.get(device_id, [])]
        raise HomeAssistantError(
            f"Scene '{scene}' not found for device {device_id}. Available: {names}"
        )
    return scene_uuid


def _build_event_kwargs(hass: HomeAssistant, coord, device_id: str, data: dict) -> dict:
    by_day = data.get("by_day")
    if by_day and by_day.upper() not in _WEEKDAYS:
        raise HomeAssistantError(f"by_day must be one of {sorted(_WEEKDAYS)}")
    repeat_until = data.get("repeat_until")
    return {
        "name": data["name"],
        "scene_uuid": _resolve_scene_uuid(coord, device_id, data["scene"]),
        "start_date": _parse_date(hass, data["start_date"]),
        "end_date": _parse_date(hass, data["end_date"]),
        "start_time": _parse_time(data["start_time"]),
        "end_time": _parse_time(data["end_time"]),
        "priority": data["priority"],
        "frequency": data["frequency"],
        "interval": data["interval"],
        "repeat_until": _parse_date(hass, repeat_until) if repeat_until else None,
        "by_day": by_day.upper() if by_day else None,
        "by_month": data.get("by_month"),
        "by_month_day": data.get("by_month_day"),
        "by_set_pos": data.get("by_set_pos"),
    }


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
            raise HomeAssistantError(
                f"No event named '{name}' on device {device_id}. Existing: {existing}"
            )
        return uuid
    raise HomeAssistantError("Provide either 'event_uuid' or 'event_name'")


def async_register_services(hass: HomeAssistant) -> None:
    """Register Celebright services once."""
    if hass.services.has_service(DOMAIN, SERVICE_CREATE_EVENT):
        return

    async def _handle_create_event(call: ServiceCall) -> ServiceResponse:
        coord, device_id = _find_coordinator(hass, call.data.get("device_id"))
        kwargs = _build_event_kwargs(hass, coord, device_id, call.data)
        ack = await coord.async_create_event(device_id, **kwargs)
        return {"created": ack}

    async def _handle_update_event(call: ServiceCall) -> ServiceResponse:
        coord, device_id = _find_coordinator(hass, call.data.get("device_id"))
        event_uuid = _resolve_event_uuid(coord, device_id, call.data)
        kwargs = _build_event_kwargs(hass, coord, device_id, call.data)
        # Reusing the same uuid turns saveEvent into an in-place update.
        ack = await coord.async_create_event(device_id, event_uuid=event_uuid, **kwargs)
        return {"updated": ack}

    async def _handle_delete_event(call: ServiceCall) -> ServiceResponse:
        coord, device_id = _find_coordinator(hass, call.data.get("device_id"))
        event_uuid = _resolve_event_uuid(coord, device_id, call.data)
        ack = await coord.async_delete_event(device_id, event_uuid)
        return {"deleted": ack}

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


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove services when the last entry unloads."""
    if not hass.config_entries.async_entries(DOMAIN):
        for svc in (SERVICE_CREATE_EVENT, SERVICE_UPDATE_EVENT, SERVICE_DELETE_EVENT):
            hass.services.async_remove(DOMAIN, svc)

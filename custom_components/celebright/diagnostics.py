"""Diagnostics: what a bug report needs, without the login or where the lights are."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .api import uses_v3_firmware
from .const import CONF_EMAIL, CONF_PASSWORD
from .coordinator import CelebrightConfigEntry

# The entry's own data. Everything else below is picked field by field, so the raw cloud replies
# (which carry the account's address and coordinates) are never included.
TO_REDACT = {CONF_EMAIL, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: CelebrightConfigEntry
) -> dict[str, Any]:
    """Return the entry, the coordinator's health and each controller, with identifying data left out."""
    coordinator = entry.runtime_data
    devices: dict[str, Any] = {}
    # Controllers are numbered, not named: the device id and name identify the account.
    for number, (device_id, info) in enumerate(coordinator.device_infos.items(), start=1):
        state = (coordinator.data or {}).get(device_id)
        devices[f"controller_{number}"] = {
            "model": info.model_name,
            "firmware": info.firmware,
            "protocol": "v3" if uses_v3_firmware(info) else "v2",
            "hardware_version": info.hw_version,
            "led_count": info.num_leds,
            "string_leds": info.string_leds,
            "rgbw": info.is_rgbw,
            "rgbw_type": info.rgbw_type,
            "color_order": info.color_order,
            "bulb_type": info.bulb_type,
            "time_zone": info.timezone_id,
            "scene_count": len(coordinator.scenes.get(device_id, [])),
            "playlist_count": len(getattr(coordinator, "playlists", {}).get(device_id, [])),
            "events": [
                {
                    "priority": event.priority,
                    "enabled": event.enabled,
                    "when": event.when_text,
                    "time": event.time_text,
                }
                for event in info.events
            ],
            "state": None
            if state is None
            else {
                "available": state.available,
                "on": state.is_on,
                "schedule_enabled": state.schedule_enabled,
                "brightness": state.brightness,
                "color": state.color_hex,
                "active_source": state.active_source,
                "has_active_event": bool(state.active_event_uuid),
                "has_active_scene": bool(state.active_scene_uuid),
                "scene_known": state.scene_known,
                "next_event_start": state.next_event_start,
                "sleep_timer": state.sleep_timer,
            },
        }

    return {
        "entry": {
            "version": entry.version,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds() if coordinator.update_interval else None
            ),
        },
        "controllers": devices,
    }

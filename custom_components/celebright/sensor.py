"""Celebright sensor platform — device info and live status sensors."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import CelebrightConfigEntry, CelebrightCoordinator
from .entity import CelebrightEntity


@dataclass(frozen=True, kw_only=True)
class CelebrightSensorDescription(SensorEntityDescription):
    value_fn: Any = None   # (coordinator, device_id) → native value
    is_static: bool = False  # True = value comes from device_infos, not live state


def _current_display(coord, device_id):
    state = coord.data.get(device_id)
    return state.current_display if state else None


def _active_source(coord, device_id):
    state = coord.data.get(device_id)
    return state.active_source if state else None


def _active_event(coord, device_id):
    """Name of the scheduled event playing now ("None" when the status says none)."""
    state = coord.data.get(device_id)
    if not state or state.active_source is None:
        return None  # no AppSync/v3 status for this device
    if not state.active_event_uuid:
        return "None"
    info = coord.device_infos.get(device_id)
    for ev in (info.events if info else []):
        if ev.uuid == state.active_event_uuid:
            return ev.name
    return state.active_event_uuid


def _next_event_start(coord, device_id):
    state = coord.data.get(device_id)
    return state.next_event_start if state else None


def _firmware(coord, device_id):
    info = coord.device_infos.get(device_id)
    return str(info.firmware) if info and info.firmware else None


def _hw_version(coord, device_id):
    info = coord.device_infos.get(device_id)
    return f"Rev {info.hw_version}" if info and info.hw_version else None


def _led_count(coord, device_id):
    info = coord.device_infos.get(device_id)
    return info.num_leds if info else None


def _model(coord, device_id):
    info = coord.device_infos.get(device_id)
    return info.model_name if info else None


def _bulb_type(coord, device_id):
    info = coord.device_infos.get(device_id)
    return info.bulb_type if info else None


def _color_order(coord, device_id):
    info = coord.device_infos.get(device_id)
    if not info:
        return None
    label = info.color_order or ""
    if info.rgbw_type:
        # "RGBW_TYPE_24V_NatW" → "24V Natural White"
        friendly = (info.rgbw_type
                    .replace("RGBW_TYPE_", "")
                    .replace("_", " ")
                    .replace("NatW", "Natural White"))
        label = f"{label} ({friendly})"
    return label


def _location(coord, device_id):
    info = coord.device_infos.get(device_id)
    if not info or not info.location_city:
        return None
    parts = [info.location_city]
    if info.location_province:
        parts.append(info.location_province)
    return ", ".join(parts)


def _scheduled_event_count(coord, device_id):
    info = coord.device_infos.get(device_id)
    return len(info.events) if info else 0


SENSOR_DESCRIPTIONS: tuple[CelebrightSensorDescription, ...] = (
    # ── Live status ──────────────────────────────────────────────────
    CelebrightSensorDescription(
        key="current_display",
        translation_key="current_display",
        value_fn=_current_display,
    ),
    CelebrightSensorDescription(
        key="active_event",
        translation_key="active_event",
        value_fn=_active_event,
    ),
    CelebrightSensorDescription(
        key="next_event_start",
        translation_key="next_event_start",
        value_fn=_next_event_start,
    ),
    CelebrightSensorDescription(
        key="active_source",
        translation_key="active_source",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_active_source,
    ),
    # ── Static device info ───────────────────────────────────────────
    CelebrightSensorDescription(
        key="model",
        translation_key="model",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_model,
        is_static=True,
    ),
    CelebrightSensorDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_firmware,
        is_static=True,
    ),
    CelebrightSensorDescription(
        key="hw_version",
        translation_key="hw_version",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_hw_version,
        is_static=True,
    ),
    CelebrightSensorDescription(
        key="led_count",
        translation_key="led_count",
        entity_registry_enabled_default=False,
        native_unit_of_measurement="LEDs",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_led_count,
        is_static=True,
    ),
    CelebrightSensorDescription(
        key="bulb_type",
        translation_key="bulb_type",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_bulb_type,
        is_static=True,
    ),
    CelebrightSensorDescription(
        key="color_order",
        translation_key="color_order",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_color_order,
        is_static=True,
    ),
    CelebrightSensorDescription(
        key="location",
        translation_key="location",
        entity_registry_enabled_default=False,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_location,
        is_static=True,
    ),
    # ── Schedule ─────────────────────────────────────────────────────
    CelebrightSensorDescription(
        key="scheduled_events",
        translation_key="scheduled_events",
        native_unit_of_measurement="events",
        value_fn=_scheduled_event_count,
        is_static=True,
    ),
)


# Updates come from the coordinator, so entities never poll on their own.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: CelebrightConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CelebrightCoordinator = entry.runtime_data
    async_add_entities(
        [
            CelebrightSensor(coordinator, device_id, description)
            for device_id in coordinator.data
            for description in SENSOR_DESCRIPTIONS
        ],
        update_before_add=True,
    )


class CelebrightSensor(CelebrightEntity, SensorEntity):
    """One sensor metric for one Celebright device."""

    entity_description: CelebrightSensorDescription

    def __init__(
        self,
        coordinator: CelebrightCoordinator,
        device_id: str,
        description: CelebrightSensorDescription,
    ) -> None:
        super().__init__(coordinator, device_id)
        self.entity_description = description
        self._attr_unique_id = f"{device_id}_{description.key}"

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator, self._device_id)

    @property
    def extra_state_attributes(self) -> dict | None:
        key = self.entity_description.key
        info = self.coordinator.device_infos.get(self._device_id)

        if key == "led_count" and info and info.string_leds:
            return {f"string_{n}": c for n, c in info.string_leds.items()}

        if key == "scheduled_events" and info:
            # Resolve each event's preset UUID to a friendly scene name
            events = [
                {
                    "uuid": ev.uuid,
                    "name": ev.name,
                    "scene": self.coordinator.scene_name_for_uuid(self._device_id, ev.scene_uuid)
                             or self._playlist_label(ev)
                             or "Unknown scene",
                    "when": ev.when_text,
                    "time": ev.time_text,
                    "priority": ev.priority,
                    "enabled": ev.enabled,
                }
                for ev in info.events
            ]
            return {"events": events}

        return None

    def _playlist_label(self, ev) -> str | None:
        playlist_uuid = (ev.raw or {}).get("playlist_uuid") if isinstance(ev.raw, dict) else None
        if not playlist_uuid:
            return None
        name = self.coordinator.playlist_name_for_uuid(self._device_id, playlist_uuid)
        return f"Playlist: {name}" if name else "Playlist"

    @property
    def available(self) -> bool:
        # Static sensors stay available while the device is offline.
        if self.entity_description.is_static:
            return self._device_id in self.coordinator.device_infos
        return super().available

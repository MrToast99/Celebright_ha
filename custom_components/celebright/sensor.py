"""Celebright sensor platform — device info and live status sensors."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import CelebrightCoordinator
from .entity import CelebrightEntity


@dataclass(frozen=True, kw_only=True)
class CelebrightSensorDescription(SensorEntityDescription):
    value_fn: Any = None   # (coordinator, device_id) → native value
    is_static: bool = False  # True = value comes from device_infos, not live state


def _current_display(coord, device_id):
    state = coord.data.get(device_id)
    return state.current_display if state else None


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
        name="Current Display",
        icon="mdi:television-play",
        value_fn=_current_display,
    ),
    # ── Static device info ───────────────────────────────────────────
    CelebrightSensorDescription(
        key="model",
        name="Model",
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_model,
        is_static=True,
    ),
    CelebrightSensorDescription(
        key="firmware",
        name="Firmware",
        icon="mdi:chip",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_firmware,
        is_static=True,
    ),
    CelebrightSensorDescription(
        key="hw_version",
        name="Hardware Version",
        icon="mdi:developer-board",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_hw_version,
        is_static=True,
    ),
    CelebrightSensorDescription(
        key="led_count",
        name="LED Count",
        icon="mdi:led-strip-variant",
        native_unit_of_measurement="LEDs",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_led_count,
        is_static=True,
    ),
    CelebrightSensorDescription(
        key="bulb_type",
        name="Bulb Type",
        icon="mdi:lightbulb-cfl",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_bulb_type,
        is_static=True,
    ),
    CelebrightSensorDescription(
        key="color_order",
        name="Color Order",
        icon="mdi:palette",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_color_order,
        is_static=True,
    ),
    CelebrightSensorDescription(
        key="location",
        name="Location",
        icon="mdi:map-marker",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_location,
        is_static=True,
    ),
    # ── Schedule ─────────────────────────────────────────────────────
    CelebrightSensorDescription(
        key="scheduled_events",
        name="Scheduled Events",
        icon="mdi:calendar-multiple",
        native_unit_of_measurement="events",
        value_fn=_scheduled_event_count,
        is_static=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
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

    # With _attr_has_entity_name = True and device_info set on the base class,
    # returning the plain sensor name here causes HA to display "{device} {name}",
    # e.g. "House Firmware". No need to include the device name manually.
    @property
    def name(self) -> str:
        return self.entity_description.name

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
                             or "Unknown scene",
                    "when": ev.when_text,
                    "time": ev.time_text,
                    "priority": ev.priority,
                }
                for ev in info.events
            ]
            return {"events": events}

        return None

    @property
    def available(self) -> bool:
        # Static sensors (firmware, model, LED count) come from device_infos which
        # are fetched once at setup and never cleared — keep them available even if
        # the device goes temporarily offline.
        if self.entity_description.is_static:
            return self._device_id in self.coordinator.device_infos
        return super().available

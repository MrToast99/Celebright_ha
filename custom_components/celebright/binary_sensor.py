"""Celebright binary sensor platform — schedule status."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import CelebrightCoordinator
from .entity import CelebrightEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CelebrightCoordinator = entry.runtime_data
    async_add_entities(
        [CelebrightScheduleBinarySensor(coordinator, device_id) for device_id in coordinator.data],
        update_before_add=True,
    )


class CelebrightScheduleBinarySensor(CelebrightEntity, BinarySensorEntity):
    """On when the device's built-in lighting schedule is enabled."""

    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: CelebrightCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_schedule_enabled"

    @property
    def name(self) -> str:
        return "Schedule"

    @property
    def is_on(self) -> bool | None:
        state = self._device_state
        if state is None:
            return None
        if state.schedule_enabled is not None:
            return state.schedule_enabled
        # v3 reports no schedule flag: fall back to "has scheduled events".
        info = self.coordinator.device_infos.get(self._device_id)
        return bool(info.events) if info else None

    @property
    def extra_state_attributes(self) -> dict[str, int] | None:
        info = self.coordinator.device_infos.get(self._device_id)
        return {"scheduled_events": len(info.events)} if info else None

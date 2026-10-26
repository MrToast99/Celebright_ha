"""Switch platform: turn the built-in schedule on/off (firmware 2.x only; 3.x has no such command)."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import CelebrightCommandError, CelebrightConnectionError, uses_v3_firmware
from .const import DOMAIN
from .coordinator import CelebrightCoordinator
from .entity import CelebrightEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CelebrightCoordinator = entry.runtime_data
    registry = er.async_get(hass)
    devices = []
    for device_id in coordinator.data:
        if uses_v3_firmware(coordinator.device_infos.get(device_id)):
            # Not supported: drop a switch an earlier version created.
            stale = registry.async_get_entity_id("switch", DOMAIN, f"{device_id}_schedule_switch")
            if stale:
                registry.async_remove(stale)
        else:
            devices.append(device_id)
    async_add_entities(
        [CelebrightScheduleSwitch(coordinator, device_id) for device_id in devices],
        update_before_add=True,
    )


class CelebrightScheduleSwitch(CelebrightEntity, SwitchEntity):
    """On = the on-device schedule runs; off = it is disabled."""

    _attr_icon = "mdi:calendar-check"

    def __init__(self, coordinator: CelebrightCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_schedule_switch"

    @property
    def name(self) -> str:
        return "Schedule Enabled"

    @property
    def is_on(self) -> bool | None:
        state = self._device_state
        # None ("unknown") until the controller has reported — or we have set — it.
        return state.schedule_enabled if state else None

    async def _set(self, enabled: bool) -> None:
        try:
            await self.coordinator.client.async_set_schedule_enabled(self._device_id, enabled)
        except (CelebrightCommandError, CelebrightConnectionError) as err:
            _LOGGER.error(
                "Celebright could not %s the schedule for %s: %s",
                "enable" if enabled else "disable", self._device_id, err,
            )
            return
        self.coordinator.async_refresh_after_command()

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)

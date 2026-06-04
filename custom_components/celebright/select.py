"""Celebright scene selector platform.

Exposes each device's saved scene list as a HA SelectEntity.
Selecting a scene activates it via MQTT loadSavedScene.
Selecting "Off" calls setResumeSchedule (returns to schedule).

Usable in automations:
  service: select.select_option
  target:
    entity_id: select.house_scene
  data:
    option: "<one of your saved scene names>"
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import CelebrightCommandError, CelebrightConnectionError
from .coordinator import CelebrightCoordinator
from .entity import CelebrightEntity

_LOGGER = logging.getLogger(__name__)

_OPTION_OFF = "Off"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CelebrightCoordinator = entry.runtime_data
    async_add_entities(
        [CelebrightSceneSelect(coordinator, device_id) for device_id in coordinator.data],
        update_before_add=True,
    )


class CelebrightSceneSelect(CelebrightEntity, SelectEntity):
    """Scene selector — one per Celebright device."""

    _attr_translation_key = "scene"

    def __init__(self, coordinator: CelebrightCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_scene"

    @property
    def name(self) -> str:
        # With has_entity_name=True and device_info, HA prepends the device name
        # automatically — return only the entity-specific part.
        return "Scene"

    @property
    def options(self) -> list[str]:
        scenes = self.coordinator.scenes.get(self._device_id, [])
        return [_OPTION_OFF] + [s.name for s in scenes]

    @property
    def current_option(self) -> str:
        state = self._device_state
        if not state or not state.is_on:
            return _OPTION_OFF
        name = self.coordinator.scene_name_for_uuid(
            self._device_id, state.active_scene_uuid
        )
        return name if name else _OPTION_OFF

    async def async_select_option(self, option: str) -> None:
        try:
            if option == _OPTION_OFF:
                await self.coordinator.client.async_resume_schedule(self._device_id)
                self.coordinator.set_active_scene(self._device_id, None)
            else:
                uuid = self.coordinator.uuid_for_scene_name(self._device_id, option)
                if not uuid:
                    _LOGGER.error("Scene %r not found for device %s", option, self._device_id)
                    return
                await self.coordinator.client.async_load_scene(self._device_id, uuid)
                self.coordinator.set_active_scene(self._device_id, uuid)
        except (CelebrightCommandError, CelebrightConnectionError) as err:
            _LOGGER.error(
                "Scene select failed for %s → %r: %s", self._device_id, option, err
            )
            return

        await self.coordinator.async_request_refresh()

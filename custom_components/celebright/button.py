"""Celebright button platform — manual refresh of scenes/schedule."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
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
        [CelebrightRefreshButton(coordinator, device_id) for device_id in coordinator.data],
        update_before_add=False,
    )


class CelebrightRefreshButton(CelebrightEntity, ButtonEntity):
    """Pulls the latest scene list (and schedule) from the Celebright account."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = ButtonEntityClass.UPDATE
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: CelebrightCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"{device_id}_refresh_scenes"

    @property
    def name(self) -> str:
        return "Refresh Scenes"

    @property
    def available(self) -> bool:
        # Refresh should be usable even if the device is briefly offline.
        return self._device_id in self.coordinator.device_infos

    async def async_press(self) -> None:
        await self.coordinator.async_refresh_scenes()

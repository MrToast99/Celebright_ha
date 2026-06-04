"""Celebright integration for Home Assistant."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import CelebrightCoordinator
from .services import async_register_services, async_unregister_services

PLATFORMS = [Platform.BINARY_SENSOR, Platform.LIGHT, Platform.SELECT, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = CelebrightCoordinator(hass, dict(entry.data))
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(coordinator.async_shutdown)

    async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    # If this is the last Celebright entry, tear down the shared services.
    if len(hass.config_entries.async_entries(DOMAIN)) <= 1:
        async_unregister_services(hass)
    return unloaded

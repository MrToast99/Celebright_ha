"""Celebright integration for Home Assistant."""
from __future__ import annotations

import asyncio
import importlib

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .api import CelebrightAuthError, CelebrightConnectionError, CelebrightLoginError
from .const import DOMAIN
from .coordinator import CelebrightCoordinator
from .services import async_register_services, async_unregister_services

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.SCENE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = CelebrightCoordinator(hass, dict(entry.data))
    try:
        await coordinator.async_setup()
        await coordinator.async_config_entry_first_refresh()

        entry.runtime_data = coordinator

        # Pre-import the platform components in the executor: the first load of one
        # (e.g. "button") does blocking file I/O that HA flags if it runs on the loop.
        await asyncio.gather(
            *(
                hass.async_add_import_executor_job(
                    importlib.import_module, f"homeassistant.components.{platform.value}"
                )
                for platform in PLATFORMS
            )
        )

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except CelebrightLoginError as err:
        await coordinator.async_shutdown()
        # Bad credentials: retrying can't help, so ask for a new password (reauth).
        raise ConfigEntryAuthFailed(f"Celebright login failed: {err}") from err
    except (CelebrightConnectionError, CelebrightAuthError) as err:
        await coordinator.async_shutdown()
        # Transient (network/AWS hiccup, or an API refusal): let HA retry with back-off.
        raise ConfigEntryNotReady(f"Cannot reach Celebright: {err}") from err
    except BaseException:
        # Any other failure after connecting: don't leak the HTTP session.
        await coordinator.async_shutdown()
        raise

    entry.async_on_unload(coordinator.async_shutdown)

    async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    # Last entry: remove the shared services.
    if len(hass.config_entries.async_entries(DOMAIN)) <= 1:
        async_unregister_services(hass)
    return unloaded

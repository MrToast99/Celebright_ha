"""Celebright integration for Home Assistant."""
from __future__ import annotations

import asyncio
import importlib
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import CoreState, Event, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.event import async_track_time_interval

from .api import CelebrightAuthError, CelebrightConnectionError, CelebrightLoginError
from .card import async_register_card, async_serve_card, async_unregister_card
from .const import DOMAIN
from .coordinator import CelebrightCoordinator
from .holiday_manager import get_manager
from .rule_engine import get_engine
from .services import async_register_services, async_unregister_services
from .sidebar import async_follow_entries, async_update_sidebar_panel
from .websocket_api import async_register_websocket

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.SCENE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Once per Home Assistant run: the card's files, websocket command, Lovelace resource and sidebar page."""
    async_register_websocket(hass)
    await async_serve_card(hass)
    # The sidebar page follows the config entries, loaded or not (see sidebar.py).
    async_follow_entries(hass)
    await async_update_sidebar_panel(hass)

    if hass.state == CoreState.running:
        await async_register_card(hass)
    else:
        # Lovelace's resource collection isn't reliably there during early boot.
        async def _on_started(_event: Event) -> None:
            await async_register_card(hass)

        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _on_started)
    return True


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
    # Turning the sidebar option on or off needs no reload, only the sidebar item to follow it.
    entry.async_on_unload(entry.add_update_listener(_options_updated))

    async_register_services(hass)
    _schedule_holiday_sync(hass, entry)
    if hass.state == CoreState.running:
        # A no-op after the first time in a run; it re-adds the card if the last entry was removed.
        await async_register_card(hass)
    await async_update_sidebar_panel(hass)
    return True


def _schedule_holiday_sync(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Keep the holiday events current: once now, then every few hours (rolls a passed window to next year)."""

    async def _sync(_now=None) -> None:
        await get_manager(hass).async_sync_all()

    entry.async_on_unload(async_track_time_interval(hass, _sync, timedelta(hours=6)))
    entry.async_create_background_task(hass, _sync(), f"{DOMAIN} holiday sync")
    # Lighting rules (aurora and the like): watch Home Assistant from now until the last entry goes.
    entry.async_create_background_task(hass, get_engine(hass).async_start(), f"{DOMAIN} rules")


async def _options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await async_update_sidebar_panel(hass)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    # Last entry: remove the shared services. (The card and sidebar page stay: a reload, e.g.
    # after re-authentication, unloads the only entry too, and nothing would put them back.)
    if len(hass.config_entries.async_entries(DOMAIN)) <= 1:
        async_unregister_services(hass)
    # A disabled entry stops asking for the sidebar page; a reloading one still does.
    await async_update_sidebar_panel(hass)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """The entry is being deleted: drop it from the sidebar page, and the card with the last one."""
    await async_update_sidebar_panel(hass, removed_entry_id=entry.entry_id)
    # Older cores still list the entry being removed.
    if not [e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id]:
        get_engine(hass).async_stop()
        await async_unregister_card(hass)

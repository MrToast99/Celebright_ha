"""The optional sidebar page: the Celebright card and automations as a page of their own.

New installs have it on (the option is stored when the entry is created); an entry from an
earlier version has no such option and keeps it off. While at least one entry has it on,
one item is registered in Home Assistant's sidebar.

The item follows the config entries, not whether they are loaded. It stays through a
reload or a cloud outage, because the frontend sends anyone looking at a panel that
disappears back to their default dashboard (a wall tablet left on this page would not come
back by itself). For the same reason, changing the option takes effect on an entry that is
not loaded too.

The page is the <celebright-panel> element defined in the card's own file, loaded from the
same URL as the Lovelace card (see card.py). It asks the integration for its data itself,
so the panel needs no configuration.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

from homeassistant.components import frontend, panel_custom
from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntry,
    ConfigEntryChange,
    ConfigEntryState,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .card import async_serve_card
from .const import CONF_SHOW_SIDEBAR, DOMAIN

# The page's address (/celebright). Dashboards must have a hyphen in theirs, so a
# user-made dashboard cannot already be using this one.
SIDEBAR_URL_PATH = "celebright"
SIDEBAR_ELEMENT = "celebright-panel"
SIDEBAR_ICON = "mdi:string-lights"
SIDEBAR_TITLE = "Celebright"

_LOGGER = logging.getLogger(__name__)

_STATE_KEY = "_sidebar"  # the module URL registered right now, or absent
_LOCK_KEY = "_sidebar_lock"

# An entry in one of these states brings the item up to date itself: setup and unload end
# with an update.
_UPDATES_ITSELF = (
    ConfigEntryState.LOADED,
    ConfigEntryState.SETUP_IN_PROGRESS,
    ConfigEntryState.UNLOAD_IN_PROGRESS,
)


def _safe_area_arguments() -> dict[str, bool]:
    """Tell newer frontends that the page keeps clear of the phone's notch itself."""
    parameters = inspect.signature(panel_custom.async_register_panel).parameters
    return {"handle_safe_area": True} if "handle_safe_area" in parameters else {}


def sidebar_enabled(entry: ConfigEntry) -> bool:
    """Whether this entry asks for the sidebar page (off unless the option was stored)."""
    return bool(entry.options.get(CONF_SHOW_SIDEBAR, False))


def _wanting_entries(hass: HomeAssistant, removed_entry_id: str | None) -> list[ConfigEntry]:
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.entry_id != removed_entry_id and not entry.disabled_by and sidebar_enabled(entry)
    ]


@callback
def async_follow_entries(hass: HomeAssistant) -> CALLBACK_TYPE:
    """Update the item when an entry that is not loaded changes.

    An entry whose setup is being retried, or that waits to be signed in again, has nothing
    running that would notice its option change.
    """

    @callback
    def _changed(change: ConfigEntryChange, entry: ConfigEntry) -> None:
        if (
            change is ConfigEntryChange.UPDATED
            and entry.domain == DOMAIN
            and entry.state not in _UPDATES_ITSELF
            and not hass.is_stopping
        ):
            # Not eagerly: this runs inside Home Assistant's own bookkeeping of the entry.
            hass.async_create_task(
                async_update_sidebar_panel(hass), "celebright sidebar update", eager_start=False
            )

    return async_dispatcher_connect(hass, SIGNAL_CONFIG_ENTRY_CHANGED, _changed)


async def async_update_sidebar_panel(
    hass: HomeAssistant, *, removed_entry_id: str | None = None
) -> None:
    """Add, refresh or remove the sidebar item so it matches the config entries.

    removed_entry_id names an entry that is being deleted: newer cores take it off their
    list first, older ones still list it then. Never raises: a problem here must not stop
    a config entry from loading.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    lock = domain_data.setdefault(_LOCK_KEY, asyncio.Lock())
    async with lock:
        try:
            await _async_update(hass, domain_data, removed_entry_id)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to update the Celebright sidebar page")


async def _async_update(
    hass: HomeAssistant, domain_data: dict[str, Any], removed_entry_id: str | None
) -> None:
    registered = domain_data.get(_STATE_KEY)

    if not _wanting_entries(hass, removed_entry_id):
        if registered is not None:
            frontend.async_remove_panel(hass, SIDEBAR_URL_PATH)
            domain_data.pop(_STATE_KEY, None)
            _LOGGER.debug("Removed the Celebright sidebar page")
        return

    module_url = await async_serve_card(hass)
    if module_url is None or module_url == registered:
        return

    # Replace in one go, so a browser asking in between never sees the item missing.
    if registered is not None:
        frontend.async_remove_panel(hass, SIDEBAR_URL_PATH)
        domain_data.pop(_STATE_KEY, None)
    try:
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=SIDEBAR_URL_PATH,
            webcomponent_name=SIDEBAR_ELEMENT,
            sidebar_title=SIDEBAR_TITLE,
            sidebar_icon=SIDEBAR_ICON,
            module_url=module_url,
            embed_iframe=False,
            require_admin=False,
            **_safe_area_arguments(),
        )
    except ValueError:
        _LOGGER.warning(
            "Could not add the Celebright sidebar page: another panel already uses /%s",
            SIDEBAR_URL_PATH,
        )
        return
    domain_data[_STATE_KEY] = module_url
    _LOGGER.debug("Celebright sidebar page registered")

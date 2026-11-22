"""Serves the Celebright card (www/celebright-card.js) and registers it as a Lovelace resource.

The file is served from this integration's own folder, so nothing has to be copied into
config/www. It is registered as a proper Lovelace resource where that's possible (storage mode), since
frontend.add_extra_js_url() injects a bare import() that can resolve after Lovelace has already
marked the card's type as unknown. YAML-mode dashboards can't have resources written, so the
card falls back to add_extra_js_url() there.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url, remove_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

try:  # Home Assistant 2025.2+
    from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE
except ImportError:  # older cores keep Lovelace in hass.data["lovelace"]
    LOVELACE_DATA, MODE_STORAGE = "lovelace", "storage"

from .const import DOMAIN

FRONTEND_URL_PATH = "/celebright_static"
CARD_FILENAME = "celebright-card.js"
CARD_URL = f"{FRONTEND_URL_PATH}/{CARD_FILENAME}"

_LOGGER = logging.getLogger(__name__)

_URL_KEY = "_card_url"
_LOCK_KEY = "_card_lock"
_REGISTERED_KEY = "_frontend_registered"
_EXTRA_KEY = "_card_extra_url"


def _version_tag(www_dir: Path) -> str:
    """Release number plus a hash of the card, so a changed file is always re-fetched."""
    try:
        version = json.loads((Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        version = "0"
    try:
        digest = hashlib.sha256((www_dir / CARD_FILENAME).read_bytes()).hexdigest()[:10]
    except OSError:
        return version
    return f"{version}-{digest}"


async def async_serve_card(hass: HomeAssistant) -> str | None:
    """Serve the www/ folder; return the versioned URL to load the card from (None if missing).

    Safe to call repeatedly: the folder is registered and the file hashed once per run.
    """
    data = hass.data.setdefault(DOMAIN, {})
    lock = data.setdefault(_LOCK_KEY, asyncio.Lock())
    async with lock:
        if _URL_KEY in data:
            return data[_URL_KEY]

        www_dir = Path(__file__).parent / "www"
        if not await hass.async_add_executor_job(www_dir.is_dir):
            _LOGGER.warning("Celebright card folder not found at %s; the card won't load", www_dir)
            data[_URL_KEY] = None
            return None

        try:
            await hass.http.async_register_static_paths(
                [StaticPathConfig(FRONTEND_URL_PATH, str(www_dir), True)]
            )
        except RuntimeError:
            _LOGGER.debug("Static path %s is already registered", FRONTEND_URL_PATH)

        tag = await hass.async_add_executor_job(_version_tag, www_dir)
        data[_URL_KEY] = f"{CARD_URL}?v={tag}"
        return data[_URL_KEY]


def _storage_resources(hass: HomeAssistant):
    """The Lovelace resource collection, or None (YAML-mode dashboards, or not loaded yet)."""
    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None:
        return None
    mode = getattr(lovelace, "resource_mode", getattr(lovelace, "mode", None))
    return lovelace.resources if mode == MODE_STORAGE else None


async def _load(resources) -> None:
    # Lovelace loads the collection lazily. Read unloaded it looks empty, and adding
    # an item then saves over every resource the user already has.
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True


async def async_register_card(hass: HomeAssistant) -> None:
    """Add (or refresh) the card's Lovelace resource. Runs once per Home Assistant run."""
    data = hass.data.setdefault(DOMAIN, {})
    if data.get(_REGISTERED_KEY):
        return
    data[_REGISTERED_KEY] = True

    url = await async_serve_card(hass)
    if url is None:
        return
    resources = _storage_resources(hass)
    if resources is None:
        # YAML-mode resources can't be edited, so load the card on every page instead.
        _load_on_every_page(hass, url, "Lovelace resources are in YAML mode")
        return

    try:
        await _load(resources)
        ours = [r for r in resources.async_items() if r["url"].split("?", 1)[0] == CARD_URL]
        if not ours:
            await resources.async_create_item({"res_type": "module", "url": url})
            _LOGGER.info("Registered the Celebright card as a Lovelace resource: %s", url)
            return
        # One entry, pointed at this version: browsers load every entry, so a stale or
        # duplicate one would run an old card beside the new one.
        first, *duplicates = ours
        if first["url"] != url:
            await resources.async_update_item(first["id"], {"url": url})
            _LOGGER.info("Updated the Celebright card resource to %s", url)
        for duplicate in duplicates:
            await resources.async_delete_item(duplicate["id"])
    except Exception:  # noqa: BLE001 - the integration works without its card
        _LOGGER.exception("Could not register the Celebright card as a Lovelace resource")
        _load_on_every_page(hass, url, "the Lovelace resource could not be written")


def _load_on_every_page(hass: HomeAssistant, url: str, reason: str) -> None:
    """Fallback: have the frontend import the card on every page (no dashboard resource needed)."""
    try:
        add_extra_js_url(hass, url)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Could not load the Celebright card; add %s as a module resource by hand", CARD_URL)
        return
    hass.data.setdefault(DOMAIN, {})[_EXTRA_KEY] = url
    _LOGGER.info("The Celebright card is loaded on every page (%s): %s", reason, url)


async def async_unregister_card(hass: HomeAssistant) -> None:
    """Remove the resource when the last entry goes: nothing serves the file after a restart."""
    data = hass.data.get(DOMAIN, {})
    data.pop(_REGISTERED_KEY, None)
    if extra := data.pop(_EXTRA_KEY, None):
        try:
            remove_extra_js_url(hass, extra)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Could not remove the Celebright card's extra module URL", exc_info=True)
    resources = _storage_resources(hass)
    if resources is None:
        return
    try:
        await _load(resources)
        for resource in list(resources.async_items()):
            if resource["url"].split("?", 1)[0] == CARD_URL:
                await resources.async_delete_item(resource["id"])
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Could not remove the Celebright card's Lovelace resource")

"""DataUpdateCoordinator — polls Celebright device statuses and scene lists."""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CelebrightCloudAPI, CelebrightConnectionError, DeviceInfo, DeviceState, SceneInfo
from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN, SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)

# Scenes/schedule change rarely — auto-refresh them at most this often (seconds).
SCENE_REFRESH_INTERVAL = 1800  # 30 minutes


class CelebrightCoordinator(DataUpdateCoordinator[dict[str, DeviceState]]):
    """Polls device statuses; device info and scene lists are fetched once at setup."""

    def __init__(self, hass: HomeAssistant, entry_data: dict[str, Any]) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.client = CelebrightCloudAPI(
            email=entry_data[CONF_EMAIL],
            password=entry_data[CONF_PASSWORD],
        )
        # Public, stable device metadata — keyed by device_id
        self.device_infos: dict[str, DeviceInfo] = {}
        # Saved scene lists — keyed by device_id
        self.scenes: dict[str, list[SceneInfo]] = {}
        # Optimistic active-scene tracking — device_id → scene_uuid | None
        self._active_scenes: dict[str, str | None] = {}
        # When scenes/device-info were last pulled (monotonic seconds)
        self._last_scene_refresh: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        await self.client.async_connect()
        # Copy device infos to a public attribute so all entities can read them
        # without reaching into the client's private state.
        self.device_infos = dict(self.client._device_infos)
        for device_id in self.device_infos:
            await self._fetch_scenes(device_id)
        self._last_scene_refresh = time.monotonic()

    async def async_shutdown(self) -> None:
        await self.client.async_disconnect()

    # ------------------------------------------------------------------
    # Poll
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, DeviceState]:
        try:
            statuses = await self.client.async_get_device_statuses()
        except CelebrightConnectionError as err:
            raise UpdateFailed(f"Celebright unreachable: {err}") from err

        for device_id, state in statuses.items():
            if not state.is_on:
                self._active_scenes[device_id] = None
            elif device_id in self._active_scenes:
                state.active_scene_uuid = self._active_scenes[device_id]

        # Periodically pick up scene/schedule changes made in the Celebright app.
        if time.monotonic() - self._last_scene_refresh >= SCENE_REFRESH_INTERVAL:
            await self._refresh_all(notify=False)

        return statuses

    # ------------------------------------------------------------------
    # Scene helpers
    # ------------------------------------------------------------------

    async def _fetch_scenes(self, device_id: str) -> None:
        try:
            self.scenes[device_id] = await self.client.async_get_scenes(device_id)
            _LOGGER.debug("Loaded %d scenes for %s", len(self.scenes[device_id]), device_id)
        except Exception as err:
            _LOGGER.warning("Could not load scenes for %s: %s", device_id, err)
            self.scenes.setdefault(device_id, [])

    def scene_name_for_uuid(self, device_id: str, uuid: str | None) -> str | None:
        if not uuid:
            return None
        for scene in self.scenes.get(device_id, []):
            if scene.uuid == uuid:
                return scene.name
        return None

    def uuid_for_scene_name(self, device_id: str, name: str) -> str | None:
        for scene in self.scenes.get(device_id, []):
            if scene.name == name:
                return scene.uuid
        return None

    def set_active_scene(self, device_id: str, scene_uuid: str | None) -> None:
        self._active_scenes[device_id] = scene_uuid

    # ------------------------------------------------------------------
    # Refresh (scenes + device info/schedule)
    # ------------------------------------------------------------------

    async def async_refresh_scenes(self) -> None:
        """Manually re-pull scene lists (and device info/schedule) from the account."""
        await self._refresh_all(notify=True)

    async def _refresh_all(self, notify: bool) -> None:
        """Re-fetch device infos and scene lists for all devices."""
        try:
            self.device_infos = dict(await self.client.async_get_device_infos())
            for device_id in self.device_infos:
                await self._fetch_scenes(device_id)
            self._last_scene_refresh = time.monotonic()
            _LOGGER.debug("Refreshed scenes/device info for %d device(s)", len(self.device_infos))
        except Exception as err:  # noqa: BLE001 - refresh is best-effort
            _LOGGER.warning("Scene refresh failed: %s", err)
            # Back off so a failing refresh doesn't hammer the API every poll
            self._last_scene_refresh = time.monotonic()
        if notify:
            self.async_update_listeners()

    # ------------------------------------------------------------------
    # Schedule writes
    # ------------------------------------------------------------------

    async def async_create_event(self, device_id: str, **kwargs: Any) -> dict[str, Any]:
        """Create (or, with event_uuid, update) a schedule event, then refresh."""
        ack = await self.client.async_create_event(device_id, **kwargs)
        await self._refresh_device_infos("create_event")
        return ack

    async def async_delete_event(self, device_id: str, event_uuid: str) -> dict[str, Any]:
        """Delete a schedule event by UUID, then refresh cached device info."""
        ack = await self.client.async_delete_event(device_id, event_uuid)
        await self._refresh_device_infos("delete_event")
        return ack

    async def _refresh_device_infos(self, why: str) -> None:
        """Re-fetch device infos so schedule changes appear in entities."""
        try:
            self.device_infos = dict(await self.client.async_get_device_infos())
        except Exception as err:  # noqa: BLE001 - refresh is best-effort
            _LOGGER.debug("Could not refresh device infos after %s: %s", why, err)
        self.async_update_listeners()

    def event_uuid_for_name(self, device_id: str, name: str) -> str | None:
        """Resolve a schedule event UUID by its event name (first match)."""
        info = self.device_infos.get(device_id)
        if not info:
            return None
        for ev in info.events:
            if ev.name == name:
                return ev.uuid
        return None

    def first_device_id(self) -> str | None:
        return next(iter(self.device_infos), None)

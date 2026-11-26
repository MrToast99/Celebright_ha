"""DataUpdateCoordinator — polls Celebright device statuses and scene lists."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    CelebrightAuthError,
    CelebrightCloudAPI,
    CelebrightCommandError,
    CelebrightConnectionError,
    CelebrightLoginError,
    DeviceInfo,
    DeviceState,
    PlaylistInfo,
    SceneInfo,
    uses_v3_firmware,
)
from .const import CONF_EMAIL, CONF_PASSWORD, DOMAIN, SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)

# Scenes/schedule change rarely — auto-refresh them at most this often (seconds).
SCENE_REFRESH_INTERVAL = 1800  # 30 minutes


class CelebrightCoordinator(DataUpdateCoordinator[dict[str, DeviceState]]):
    """Polls device statuses; device info and scenes refresh every 30 minutes or on demand."""

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
        # Scene playlists (firmware 3.x only) — keyed by device_id
        self.playlists: dict[str, list[PlaylistInfo]] = {}
        self._playlist_warned: set[str] = set()
        # Optimistic active-scene tracking — device_id → scene_uuid | None
        self._active_scenes: dict[str, str | None] = {}
        # When scenes/device-info were last pulled (monotonic seconds)
        self._last_scene_refresh: float = 0.0

    # --- Lifecycle ---

    async def async_setup(self) -> None:
        await self.client.async_connect()
        # Public copy, so entities don't reach into the client's private state.
        self.device_infos = dict(self.client._device_infos)
        for device_id in self.device_infos:
            await self._fetch_scenes(device_id)
            await self._fetch_playlists(device_id)
        self._last_scene_refresh = time.monotonic()

    async def async_shutdown(self) -> None:
        await self.client.async_disconnect()

    # --- Poll ---

    async def _async_update_data(self) -> dict[str, DeviceState]:
        try:
            statuses = await self.client.async_get_device_statuses()
        except CelebrightLoginError as err:
            # Cognito rejected the account: start re-authentication instead of failing every poll.
            raise ConfigEntryAuthFailed(f"Celebright login failed: {err}") from err
        except (CelebrightConnectionError, CelebrightAuthError, CelebrightCommandError) as err:
            # Unreachable, a server error, or a refusal with a good login: treat as transient.
            raise UpdateFailed(f"Celebright unreachable: {err}") from err

        for device_id, state in statuses.items():
            if not state.is_on:
                self._active_scenes[device_id] = None
            elif state.active_scene_uuid is not None:
                # The device-reported scene wins; mirror it into the optimistic cache so a poll
                # that can't reach the device falls back to it, not to a stale HA selection.
                self._active_scenes[device_id] = state.active_scene_uuid
            elif state.scene_known:
                # Status says "no saved scene" (e.g. a solid colour): drop any stale selection.
                self._active_scenes[device_id] = None
            elif device_id in self._active_scenes:
                state.active_scene_uuid = self._active_scenes[device_id]

        # Periodically pick up scene/schedule changes made in the Celebright app.
        if time.monotonic() - self._last_scene_refresh >= SCENE_REFRESH_INTERVAL:
            await self._refresh_all(notify=False)

        return statuses

    # --- Scene helpers ---

    async def _fetch_scenes(self, device_id: str) -> None:
        try:
            self.scenes[device_id] = await self.client.async_get_scenes(device_id)
            _LOGGER.debug("Loaded %d scenes for %s", len(self.scenes[device_id]), device_id)
        except Exception as err:
            _LOGGER.warning("Could not load scenes for %s: %s", device_id, err)
            self.scenes.setdefault(device_id, [])

    async def _fetch_playlists(self, device_id: str) -> None:
        """Playlists exist on firmware 3.x only. A failure keeps the last list and is reported once."""
        if not uses_v3_firmware(self.device_infos.get(device_id)):
            self.playlists[device_id] = []
            return
        try:
            self.playlists[device_id] = await self.client.async_get_playlists(device_id)
            _LOGGER.debug("Loaded %d playlists for %s", len(self.playlists[device_id]), device_id)
        except Exception as err:  # noqa: BLE001 - playlists are optional
            level = _LOGGER.debug if device_id in self._playlist_warned else _LOGGER.warning
            self._playlist_warned.add(device_id)
            level("Could not load playlists for %s: %s", device_id, err)
            self.playlists.setdefault(device_id, [])

    def playlist_uuid_for(self, device_id: str, ident: str) -> str | None:
        """A playlist's uuid from its uuid or its name."""
        found = self.playlists.get(device_id, [])
        for playlist in found:
            if playlist.uuid == ident:
                return playlist.uuid
        return next((p.uuid for p in found if p.name == ident), None)

    def playlist_name_for_uuid(self, device_id: str, playlist_uuid: str | None) -> str | None:
        return next((p.name for p in self.playlists.get(device_id, []) if p.uuid == playlist_uuid), None)

    async def async_play_playlist(
        self, device_id: str, playlist_uuid: str, *, seconds: int, shuffle: bool, sleep_minutes: int | None
    ) -> None:
        await self.client.async_load_playlist(device_id, playlist_uuid, seconds, shuffle, sleep_minutes)
        self.set_active_scene(device_id, None)
        self.async_refresh_after_command()

    async def async_save_playlist(
        self, device_id: str, *, name: str, scene_uuids: list[str], description: str | None = None,
        playlist_uuid: str | None = None,
    ) -> PlaylistInfo:
        saved = await self.client.async_save_playlist(
            device_id, name=name, scene_uuids=scene_uuids, description=description, playlist_uuid=playlist_uuid
        )
        await self._fetch_playlists(device_id)
        self.async_update_listeners()
        return saved

    async def async_delete_playlist(self, device_id: str, playlist_uuid: str) -> None:
        await self.client.async_delete_playlist(device_id, playlist_uuid)
        await self._fetch_playlists(device_id)
        self.async_update_listeners()

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

    def async_refresh_after_command(self, delay: float = 1.5) -> None:
        """Poll shortly after a command without blocking (the cloud status lags the controller)."""
        async def _later() -> None:
            await asyncio.sleep(delay)
            await self.async_request_refresh()

        self.hass.async_create_background_task(_later(), name=f"{DOMAIN} refresh after command")

    # --- Refresh (scenes + device info/schedule) ---

    async def async_refresh_scenes(self) -> None:
        """Manually re-pull scene lists (and device info/schedule) from the account."""
        await self._refresh_all(notify=True)

    async def _refresh_all(self, notify: bool) -> None:
        """Re-fetch device infos and scene lists for all devices."""
        try:
            self.device_infos = dict(await self.client.async_get_device_infos())
            for device_id in self.device_infos:
                await self._fetch_scenes(device_id)
                await self._fetch_playlists(device_id)
            self._last_scene_refresh = time.monotonic()
            _LOGGER.debug("Refreshed scenes/device info for %d device(s)", len(self.device_infos))
        except Exception as err:  # noqa: BLE001 - refresh is best-effort
            _LOGGER.warning("Scene refresh failed: %s", err)
            # Back off so a failing refresh doesn't hammer the API every poll
            self._last_scene_refresh = time.monotonic()
        if notify:
            self.async_update_listeners()

    # --- Schedule writes ---

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

    async def async_set_event_enabled(
        self, device_id: str, event_uuid: str, enabled: bool
    ) -> dict[str, Any]:
        """Enable/disable one schedule event, then refresh the cached schedule."""
        ack = await self.client.async_set_event_enabled(device_id, event_uuid, enabled)
        await self._refresh_device_infos("set_event_enabled")
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


# A config entry whose runtime_data is the coordinator (typed, so entry.runtime_data checks out).
CelebrightConfigEntry = ConfigEntry[CelebrightCoordinator]

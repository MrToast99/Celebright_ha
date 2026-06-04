"""Celebright light platform.

Each CLC controller is one HA light entity. Supports:
  - On/off
  - RGB color (maps to MQTT setColor with hex)
  - Brightness (sent as scaled hex channels: brightness * color / 255)
  - Defaults to warm white (FFFFFF) when turned on without a color argument
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import CelebrightCommandError, CelebrightConnectionError
from .coordinator import CelebrightCoordinator
from .entity import CelebrightEntity

_LOGGER = logging.getLogger(__name__)

_DEFAULT_COLOR = "FFFFFF"


def _rgb_brightness_to_hex(rgb: tuple[int, int, int], brightness: int) -> str:
    """Scale RGB by brightness and return 6-char hex."""
    scale = brightness / 255.0
    r = round(rgb[0] * scale)
    g = round(rgb[1] * scale)
    b = round(rgb[2] * scale)
    return f"{r:02X}{g:02X}{b:02X}"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#").upper()
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CelebrightCoordinator = entry.runtime_data
    async_add_entities(
        [CelebrightLight(coordinator, device_id) for device_id in coordinator.data],
        update_before_add=True,
    )


class CelebrightLight(CelebrightEntity, LightEntity):
    """One Celebright CLC controller — on/off + RGB + brightness."""

    _attr_color_mode = ColorMode.RGB
    _attr_supported_color_modes = {ColorMode.RGB}
    _attr_supported_features = LightEntityFeature(0)

    def __init__(self, coordinator: CelebrightCoordinator, device_id: str) -> None:
        super().__init__(coordinator, device_id)
        # Optimistic cache — updated on each turn_on, cleared on turn_off
        self._last_hex: str = _DEFAULT_COLOR

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def is_on(self) -> bool:
        state = self._device_state
        return bool(state and state.is_on)

    @property
    def brightness(self) -> int | None:
        state = self._device_state
        if state and state.brightness is not None:
            return state.brightness
        return None

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        state = self._device_state
        if state and state.color_hex:
            try:
                return _hex_to_rgb(state.color_hex)
            except (ValueError, IndexError):
                pass
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self._device_state
        if not state:
            return {}
        return {
            "current_display": state.current_display,
            "schedule_enabled": state.schedule_enabled,
            "model": state.model_name,
            "num_leds": state.num_leds,
        }

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    async def async_turn_on(self, **kwargs: Any) -> None:
        rgb: tuple[int, int, int] | None = kwargs.get(ATTR_RGB_COLOR)
        brightness: int | None = kwargs.get(ATTR_BRIGHTNESS)

        if rgb and brightness is not None:
            hex_color = _rgb_brightness_to_hex(rgb, brightness)
        elif rgb:
            hex_color = f"{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
        elif brightness is not None:
            # Re-apply brightness to last known color
            try:
                base_rgb = _hex_to_rgb(self._last_hex)
                hex_color = _rgb_brightness_to_hex(base_rgb, brightness)
            except (ValueError, IndexError):
                hex_color = f"{brightness:02X}{brightness:02X}{brightness:02X}"
        else:
            hex_color = self._last_hex

        try:
            await self.coordinator.client.async_set_color(self._device_id, hex_color)
            self._last_hex = hex_color
            # setColor clears any active saved scene
            self.coordinator.set_active_scene(self._device_id, None)
        except (CelebrightCommandError, CelebrightConnectionError) as err:
            _LOGGER.error("Celebright turn_on failed for %s: %s", self._device_id, err)
            return

        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        try:
            await self.coordinator.client.async_resume_schedule(self._device_id)
            self.coordinator.set_active_scene(self._device_id, None)
        except (CelebrightCommandError, CelebrightConnectionError) as err:
            _LOGGER.error("Celebright turn_off failed for %s: %s", self._device_id, err)
            return

        await self.coordinator.async_request_refresh()

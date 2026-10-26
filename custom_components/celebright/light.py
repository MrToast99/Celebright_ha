"""Light platform: one entity per controller (on/off, RGB colour, brightness).

Turning on with no colour uses white, or the last colour and brightness.
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


def _normalize(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    """Scale so the brightest channel is 255 (HA's rgb_color excludes brightness)."""
    peak = max(rgb)
    if not peak:
        return rgb
    return (round(rgb[0] * 255 / peak), round(rgb[1] * 255 / peak), round(rgb[2] * 255 / peak))


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
        # Last colour (always full brightness) and brightness sent, to restore either one.
        self._last_hex: str = _DEFAULT_COLOR
        self._last_brightness: int | None = None

    # --- State ---

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
                # HA reports brightness separately: strip any brightness baked into the colour.
                return _normalize(_hex_to_rgb(state.color_hex))
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
            "active_source": state.active_source,
            "schedule_enabled": state.schedule_enabled,
            "model": state.model_name,
            "num_leds": state.num_leds,
        }

    # --- Commands ---

    async def async_turn_on(self, **kwargs: Any) -> None:
        rgb: tuple[int, int, int] | None = kwargs.get(ATTR_RGB_COLOR)
        brightness: int | None = kwargs.get(ATTR_BRIGHTNESS)
        client = self.coordinator.client

        # The colour to use, always at full brightness.
        if rgb:
            base = _normalize(rgb)
        else:
            try:
                base = self.rgb_color or _normalize(_hex_to_rgb(self._last_hex))
            except (ValueError, IndexError):
                base = _normalize(_hex_to_rgb(_DEFAULT_COLOR))
        base_hex = f"{base[0]:02X}{base[1]:02X}{base[2]:02X}"

        try:
            if rgb is None and brightness is not None and self.is_on:
                # Dim / brighten whatever is showing (a scene stays a scene).
                level = brightness
                await client.async_set_brightness(self._device_id, level, base_hex)
            else:
                level = brightness
                if level is None:
                    # A colour change keeps the current brightness; turn-on restores the last.
                    level = self.brightness if (rgb and self.is_on) else self._last_brightness
                await client.async_set_color(self._device_id, base_hex, level)
                # A solid colour replaces any active saved scene.
                self.coordinator.set_active_scene(self._device_id, None)
        except (CelebrightCommandError, CelebrightConnectionError) as err:
            _LOGGER.error("Celebright turn_on failed for %s: %s", self._device_id, err)
            return

        self._last_hex = base_hex
        if level is not None:
            self._last_brightness = level
        self.coordinator.async_refresh_after_command()

    async def async_turn_off(self, **kwargs: Any) -> None:
        # Lights off. (Select "Off" is the separate "resume the schedule" action.)
        try:
            await self.coordinator.client.async_turn_off(self._device_id)
            self.coordinator.set_active_scene(self._device_id, None)
        except (CelebrightCommandError, CelebrightConnectionError) as err:
            _LOGGER.error("Celebright turn_off failed for %s: %s", self._device_id, err)
            return

        self.coordinator.async_refresh_after_command()

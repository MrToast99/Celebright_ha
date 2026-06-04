"""Abstract base and shared data types for the Celebright API."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EventInfo:
    """One scheduled lighting event from getUserData's `events` array."""
    uuid: str
    name: str
    scene_uuid: str          # devicePresetUuid — resolves to a scene name
    priority: int
    when_text: str           # human-readable recurrence, e.g. "Every December 31"
    time_text: str           # human-readable window, e.g. "Sunset – Sunrise"
    raw: dict[str, Any] | None = None


@dataclass
class DeviceInfo:
    """Static device metadata from getUserData — fetched once at setup."""
    device_id: str
    name: str
    model_name: str
    num_leds: int
    is_rgbw: bool
    color_order: str
    firmware: float | None = None
    bulb_type: str | None = None        # e.g. "SC24-GEN1"
    rgbw_type: str | None = None        # e.g. "RGBW_TYPE_24V_NatW"
    hw_version: int | None = None       # hardware PCB revision
    timezone_id: str | None = None      # e.g. "MT"
    location_city: str | None = None    # e.g. "Springfield"
    location_province: str | None = None
    string_leds: dict[int, int] = None  # {string_number: count} for non-zero strings only
    events: list["EventInfo"] = field(default_factory=list)  # built-in schedule
    raw: dict[str, Any] | None = None


@dataclass
class SceneInfo:
    """One saved scene from getDeviceScenes."""
    uuid: str
    name: str


@dataclass
class DeviceState:
    """Combined state: REST status + optional MQTT systemState."""
    device_id: str
    available: bool          # Status == "Online"
    is_on: bool              # userDisplay != 0
    current_display: str     # scene name or "Off"
    schedule_enabled: bool

    # Populated from MQTT systemState when available
    color_hex: str | None = None          # "RRGGBB" hex string
    brightness: int | None = None         # 0–255
    active_scene_uuid: str | None = None  # UUID if a saved scene is active

    # Merged from DeviceInfo for convenience
    name: str = ""
    model_name: str = ""
    num_leds: int = 0
    is_rgbw: bool = False

    raw: dict[str, Any] | None = None


class CelebrightAPIBase(ABC):

    @abstractmethod
    async def async_connect(self) -> None:
        """Authenticate and prepare the session."""

    @abstractmethod
    async def async_disconnect(self) -> None:
        """Clean up sessions and connections."""

    @abstractmethod
    async def async_get_device_infos(self) -> dict[str, DeviceInfo]:
        """Return static device metadata keyed by device_id."""

    @abstractmethod
    async def async_get_device_statuses(self) -> dict[str, DeviceState]:
        """Return current state for all devices, keyed by device_id."""

    @abstractmethod
    async def async_get_scenes(self, device_id: str) -> list[SceneInfo]:
        """Return the saved scene list for a device."""

    @abstractmethod
    async def async_set_color(self, device_id: str, hex_color: str) -> None:
        """Turn device on with a solid hex color (e.g. 'FF0000')."""

    @abstractmethod
    async def async_load_scene(self, device_id: str, scene_uuid: str) -> None:
        """Activate a saved scene by UUID."""

    @abstractmethod
    async def async_resume_schedule(self, device_id: str) -> None:
        """Return device to its scheduled display (turn off manual override)."""


class CelebrightError(Exception):
    """Base exception."""


class CelebrightConnectionError(CelebrightError):
    """Device or API unreachable."""


class CelebrightAuthError(CelebrightError):
    """Authentication failed."""


class CelebrightCommandError(CelebrightError):
    """Command rejected by device or API."""

"""Scene platform: one scene entity per saved scene, so automations can pick scenes from a list.

Activating one loads the scene on the controller (like picking it in the scene dropdown).
Scenes added or removed in the Celebright app appear or disappear on the next refresh.
They live on a "<device> Scenes" sub-device, so a long list shows on the controller's page only
as one "Connected device" link. Names carry the controller's name (e.g. "House Candy Cane").
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import CelebrightCommandError, CelebrightConnectionError
from .const import DOMAIN
from .coordinator import CelebrightCoordinator
from .entity import CelebrightEntity


def _unique_id(device_id: str, scene_uuid: str) -> str:
    return f"{device_id}_scene_{scene_uuid}"


def _scenes_device_id(device_id: str) -> str:
    return f"{device_id}_scenes"


def _device_name(coordinator: CelebrightCoordinator, device_id: str) -> str:
    info = coordinator.device_infos.get(device_id)
    return info.name if info else device_id


def _register_devices(
    devices: dr.DeviceRegistry, entry: ConfigEntry, coordinator: CelebrightCoordinator, device_id: str
) -> None:
    """Create the controller's device, then the "<device> Scenes" sub-device linked to it."""
    name = _device_name(coordinator, device_id)
    parent = devices.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, device_id)},
        manufacturer="Celebright",
        name=name,
    )
    sub = dict(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, _scenes_device_id(device_id))},
        manufacturer="Celebright",
        model="Saved scenes",
        name=f"{name} Scenes",
    )
    try:
        devices.async_get_or_create(**sub, via_device_id=parent.id)
    except TypeError:  # Home Assistant too old for via_device_id
        devices.async_get_or_create(**sub, via_device=(DOMAIN, device_id))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CelebrightCoordinator = entry.runtime_data
    registry = er.async_get(hass)
    devices = dr.async_get(hass)
    known: dict[str, set[str]] = {}  # device_id -> scene UUIDs that have an entity

    def sync() -> None:
        new: list[CelebrightScene] = []
        for device_id in coordinator.data:
            scenes = coordinator.scenes.get(device_id, [])
            if device_id not in known:
                _register_devices(devices, entry, coordinator, device_id)
            seen = known.setdefault(device_id, set())
            current = {scene.uuid for scene in scenes}
            new.extend(
                CelebrightScene(coordinator, device_id, scene.uuid)
                for scene in scenes
                if scene.uuid not in seen
            )
            seen |= current
            if not current:
                continue  # an empty list is more likely a failed fetch than "no scenes"
            for gone in list(seen - current):
                seen.discard(gone)
                entity_id = registry.async_get_entity_id("scene", DOMAIN, _unique_id(device_id, gone))
                if entity_id:
                    registry.async_remove(entity_id)
        if new:
            async_add_entities(new)

    sync()
    entry.async_on_unload(coordinator.async_add_listener(sync))


class CelebrightScene(CelebrightEntity, Scene):
    """A saved scene on the controller."""

    _attr_icon = "mdi:string-lights"
    _attr_has_entity_name = False

    def __init__(self, coordinator: CelebrightCoordinator, device_id: str, scene_uuid: str) -> None:
        super().__init__(coordinator, device_id)
        self._scene_uuid = scene_uuid
        self._attr_unique_id = _unique_id(device_id, scene_uuid)

    @property
    def _scene_name(self) -> str:
        return self.coordinator.scene_name_for_uuid(self._device_id, self._scene_uuid) or "Scene"

    @property
    def device_info(self) -> DeviceInfo:
        # The link to the controller is set in _register_devices (via_device is deprecated here).
        return DeviceInfo(
            identifiers={(DOMAIN, _scenes_device_id(self._device_id))},
            name=f"{_device_name(self.coordinator, self._device_id)} Scenes",
            manufacturer="Celebright",
            model="Saved scenes",
        )

    @property
    def name(self) -> str:
        return f"{_device_name(self.coordinator, self._device_id)} {self._scene_name}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # The exact scene-dropdown option, for comparing with the scene select's state.
        return {"scene_name": self._scene_name}

    async def async_activate(self, **kwargs: Any) -> None:
        coordinator = self.coordinator
        try:
            await coordinator.client.async_load_scene(self._device_id, self._scene_uuid)
        except (CelebrightCommandError, CelebrightConnectionError) as err:
            raise HomeAssistantError(f"Could not activate {self._scene_name}: {err}") from err
        coordinator.set_active_scene(self._device_id, self._scene_uuid)
        coordinator.async_refresh_after_command()

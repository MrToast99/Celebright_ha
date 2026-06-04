"""Base entity for all Celebright platforms."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DeviceState
from .const import DOMAIN
from .coordinator import CelebrightCoordinator


class CelebrightEntity(CoordinatorEntity[CelebrightCoordinator]):
    """Base class: ties every entity to a HA Device entry and the coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CelebrightCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        # Default unique_id — subclasses override _attr_unique_id after super().__init__()
        self._attr_unique_id = device_id

    # ------------------------------------------------------------------
    # HA Device registration
    # ------------------------------------------------------------------

    @property
    def device_info(self) -> DeviceInfo:
        info = self.coordinator.device_infos.get(self._device_id)
        if not info:
            return DeviceInfo(
                identifiers={(DOMAIN, self._device_id)},
                name=self._device_id,
                manufacturer="Celebright",
            )

        hw = f"Rev {info.hw_version}" if info.hw_version else None
        model_detail = info.model_name
        if info.bulb_type:
            model_detail = f"{info.model_name} ({info.bulb_type})"

        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=info.name,
            manufacturer="Celebright",
            model=model_detail,
            sw_version=str(info.firmware) if info.firmware else None,
            hw_version=hw,
        )

    # ------------------------------------------------------------------
    # Common properties
    # ------------------------------------------------------------------

    @property
    def _device_state(self) -> DeviceState | None:
        return self.coordinator.data.get(self._device_id)

    @property
    def name(self) -> str | None:
        # Primary entities (light) return None so HA uses the device name directly.
        # Sub-entities (sensors, select) override this with their specific name.
        return None

    @property
    def available(self) -> bool:
        state = self._device_state
        return state is not None and state.available and super().available

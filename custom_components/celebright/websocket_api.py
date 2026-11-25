"""Websocket commands the Celebright cards use: controller info, holidays and lighting rules."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .card_data import build_card_info
from .const import DOMAIN
from .coordinator import CelebrightCoordinator
from .holiday_manager import get_manager
from .rule_engine import get_engine
from .rules import PRESETS


def _local_date(epoch: int) -> str:
    return dt_util.as_local(dt_util.utc_from_timestamp(epoch)).strftime("%Y-%m-%d")


@websocket_api.websocket_command({vol.Required("type"): "celebright/card_info"})
@callback
def ws_card_info(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Entities, scenes and schedule events of every loaded controller."""
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    coordinators = []
    registry_ids: dict[str, str] = {}   # Celebright device id -> Home Assistant device id
    for entry in hass.config_entries.async_entries(DOMAIN):
        if not isinstance(getattr(entry, "runtime_data", None), CelebrightCoordinator):
            continue
        coordinators.append(entry.runtime_data)
        # Look devices up per config entry: identifiers are no longer unique across entries,
        # which is why async_get_device is deprecated.
        for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
            for domain, identifier in device.identifiers:
                if domain == DOMAIN:
                    registry_ids.setdefault(identifier, device.id)

    def device_entry_id(device_id: str) -> str | None:
        return registry_ids.get(device_id)

    connection.send_result(
        msg["id"],
        build_card_info(
            coordinators,
            lambda domain, unique_id: entities.async_get_entity_id(domain, DOMAIN, unique_id),
            device_entry_id,
            _local_date,
        ),
    )


@websocket_api.websocket_command({vol.Required("type"): "celebright/holidays"})
@websocket_api.async_response
async def ws_holidays(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Every controller's holidays: settings, the next dates, and whether the event is in place."""
    manager = get_manager(hass)
    await manager.async_load()
    devices = {}
    for entry in hass.config_entries.async_entries(DOMAIN):
        coord = getattr(entry, "runtime_data", None)
        if isinstance(coord, CelebrightCoordinator):
            for device_id in coord.device_infos:
                devices[device_id] = manager.view(device_id)
    connection.send_result(msg["id"], {"devices": devices})


def _admin_write(schema: dict, service=get_manager):
    """A command that changes the controller's lighting: admins only, errors reported to the card."""

    def decorate(handler):
        @websocket_api.require_admin
        @websocket_api.websocket_command(schema)
        @websocket_api.async_response
        async def wrapper(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
            try:
                connection.send_result(msg["id"], await handler(service(hass), msg))
            except HomeAssistantError as err:
                connection.send_error(msg["id"], "failed", str(err))

        return wrapper

    return decorate


@_admin_write({
    vol.Required("type"): "celebright/holiday_set",
    vol.Required("device_id"): str,
    vol.Required("holiday_id"): str,
    vol.Optional("scene"): vol.Any(str, None),
    vol.Required("enabled"): bool,
    vol.Optional("before", default=0): int,
    vol.Optional("after", default=0): int,
})
async def ws_holiday_set(manager, msg: dict):
    return await manager.async_set(
        msg["device_id"], msg["holiday_id"], scene=msg.get("scene"), enabled=msg["enabled"],
        before=msg["before"], after=msg["after"],
    )


@_admin_write({
    vol.Required("type"): "celebright/holiday_custom_save",
    vol.Required("device_id"): str,
    vol.Optional("holiday_id"): str,
    vol.Required("name"): str,
    vol.Required("start"): str,
    vol.Required("end"): str,
})
async def ws_holiday_custom_save(manager, msg: dict):
    holiday_id = await manager.async_save_custom(
        msg["device_id"], holiday_id=msg.get("holiday_id"), name=msg["name"], start=msg["start"], end=msg["end"]
    )
    return {"holiday_id": holiday_id}


@_admin_write({
    vol.Required("type"): "celebright/holiday_custom_remove",
    vol.Required("device_id"): str,
    vol.Required("holiday_id"): str,
})
async def ws_holiday_custom_remove(manager, msg: dict):
    await manager.async_remove_custom(msg["device_id"], msg["holiday_id"])
    return {}


@websocket_api.websocket_command({vol.Required("type"): "celebright/rules"})
@websocket_api.async_response
async def ws_rules(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict) -> None:
    """Every controller's lighting rules with their status, and the presets to start from."""
    engine = get_engine(hass)
    await engine.async_load()
    devices = {}
    for entry in hass.config_entries.async_entries(DOMAIN):
        coord = getattr(entry, "runtime_data", None)
        if isinstance(coord, CelebrightCoordinator):
            for device_id in coord.device_infos:
                devices[device_id] = engine.view(device_id)
    connection.send_result(msg["id"], {"devices": devices, "presets": list(PRESETS)})


@_admin_write({
    vol.Required("type"): "celebright/rule_save",
    vol.Required("device_id"): str,
    vol.Required("rule"): dict,
}, service=get_engine)
async def ws_rule_save(engine, msg: dict):
    return await engine.async_save_rule(msg["device_id"], msg["rule"])


@_admin_write({
    vol.Required("type"): "celebright/rule_delete",
    vol.Required("device_id"): str,
    vol.Required("rule_id"): str,
}, service=get_engine)
async def ws_rule_delete(engine, msg: dict):
    await engine.async_delete_rule(msg["device_id"], msg["rule_id"])
    return {}


@_admin_write({
    vol.Required("type"): "celebright/rule_move",
    vol.Required("device_id"): str,
    vol.Required("rule_id"): str,
    vol.Required("direction"): vol.Any("up", "down"),
}, service=get_engine)
async def ws_rule_move(engine, msg: dict):
    await engine.async_move_rule(msg["device_id"], msg["rule_id"], msg["direction"])
    return {}


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    for command in (ws_card_info, ws_holidays, ws_holiday_set, ws_holiday_custom_save, ws_holiday_custom_remove,
                    ws_rules, ws_rule_save, ws_rule_delete, ws_rule_move):
        websocket_api.async_register_command(hass, command)

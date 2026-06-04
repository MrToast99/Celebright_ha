"""Celebright cloud API — REST polling + AWS IoT MQTT control.

Auth:    Cognito USER_PASSWORD_AUTH → IdToken (REST) + temp AWS creds (MQTT)
State:   POST app-api.celebright.com/getUserDeviceStatuses  (REST, polled)
Control: MQTT PUBLISH via AWS IoT WebSocket (SigV4 signed)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .auth import CelebrightAuth
from .base import (
    CelebrightAPIBase,
    CelebrightAuthError,
    CelebrightCommandError,
    CelebrightConnectionError,
    DeviceInfo,
    DeviceState,
    EventInfo,
    SceneInfo,
)
from .mqtt import CelebrightMQTT, compute_event_md5
from ..const import (
    API_BASE,
    AWS_REGION,
    CURRENT_DISPLAY_FIELD,
    DISPLAY_OFF,
    EP_GET_DEVICE_SCENES,
    EP_GET_DEVICE_STATUSES,
    EP_GET_USER_DATA,
    IOT_ENDPOINT,
    SCHEDULE_ENABLED_FIELD,
    STATE_FIELD,
    STATUS_FIELD,
    STATUS_ONLINE,
)

_LOGGER = logging.getLogger(__name__)

# --- Schedule decoding helpers ------------------------------------------

_MONTHS = ["", "January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]
_WEEKDAYS = {"SU": "Sunday", "MO": "Monday", "TU": "Tuesday", "WE": "Wednesday",
             "TH": "Thursday", "FR": "Friday", "SA": "Saturday"}
_ORDINALS = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", -1: "last"}


def _decode_event_time(code: Any) -> str:
    """Celebright encodes time-of-day as: -1=Sunrise, -2=Sunset, 0=Midnight, n>0=seconds since midnight."""
    if code is None:
        return "?"
    if code == -1:
        return "Sunrise"
    if code == -2:
        return "Sunset"
    if code == 0:
        return "Midnight"
    if code > 0:
        h, m = divmod(code // 60, 60)
        return f"{h:02d}:{m:02d}"
    return str(code)


def _decode_event_when(e: dict[str, Any]) -> str:
    """Produce a human-readable recurrence description for a schedule event."""
    by_month = e.get("byMonth")
    by_month_day = e.get("byMonthDay")
    by_day = e.get("byDay")
    by_set_pos = e.get("bySetPos")

    if by_month and by_month_day:
        return f"Every {_MONTHS[by_month]} {by_month_day}"
    if by_month and by_day and by_set_pos:
        pos = _ORDINALS.get(by_set_pos, str(by_set_pos))
        return f"{pos} {_WEEKDAYS.get(by_day, by_day)} of {_MONTHS[by_month]}"

    # Fall back to a date range using the raw start/end epochs
    from datetime import datetime, timezone
    start = e.get("startDate")
    end = e.get("endDate")
    if start:
        s = datetime.fromtimestamp(start, tz=timezone.utc)
        label = f"{_MONTHS[s.month]} {s.day}"
        if end and end != start:
            en = datetime.fromtimestamp(end, tz=timezone.utc)
            label += f" – {_MONTHS[en.month]} {en.day}"
        if e.get("repeatUntil"):
            label += " (seasonal)"
        return label
    return "Custom"


def _parse_events(raw_events: list[dict[str, Any]]) -> list[EventInfo]:
    events: list[EventInfo] = []
    for e in raw_events:
        start_t = _decode_event_time(e.get("startTime"))
        end_t = _decode_event_time(e.get("endTime"))
        events.append(
            EventInfo(
                uuid=e.get("uuid", ""),
                name=e.get("eventName", "Event"),
                scene_uuid=e.get("devicePresetUuid", ""),
                priority=e.get("priority", 0),
                when_text=_decode_event_when(e),
                time_text=f"{start_t} – {end_t}",
                raw=e,
            )
        )
    # Higher priority first, then by name
    events.sort(key=lambda ev: (-ev.priority, ev.name.lower()))
    return events


def _parse_device_info(device_id: str, raw: dict[str, Any]) -> DeviceInfo:
    # Preserve the original string number for non-zero strings (e.g. {1: 74, 3: 51})
    string_leds = {
        i: raw[key]
        for i, key in enumerate(
            ("string1NumLeds","string2NumLeds","string3NumLeds","string4NumLeds","string5NumLeds"),
            start=1,
        )
        if raw.get(key)
    }

    hw = raw.get("hardware") or {}
    loc = raw.get("location") or {}

    return DeviceInfo(
        device_id=device_id,
        name=raw.get("name", "Celebright Light"),
        model_name=raw.get("modelName", ""),
        num_leds=raw.get("numLeds", 0),
        is_rgbw=raw.get("isRGBW", False),
        color_order=raw.get("colorOrder", "RGBW"),
        firmware=raw.get("firmware"),
        bulb_type=raw.get("bulb_type"),
        rgbw_type=raw.get("RGBW_type"),
        hw_version=hw.get("hwVersion"),
        timezone_id=raw.get("timezoneId"),
        location_city=loc.get("city"),
        location_province=loc.get("state_province"),
        string_leds=string_leds,
        events=_parse_events(raw.get("events") or []),
        raw=raw,
    )


def _parse_device_status(
    device_id: str,
    raw: dict[str, Any],
    info: DeviceInfo | None = None,
) -> DeviceState:
    state = DeviceState(
        device_id=device_id,
        available=raw.get(STATUS_FIELD) == STATUS_ONLINE,
        is_on=raw.get(STATE_FIELD, 0) != 0,
        current_display=raw.get(CURRENT_DISPLAY_FIELD, DISPLAY_OFF),
        schedule_enabled=raw.get(SCHEDULE_ENABLED_FIELD, False),
        raw=raw,
    )
    if info:
        state.name = info.name
        state.model_name = info.model_name
        state.num_leds = info.num_leds
        state.is_rgbw = info.is_rgbw
    return state


def _mqtt_for_device(device_id: str, auth: CelebrightAuth) -> CelebrightMQTT:
    creds = auth.aws_credentials
    return CelebrightMQTT(
        device_id=device_id,
        access_key=creds.access_key_id,
        secret_key=creds.secret_access_key,
        session_token=creds.session_token,
        region=AWS_REGION,
        endpoint=IOT_ENDPOINT,
    )


class CelebrightCloudAPI(CelebrightAPIBase):
    """Full cloud client: Cognito auth + REST polling + IoT MQTT control."""

    def __init__(self, email: str, password: str) -> None:
        self._email = email
        self._password = password
        self._session: aiohttp.ClientSession | None = None
        self._auth: CelebrightAuth | None = None
        self._device_infos: dict[str, DeviceInfo] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_connect(self) -> None:
        self._session = aiohttp.ClientSession()
        self._auth = CelebrightAuth(self._email, self._password, self._session)
        await self._auth.async_authenticate()
        self._device_infos = await self.async_get_device_infos()

    async def async_disconnect(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # Read (REST)
    # ------------------------------------------------------------------

    async def async_get_device_infos(self) -> dict[str, DeviceInfo]:
        data = await self._post(EP_GET_USER_DATA, {"email": self._email})
        devices: dict[str, Any] = data.get("devices", {})
        return {
            dev_id: _parse_device_info(dev_id, dev_raw)
            for dev_id, dev_raw in devices.items()
        }

    async def async_get_scenes(self, device_id: str) -> list[SceneInfo]:
        data = await self._post(EP_GET_DEVICE_SCENES, {"deviceId": device_id})
        return [
            SceneInfo(uuid=s["uuid"], name=s["name"])
            for s in data.get("scenes", [])
            if s.get("uuid") and s.get("name")
        ]

    async def async_get_device_statuses(self) -> dict[str, DeviceState]:
        data = await self._post(EP_GET_DEVICE_STATUSES, {})
        return {
            dev_id: _parse_device_status(
                dev_id, status_raw, self._device_infos.get(dev_id)
            )
            for dev_id, status_raw in data.items()
        }

    # ------------------------------------------------------------------
    # Write (MQTT)
    # ------------------------------------------------------------------

    async def async_load_scene(self, device_id: str, scene_uuid: str) -> None:
        assert self._auth
        await self._auth.async_ensure_valid()
        mqtt = _mqtt_for_device(device_id, self._auth)
        await mqtt.async_load_scene(scene_uuid)

    async def async_set_color(self, device_id: str, hex_color: str) -> None:
        assert self._auth
        await self._auth.async_ensure_valid()
        mqtt = _mqtt_for_device(device_id, self._auth)
        await mqtt.async_set_color(hex_color)

    async def async_resume_schedule(self, device_id: str) -> None:
        assert self._auth
        await self._auth.async_ensure_valid()
        mqtt = _mqtt_for_device(device_id, self._auth)
        await mqtt.async_resume_schedule()

    async def async_create_event(
        self,
        device_id: str,
        *,
        name: str,
        scene_uuid: str,
        start_date: int,
        start_time: int,
        end_date: int,
        end_time: int,
        priority: int = 3,
        frequency: int = 1,
        interval: int = 1,
        repeat_until: int | None = None,
        by_day: str | None = None,
        by_month_day: int | None = None,
        by_month: int | None = None,
        by_set_pos: int | None = None,
        event_uuid: str | None = None,
    ) -> dict[str, Any]:
        """Build and publish a schedule event; returns the device ack.

        Time fields use Celebright codes: -2=Sunset, -1=Sunrise, 0=Midnight,
        or seconds-since-midnight. The md5 is computed to match the app exactly.
        """
        import uuid as _uuid

        assert self._auth
        await self._auth.async_ensure_valid()

        ev_uuid = event_uuid or str(_uuid.uuid4())
        md5 = compute_event_md5(
            uuid=ev_uuid,
            device_preset_uuid=scene_uuid,
            event_name=name,
            priority=priority,
            start_date=start_date,
            start_time=start_time,
            end_date=end_date,
            end_time=end_time,
            frequency=frequency,
            interval=interval,
            repeat_until=repeat_until,
            by_day=by_day,
            by_month_day=by_month_day,
            by_month=by_month,
            by_set_pos=by_set_pos,
        )
        event = {
            "uuid": ev_uuid,
            "md5": md5,
            "event_name": name,
            "savedScene_uuid": scene_uuid,
            "device_preset_uuid": scene_uuid,
            "priority": priority,
            "start_date": start_date,
            "start_time": start_time,
            "end_date": end_date,
            "end_time": end_time,
            "frequency": frequency,
            "interval": interval,
            "repeat_until": repeat_until,
            "byDay": by_day,
            "byMonthDay": by_month_day,
            "byMonth": by_month,
            "bySetPos": by_set_pos,
        }
        mqtt = _mqtt_for_device(device_id, self._auth)
        return await mqtt.async_save_event(event)

    async def async_delete_event(self, device_id: str, event_uuid: str) -> dict[str, Any]:
        """Delete a schedule event by UUID. Returns the device ack."""
        assert self._auth
        await self._auth.async_ensure_valid()
        mqtt = _mqtt_for_device(device_id, self._auth)
        return await mqtt.async_delete_event(event_uuid)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        assert self._auth
        return {
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": self._auth.id_token,
        }

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        assert self._session and self._auth
        await self._auth.async_ensure_valid()
        try:
            async with asyncio.timeout(15):
                resp = await self._session.post(
                    f"{API_BASE}{path}",
                    json=payload,
                    headers=self._auth_headers(),
                )
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise CelebrightConnectionError(str(err)) from err

        if resp.status == 401:
            raise CelebrightAuthError("API returned 401")
        if resp.status >= 400:
            text = await resp.text()
            raise CelebrightCommandError(f"HTTP {resp.status}: {text}")

        return await resp.json(content_type=None)

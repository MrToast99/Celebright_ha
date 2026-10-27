"""Celebright cloud client: Cognito login, REST + AppSync status, MQTT control."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import aiohttp

from . import events_v3
from .appsync import build_status_query, parse_status_response
from .auth import CelebrightAuth
from .base import (
    uses_v3_firmware,
    CelebrightAPIBase,
    CelebrightAuthError,
    CelebrightCommandError,
    CelebrightConnectionError,
    CelebrightError,
    DeviceInfo,
    DeviceState,
    EventInfo,
    SceneInfo,
)
from .mqtt import CelebrightMQTT, compute_event_md5
from ..const import (
    API_BASE,
    APPSYNC_URL,
    AWS_REGION,
    CURRENT_DISPLAY_FIELD,
    DISPLAY_OFF,
    EP_GET_DEVICE_EVENTS,
    EP_GET_DEVICE_SCENES,
    EP_GET_DEVICE_STATUSES,
    EP_GET_USER_DATA,
    IOT_ENDPOINT,
    MQTT_ACTIVE_SCENE_FIELD,
    MQTT_DEFAULT_PROTOCOL,
    MQTT_STATE_BRIGHTNESS_FIELD,
    MQTT_STATE_COLOR_FIELD,
    SCHEDULE_ENABLED_FIELD,
    STATE_FIELD,
    STATUS_FIELD,
    STATUS_ONLINE,
)

_LOGGER = logging.getLogger(__name__)

# After a failed protocol probe, don't re-probe from the 30 s poll for this long.
_PROBE_BACKOFF_SECONDS = 300
# After a failed AppSync status request, use MQTT/REST-only for this long.
_GRAPHQL_BACKOFF_SECONDS = 300
# The AppSync status has no schedule on/off flag; ask the controller this often.
_SCHEDULE_PROBE_SECONDS = 900

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
        # Newer (v3) status payloads dropped this field — unknown, not "off".
        schedule_enabled=raw.get(SCHEDULE_ENABLED_FIELD),
        raw=raw,
    )
    if info:
        state.name = info.name
        state.model_name = info.model_name
        state.num_leds = info.num_leds
        state.is_rgbw = info.is_rgbw
    return state


def _schedule_flag(system_state: dict[str, Any]) -> bool | None:
    """systemState.scheduleEnabled (1/0) -> bool, None when not reported."""
    if "scheduleEnabled" not in system_state:
        return None
    return system_state["scheduleEnabled"] in (1, True, "1", "true", "True")


def _merge_system_state(state: DeviceState, system_state: dict[str, Any]) -> None:
    """Merge a v2 MQTT systemState onto a DeviceState (best effort; unknown keys stay None)."""
    if not system_state:
        return

    if "active_source" in system_state:  # protocol v3
        _merge_system_state_v3(state, system_state)
        return

    state.active_scene_uuid = system_state.get(MQTT_ACTIVE_SCENE_FIELD) or None
    flag = _schedule_flag(system_state)
    if flag is not None:
        state.schedule_enabled = flag

    color = system_state.get(MQTT_STATE_COLOR_FIELD)
    if isinstance(color, str) and len(color) >= 6:
        hex_color = color.lstrip("#").upper()
        state.color_hex = hex_color
        try:
            r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            pass
        else:
            # No separate brightness channel: setColor bakes it into the RGB, so use the peak.
            state.brightness = max(r, g, b)

    brightness = system_state.get(MQTT_STATE_BRIGHTNESS_FIELD)
    if isinstance(brightness, (int, float)):
        state.brightness = int(brightness)


def _merge_system_state_v3(state: DeviceState, system_state: dict[str, Any]) -> None:
    """Merge a v3 systemState: active_source, plus brightness/colour of the first look.

    lookType 1 = solid colour, 2 = pattern (no colour); the scene UUID isn't reported.
    """
    if system_state.get("active_source") is not None:
        state.active_source = system_state["active_source"]
    # Event fields, when the controller reports them (AppSync is the usual source).
    if "activeEvent" in system_state:
        state.active_event_uuid = _as_uuid(system_state["activeEvent"])
    if system_state.get("next_event_start_local"):
        state.next_event_start = system_state["next_event_start_local"]
    flag = _schedule_flag(system_state)
    if flag is not None:
        state.schedule_enabled = flag
    scene = system_state.get("currentScene") or []
    look = (scene[0].get("lookData") or {}) if scene and isinstance(scene[0], dict) else {}

    # v3 brightness is its own 0-255 field on every look (solid colour or pattern).
    bright = look.get("brightness")
    has_brightness = isinstance(bright, (int, float)) and not isinstance(bright, bool)
    if has_brightness:
        state.brightness = max(0, min(255, int(bright)))

    color = look.get("color")
    if not (isinstance(color, str) and len(color) >= 6):
        return
    hex_color = color.lstrip("#").upper()
    try:
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return
    state.color_hex = hex_color
    if not has_brightness:
        # No brightness reported: use the colour's peak channel.
        state.brightness = max(r, g, b)


def _first_graphql_error(body: dict[str, Any]) -> str:
    errors = body.get("errors") or [{}]
    first = errors[0]
    if isinstance(first, dict):
        kind, msg = first.get("errorType"), first.get("message")
        return "AppSync error: " + ": ".join(str(x) for x in (kind, msg) if x)
    return f"AppSync error: {first}"


def _graphql_unauthorized(body: dict[str, Any]) -> bool:
    for err in body.get("errors") or []:
        text = f"{err.get('errorType', '')} {err.get('message', '')}" if isinstance(err, dict) else str(err)
        if "unauthorized" in text.lower() or "not authorized" in text.lower():
            return True
    return False


def _as_uuid(value: Any) -> str | None:
    """activeSavedScene / activeEvent: a uuid string (or an object carrying one)."""
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        return value.get("uuid") or value.get("id") or None
    return None


def _merge_graphql_status(state: DeviceState, item: dict[str, Any]) -> None:
    """Merge one AppSync getDeviceStatusV3 item onto a DeviceState."""
    state.active_source = item.get("activeSource")
    state.active_scene_uuid = _as_uuid(item.get("activeSavedScene"))
    state.active_event_uuid = _as_uuid(item.get("activeEvent"))
    state.next_event_start = item.get("nextEventStartLocal")
    state.sleep_timer = item.get("sleepTimer")
    state.scene_known = True  # AppSync reports "no scene" explicitly (null)

    scene = item.get("currentScene")
    if isinstance(scene, str):  # JSON-encoded string, e.g. "[]"
        try:
            scene = json.loads(scene)
        except ValueError:
            scene = []
    _merge_system_state_v3(state, {"currentScene": scene if isinstance(scene, list) else []})


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
        # Per-device MQTT topic protocol ("v3"/"v2"), detected on first use.
        self._protocols: dict[str, str] = {}
        self._probe_retry_at: dict[str, float] = {}
        self._graphql_retry_at = 0.0
        self._graphql_failed_before = False
        self._graphql_ok_logged = False
        self._graphql_token_kind = "access"  # which token AppSync accepted
        # Last known schedule on/off per device (reported, or set by us)
        self._schedule_enabled: dict[str, bool] = {}
        self._schedule_probe_at: dict[str, float] = {}

    # --- Lifecycle ---

    async def async_connect(self) -> None:
        self._session = aiohttp.ClientSession()
        self._auth = CelebrightAuth(self._email, self._password, self._session)
        try:
            await self._auth.async_authenticate()
            self._device_infos = await self.async_get_device_infos()
        except BaseException:
            # Setup failed: nothing else will close this session.
            await self.async_disconnect()
            raise

    async def async_disconnect(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    # --- Read (REST) ---

    async def async_get_device_infos(self) -> dict[str, DeviceInfo]:
        data = await self._post(EP_GET_USER_DATA, {"email": self._email})
        devices: dict[str, Any] = data.get("devices", {})
        # Statuses merge name/model/etc. from this cache, so refresh it on every call.
        self._device_infos = {
            dev_id: _parse_device_info(dev_id, dev_raw)
            for dev_id, dev_raw in devices.items()
        }
        # v3 controllers keep richer events (anchors, offsets, RRULE, enabled) than getUserData.
        for dev_id, info in self._device_infos.items():
            v3_events = await self._get_v3_events(dev_id, info)
            if v3_events is not None:
                info.events = v3_events
        return self._device_infos

    async def _get_events_raw(self, device_id: str) -> list[dict[str, Any]] | None:
        """The device's events from getDeviceEvents (None if unavailable)."""
        try:
            data = await self._post(EP_GET_DEVICE_EVENTS, {"deviceId": device_id})
        except CelebrightError as err:
            _LOGGER.debug("getDeviceEvents failed for %s: %s", device_id, err)
            return None
        events = data.get("events") if isinstance(data, dict) else None
        return events if isinstance(events, list) else None

    async def _get_v3_events(self, device_id: str, info: DeviceInfo):
        raw = await self._get_events_raw(device_id)
        if raw is None:
            return None
        if not raw:
            # Empty counts only if the legacy list is empty too (older accounts may return nothing).
            return [] if not info.events else None
        if not events_v3.is_v3_event_list(raw):
            return None
        return events_v3.parse_events(raw)

    async def _wait_for_event(self, device_id: str, event_uuid: str, matches, attempts: int = 5, delay: float = 2.0) -> bool:
        """Poll until matches(event_or_None, is_last_try) holds; writes reach the cloud shortly after the command."""
        for attempt in range(attempts):
            raw = await self._get_events_raw(device_id)
            if raw is not None:
                found = next((e for e in raw if isinstance(e, dict) and e.get("uuid") == event_uuid), None)
                if matches(found, attempt == attempts - 1):
                    return True
            if attempt < attempts - 1:
                await asyncio.sleep(delay)
        return False

    async def async_get_scenes(self, device_id: str) -> list[SceneInfo]:
        data = await self._post(EP_GET_DEVICE_SCENES, {"deviceId": device_id})
        return [
            SceneInfo(uuid=s["uuid"], name=s["name"])
            for s in data.get("scenes", [])
            if s.get("uuid") and s.get("name")
        ]

    async def async_get_device_statuses(self) -> dict[str, DeviceState]:
        data = await self._post(EP_GET_DEVICE_STATUSES, {})
        statuses = {
            dev_id: _parse_device_status(
                dev_id, status_raw, self._device_infos.get(dev_id)
            )
            for dev_id, status_raw in data.items()
        }

        # Preferred source for colour, scene and event: the app's AppSync status (one call for all devices).
        graphql = await self._graphql_statuses(list(statuses))

        # Fallback (no AppSync record, or unavailable): MQTT systemState from each powered-on
        # controller. Best effort; a slow device must not fail the poll.
        for device_id, state in statuses.items():
            item = graphql.get(device_id)
            if item is not None:
                _merge_graphql_status(state, item)
                await self._probe_schedule_flag(device_id, state)
            elif state.available and state.is_on:
                try:
                    mqtt = await self._mqtt(device_id, allow_probe_backoff=True)
                    system_state = await mqtt.async_get_system_state() if mqtt else {}
                except CelebrightError as err:
                    _LOGGER.debug("systemState fetch failed for %s: %s", device_id, err)
                    system_state = {}
                _merge_system_state(state, system_state)

            # Remember the schedule flag; reuse the last known one when a poll doesn't carry it.
            if state.schedule_enabled is not None:
                self._schedule_enabled[device_id] = state.schedule_enabled
            else:
                state.schedule_enabled = self._schedule_enabled.get(device_id)

        return statuses

    async def _probe_schedule_flag(self, device_id: str, state: DeviceState) -> None:
        """AppSync has no schedule flag; ask the controller occasionally (MQTT systemState may carry it)."""
        if state.schedule_enabled is not None or not state.available:
            return
        if uses_v3_firmware(self._device_infos.get(device_id)):
            return  # v3 never reports it
        if time.monotonic() < self._schedule_probe_at.get(device_id, 0.0):
            return
        self._schedule_probe_at[device_id] = time.monotonic() + _SCHEDULE_PROBE_SECONDS
        try:
            mqtt = await self._mqtt(device_id, allow_probe_backoff=True)
            system_state = await mqtt.async_get_system_state() if mqtt else {}
        except CelebrightError as err:
            _LOGGER.debug("schedule flag probe failed for %s: %s", device_id, err)
            return
        flag = _schedule_flag(system_state)
        if flag is not None:
            state.schedule_enabled = flag

    # --- AppSync (GraphQL) status ---

    async def _graphql_statuses(self, device_ids: list[str]) -> dict[str, dict[str, Any]]:
        """AppSync status items by device id; {} when unavailable (caller falls back)."""
        if not device_ids or time.monotonic() < self._graphql_retry_at:
            return {}
        try:
            body = await self._graphql(build_status_query(device_ids))
            result = parse_status_response(device_ids, body)
            if not result and body.get("errors"):
                # 200 OK but every record null with errors (e.g. field-level auth): report it, not "no record".
                raise CelebrightCommandError(_first_graphql_error(body))
        except CelebrightError as err:
            self._graphql_retry_at = time.monotonic() + _GRAPHQL_BACKOFF_SECONDS
            log = _LOGGER.debug if self._graphql_failed_before else _LOGGER.warning
            self._graphql_failed_before = True
            log(
                "AppSync status unavailable (%s) — using MQTT for state; retrying in %ds",
                err, _GRAPHQL_BACKOFF_SECONDS,
            )
            return {}
        if self._graphql_failed_before or not self._graphql_ok_logged:
            _LOGGER.info(
                "Celebright AppSync status active (authorized with the %s token)",
                self._graphql_token_kind,
            )
            self._graphql_ok_logged = True
        self._graphql_failed_before = False
        return result

    async def _graphql(self, query: str) -> dict[str, Any]:
        """POST a query with the access token (the app's choice), falling back to the id token; remembers which works."""
        assert self._auth
        await self._auth.async_ensure_valid()
        tokens = [("access", self._auth.access_token), ("id", self._auth.id_token)]
        if self._graphql_token_kind == "id":
            tokens.reverse()
        last_auth_err: CelebrightAuthError | None = None
        for kind, token in tokens:
            try:
                body = await self._graphql_request(query, token)
            except CelebrightAuthError as err:
                last_auth_err = err
                continue
            self._graphql_token_kind = kind
            return body
        assert last_auth_err is not None
        raise last_auth_err

    async def _graphql_request(self, query: str, token: str) -> dict[str, Any]:
        assert self._session
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": token,
        }
        try:
            async with asyncio.timeout(15):
                resp = await self._session.post(
                    APPSYNC_URL, json={"query": query, "variables": {}}, headers=headers
                )
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise CelebrightConnectionError(f"AppSync request failed: {err}") from err

        if resp.status in (401, 403):
            raise CelebrightAuthError(f"AppSync HTTP {resp.status}: {(await resp.text())[:200]}")
        if resp.status >= 400:
            raise CelebrightCommandError(f"AppSync HTTP {resp.status}: {(await resp.text())[:200]}")
        body = await resp.json(content_type=None)
        if not isinstance(body, dict):
            raise CelebrightCommandError("AppSync returned an unexpected response")
        data = body.get("data")
        nothing_returned = not data or all(v is None for v in data.values())
        if body.get("errors") and nothing_returned:
            if _graphql_unauthorized(body):
                raise CelebrightAuthError(_first_graphql_error(body))
            raise CelebrightCommandError(_first_graphql_error(body))
        return body

    # --- MQTT client selection ---

    async def _mqtt(
        self, device_id: str, *, allow_probe_backoff: bool = False
    ) -> CelebrightMQTT | None:
        """MQTT client on the protocol this controller answers (probed once per device, cached).

        If the probe gets no answer, commands use the default protocol and fail on the
        missing reply; with allow_probe_backoff the poll gets None until the back-off ends.
        """
        assert self._auth
        await self._auth.async_ensure_valid()
        mqtt = _mqtt_for_device(device_id, self._auth)

        protocol = self._protocols.get(device_id)
        if protocol is None:
            if allow_probe_backoff and time.monotonic() < self._probe_retry_at.get(device_id, 0.0):
                return None
            protocol = await mqtt.async_probe_protocol()
            if protocol is None:
                self._probe_retry_at[device_id] = time.monotonic() + _PROBE_BACKOFF_SECONDS
                _LOGGER.debug("Celebright %s answered on no known MQTT protocol", device_id)
                if allow_probe_backoff:
                    return None
                protocol = MQTT_DEFAULT_PROTOCOL
            else:
                self._protocols[device_id] = protocol
                self._probe_retry_at.pop(device_id, None)
                _LOGGER.info("Celebright %s speaks MQTT protocol %s", device_id, protocol)
        return mqtt.with_protocol(protocol)

    async def async_load_scene(self, device_id: str, scene_uuid: str) -> None:
        mqtt = await self._mqtt(device_id)
        assert mqtt
        await mqtt.async_load_scene(scene_uuid)

    async def async_set_color(
        self, device_id: str, hex_color: str, brightness: int | None = None
    ) -> None:
        mqtt = await self._mqtt(device_id)
        assert mqtt
        await mqtt.async_set_color(hex_color, brightness)

    async def async_set_brightness(
        self, device_id: str, brightness: int, base_hex: str
    ) -> None:
        mqtt = await self._mqtt(device_id)
        assert mqtt
        await mqtt.async_set_brightness(brightness, base_hex)

    async def async_turn_off(self, device_id: str) -> None:
        mqtt = await self._mqtt(device_id)
        assert mqtt
        await mqtt.async_turn_off()

    async def async_set_schedule_enabled(self, device_id: str, enabled: bool) -> None:
        mqtt = await self._mqtt(device_id)
        assert mqtt
        await mqtt.async_set_schedule_enabled(enabled)
        self._schedule_enabled[device_id] = bool(enabled)

    async def async_resume_schedule(self, device_id: str) -> None:
        mqtt = await self._mqtt(device_id)
        assert mqtt
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
        v3_event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create or update (with event_uuid) a schedule event.

        Legacy args use Celebright time codes (-2 sunset, -1 sunrise, 0 midnight, else
        seconds) and the app's md5; v3 controllers use `v3_event` instead.
        """
        import uuid as _uuid

        mqtt = await self._mqtt(device_id)
        assert mqtt
        if mqtt.protocol == "v3":
            if v3_event is None:
                raise CelebrightCommandError("This controller needs a v3 event specification")
            return await self._save_event_v3(device_id, mqtt, v3_event, event_uuid)

        if frequency == 0:
            raise CelebrightCommandError(
                "'Once' events need a controller on the newer protocol (v3). On this "
                "controller use frequency 1 with a repeat_until date."
            )
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
        return await mqtt.async_save_event(event)

    async def _save_event_v3(
        self, device_id: str, mqtt: CelebrightMQTT, spec: dict[str, Any], event_uuid: str | None
    ) -> dict[str, Any]:
        """Create/update a v3 event and confirm it by reading it back."""
        import uuid as _uuid

        ev = events_v3.build_event(uuid=event_uuid or str(_uuid.uuid4()), **spec)
        await mqtt.async_save_event(ev)  # raises on a failure ack / unreachable controller

        def stored(found: dict[str, Any] | None, last_try: bool) -> bool:
            if found is None:
                return False
            if found.get("md5") == ev["md5"]:
                return True
            # On the last look accept the same event stored with other normalisation.
            return last_try and all(
                found.get(k) == ev.get(k)
                for k in ("event_name", "saved_scene_uuid", "recurrence_rule", "start_date")
            )

        if not await self._wait_for_event(device_id, ev["uuid"], stored):
            raise CelebrightCommandError(
                f"saveEvent was sent but event '{ev['event_name']}' ({ev['uuid']}) did not "
                "appear in your account within 10 s — check the Celebright app before retrying"
            )
        return {"uuid": ev["uuid"], "name": ev["event_name"], "md5": ev["md5"], "verified": True}

    async def async_delete_event(self, device_id: str, event_uuid: str) -> dict[str, Any]:
        """Delete a schedule event by UUID. Returns the device ack."""
        mqtt = await self._mqtt(device_id)
        assert mqtt
        ack = await mqtt.async_delete_event(event_uuid)
        if mqtt.protocol != "v3":
            return ack
        if not await self._wait_for_event(device_id, event_uuid, lambda found, _last: found is None):
            raise CelebrightCommandError(
                f"deleteEvent was sent but event {event_uuid} is still in your account "
                "after 10 s — check the Celebright app"
            )
        return {"uuid": event_uuid, "verified": True}

    async def async_set_event_enabled(
        self, device_id: str, event_uuid: str, enabled: bool
    ) -> dict[str, Any]:
        """Enable or disable one schedule event (v3 controllers only)."""
        mqtt = await self._mqtt(device_id)
        assert mqtt
        await mqtt.async_set_event_enabled(event_uuid, enabled)
        want = bool(enabled)
        reflected = await self._wait_for_event(
            device_id, event_uuid,
            lambda found, _last: found is not None and bool(found.get("enabled", True)) == want,
        )
        if not reflected:
            # Not fatal: no capture of this command exists to be sure it shows up promptly.
            _LOGGER.warning(
                "Event %s was sent as %s but the account doesn't show it yet",
                event_uuid, "enabled" if want else "disabled",
            )
        return {"uuid": event_uuid, "enabled": want, "verified": reflected}

    # --- HTTP helpers ---

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

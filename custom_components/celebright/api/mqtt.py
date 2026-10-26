"""MQTT-over-WebSocket client for Celebright controllers (AWS IoT, SigV4-signed URL).

Topics: devices/{id}/{ver}/app/{command} (we publish); .../device/... and .../server/...
(we subscribe). {ver} is "v3" on firmware 3.x and "v2" on older controllers; a command on
the wrong version is silently ignored, so the version is probed per device.

v3 replies arrive as `commandAck` and/or a `systemState` push; large ones are chunked
(`msgChunk`).
"""
from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import hmac
import json
import logging
import struct
import time
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Any

import aiohttp
import yarl

from .base import CelebrightCommandError, CelebrightConnectionError
from .events_v3 import utc_now_str
from ..const import MQTT_DEFAULT_PROTOCOL, MQTT_PROTOCOLS

_LOGGER = logging.getLogger(__name__)

# aiohttp returns these instantly once the socket is closed; treat them as terminal
# so receive loops fail fast instead of spinning.
_TERMINAL_WS_TYPES = {
    aiohttp.WSMsgType.CLOSE,
    aiohttp.WSMsgType.CLOSING,
    aiohttp.WSMsgType.CLOSED,
    aiohttp.WSMsgType.ERROR,
}

# --- SigV4 URL presigning ---

_SERVICE = "iotdevicegateway"
_ALGORITHM = "AWS4-HMAC-SHA256"


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def presign_mqtt_wss_url(
    access_key: str,
    secret_key: str,
    session_token: str,
    region: str,
    endpoint: str,
) -> str:
    """Return a SigV4-presigned wss:// URL for MQTT over WebSocket."""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y%m%d")
    datetime_str = now.strftime("%Y%m%dT%H%M%SZ")

    credential = f"{access_key}/{date_str}/{region}/{_SERVICE}/aws4_request"

    _enc = lambda v: urllib.parse.quote(v, safe="")

    # IoT signs the query WITHOUT Security-Token and appends the token afterwards
    # (as Amplify and the AWS IoT JS SDK do); signing it too gives a 403.
    qs_to_sign: dict[str, str] = {
        "X-Amz-Algorithm": _ALGORITHM,
        "X-Amz-Credential": credential,
        "X-Amz-Date": datetime_str,
        "X-Amz-SignedHeaders": "host",
    }
    canonical_qs = "&".join(
        f"{_enc(k)}={_enc(v)}" for k, v in sorted(qs_to_sign.items())
    )

    canonical_request = "\n".join([
        "GET",
        "/mqtt",
        canonical_qs,
        f"host:{endpoint}\n",
        "host",
        hashlib.sha256(b"").hexdigest(),
    ])

    string_to_sign = "\n".join([
        _ALGORITHM,
        datetime_str,
        f"{date_str}/{region}/{_SERVICE}/aws4_request",
        hashlib.sha256(canonical_request.encode()).hexdigest(),
    ])

    k_date = _hmac_sha256(f"AWS4{secret_key}".encode(), date_str)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, _SERVICE)
    k_signing = _hmac_sha256(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()

    # Final URL: signed params → signature → token (token appended last, not signed)
    return (
        f"wss://{endpoint}/mqtt?"
        f"{canonical_qs}"
        f"&X-Amz-Signature={signature}"
        f"&X-Amz-Security-Token={_enc(session_token)}"
    )


# --- Minimal MQTT 3.1.1 framing (QoS 0 only — matches what the app uses) ---

def _encode_remaining(n: int) -> bytes:
    out = []
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            break
    return bytes(out)


def _encode_str(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack(">H", len(b)) + b


def build_connect(client_id: str, keepalive: int = 60) -> bytes:
    payload = (
        _encode_str("MQTT")    # protocol name
        + bytes([4, 2])        # level=4 (3.1.1), flags=clean-session
        + struct.pack(">H", keepalive)
        + _encode_str(client_id)
    )
    return bytes([0x10]) + _encode_remaining(len(payload)) + payload


def build_subscribe(topic: str, packet_id: int = 1) -> bytes:
    body = struct.pack(">H", packet_id) + _encode_str(topic) + bytes([0])
    return bytes([0x82]) + _encode_remaining(len(body)) + body


def build_publish(topic: str, payload: str) -> bytes:
    body = _encode_str(topic) + payload.encode("utf-8")
    return bytes([0x30]) + _encode_remaining(len(body)) + body


def build_disconnect() -> bytes:
    return bytes([0xE0, 0x00])


def compute_event_md5(
    *,
    uuid: str,
    device_preset_uuid: str,
    event_name: str,
    priority: int,
    start_date: int,
    start_time: int,
    end_date: int,
    end_time: int,
    frequency: int,
    interval: int,
    repeat_until: int | None,
    by_day: str | None,
    by_month_day: int | None,
    by_month: int | None,
    by_set_pos: int | None,
) -> str:
    """The app's legacy (v2) event md5: MD5 of these fields concatenated, no separators, null -> "":
    uuid, device_preset_uuid, event_name, priority, start_date, start_time, end_date,
    end_time, frequency, interval, repeat_until, byDay, byMonthDay, byMonth, bySetPos.
    """
    import hashlib

    def s(x: Any) -> str:
        return "" if x is None else str(x)

    preimage = (
        s(uuid) + s(device_preset_uuid) + s(event_name) + s(priority)
        + s(start_date) + s(start_time) + s(end_date) + s(end_time)
        + s(frequency) + s(interval) + s(repeat_until)
        + s(by_day) + s(by_month_day) + s(by_month) + s(by_set_pos)
    )
    return hashlib.md5(preimage.encode("utf-8")).hexdigest()


def parse_incoming(data: bytes) -> tuple[int, str, str] | None:
    """Parse an inbound MQTT frame. Returns (packet_type, topic, payload) for PUBLISH, else None."""
    if not data:
        return None
    ptype = (data[0] >> 4) & 0xF
    if ptype != 3:  # only care about PUBLISH
        return None

    # Decode remaining length
    multiplier = 1
    value = 0
    offset = 1
    while offset < len(data):
        b = data[offset]
        offset += 1
        value += (b & 0x7F) * multiplier
        multiplier *= 128
        if not (b & 0x80):
            break

    # Topic
    if offset + 2 > len(data):
        return None
    topic_len = struct.unpack_from(">H", data, offset)[0]
    offset += 2
    topic = data[offset:offset + topic_len].decode("utf-8", errors="replace")
    offset += topic_len

    # QoS 0: no packet ID
    payload_bytes = data[offset:]
    payload = payload_bytes.decode("utf-8", errors="replace")
    return ptype, topic, payload


# --- High-level MQTT client ---

class MessageAssembler:
    """Reassembles chunked controller messages (topic suffix "msgChunk").

    Pieces are {"id","seq","total","data"} (base64 slices of a JSON envelope
    {"topic","message"}); other messages pass through. feed() returns None until complete.
    """

    _MAX_PENDING = 16

    def __init__(self) -> None:
        self._pending: dict[Any, dict[int, str]] = {}

    def feed(self, topic: str, payload: str) -> tuple[str, str] | None:
        if not topic.endswith("/msgChunk"):
            return topic, payload
        try:
            msg = json.loads(payload)
            chunk_id, seq, total, data = msg["id"], int(msg["seq"]), int(msg["total"]), msg["data"]
        except (ValueError, KeyError, TypeError):
            return None
        if total < 1 or not 0 <= seq < total or not isinstance(data, str):
            self._pending.pop(chunk_id, None)
            return None
        if chunk_id not in self._pending and len(self._pending) >= self._MAX_PENDING:
            self._pending.pop(next(iter(self._pending)))
        parts = self._pending.setdefault(chunk_id, {})
        parts[seq] = data
        if len(parts) < total:
            return None
        del self._pending[chunk_id]
        try:
            envelope = json.loads(
                b"".join(base64.b64decode(parts[i]) for i in range(total)).decode("utf-8")
            )
        except (KeyError, ValueError):
            return None
        if not (isinstance(envelope, dict) and isinstance(envelope.get("topic"), str)):
            return None
        inner = envelope.get("message")
        prefix = topic.rsplit("/", 1)[0]
        return f"{prefix}/{envelope['topic']}", json.dumps(inner if inner is not None else {})


# Commands already warned about this run (their silence is normal).
_UNACKED_REPORTED: set[str] = set()


def _brightness_verdict(state: dict[str, Any], wanted: int) -> bool | None:
    scene = state.get("currentScene") or []
    look = (scene[0].get("lookData") or {}) if scene and isinstance(scene[0], dict) else {}
    level = look.get("brightness")
    if not isinstance(level, (int, float)) or isinstance(level, bool):
        return None
    return abs(int(level) - int(wanted)) <= 2


def _resume_verdict(state: dict[str, Any]) -> bool | None:
    if "active_source" not in state:
        return None
    return state["active_source"] != "user_display"


def _scale_hex(hex_color: str, brightness: int) -> str:
    """Bake a 0-255 brightness into an RRGGBB colour (what v2 controllers expect)."""
    scale = max(0, min(255, brightness)) / 255.0
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"{round(r * scale):02X}{round(g * scale):02X}{round(b * scale):02X}"


class CelebrightMQTT:
    """Fire-and-forget MQTT command sender + one-shot state reader."""

    def __init__(
        self,
        device_id: str,
        access_key: str,
        secret_key: str,
        session_token: str,
        region: str,
        endpoint: str,
        protocol: str = MQTT_DEFAULT_PROTOCOL,
    ) -> None:
        self._device_id = device_id
        self._access_key = access_key
        self._secret_key = secret_key
        self._session_token = session_token
        self._region = region
        self._endpoint = endpoint
        self._protocol = protocol

    @property
    def protocol(self) -> str:
        return self._protocol

    def with_protocol(self, protocol: str) -> "CelebrightMQTT":
        """Copy of this client that talks the given topic protocol ("v2"/"v3")."""
        other = copy.copy(self)
        other._protocol = protocol
        return other

    def _app_topic(self, command: str) -> str:
        return f"devices/{self._device_id}/{self._protocol}/app/{command}"

    def _device_topic(self, subtopic: str) -> str:
        return f"devices/{self._device_id}/{self._protocol}/device/{subtopic}"

    def _state_topic(self) -> str:
        return self._device_topic("systemState")

    async def _connect(self, session: aiohttp.ClientSession) -> aiohttp.ClientWebSocketResponse:
        url = presign_mqtt_wss_url(
            self._access_key,
            self._secret_key,
            self._session_token,
            self._region,
            self._endpoint,
        )
        try:
            # encoded=True stops yarl re-encoding the signed query (e.g. %2F in the token),
            # which would make the URL differ from what was signed (403).
            ws = await session.ws_connect(
                yarl.URL(url, encoded=True),
                protocols=["mqtt", "mqttv3.1", "mqttv3.11"],
                timeout=aiohttp.ClientTimeout(total=15),
            )
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise CelebrightConnectionError(f"IoT WebSocket connect failed: {err}") from err

        client_id = f"ha-celebright-{uuid.uuid4().hex[:8]}"
        await ws.send_bytes(build_connect(client_id))

        # Wait for CONNACK
        try:
            async with asyncio.timeout(10):
                msg = await ws.receive()
        except asyncio.TimeoutError as err:
            raise CelebrightConnectionError("MQTT CONNACK timeout") from err

        if msg.type != aiohttp.WSMsgType.BINARY:
            raise CelebrightConnectionError(f"Unexpected WS message type: {msg.type}")

        data: bytes = msg.data
        if len(data) < 4 or (data[0] >> 4) != 2:
            raise CelebrightConnectionError("Expected CONNACK, got unexpected packet")
        if data[3] != 0:
            raise CelebrightConnectionError(f"MQTT CONNACK error code: {data[3]}")

        return ws

    async def async_send_command(
        self, command: str, payload: dict[str, Any]
    ) -> None:
        """Open a connection, publish one command, close."""
        async with aiohttp.ClientSession() as session:
            ws = await self._connect(session)
            try:
                await ws.send_bytes(
                    build_publish(self._app_topic(command), json.dumps(payload))
                )
                # Brief wait so the device receives the message before we disconnect
                await asyncio.sleep(0.3)
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise CelebrightCommandError(f"MQTT publish failed: {err}") from err
            finally:
                try:
                    await ws.send_bytes(build_disconnect())
                    await ws.close()
                except Exception:
                    pass

    async def _await_message(
        self, ws: aiohttp.ClientWebSocketResponse, accept, timeout: float
    ) -> tuple[str, dict[str, Any]] | None:
        """Wait for a PUBLISH for which accept(topic, body) is true; None on timeout
        or a closed socket. Chunked (msgChunk) messages are reassembled first."""
        assembler = MessageAssembler()
        deadline = time.monotonic() + timeout
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                async with asyncio.timeout(remaining):
                    msg = await ws.receive()
            except asyncio.TimeoutError:
                return None
            if msg.type in _TERMINAL_WS_TYPES:
                return None
            if msg.type != aiohttp.WSMsgType.BINARY:
                continue
            parsed = parse_incoming(msg.data)
            if not parsed:
                continue
            fed = assembler.feed(parsed[1], parsed[2])
            if fed is None:
                continue
            topic, payload = fed
            try:
                body = json.loads(payload)
            except json.JSONDecodeError:
                body = {}
            if not isinstance(body, dict):
                body = {}
            if accept(topic, body):
                return topic, body
        return None

    async def _await_topic(
        self, ws: aiohttp.ClientWebSocketResponse, topic: str, timeout: float
    ) -> dict[str, Any] | None:
        """Wait for a PUBLISH on `topic`; None on timeout or a closed socket."""
        got = await self._await_message(ws, lambda t, _b: t == topic, timeout)
        return got[1] if got else None

    async def async_get_system_state(self, timeout: float = 5.0) -> dict[str, Any]:
        """Request and return the device systemState via MQTT ({} if none arrives)."""
        async with aiohttp.ClientSession() as session:
            ws = await self._connect(session)
            try:
                # Subscribe to the device topic so we receive the response
                await ws.send_bytes(build_subscribe(self._device_topic("#")))

                # Request state
                await ws.send_bytes(
                    build_publish(
                        self._app_topic("getSystemState"),
                        json.dumps({"UTCTimeFromApp": int(time.time())}),
                    )
                )
                received = await self._await_topic(ws, self._state_topic(), timeout)
            finally:
                try:
                    await ws.send_bytes(build_disconnect())
                    await ws.close()
                except Exception:
                    pass

        return received or {}

    async def async_probe_protocol(self, timeout: float = 4.0) -> str | None:
        """Which topic protocol answers ("v3" first, then "v2"); None if neither (e.g. offline)."""
        for protocol in MQTT_PROTOCOLS:
            state = await self.with_protocol(protocol).async_get_system_state(timeout)
            if state:
                return protocol
        return None

    async def _send_confirmed(
        self,
        command: str,
        payload: dict[str, Any],
        timeout: float = 5.0,
        strict: bool = True,
        warn: bool = True,
        verify=None,
        ack_phase: str | None = None,
    ) -> dict[str, Any]:
        """Publish a command and wait for the controller's reply (`commandAck` and/or `systemState`).

        A failure ack always raises. On silence: strict raises; non-strict first checks the
        controller is alive (getSystemState; dead raises), then `verify(state)` may decide
        (True/False; None = can't tell), else it warns once per command.
        `ack_phase`: wait for that final ack phase ("databaseWrite" follows "commandAccept");
        a first-phase ack alone still counts as success.
        """
        state_topic = self._state_topic()
        ack_topic = self._device_topic("commandAck")
        error_topic = self._device_topic("logDeviceError")

        def accept(topic: str, body: dict[str, Any]) -> bool:
            if topic == error_topic:  # e.g. "Unrecognized topic [setFoo] No action taken"
                return f"[{command}]" in str(body.get("message", ""))
            return topic == state_topic or (
                topic == ack_topic and body.get("command") == command
            )

        alive: dict[str, Any] | None = None
        async with aiohttp.ClientSession() as session:
            ws = await self._connect(session)
            try:
                await ws.send_bytes(build_subscribe(self._device_topic("#")))
                await ws.send_bytes(
                    build_publish(self._app_topic(command), json.dumps(payload))
                )
                got = None
                accepted = None
                deadline = time.monotonic() + timeout
                while (remaining := deadline - time.monotonic()) > 0:
                    msg = await self._await_message(ws, accept, remaining)
                    if msg is None:
                        break
                    topic, body = msg
                    failed = str(body.get("status", "")).lower() == "failure"
                    if (
                        topic == ack_topic and not failed and ack_phase
                        and body.get("phase") != ack_phase
                    ):
                        accepted = msg  # earlier phase succeeded; wait for the final one
                        continue
                    got = msg
                    break
                if got is None:
                    got = accepted
                if got is None and not strict:
                    await ws.send_bytes(
                        build_publish(
                            self._app_topic("getSystemState"),
                            json.dumps({"UTCTimeFromApp": int(time.time())}),
                        )
                    )
                    alive = await self._await_topic(ws, state_topic, 3.0)
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise CelebrightCommandError(f"{command} failed: {err}") from err
            finally:
                try:
                    await ws.send_bytes(build_disconnect())
                    await ws.close()
                except Exception:
                    pass

        if got is not None:
            topic, body = got
            if topic == error_topic:
                raise CelebrightCommandError(
                    f"{command}: the controller rejected it: {body.get('message')}"
                )
            if topic == ack_topic and str(body.get("status", "")).lower() == "failure":
                raise CelebrightCommandError(
                    f"{command} was rejected by the controller: {body}"
                )
            return body
        if strict or alive is None:
            raise CelebrightCommandError(
                f"{command}: the controller did not respond on MQTT protocol "
                f"{self._protocol} (is it online?)"
            )
        verdict = verify(alive) if verify is not None else None
        if verdict is True:
            _LOGGER.debug("%s has no acknowledgement; confirmed from the controller's state", command)
            return alive
        if verdict is False:
            raise CelebrightCommandError(
                f"{command}: the controller is online but its reported state doesn't "
                "show the change"
            )
        if warn:
            level = _LOGGER.debug if command in _UNACKED_REPORTED else _LOGGER.warning
            _UNACKED_REPORTED.add(command)
            level(
                "%s was not acknowledged by the controller and its state can't confirm "
                "it (the controller is online, so the command may have been ignored)",
                command,
            )
        return alive

    @property
    def _is_v3(self) -> bool:
        return self._protocol == "v3"

    async def async_set_color(self, hex_color: str, brightness: int | None = None) -> None:
        """Solid colour (full-brightness RRGGBB) with optional 0-255 brightness (v2 bakes it in)."""
        color = hex_color.upper()
        if self._is_v3:
            payload: dict[str, Any] = {"color": color, "source": "user_display"}
            if brightness is not None:
                payload["brightness"] = int(brightness)
            await self._send_confirmed("setColor", payload)
        else:
            if brightness is not None:
                color = _scale_hex(color, brightness)
            await self.async_send_command("setColor", {"color": color})

    async def async_set_brightness(self, brightness: int, base_hex: str) -> None:
        """Brightness only: v3 dims whatever is showing; v2 can only resend base_hex scaled."""
        if self._is_v3:
            await self._send_confirmed(
                "setBrightness", {"brightness": int(brightness)}, strict=False,
                verify=lambda st: _brightness_verdict(st, brightness),
            )
        else:
            await self.async_set_color(base_hex, brightness)

    async def async_load_scene(self, scene_uuid: str) -> None:
        """Activate a saved scene by UUID."""
        if self._is_v3:
            await self._send_confirmed(
                "loadSavedScene",
                {"savedSceneUuid": scene_uuid, "source": "user_display"},
                strict=False,
            )
        else:
            await self.async_send_command(
                "loadSavedScene", {"savedSceneUuid": scene_uuid}
            )

    async def async_turn_off(self) -> None:
        """Lights off. v3 has a real turnOff; v2 only has "resume the schedule"."""
        if self._is_v3:
            await self._send_confirmed("turnOff", {})
        else:
            await self.async_send_command("setResumeSchedule", {})

    async def async_resume_schedule(self) -> None:
        """Hand control back to the schedule (same command on v2 and v3)."""
        if self._is_v3:
            await self._send_confirmed(
                "setResumeSchedule", {}, strict=False, verify=_resume_verdict
            )
        else:
            await self.async_send_command("setResumeSchedule", {})

    async def async_set_schedule_enabled(self, enabled: bool) -> None:
        """Enable/disable the on-device schedule (v2 only; v3 firmware rejects the command)."""
        if self._is_v3:
            raise CelebrightCommandError(
                "Firmware 3.x has no global schedule switch (the controller rejects the "
                "command); use celebright.set_event_enabled to switch individual events."
            )
        await self.async_send_command("setEnableSchedule", {"scheduleEnabled": bool(enabled)})

    def _require_v2_for_schedule_writes(self, command: str) -> None:
        if self._is_v3:
            raise CelebrightCommandError(
                f"{command}: editing the on-device schedule isn't supported yet on "
                "this controller's newer protocol (v3). Viewing the schedule still "
                "works; use the Celebright app to change it."
            )

    async def _publish_and_await(
        self,
        command: str,
        payload: dict[str, Any],
        success_subtopic: str,
        timeout: float,
    ) -> dict[str, Any]:
        """Publish an app command and wait for a specific device/<subtopic> ack."""
        self._require_v2_for_schedule_writes(command)
        success_topic = self._device_topic(success_subtopic)
        ack: dict[str, Any] = {}

        async with aiohttp.ClientSession() as session:
            ws = await self._connect(session)
            try:
                await ws.send_bytes(build_subscribe(self._device_topic("#")))
                await ws.send_bytes(
                    build_publish(self._app_topic(command), json.dumps(payload))
                )

                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    remaining = deadline - time.monotonic()
                    try:
                        async with asyncio.timeout(remaining):
                            msg = await ws.receive()
                    except asyncio.TimeoutError:
                        break
                    if msg.type in _TERMINAL_WS_TYPES:
                        raise CelebrightCommandError(
                            f"{command}: IoT WebSocket closed while waiting ({msg.type})"
                        )
                    if msg.type != aiohttp.WSMsgType.BINARY:
                        continue
                    parsed = parse_incoming(msg.data)
                    if parsed and parsed[1] == success_topic:
                        try:
                            ack = json.loads(parsed[2])
                        except json.JSONDecodeError:
                            ack = {}
                        break
                else:
                    raise CelebrightCommandError(f"{command}: no acknowledgement from device")

                if not ack:
                    raise CelebrightCommandError(f"{command}: device did not confirm")

            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                raise CelebrightCommandError(f"{command} failed: {err}") from err
            finally:
                try:
                    await ws.send_bytes(build_disconnect())
                    await ws.close()
                except Exception:
                    pass

        return ack

    async def async_save_event(self, event: dict[str, Any], timeout: float = 8.0) -> dict[str, Any]:
        """Create or update (same uuid) an event; v2 awaits saveEventSuccess."""
        if self._is_v3:
            # The save reply isn't relied on; the caller confirms by reading the event back.
            return await self._send_confirmed(
                "saveEvent", {"event": event}, timeout, strict=False, warn=False,
                ack_phase="databaseWrite",
            )
        return await self._publish_and_await(
            "saveEvent", {"event": event}, "saveEventSuccess", timeout
        )

    async def async_delete_event(self, event_uuid: str, timeout: float = 8.0) -> dict[str, Any]:
        """Delete a schedule event by UUID; await deleteEventSuccess. Returns {"uuid": ...}."""
        if self._is_v3:
            return await self._send_confirmed(
                "deleteEvent", {"eventUuid": event_uuid}, timeout, strict=False, warn=False,
                ack_phase="databaseWrite",
            )
        return await self._publish_and_await(
            "deleteEvent", {"eventUuid": event_uuid}, "deleteEventSuccess", timeout
        )

    async def async_set_event_enabled(
        self, event_uuid: str, enabled: bool, timeout: float = 8.0
    ) -> dict[str, Any]:
        """Enable/disable one schedule event (v3 only)."""
        if not self._is_v3:
            raise CelebrightCommandError(
                "Enabling or disabling a single event needs a controller on the newer "
                "protocol (v3)."
            )
        return await self._send_confirmed(
            "setEventEnabled",
            {"eventUuid": event_uuid, "enabled": bool(enabled), "last_modified_utc": utc_now_str()},
            timeout, strict=False, warn=False, ack_phase="databaseWrite",
        )

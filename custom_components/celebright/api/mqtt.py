"""MQTT over WebSocket client for Celebright device control.

Celebright uses AWS IoT Core with SigV4-signed WebSocket URLs.
All device commands are MQTT PUBLISH messages; state is read back
from the device/systemState topic.

Protocol facts from HAR analysis:
  Subscribe: devices/{id}/v2/server/#  and  devices/{id}/v2/device/#
  Commands:  devices/{id}/v2/app/{command}  (PUBLISH, QoS 0)
  State:     devices/{id}/v2/device/systemState  (inbound PUBLISH)

Commands confirmed:
  setColor           {"color": "RRGGBB"}
  setResumeSchedule  {}
  getSystemState     {"UTCTimeFromApp": <epoch_int>}
"""
from __future__ import annotations

import asyncio
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

_LOGGER = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# SigV4 URL presigning
# -----------------------------------------------------------------------

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

    # For IoT MQTT WebSocket presigning the Security-Token is NOT part of the
    # signed query string — it is appended after the signature. This matches
    # how Amplify Flutter (and the official AWS IoT JS SDK) build the URL.
    # Including the token in the canonical QS produces a different signature
    # than what AWS IoT expects, resulting in a 403.
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


# -----------------------------------------------------------------------
# Minimal MQTT 3.1.1 framing (QoS 0 only — matches what the app uses)
# -----------------------------------------------------------------------

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


def build_pingreq() -> bytes:
    return bytes([0xC0, 0x00])


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
    """Replicate the Celebright app's event md5 (reverse-engineered from main.dart.js `cMK`).

    Preimage = no-separator concatenation in this exact field order, with null → "":
      uuid + device_preset_uuid + event_name + priority + start_date + start_time
      + end_date + end_time + frequency + interval + repeat_until + byDay
      + byMonthDay + byMonth + bySetPos
    Then md5 hex (lowercase, zero-padded to 32). Verified against 9 server events + 1 app write.
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


# -----------------------------------------------------------------------
# High-level MQTT client
# -----------------------------------------------------------------------

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
    ) -> None:
        self._device_id = device_id
        self._access_key = access_key
        self._secret_key = secret_key
        self._session_token = session_token
        self._region = region
        self._endpoint = endpoint

    def _app_topic(self, command: str) -> str:
        return f"devices/{self._device_id}/v2/app/{command}"

    def _state_topic(self) -> str:
        return f"devices/{self._device_id}/v2/device/systemState"

    async def _connect(self, session: aiohttp.ClientSession) -> aiohttp.ClientWebSocketResponse:
        url = presign_mqtt_wss_url(
            self._access_key,
            self._secret_key,
            self._session_token,
            self._region,
            self._endpoint,
        )
        try:
            # yarl.URL(..., encoded=True) prevents aiohttp/yarl from re-encoding
            # the already-signed query string — decoding %2F back to / in the token
            # would make the actual URL differ from what was signed, causing a 403.
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

    async def async_get_system_state(self) -> dict[str, Any]:
        """Request and return the device systemState via MQTT."""
        state_topic = self._state_topic()
        received: dict[str, Any] = {}

        async with aiohttp.ClientSession() as session:
            ws = await self._connect(session)
            try:
                # Subscribe to the device topic so we receive the response
                await ws.send_bytes(
                    build_subscribe(f"devices/{self._device_id}/v2/device/#")
                )

                # Request state
                await ws.send_bytes(
                    build_publish(
                        self._app_topic("getSystemState"),
                        json.dumps({"UTCTimeFromApp": int(time.time())}),
                    )
                )

                # Wait up to 5 s for systemState response
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    remaining = deadline - time.monotonic()
                    try:
                        async with asyncio.timeout(remaining):
                            msg = await ws.receive()
                    except asyncio.TimeoutError:
                        break

                    if msg.type != aiohttp.WSMsgType.BINARY:
                        continue

                    parsed = parse_incoming(msg.data)
                    if parsed and parsed[1] == state_topic:
                        try:
                            received = json.loads(parsed[2])
                        except json.JSONDecodeError:
                            pass
                        break

            finally:
                try:
                    await ws.send_bytes(build_disconnect())
                    await ws.close()
                except Exception:
                    pass

        return received

    # ------------------------------------------------------------------
    # Convenience command wrappers
    # ------------------------------------------------------------------

    async def async_set_color(self, hex_color: str) -> None:
        """Turn on with a solid hex color (e.g. 'FFFFFF')."""
        await self.async_send_command("setColor", {"color": hex_color.upper()})

    async def async_load_scene(self, scene_uuid: str) -> None:
        """Activate a saved scene by UUID."""
        await self.async_send_command("loadSavedScene", {"savedSceneUuid": scene_uuid})

    async def async_resume_schedule(self) -> None:
        """Return the device to its scheduled display (effectively 'off' from manual mode)."""
        await self.async_send_command("setResumeSchedule", {})

    async def _publish_and_await(
        self,
        command: str,
        payload: dict[str, Any],
        success_subtopic: str,
        timeout: float,
    ) -> dict[str, Any]:
        """Publish an app command and wait for a specific device/<subtopic> ack."""
        success_topic = f"devices/{self._device_id}/v2/device/{success_subtopic}"
        ack: dict[str, Any] = {}

        async with aiohttp.ClientSession() as session:
            ws = await self._connect(session)
            try:
                await ws.send_bytes(
                    build_subscribe(f"devices/{self._device_id}/v2/device/#")
                )
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
        """Create or update a schedule event (same uuid = update); await saveEventSuccess.

        `event` must be a fully-formed event dict (snake_case keys, with a valid `md5`).
        Returns the ack payload, e.g. {"name": "...", "uuid": "..."}.
        """
        return await self._publish_and_await(
            "saveEvent", {"event": event}, "saveEventSuccess", timeout
        )

    async def async_delete_event(self, event_uuid: str, timeout: float = 8.0) -> dict[str, Any]:
        """Delete a schedule event by UUID; await deleteEventSuccess. Returns {"uuid": ...}."""
        return await self._publish_and_await(
            "deleteEvent", {"eventUuid": event_uuid}, "deleteEventSuccess", timeout
        )

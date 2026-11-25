"""Keeps the holiday events on the controllers in step with the user's holiday settings.

Settings (a scene per holiday, extra days, custom holidays) live in Home Assistant's storage.
Each enabled holiday is ONE controller event named "Holiday: <name>" that holds the next
occurrence's dates (see holidays.py). A sync creates it, moves it to the following year once
its window has passed, or deletes it when the holiday is switched off. Only events this
manager created are ever changed or deleted; the user's own events are never touched.
"""
from __future__ import annotations

import asyncio
import logging
import uuid as _uuid
from datetime import date
from typing import Any, Callable

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import holidays as hol
from .api.base import CelebrightError
from .card_data import event_form
from .const import DOMAIN
from .coordinator import CelebrightCoordinator

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}_holidays"
STORAGE_VERSION = 1
MAX_CUSTOM = 12


def _local_date(epoch: int) -> str:
    return dt_util.as_local(dt_util.utc_from_timestamp(epoch)).strftime("%Y-%m-%d")


class HolidayManager:
    def __init__(self, hass: HomeAssistant, coordinators: Callable[[], list[Any]]) -> None:
        self.hass = hass
        self._coordinators = coordinators
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, dict[str, Any]] | None = None
        self._status: dict[tuple[str, str], dict[str, str]] = {}
        self._lock = asyncio.Lock()

    # ---- storage ----------------------------------------------------------

    async def async_load(self) -> None:
        if self._data is None:
            stored = await self._store.async_load()
            self._data = stored if isinstance(stored, dict) else {}

    async def _save(self) -> None:
        await self._store.async_save(self._data)

    def _device(self, device_id: str) -> dict[str, Any]:
        entry = self._data.setdefault(device_id, {})
        entry.setdefault("holidays", {})
        entry.setdefault("custom", [])
        entry.setdefault("managed", {})
        return entry

    def _find(self, device_id: str) -> tuple[Any, str]:
        for coord in self._coordinators():
            if device_id in coord.device_infos:
                return coord, device_id
        raise HomeAssistantError(f"Unknown Celebright device {device_id}")

    def _holiday(self, device_id: str, holiday_id: str) -> hol.Holiday:
        if holiday_id in hol.BY_ID:
            return hol.BY_ID[holiday_id]
        for spec in self._device(device_id)["custom"]:
            if spec.get("id") == holiday_id:
                custom = hol.custom_holiday(spec)
                if custom:
                    return custom
        raise HomeAssistantError(f"Unknown holiday {holiday_id}")

    def _all(self, device_id: str) -> list[hol.Holiday]:
        customs = [h for h in (hol.custom_holiday(s) for s in self._device(device_id)["custom"]) if h]
        return [*hol.CATALOG, *customs]

    # ---- what the card shows ---------------------------------------------

    def view(self, device_id: str) -> list[dict[str, Any]]:
        dev = self._device(device_id)
        today = dt_util.now().date()
        rows = []
        for holiday in self._all(device_id):
            st = dev["holidays"].get(holiday.id, {})
            before, after = hol.clamp_adjust(st.get("before")), hol.clamp_adjust(st.get("after"))
            start, end = hol.next_window(holiday, today, before, after)
            row = {
                "id": holiday.id, "name": holiday.name, "info": holiday.info, "custom": holiday.custom,
                "scene": st.get("scene"), "playlist": st.get("playlist"),
                "seconds": st.get("seconds") or 30, "shuffle": bool(st.get("shuffle")),
                "enabled": bool(st.get("enabled")), "before": before, "after": after,
                "next": {"start": start.isoformat(), "end": end.isoformat()},
                "status": self._status.get((device_id, holiday.id)) or {"state": "off" if not st.get("enabled") else "pending", "message": ""},
            }
            if holiday.custom:
                spec = next(s for s in dev["custom"] if s.get("id") == holiday.id)
                row["start"], row["end"] = spec["start"], spec["end"]
            rows.append(row)
        return rows

    # ---- changes ----------------------------------------------------------

    async def async_set(self, device_id: str, holiday_id: str, *, scene: str | None, enabled: bool,
                        before: Any = 0, after: Any = 0, playlist: str | None = None,
                        seconds: Any = 30, shuffle: bool = False) -> dict[str, Any]:
        """Save one holiday's settings and bring its event in line right away.

        A holiday shows one scene, or a playlist (with seconds per scene and shuffle).
        """
        await self.async_load()
        coord, _ = self._find(device_id)
        holiday = self._holiday(device_id, holiday_id)
        if scene and playlist:
            raise HomeAssistantError("Choose a scene or a playlist for this holiday, not both.")
        if scene and scene not in {s.uuid for s in coord.scenes.get(device_id, [])}:
            raise HomeAssistantError("That scene no longer exists. Refresh the scenes and pick another.")
        if playlist and playlist not in {p.uuid for p in getattr(coord, "playlists", {}).get(device_id, [])}:
            raise HomeAssistantError("That playlist no longer exists. Refresh and pick another.")
        if enabled and not (scene or playlist):
            raise HomeAssistantError("Choose a scene or playlist for this holiday first.")
        try:
            seconds = max(1, min(3600, int(seconds)))
        except (TypeError, ValueError):
            seconds = 30
        async with self._lock:
            self._device(device_id)["holidays"][holiday_id] = {
                "scene": scene, "playlist": playlist, "seconds": seconds, "shuffle": bool(shuffle),
                "enabled": bool(enabled),
                "before": hol.clamp_adjust(before), "after": hol.clamp_adjust(after),
            }
            await self._save()
            await self._sync_one(coord, device_id, holiday)
        return next(r for r in self.view(device_id) if r["id"] == holiday_id)

    async def async_save_custom(self, device_id: str, *, holiday_id: str | None, name: str, start: str, end: str) -> str:
        await self.async_load()
        self._find(device_id)
        spec = {"id": holiday_id or _uuid.uuid4().hex[:8], "name": str(name).strip(), "start": start, "end": end}
        if not hol.custom_holiday(spec):
            raise HomeAssistantError("Give the holiday a name and valid start and end dates.")
        async with self._lock:
            dev = self._device(device_id)
            existing = next((s for s in dev["custom"] if s["id"] == spec["id"]), None)
            if existing is None and len(dev["custom"]) >= MAX_CUSTOM:
                raise HomeAssistantError(f"At most {MAX_CUSTOM} custom holidays.")
            dev["custom"] = [s for s in dev["custom"] if s["id"] != spec["id"]] + [spec]
            await self._save()
            # A renamed holiday has a new event name: sync moves the existing event (same uuid).
            coord, _ = self._find(device_id)
            await self._sync_one(coord, device_id, self._holiday(device_id, spec["id"]))
        return spec["id"]

    async def async_remove_custom(self, device_id: str, holiday_id: str) -> None:
        await self.async_load()
        coord, _ = self._find(device_id)
        async with self._lock:
            dev = self._device(device_id)
            holiday = self._holiday(device_id, holiday_id)
            if not holiday.custom:
                raise HomeAssistantError("Only your own holidays can be removed.")
            dev["holidays"].setdefault(holiday_id, {})["enabled"] = False
            await self._sync_one(coord, device_id, holiday)
            dev["custom"] = [s for s in dev["custom"] if s["id"] != holiday_id]
            dev["holidays"].pop(holiday_id, None)
            dev["managed"].pop(holiday_id, None)
            self._status.pop((device_id, holiday_id), None)
            await self._save()

    async def async_sync_all(self) -> None:
        """Bring every holiday on every controller in line (also rolls a past window to next year)."""
        await self.async_load()
        for coord in self._coordinators():
            for device_id in list(coord.device_infos):
                async with self._lock:
                    for holiday in self._all(device_id):
                        if not self._device(device_id)["holidays"].get(holiday.id, {}).get("enabled") \
                                and holiday.id not in self._device(device_id)["managed"]:
                            continue
                        await self._sync_one(coord, device_id, holiday)

    # ---- the sync of one holiday -----------------------------------------

    async def _sync_one(self, coord: Any, device_id: str, holiday: hol.Holiday) -> None:
        key = (device_id, holiday.id)
        try:
            self._status[key] = await self._sync(coord, device_id, holiday)
        except (CelebrightError, HomeAssistantError) as err:
            _LOGGER.warning("Holiday %r on %s: %s", holiday.name, device_id, err)
            self._status[key] = {"state": "error", "message": str(err)}
        except Exception as err:  # noqa: BLE001 - one holiday must not stop the rest
            _LOGGER.exception("Holiday %r on %s failed", holiday.name, device_id)
            self._status[key] = {"state": "error", "message": str(err)}

    def _event_for(self, coord: Any, device_id: str, holiday: hol.Holiday, managed_uuid: str | None):
        events = coord.device_infos[device_id].events
        if managed_uuid:
            found = next((e for e in events if e.uuid == managed_uuid), None)
            if found:
                return found
        # Lost the record: adopt an event that has exactly our name (no duplicate is created).
        return next((e for e in events if e.name == hol.event_name(holiday)), None)

    async def _sync(self, coord: Any, device_id: str, holiday: hol.Holiday) -> dict[str, str]:
        from .services import _build_event_kwargs  # late: services imports a lot of Home Assistant

        dev = self._device(device_id)
        st = dev["holidays"].get(holiday.id, {})
        managed = dev["managed"]
        existing = self._event_for(coord, device_id, holiday, managed.get(holiday.id))

        if not st.get("enabled") or not (st.get("scene") or st.get("playlist")):
            if existing is not None and holiday.id in managed:  # never an event we didn't create
                await coord.async_delete_event(device_id, existing.uuid)
            managed.pop(holiday.id, None)
            await self._save()
            return {"state": "off", "message": ""}

        playlist = None
        if st.get("playlist"):
            if st["playlist"] not in {p.uuid for p in getattr(coord, "playlists", {}).get(device_id, [])}:
                return {"state": "error", "message": "The chosen playlist no longer exists. Pick another."}
            playlist = {"uuid": st["playlist"], "seconds": st.get("seconds") or 30, "shuffle": bool(st.get("shuffle"))}
        elif st["scene"] not in {s.uuid for s in coord.scenes.get(device_id, [])}:
            return {"state": "error", "message": "The chosen scene no longer exists. Pick another."}

        today = dt_util.now().date()
        span = hol.next_window(holiday, today, hol.clamp_adjust(st.get("before")), hol.clamp_adjust(st.get("after")))
        fields = hol.event_fields(holiday, span, st.get("scene"), playlist=playlist)
        message = f"{span[0]:%b} {span[0].day} – {span[1]:%b} {span[1].day}, {span[1].year}"

        if existing is not None and self._matches(existing, fields):
            managed[holiday.id] = existing.uuid
            await self._save()
            return {"state": "ok", "message": message}

        data = {"priority": fields["priority"], "interval": 1, **fields}
        kwargs = _build_event_kwargs(self.hass, coord, device_id, data)
        if existing is None:
            ack = await coord.async_create_event(device_id, **kwargs)
        else:
            ack = await coord.async_create_event(device_id, event_uuid=existing.uuid, **kwargs)
        event_uuid = (ack or {}).get("uuid") or (existing.uuid if existing else None)
        if not event_uuid:
            created = self._event_for(coord, device_id, holiday, None)
            event_uuid = created.uuid if created else None
        if event_uuid:
            managed[holiday.id] = event_uuid
            await self._save()
        return {"state": "ok", "message": message}

    @staticmethod
    def _matches(event: Any, fields: dict[str, Any]) -> bool:
        """Whether the controller's event already is exactly what the settings call for."""
        form = event_form(event.raw, _local_date)
        if not form:
            return False
        raw = event.raw if isinstance(event.raw, dict) else {}
        if "playlist" in fields:
            same_content = (
                raw.get("playlist_uuid") == fields["playlist"]
                and (raw.get("playlist_scene_display_duration_seconds") or 30) == fields["seconds_per_scene"]
                and bool(raw.get("playlist_randomize")) == bool(fields["shuffle"])
                and not raw.get("playlist_once_per_event")
            )
        else:
            same_content = event.scene_uuid == fields["scene"] and not raw.get("playlist_uuid")
        return (
            same_content
            and event.priority == fields["priority"]
            and event.name == fields["name"]
            and event.enabled
            and form.get("frequency") == 1
            and all(form.get(k) == fields[k] for k in ("start_date", "end_date", "start_time", "end_time", "repeat_until"))
        )


_KEY = "_holiday_manager"


def get_manager(hass: HomeAssistant) -> HolidayManager:
    """The one manager of this Home Assistant run (created on first use)."""
    data = hass.data.setdefault(DOMAIN, {})
    if _KEY not in data:
        data[_KEY] = HolidayManager(
            hass,
            lambda: [
                entry.runtime_data
                for entry in hass.config_entries.async_entries(DOMAIN)
                if isinstance(getattr(entry, "runtime_data", None), CelebrightCoordinator)
            ],
        )
    return data[_KEY]

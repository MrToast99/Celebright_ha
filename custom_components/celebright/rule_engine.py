"""Runs the lighting rules (see rules.py): watches the entities they use and the sun.

Each controller has an ordered list of rules. The first rule that is true wins. When the winner
changes, its scene is shown (this overrides the controller's schedule, like picking the scene
by hand). When no rule is true any more, the schedule is resumed, but only if the scene this
engine set is still the one showing, so a scene someone picked by hand in the meantime is
never cleared. The engine acts on changes, not on every look, so it does not fight manual
changes while a rule stays true.

Home Assistant runs this, so rules only act while Home Assistant does.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import rules as rl
from .api.base import CelebrightError
from .const import DOMAIN
from .coordinator import CelebrightCoordinator

_LOGGER = logging.getLogger(__name__)

STORAGE_KEY = f"{DOMAIN}_rules"
STORAGE_VERSION = 1
SUN = "sun.sun"
RETRY_AFTER = timedelta(minutes=5)


class RuleEngine:
    def __init__(self, hass: HomeAssistant, coordinators: Callable[[], list[Any]]) -> None:
        self.hass = hass
        self._coordinators = coordinators
        self._store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, dict[str, Any]] | None = None
        self._applied: dict[str, dict[str, Any]] = {}      # device -> {rule_id, scene, at}
        self._expired: set[tuple[str, str]] = set()        # (device, rule) that ran out of time
        self._errors: dict[tuple[str, str], tuple[datetime, str]] = {}  # (device, rule) -> when, why it failed
        self._entity_unsub: Callable[[], None] | None = None
        self._lock = asyncio.Lock()
        self._again = False
        self._unsubs: list[Callable[[], None]] = []
        self._started = False

    # ---- storage ----------------------------------------------------------

    async def async_load(self) -> None:
        if self._data is None:
            stored = await self._store.async_load()
            self._data = stored if isinstance(stored, dict) else {}

    async def _save(self) -> None:
        await self._store.async_save(self._data)

    def _rules(self, device_id: str) -> list[dict[str, Any]]:
        return self._data.setdefault(device_id, {}).setdefault("rules", [])

    def _find(self, device_id: str) -> Any:
        for coord in self._coordinators():
            if device_id in coord.device_infos:
                return coord
        raise HomeAssistantError(f"Unknown Celebright device {device_id}")

    # ---- what the card shows ---------------------------------------------

    def view(self, device_id: str) -> list[dict[str, Any]]:
        applied = self._applied.get(device_id)
        now = dt_util.now()
        dark = self._read(SUN) == "below_horizon"
        out = []
        for rule in self._rules(device_id):
            key = (device_id, rule["id"])
            met = rule["enabled"] and rl.is_met(rule, self._read, now, dark)
            if not rule["enabled"]:
                status = {"state": "off", "message": ""}
            elif applied and applied["rule_id"] == rule["id"]:
                status = {"state": "applied", "message": f"Showing since {dt_util.as_local(applied['at']):%H:%M}"}
            elif met and key in self._errors:
                status = {"state": "error", "message": self._errors[key][1]}
            elif met:
                status = {"state": "met", "message": "Timed out" if key in self._expired else "A rule above it is showing"}
            else:
                status = {"state": "idle", "message": ""}
            out.append({**rule, "summary": rl.describe(rule), "status": status})
        return out

    # ---- changes ----------------------------------------------------------

    async def async_save_rule(self, device_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        await self.async_load()
        coord = self._find(device_id)
        try:
            rule = rl.validate_rule(raw)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        if rule["scene"] not in {s.uuid for s in coord.scenes.get(device_id, [])}:
            raise HomeAssistantError("That scene no longer exists. Refresh the scenes and pick another.")
        async with self._lock:
            rules = self._rules(device_id)
            index = next((i for i, r in enumerate(rules) if r["id"] == rule["id"]), None)
            if index is None:
                if len(rules) >= rl.MAX_RULES:
                    raise HomeAssistantError(f"At most {rl.MAX_RULES} rules.")
                rules.append(rule)
            else:
                rules[index] = rule
            self._expired.discard((device_id, rule["id"]))
            await self._save()
        self._resubscribe()
        await self.async_evaluate()
        return next(r for r in self.view(device_id) if r["id"] == rule["id"])

    async def async_delete_rule(self, device_id: str, rule_id: str) -> None:
        await self.async_load()
        self._find(device_id)
        async with self._lock:
            self._data[device_id]["rules"] = [r for r in self._rules(device_id) if r["id"] != rule_id]
            self._errors.pop((device_id, rule_id), None)
            await self._save()
        self._resubscribe()
        await self.async_evaluate()

    async def async_move_rule(self, device_id: str, rule_id: str, direction: str) -> None:
        await self.async_load()
        self._find(device_id)
        async with self._lock:
            rules = self._rules(device_id)
            i = next((n for n, r in enumerate(rules) if r["id"] == rule_id), None)
            j = None if i is None else i + (-1 if direction == "up" else 1)
            if i is None or j is None or not 0 <= j < len(rules):
                return
            rules[i], rules[j] = rules[j], rules[i]
            await self._save()
        await self.async_evaluate()

    # ---- watching ---------------------------------------------------------

    async def async_start(self) -> None:
        """Load the rules, start watching, and look once. Safe to call again."""
        await self.async_load()
        if not self._started:
            self._started = True
            self._unsubs.append(async_track_time_interval(self.hass, self._on_tick, timedelta(minutes=1)))
        self._resubscribe()
        await self.async_evaluate()

    @property
    def started(self) -> bool:
        return self._started

    def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._entity_unsub:
            self._entity_unsub()
            self._entity_unsub = None
        self._started = False

    def _resubscribe(self) -> None:
        if self._entity_unsub:
            self._entity_unsub()
        entities = {SUN}
        for device in (self._data or {}).values():
            for rule in device.get("rules", []):
                entities.add(rule["when"]["entity_id"])
        self._entity_unsub = async_track_state_change_event(self.hass, sorted(entities), self._on_state)

    def _on_state(self, event: Event) -> None:
        self.hass.async_create_task(self.async_evaluate(), "celebright rules", eager_start=False)

    async def _on_tick(self, _now: datetime) -> None:
        await self.async_evaluate()

    # ---- the decision -----------------------------------------------------

    def _read(self, entity_id: str) -> str | None:
        state = self.hass.states.get(entity_id)
        return state.state if state else None

    async def async_evaluate(self) -> None:
        """Look at every rule of every controller and show or release scenes as needed."""
        if self._data is None:
            return
        if self._lock.locked():          # another look is running: ask it to go round again
            self._again = True
            return
        async with self._lock:
            while True:
                self._again = False
                for coord in self._coordinators():
                    for device_id in list(coord.device_infos):
                        await self._evaluate_device(coord, device_id)
                if not self._again:
                    break

    async def _evaluate_device(self, coord: Any, device_id: str) -> None:
        rules = self._rules(device_id)
        if not rules:
            await self._release(coord, device_id)
            return
        now = dt_util.now()
        dark = self._read(SUN) == "below_horizon"
        applied = self._applied.get(device_id)

        met_ids = {r["id"] for r in rules if r["enabled"] and rl.is_met(r, self._read, now, dark)}
        for rule in rules:
            if rule["id"] not in met_ids:
                self._expired.discard((device_id, rule["id"]))
        # A rule that has been showing longer than its limit stops, until its condition ends and returns.
        if applied and applied["rule_id"] in met_ids:
            running = next(r for r in rules if r["id"] == applied["rule_id"])
            if running["max_hours"] and now - applied["at"] >= timedelta(hours=running["max_hours"]):
                self._expired.add((device_id, running["id"]))

        for rule in rules:
            if rule["id"] not in met_ids:
                self._errors.pop((device_id, rule["id"]), None)

        winner = next((r for r in rules if r["id"] in met_ids and (device_id, r["id"]) not in self._expired), None)
        if winner is None:
            await self._release(coord, device_id)
        elif applied is None or applied["rule_id"] != winner["id"] or applied["scene"] != winner["scene"]:
            failed = self._errors.get((device_id, winner["id"]))
            if failed is None or now - failed[0] >= RETRY_AFTER:   # don't hammer a controller that isn't answering
                await self._apply(coord, device_id, winner, now)

    async def _apply(self, coord: Any, device_id: str, rule: dict[str, Any], now: datetime) -> None:
        key = (device_id, rule["id"])
        try:
            await coord.client.async_load_scene(device_id, rule["scene"])
        except Exception as err:  # noqa: BLE001 - one rule must not stop the others
            if isinstance(err, (CelebrightError, HomeAssistantError)):
                _LOGGER.warning("Rule %r could not show its scene on %s: %s", rule["name"], device_id, err)
            else:
                _LOGGER.exception("Rule %r failed on %s", rule["name"], device_id)
            self._errors[key] = (now, str(err))
            return
        self._errors.pop(key, None)
        self._applied[device_id] = {"rule_id": rule["id"], "scene": rule["scene"], "at": now}
        coord.set_active_scene(device_id, rule["scene"])
        coord.async_refresh_after_command()

    async def _release(self, coord: Any, device_id: str) -> None:
        """Back to the schedule, if the scene we set is still the one showing."""
        applied = self._applied.pop(device_id, None)
        if applied is None:
            return
        state = (getattr(coord, "data", None) or {}).get(device_id)
        if state is not None and getattr(state, "scene_known", False) and state.active_scene_uuid != applied["scene"]:
            _LOGGER.debug("Rule scene on %s was replaced by hand; leaving it", device_id)
            return
        try:
            await coord.client.async_resume_schedule(device_id)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Could not return %s to its schedule: %s", device_id, err)
            return
        coord.set_active_scene(device_id, None)
        coord.async_refresh_after_command()


_KEY = "_rule_engine"


def get_engine(hass: HomeAssistant) -> RuleEngine:
    """The one engine of this Home Assistant run (created on first use)."""
    data = hass.data.setdefault(DOMAIN, {})
    if _KEY not in data:
        data[_KEY] = RuleEngine(
            hass,
            lambda: [
                entry.runtime_data
                for entry in hass.config_entries.async_entries(DOMAIN)
                if isinstance(getattr(entry, "runtime_data", None), CelebrightCoordinator)
            ],
        )
    return data[_KEY]

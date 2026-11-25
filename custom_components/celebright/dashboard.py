"""Build the Celebright dashboard for one controller from the bundled template.

The template (dashboard.yaml) holds the controller's device id (`__DEVICE_ID__`) for the
Celebright cards, and can hold placeholder entity IDs (`light.house`, ...), each swapped for the
controller's real entity (found by unique ID, so renamed entities work).
"""
from __future__ import annotations

import re
from typing import Callable

# The Playlists view is wrapped in these markers: kept for a controller on firmware 3.x, cut out otherwise.
_PLAYLISTS_VIEW = re.compile(r"^[ \t]*# playlists-view:start\n(.*?)^[ \t]*# playlists-view:end\n", re.M | re.S)

# Placeholder entity IDs look like <domain>.house[_<tail>]
_PLACEHOLDER = re.compile(r"\b(light|select|sensor|binary_sensor|switch|button)\.house(_\w+)?")

# Entity unique IDs are the device id, plus "_<suffix>" (see each platform).
_FIXED_SUFFIX = {
    ("select", "_scene"): "scene",
    ("binary_sensor", "_schedule"): "schedule_enabled",
    ("switch", "_schedule_enabled"): "schedule_switch",
    ("button", "_refresh_scenes"): "refresh_scenes",
}


def _unique_suffix(domain: str, tail: str) -> str | None:
    """Unique-ID suffix for a placeholder ("" = the bare device id), None if unknown."""
    if domain == "light":
        return "" if not tail else None
    if domain == "sensor":
        return tail[1:] if tail else None  # sensor unique IDs end in the sensor key
    return _FIXED_SUFFIX.get((domain, tail))


def build_dashboard(
    template: str,
    device_name: str,
    device_id: str,
    lookup: Callable[[str, str], str | None],
    *,
    playlists: bool = False,
) -> tuple[str, list[str]]:
    """Fill the template for one device.

    playlists: keep the Playlists view (controllers on firmware 3.x have playlists, others don't).
    lookup(domain, unique_id) returns the registered entity ID or None. Returns the
    dashboard text and the placeholders that couldn't be resolved (their card rows are
    dropped; any other mention is left unchanged).
    """
    missing: list[str] = []

    def swap(match: re.Match) -> str:
        domain, tail = match.group(1), match.group(2) or ""
        suffix = _unique_suffix(domain, tail)
        unique_id = None if suffix is None else (device_id if suffix == "" else f"{device_id}_{suffix}")
        entity_id = lookup(domain, unique_id) if unique_id else None
        if entity_id is None:
            if match.group(0) not in missing:
                missing.append(match.group(0))
            return match.group(0)
        return entity_id

    template = _PLAYLISTS_VIEW.sub(r"\1" if playlists else "", template)
    text = _PLACEHOLDER.sub(swap, template.replace("__DEVICE_ID__", device_id))
    # Drop card rows for entities this controller doesn't have (instead of "Entity not found").
    for placeholder in missing:
        text = re.sub(
            rf"^([ \t]*)- entity: {re.escape(placeholder)}\n(?:\1  name: .*\n)?", "", text, flags=re.M
        )
    return text, missing

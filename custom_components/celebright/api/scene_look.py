"""Colour preview of a saved scene, from the `displays` that getDeviceScenes returns.

A display's `mode` is 1 = solid colour, 2 = pattern (a palette; the motion isn't drawn),
3 = individual bulbs. Only the first display is used, so a scene split into zones previews its
first zone.
"""
from __future__ import annotations

import re
from typing import Any

_HEX = re.compile(r"^[0-9a-fA-F]{6}$")
_MAX_BULBS = 24  # enough dots for a preview strip


def _hex(value: Any) -> str | None:
    """'FF8000' / 'ff8000' -> 'ff8000'; anything else -> None."""
    return value.lower() if isinstance(value, str) and _HEX.match(value) else None


def scene_preview(displays: Any) -> dict[str, Any] | None:
    """{"kind": "solid"|"pattern"|"bulbs", "colors": [...], ...} or None if there is nothing to draw.

    Pattern previews also carry `blend` (fade between colours) and `bg` (background colour).
    """
    if not isinstance(displays, list) or not displays or not isinstance(displays[0], dict):
        return None
    display = displays[0]
    data = display.get("data")
    if not isinstance(data, dict):
        return None
    mode = display.get("mode")

    if mode == 1:
        color = _hex(data.get("color"))
        return {"kind": "solid", "colors": [color]} if color else None

    if mode == 2:
        palette = data.get("colorPalette")
        if not isinstance(palette, list):
            return None
        try:
            size = int(data.get("colorPaletteSize") or len(palette))
        except (TypeError, ValueError):
            size = len(palette)
        colors = [c for c in (_hex(p) for p in palette[: max(size, 1)]) if c]
        if not colors:
            return None
        preview: dict[str, Any] = {"kind": "pattern", "colors": colors, "blend": bool(data.get("colorPaletteBlending"))}
        if (bg := _hex(data.get("backgroundColor"))) and bg != "000000":
            preview["bg"] = bg
        return preview

    if mode == 3:
        bulbs = data.get("bulbs")
        if not isinstance(bulbs, dict):
            return None
        colors = []
        for _, value in sorted(bulbs.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0):
            if color := _hex(value):
                colors.append(color)
        if not colors:
            return None
        if len(colors) > _MAX_BULBS:  # even sample, keeping the strip's overall look
            step = len(colors) / _MAX_BULBS
            colors = [colors[int(i * step)] for i in range(_MAX_BULBS)]
        return {"kind": "bulbs", "colors": colors}

    return None

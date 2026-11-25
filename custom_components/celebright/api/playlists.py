"""Scene playlists (firmware 3.x): an ordered list of saved scenes the controller cycles through.

Pure functions, no Home Assistant imports. The shapes come from the Celebright app's own code;
none of it has been seen on the wire yet, so the parser accepts anything list-shaped and skips
what it doesn't understand.
"""
from __future__ import annotations

import json
import hashlib
import uuid as _uuid
from typing import Any

from .base import PlaylistInfo
from .events_v3 import utc_now_str

# What the app's "Play" dialog offers: seconds per scene (default 30), shuffle, and an optional
# turn-off timer in minutes (default 60, in steps of 5).
DEFAULT_SECONDS = 30
MIN_SECONDS, MAX_SECONDS = 1, 3600
MAX_SLEEP_MINUTES = 1440


def parse_playlists(raw: Any) -> list[PlaylistInfo]:
    """The `playlists` array of /getDevicePlaylists, scenes in their saved order."""
    playlists: list[PlaylistInfo] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not item.get("uuid") or not item.get("name"):
            continue
        entries = [s for s in item.get("scenes") or [] if isinstance(s, dict) and s.get("saved_scene_uuid")]
        entries.sort(key=lambda s: s.get("position") if isinstance(s.get("position"), (int, float)) else 0)
        playlists.append(
            PlaylistInfo(
                uuid=str(item["uuid"]),
                name=str(item["name"]),
                description=str(item["description"]) if item.get("description") else None,
                scene_uuids=[str(s["saved_scene_uuid"]) for s in entries],
                md5=str(item.get("md5") or ""),
            )
        )
    return playlists


def _scene_entries(scene_uuids: list[str]) -> list[dict[str, Any]]:
    return [{"saved_scene_uuid": scene_uuid, "position": position} for position, scene_uuid in enumerate(scene_uuids)]


def playlist_md5(playlist_uuid: str, name: str, description: str | None, scene_uuids: list[str]) -> str:
    """The app's checksum: MD5 of the compact JSON of the playlist without its md5 and timestamp."""
    body = {
        "uuid": playlist_uuid,
        "name": name,
        "description": description,
        "scenes": _scene_entries(scene_uuids),
    }
    text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def build_playlist(
    name: str,
    scene_uuids: list[str],
    description: str | None = None,
    playlist_uuid: str | None = None,
) -> dict[str, Any]:
    """The `playlist` object of savePlaylist (a new uuid when none is given)."""
    description = (description or "").strip() or None
    playlist_uuid = playlist_uuid or str(_uuid.uuid4())
    name = name.strip()
    return {
        "uuid": playlist_uuid,
        "md5": playlist_md5(playlist_uuid, name, description, scene_uuids),
        "name": name,
        "description": description,
        "scenes": _scene_entries(scene_uuids),
        "last_modified_utc": utc_now_str(),
    }


def load_payload(
    playlist_uuid: str,
    seconds: int = DEFAULT_SECONDS,
    shuffle: bool = False,
    sleep_minutes: int | None = None,
) -> dict[str, Any]:
    """The `loadPlaylist` payload: shuffle and the timer appear only when used, as in the app."""
    payload: dict[str, Any] = {"playlistUuid": playlist_uuid, "scene_display_duration_seconds": int(seconds)}
    if shuffle:
        payload["randomize"] = True
    if sleep_minutes:
        payload["sleepTimerMinutes"] = int(sleep_minutes)
    return payload

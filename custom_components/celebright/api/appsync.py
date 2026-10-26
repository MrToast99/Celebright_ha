"""AWS AppSync (GraphQL) status: the same batched query the Celebright app uses.

Authorized with the Cognito *access* token. `currentScene` is a JSON-encoded string;
`activeSavedScene` / `activeEvent` are null when nothing is playing.
"""
from __future__ import annotations

import json
from typing import Any

STATUS_FIELDS = (
    "id online activeSource retainedUserDisplay nextEventStartLocal sleepTimer "
    "dbWriteQueueSize md5Present deviceTimeUtc updatedAtServer currentScene "
    "activeEvent activeSavedScene _deleted"
)


def build_status_query(device_ids: list[str]) -> str:
    """One aliased getDeviceStatusV3 selection per device (ids JSON-quoted)."""
    selections = "\n".join(
        f"d{i}: getDeviceStatusV3(id: {json.dumps(str(dev))}) {{ {STATUS_FIELDS} }}"
        for i, dev in enumerate(device_ids)
    )
    return f"query GetDeviceStatusV3Batch {{\n{selections}\n}}"


def parse_status_response(
    device_ids: list[str], body: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """device_id -> status item; devices AppSync has no (or a deleted) record for are omitted."""
    data = body.get("data") or {}
    out: dict[str, dict[str, Any]] = {}
    for i, dev in enumerate(device_ids):
        item = data.get(f"d{i}")
        if isinstance(item, dict) and not item.get("_deleted"):
            out[dev] = item
    return out

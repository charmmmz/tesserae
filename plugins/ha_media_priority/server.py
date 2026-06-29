"""ha_media_priority, ordered now-playing selector for HA media_player entities.

Fetches all Home Assistant states once, walks the configured media_player
priority list, and returns the first entity whose state is exactly
``playing``. Paused media is intentionally ignored for the E1004 poster
workflow so a paused higher-priority device does not block an actively
playing lower-priority source.
"""

from __future__ import annotations

import re
from typing import Any

from flask import current_app


def _core() -> Any:
    plugin = current_app.config["PLUGIN_REGISTRY"].get("ha_core")
    return plugin.server_module if plugin is not None else None


def _ha_media() -> Any:
    plugin = current_app.config["PLUGIN_REGISTRY"].get("ha_media")
    return plugin.server_module if plugin is not None else None


def choices(name: str) -> list[dict[str, str]]:
    """Expose media_player choices for future editor affordances."""
    core = _core()
    if name == "entity" and core is not None:
        return core.entity_choices(domains=("media_player",))
    return []


def _entity_list(raw: Any) -> list[str]:
    """Parse textarea/list input into ordered entity ids.

    The editor uses a textarea so priority order is explicit. Tests and
    preview routes may pass a list; legacy comma-separated values are
    tolerated to make manual URL testing less brittle.
    """
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    return [tok.strip() for tok in re.split(r"[\n,]+", text) if tok.strip()]


def _empty(entities: list[str]) -> dict[str, Any]:
    return {
        "empty": True,
        "name": "Media Priority",
        "state": "idle",
        "checked_entities": entities,
    }


def fetch(
    options: dict[str, Any], settings: dict[str, Any], *, ctx: dict[str, Any]
) -> dict[str, Any]:
    del settings, ctx
    core = _core()
    if core is None:
        return {"error": "Install the Home Assistant Core plugin to use this widget."}
    media = _ha_media()
    if media is None or not hasattr(media, "shape_media_state"):
        return {"error": "Install the Home Assistant Media widget to use this widget."}

    entities = _entity_list(options.get("entities"))
    if not entities:
        return _empty([])

    try:
        states = core.get_states()
    except Exception as err:
        return {"error": core.coerce_error(err)}

    by_id = {str(st.get("entity_id") or ""): st for st in states if isinstance(st, dict)}
    for entity_id in entities:
        st = by_id.get(entity_id)
        if not st:
            continue
        if st.get("state") != "playing":
            continue
        out = media.shape_media_state(core, entity_id, st)
        out["selected_entity_id"] = entity_id
        out["checked_entities"] = entities
        return out

    return _empty(entities)

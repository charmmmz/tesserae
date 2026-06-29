# HA Media Priority Widget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `ha_media_priority` Tesserae widget that selects the first Home Assistant `media_player` entity whose state is exactly `playing`.

**Architecture:** Reuse the existing `ha_media` normalization and rendering path instead of duplicating media-card behavior. Add a small server plugin that fetches all HA states once, picks the first configured playing entity, then delegates state shaping to `ha_media`. Add an empty-state path for “nothing playing” so ambient/gallery content can stay separate.

**Tech Stack:** Python 3.11, Flask plugin registry, Tesserae widget manifests, ES module widget clients, pytest.

---

## File Structure

- Modify `plugins/ha_media/server.py`: extract existing single-entity media normalization into `shape_media_state(core, entity_id, st)`.
- Create `plugins/ha_media/tests/test_smoke.py`: cover the reusable normalizer and existing render smoke for `ha_media`.
- Create `plugins/ha_media_priority/plugin.json`: declare the new widget, ordered entity textarea, and display toggles.
- Create `plugins/ha_media_priority/server.py`: parse ordered entity IDs, fetch HA states once, select the first `playing` entity, return an empty state when none are playing.
- Create `plugins/ha_media_priority/client.js`: reuse `ha_media/client.js` through an ES module import.
- Create `plugins/ha_media_priority/tests/test_smoke.py`: cover priority selection, paused filtering, missing entities, errors, choices, and render smoke.
- Modify `plugins/ha_media/client.js`: use `ctx.cell.plugin_id` for the root `data-widget` value and render a quiet empty state when `data.empty` is true.
- Modify `app/widget_samples.py`: add a sample payload for the new widget so `/_test/widgets?sample=1` and `/_test/render?plugin=ha_media_priority&sample=1` show a real media card.

## Task 1: Extract Reusable HA Media State Shaping

**Files:**
- Create: `plugins/ha_media/tests/test_smoke.py`
- Modify: `plugins/ha_media/server.py`

- [ ] **Step 1: Write the failing normalizer test**

Create `plugins/ha_media/tests/test_smoke.py`:

```python
"""ha_media smoke: reusable media state shaping plus render mounting."""

from __future__ import annotations

from flask import Flask
from flask.testing import FlaskClient


def _mods(app: Flask):
    reg = app.config["PLUGIN_REGISTRY"]
    return reg.get("ha_media").server_module, reg.get("ha_core").server_module


def test_shape_media_state_normalizes_progress_volume_and_art(
    app: Flask, monkeypatch
) -> None:
    media, core = _mods(app)
    state = {
        "entity_id": "media_player.living_room",
        "state": "playing",
        "attributes": {
            "friendly_name": "Living Room",
            "media_title": "Light Years",
            "media_artist": "The National",
            "media_album_name": "Sleep Well Beast",
            "entity_picture": "/api/media_player_proxy/media_player.living_room?token=abc",
            "source": "Emby",
            "media_position": 92,
            "media_duration": 248,
            "volume_level": 0.64,
        },
    }

    with app.app_context():
        monkeypatch.setattr(core, "base_url", lambda: "http://ha.local:8123")
        out = media.shape_media_state(core, "media_player.living_room", state)

    assert out["entity_id"] == "media_player.living_room"
    assert out["name"] == "Living Room"
    assert out["state"] == "playing"
    assert out["title"] == "Light Years"
    assert out["artist"] == "The National"
    assert out["album"] == "Sleep Well Beast"
    assert out["source"] == "Emby"
    assert out["volume_pct"] == 64.0
    assert out["media_position"] == 92.0
    assert out["media_duration"] == 248.0
    assert out["position_pct"] == 37.1
    assert (
        out["art_url"]
        == "http://ha.local:8123/api/media_player_proxy/media_player.living_room?token=abc"
    )


def test_shape_media_state_collapses_standby_and_blanks_unknowns(app: Flask) -> None:
    media, core = _mods(app)
    state = {
        "entity_id": "media_player.apple_tv",
        "state": "standby",
        "attributes": {
            "friendly_name": "Apple TV",
            "media_title": "unknown",
            "media_artist": "unavailable",
            "entity_picture": "",
            "media_position": "unknown",
            "media_duration": "unavailable",
            "volume_level": "unknown",
        },
    }

    with app.app_context():
        out = media.shape_media_state(core, "media_player.apple_tv", state)

    assert out["state"] == "off"
    assert out["title"] == ""
    assert out["artist"] == ""
    assert out["art_url"] is None
    assert out["media_position"] is None
    assert out["media_duration"] is None
    assert out["position_pct"] is None
    assert out["volume_pct"] is None


def test_composer_mounts_widget(client: FlaskClient) -> None:
    resp = client.get("/_test/render?plugin=ha_media&size=md&sample=1")
    assert resp.status_code == 200
    assert 'data-plugin="ha_media"' in resp.get_data(as_text=True)
```

- [ ] **Step 2: Run the new test to verify it fails**

Run:

```bash
./.venv/bin/python -m pytest plugins/ha_media/tests/test_smoke.py::test_shape_media_state_normalizes_progress_volume_and_art -q
```

Expected: FAIL with `AttributeError` because `plugins.ha_media.server` does not yet expose `shape_media_state`.

- [ ] **Step 3: Add the reusable helper and make `fetch()` use it**

In `plugins/ha_media/server.py`, add this function after `_resolve_art(...)`:

```python
def shape_media_state(core: Any, entity_id: str, st: dict[str, Any]) -> dict[str, Any]:
    """Normalize one HA media_player state for ha_media-style clients."""
    attrs = st.get("attributes") or {}
    state = str(st.get("state") or "").lower()
    # HA's media_player domain reports state as one of:
    #   playing / paused / idle / off / standby / unavailable / unknown
    # We collapse standby + unknown into "off" so the client only has to
    # branch on four buckets.
    if state in ("unknown", ""):
        state = "off"
    if state == "standby":
        state = "off"

    position = _f_or_none(attrs.get("media_position"))
    duration = _f_or_none(attrs.get("media_duration"))
    pct: float | None = None
    if position is not None and duration and duration > 0:
        pct = max(0.0, min(100.0, (position / duration) * 100.0))

    volume = _f_or_none(attrs.get("volume_level"))
    volume_pct = None if volume is None else max(0.0, min(100.0, volume * 100.0))

    return {
        "entity_id": entity_id,
        "name": core.friendly_name(st),
        "state": state,
        "title": _str(attrs.get("media_title")),
        "artist": _str(attrs.get("media_artist")),
        "album": _str(attrs.get("media_album_name")),
        "art_url": _resolve_art(core, str(attrs.get("entity_picture") or "")),
        "source": _str(attrs.get("source") or attrs.get("app_name")),
        "volume_pct": round(volume_pct, 1) if volume_pct is not None else None,
        "media_position": position,
        "media_duration": duration,
        "position_pct": round(pct, 1) if pct is not None else None,
    }
```

Then replace the body of `fetch(...)` after the `if not st:` block with:

```python
    return shape_media_state(core, entity_id, st)
```

After this edit, the end of `fetch(...)` should be:

```python
    if not st:
        return {"error": f"Entity {entity_id} not found."}

    return shape_media_state(core, entity_id, st)
```

- [ ] **Step 4: Run the HA media tests to verify green**

Run:

```bash
./.venv/bin/python -m pytest plugins/ha_media/tests/test_smoke.py -q
```

Expected: PASS, 3 tests.

- [ ] **Step 5: Commit Task 1**

Run:

```bash
git add plugins/ha_media/server.py plugins/ha_media/tests/test_smoke.py
git commit -m "Refactor HA media state shaping"
```

## Task 2: Add Priority Selection Server Plugin

**Files:**
- Create: `plugins/ha_media_priority/plugin.json`
- Create: `plugins/ha_media_priority/server.py`
- Create: `plugins/ha_media_priority/client.js`
- Create: `plugins/ha_media_priority/tests/test_smoke.py`

- [ ] **Step 1: Write the failing priority-selection tests**

Create `plugins/ha_media_priority/tests/test_smoke.py`:

```python
"""ha_media_priority smoke: ordered HA media_player priority selection."""

from __future__ import annotations

from flask import Flask


_STATES = [
    {
        "entity_id": "media_player.apple_tv",
        "state": "paused",
        "attributes": {
            "friendly_name": "Apple TV",
            "media_title": "Paused Movie",
            "source": "Emby",
        },
    },
    {
        "entity_id": "media_player.emby",
        "state": "playing",
        "attributes": {
            "friendly_name": "Emby Theater",
            "media_title": "Dune",
            "media_artist": "",
            "media_album_name": "",
            "entity_picture": "/api/media_player_proxy/media_player.emby?token=abc",
            "source": "Emby",
            "media_position": 300,
            "media_duration": 9300,
            "volume_level": 0.42,
        },
    },
    {
        "entity_id": "media_player.sonos",
        "state": "playing",
        "attributes": {
            "friendly_name": "Living Room Sonos",
            "media_title": "Light Years",
            "media_artist": "The National",
            "media_album_name": "Sleep Well Beast",
            "entity_picture": "https://cdn.example.test/light-years.jpg",
            "source": "Apple Music",
            "media_position": 92,
            "media_duration": 248,
        },
    },
]


def _mods(app: Flask):
    reg = app.config["PLUGIN_REGISTRY"]
    return reg.get("ha_media_priority").server_module, reg.get("ha_core").server_module


def test_selects_first_playing_entity_by_configured_priority(
    app: Flask, monkeypatch
) -> None:
    priority, core = _mods(app)
    wanted = ["media_player.apple_tv", "media_player.emby", "media_player.sonos"]

    with app.app_context():
        monkeypatch.setattr(core, "get_states", lambda: _STATES)
        monkeypatch.setattr(core, "base_url", lambda: "http://ha.local:8123")
        out = priority.fetch({"entities": "\n".join(wanted)}, {}, ctx={})

    assert out["entity_id"] == "media_player.emby"
    assert out["selected_entity_id"] == "media_player.emby"
    assert out["checked_entities"] == wanted
    assert out["state"] == "playing"
    assert out["name"] == "Emby Theater"
    assert out["title"] == "Dune"
    assert out["source"] == "Emby"
    assert out["volume_pct"] == 42.0
    assert out["position_pct"] == 3.2
    assert (
        out["art_url"]
        == "http://ha.local:8123/api/media_player_proxy/media_player.emby?token=abc"
    )


def test_ignores_higher_priority_paused_entity(app: Flask, monkeypatch) -> None:
    priority, core = _mods(app)

    with app.app_context():
        monkeypatch.setattr(core, "get_states", lambda: _STATES)
        out = priority.fetch(
            {"entities": ["media_player.apple_tv", "media_player.sonos"]}, {}, ctx={}
        )

    assert out["entity_id"] == "media_player.sonos"
    assert out["title"] == "Light Years"


def test_missing_entities_are_skipped(app: Flask, monkeypatch) -> None:
    priority, core = _mods(app)

    with app.app_context():
        monkeypatch.setattr(core, "get_states", lambda: _STATES)
        out = priority.fetch(
            {"entities": "media_player.ghost\nmedia_player.emby"}, {}, ctx={}
        )

    assert out["entity_id"] == "media_player.emby"
    assert out["checked_entities"] == ["media_player.ghost", "media_player.emby"]


def test_empty_when_no_configured_entity_is_playing(app: Flask, monkeypatch) -> None:
    priority, core = _mods(app)
    states = [
        {"entity_id": "media_player.apple_tv", "state": "paused", "attributes": {}},
        {"entity_id": "media_player.sonos", "state": "idle", "attributes": {}},
    ]
    wanted = ["media_player.apple_tv", "media_player.sonos"]

    with app.app_context():
        monkeypatch.setattr(core, "get_states", lambda: states)
        out = priority.fetch({"entities": wanted}, {}, ctx={})

    assert out["empty"] is True
    assert out["state"] == "idle"
    assert out["name"] == "Media Priority"
    assert out["checked_entities"] == wanted
    assert "error" not in out


def test_empty_when_no_entities_configured(app: Flask) -> None:
    priority, _core = _mods(app)

    with app.app_context():
        out = priority.fetch({"entities": "  "}, {}, ctx={})

    assert out["empty"] is True
    assert out["checked_entities"] == []
    assert out["name"] == "Media Priority"


def test_fetch_surfaces_home_assistant_errors(app: Flask, monkeypatch) -> None:
    priority, core = _mods(app)

    def boom() -> list:
        raise RuntimeError("nope")

    with app.app_context():
        monkeypatch.setattr(core, "get_states", boom)
        monkeypatch.setattr(core, "coerce_error", lambda err: f"coerced: {err}")
        out = priority.fetch({"entities": "media_player.emby"}, {}, ctx={})

    assert out == {"error": "coerced: nope"}


def test_choices_delegates_to_media_player_entities(app: Flask, monkeypatch) -> None:
    priority, core = _mods(app)

    with app.app_context():
        monkeypatch.setattr(
            core,
            "entity_choices",
            lambda *a, **k: [{"value": "media_player.emby", "label": "Emby"}],
        )
        assert priority.choices("entity") == [
            {"value": "media_player.emby", "label": "Emby"}
        ]
        assert priority.choices("other") == []
```

- [ ] **Step 2: Run the priority tests to verify they fail**

Run:

```bash
./.venv/bin/python -m pytest plugins/ha_media_priority/tests/test_smoke.py::test_selects_first_playing_entity_by_configured_priority -q
```

Expected: FAIL with an error caused by missing `ha_media_priority` plugin registration.

- [ ] **Step 3: Add the new plugin manifest**

Create `plugins/ha_media_priority/plugin.json`:

```json
{
  "tesserae_compat": "1.x",
  "name": "Home Assistant, Media Priority",
  "version": "0.1.0",
  "kind": "widget",
  "description": "Now-playing tile that checks an ordered list of Home Assistant media_player entities and renders the first one that is currently playing. Paused, idle, off, unavailable, and missing entities are ignored. Requires the Home Assistant Core plugin.",
  "icon": "ph-stack",
  "supports": {
    "sizes": [
      "sm",
      "md",
      "lg"
    ]
  },
  "cell_options": [
    {
      "name": "entities",
      "type": "textarea",
      "label": "media_player priority list, one entity_id per line",
      "default": ""
    },
    {
      "name": "show_progress",
      "type": "boolean",
      "label": "Show progress bar",
      "default": true
    },
    {
      "name": "show_waveform",
      "type": "boolean",
      "label": "Show audio waveform glyph (per-track decorative)",
      "default": true
    },
    {
      "name": "show_art_bleed",
      "type": "boolean",
      "label": "Tint cell with blurred album art behind the body",
      "default": true
    }
  ],
  "render": {
    "dither": "none",
    "needs_network": true
  }
}
```

- [ ] **Step 4: Add the priority server implementation**

Create `plugins/ha_media_priority/server.py`:

```python
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
        if str(st.get("state") or "").lower() != "playing":
            continue
        out = media.shape_media_state(core, entity_id, st)
        out["selected_entity_id"] = entity_id
        out["checked_entities"] = entities
        return out

    return _empty(entities)
```

- [ ] **Step 5: Add the initial client module**

Create `plugins/ha_media_priority/client.js`:

```javascript
import renderMedia from "../ha_media/client.js";

export default renderMedia;
```

- [ ] **Step 6: Run priority server tests to verify green**

Run:

```bash
./.venv/bin/python -m pytest plugins/ha_media_priority/tests/test_smoke.py -q
```

Expected: PASS, 7 tests.

- [ ] **Step 7: Commit Task 2**

Run:

```bash
git add plugins/ha_media_priority/plugin.json plugins/ha_media_priority/server.py plugins/ha_media_priority/client.js plugins/ha_media_priority/tests/test_smoke.py
git commit -m "Add HA media priority selector"
```

## Task 3: Add Empty-State Rendering and Widget Sample

**Files:**
- Modify: `plugins/ha_media/client.js`
- Modify: `plugins/ha_media_priority/tests/test_smoke.py`
- Modify: `app/widget_samples.py`

- [ ] **Step 1: Write the failing sample and render smoke tests**

Append these tests to `plugins/ha_media_priority/tests/test_smoke.py`:

```python
def test_sample_payload_exists() -> None:
    from app.widget_samples import get_sample

    sample = get_sample("ha_media_priority")
    assert sample is not None
    assert sample["state"] == "playing"
    assert sample["selected_entity_id"] == "media_player.living_room"
    assert sample["checked_entities"] == [
        "media_player.apple_tv",
        "media_player.living_room",
        "media_player.living_room_sonos",
    ]


def test_composer_mounts_widget(client) -> None:
    resp = client.get("/_test/render?plugin=ha_media_priority&size=md&sample=1")
    assert resp.status_code == 200
    assert 'data-plugin="ha_media_priority"' in resp.get_data(as_text=True)
```

- [ ] **Step 2: Run the new sample test to verify it fails**

Run:

```bash
./.venv/bin/python -m pytest plugins/ha_media_priority/tests/test_smoke.py::test_sample_payload_exists -q
```

Expected: FAIL because `get_sample("ha_media_priority")` returns `None`.

- [ ] **Step 3: Make `ha_media/client.js` reusable by plugin id and add empty rendering**

In `plugins/ha_media/client.js`, add this helper after `stateAccent(...)`:

```javascript
function widgetIdFromCtx(ctx) {
  const raw = ctx?.cell?.plugin_id || ctx?.cell?.plugin || "ha_media";
  return String(raw).replace(/[^a-z0-9_-]/gi, "") || "ha_media";
}
```

At the start of `render(shadow, ctx)`, after `const data = ctx?.data ?? {};`, add:

```javascript
  const widgetId = widgetIdFromCtx(ctx);
```

In the error branch, change the root widget attribute from:

```javascript
      <div class="w" data-widget="ha_media">
```

to:

```javascript
      <div class="w" data-widget="${escapeHtml(widgetId)}">
```

Immediately after the error branch, add this empty-state branch:

```javascript
  if (data.empty) {
    const idleName = data.name || "Media Priority";
    shadow.innerHTML = `
      ${css}
      <div class="w" data-widget="${escapeHtml(widgetId)}">
        <div class="w-title">
          <i class="ph-bold ph-stack" style="color:var(--text-muted)"></i>
          <h3>${escapeHtml(idleName)}</h3>
          <span class="w-title-meta" style="color:var(--text-muted)">idle</span>
        </div>
        <div class="w-body img-body">
          <div class="img-hero"><i class="ph-bold ph-music-notes"></i></div>
          <div class="img-meta">
            <span class="title">No media playing</span>
            <span class="sub">Waiting for Home Assistant playback</span>
          </div>
        </div>
      </div>`;
    return;
  }
```

In the `layout` template string, replace each hard-coded selector:

```css
    .w[data-widget="ha_media"] {
```

with:

```css
    .w[data-widget="${widgetId}"] {
```

and replace this selector block:

```css
    .w[data-widget="ha_media"] .w-title,
    .w[data-widget="ha_media"] .w-body {
```

with:

```css
    .w[data-widget="${widgetId}"] .w-title,
    .w[data-widget="${widgetId}"] .w-body {
```

In the final widget markup, change:

```javascript
    <div class="w" data-widget="ha_media">
```

to:

```javascript
    <div class="w" data-widget="${escapeHtml(widgetId)}">
```

- [ ] **Step 4: Add the sample payload**

In `app/widget_samples.py`, add this function immediately after `_ha_media()`:

```python
def _ha_media_priority() -> dict[str, Any]:
    sample = _ha_media()
    sample["selected_entity_id"] = "media_player.living_room"
    sample["checked_entities"] = [
        "media_player.apple_tv",
        "media_player.living_room",
        "media_player.living_room_sonos",
    ]
    return sample
```

Then add this entry in `SAMPLES` immediately after `"ha_media": _ha_media,`:

```python
    "ha_media_priority": _ha_media_priority,
```

- [ ] **Step 5: Run the priority widget tests to verify green**

Run:

```bash
./.venv/bin/python -m pytest plugins/ha_media_priority/tests/test_smoke.py -q
```

Expected: PASS, 9 tests.

- [ ] **Step 6: Run HA media tests to verify the shared client/server path remains healthy**

Run:

```bash
./.venv/bin/python -m pytest plugins/ha_media/tests/test_smoke.py plugins/ha_media_priority/tests/test_smoke.py -q
```

Expected: PASS, 12 tests.

- [ ] **Step 7: Commit Task 3**

Run:

```bash
git add plugins/ha_media/client.js plugins/ha_media_priority/tests/test_smoke.py app/widget_samples.py
git commit -m "Render HA media priority widget"
```

## Task 4: Final Verification

**Files:**
- Verify: `plugins/ha_media/server.py`
- Verify: `plugins/ha_media/client.js`
- Verify: `plugins/ha_media_priority/plugin.json`
- Verify: `plugins/ha_media_priority/server.py`
- Verify: `plugins/ha_media_priority/client.js`
- Verify: `plugins/ha_media_priority/tests/test_smoke.py`
- Verify: `app/widget_samples.py`

- [ ] **Step 1: Run focused tests**

Run:

```bash
./.venv/bin/python -m pytest plugins/ha_media/tests/test_smoke.py plugins/ha_media_priority/tests/test_smoke.py -q
```

Expected: PASS.

- [ ] **Step 2: Run adjacent HA widget tests**

Run:

```bash
./.venv/bin/python -m pytest plugins/ha_core/tests/test_smoke.py plugins/ha_entities/tests/test_smoke.py plugins/ha_sensor/tests/test_smoke.py plugins/ha_media/tests/test_smoke.py plugins/ha_media_priority/tests/test_smoke.py -q
```

Expected: PASS.

- [ ] **Step 3: Run manifest/loader tests**

Run:

```bash
./.venv/bin/python -m pytest tests/test_plugin_loader.py tests/test_page_routes.py::test_multiselect_cell_option_coercion -q
```

Expected: PASS.

- [ ] **Step 4: Inspect final diff**

Run:

```bash
git diff --stat HEAD~3..HEAD
git status --short
```

Expected: the three implementation commits are present and `git status --short` is clean.

- [ ] **Step 5: Push the branch**

Run:

```bash
git push origin codex/seeed-e1004-support
```

Expected: push succeeds for branch `codex/seeed-e1004-support`.

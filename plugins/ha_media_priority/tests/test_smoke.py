"""ha_media_priority smoke: ordered HA media_player priority selection."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest
from flask import Flask


ROOT = Path(__file__).resolve().parents[3]


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


def test_ignores_non_exact_playing_state_values(app: Flask, monkeypatch) -> None:
    priority, core = _mods(app)
    states = [
        {"entity_id": "media_player.upper", "state": "PLAYING", "attributes": {}},
        {"entity_id": "media_player.mixed", "state": "Playing", "attributes": {}},
        {"entity_id": "media_player.none", "state": None, "attributes": {}},
    ]
    wanted = [
        "media_player.upper",
        "media_player.mixed",
        "media_player.none",
    ]

    with app.app_context():
        monkeypatch.setattr(core, "get_states", lambda: states)
        out = priority.fetch({"entities": wanted}, {}, ctx={})

    assert out["empty"] is True
    assert out["state"] == "idle"
    assert out["checked_entities"] == wanted


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
    html = resp.get_data(as_text=True)
    assert 'data-plugin="ha_media_priority"' in html
    assert "Light Years" in html
    assert "media_player.living_room" in html
    assert "media_player.living_room_sonos" in html


def _run_node_media_client(script: str) -> subprocess.CompletedProcess[str]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node executable is not available")
    return subprocess.run(
        [node, "--input-type=module", "-e", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_shared_client_renders_priority_widget_id_and_empty_state() -> None:
    client_url = (ROOT / "plugins/ha_media/client.js").as_uri()
    script = textwrap.dedent(
        f"""
        import assert from "node:assert/strict";

        const {{ default: render }} = await import({json.dumps(client_url)});

        function renderHtml(pluginId, data) {{
          const shadow = {{ innerHTML: "" }};
          render(shadow, {{ cell: {{ plugin_id: pluginId }}, data }});
          return shadow.innerHTML;
        }}

        const normal = renderHtml("ha_media_priority", {{
          name: "Living Room",
          state: "playing",
          title: "Light Years",
          artist: "The National",
          album: "Sleep Well Beast",
          media_duration: 248,
          media_position: 92,
          position_pct: 37,
        }});
        assert.match(normal, /data-widget="ha_media_priority"/);
        assert.match(normal, /Light Years/);
        assert.match(normal, /\\.w\\[data-widget="ha_media_priority"\\]/);

        const empty = renderHtml("ha_media_priority", {{
          empty: true,
          name: "Media Priority",
        }});
        assert.match(empty, /No media playing/);
        assert.match(empty, /Waiting for Home Assistant playback/);
        assert.match(empty, /data-widget="ha_media_priority"/);

        const sanitized = renderHtml('ha_media_priority"><script', {{
          empty: true,
          name: "Media Priority",
        }});
        assert.doesNotMatch(sanitized, /<script/);
        assert.match(sanitized, /data-widget="ha_media_priorityscript"/);
        """
    )

    result = _run_node_media_client(script)

    assert result.returncode == 0, result.stdout + result.stderr

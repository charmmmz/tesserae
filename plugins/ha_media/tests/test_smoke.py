"""ha_media smoke: reusable media state shaping plus render mounting."""

from __future__ import annotations

import pytest
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


@pytest.mark.parametrize("entity_picture", ["unavailable", "unknown"])
def test_shape_media_state_omits_art_placeholders(
    app: Flask, monkeypatch, entity_picture: str
) -> None:
    media, core = _mods(app)
    state = {
        "entity_id": "media_player.apple_tv",
        "state": "playing",
        "attributes": {
            "friendly_name": "Apple TV",
            "entity_picture": entity_picture,
        },
    }

    with app.app_context():
        monkeypatch.setattr(core, "base_url", lambda: "http://ha.local:8123")
        out = media.shape_media_state(core, "media_player.apple_tv", state)

    assert out["art_url"] is None


def test_composer_mounts_widget(client: FlaskClient) -> None:
    resp = client.get("/_test/render?plugin=ha_media&size=md&sample=1")
    assert resp.status_code == 200
    assert 'data-plugin="ha_media"' in resp.get_data(as_text=True)

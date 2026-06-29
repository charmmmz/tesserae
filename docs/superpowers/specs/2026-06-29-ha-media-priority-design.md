# HA Media Priority Widget Design

## Goal

Add a Tesserae widget that chooses the first currently playing Home Assistant media player from a user-configured priority list, then renders it with the existing now-playing visual treatment.

The first version is for the E1004 poster project flow:

1. Emby or Apple TV playing a movie should win.
2. Sonos or Apple TV playing music should win when no higher-priority movie source is playing.
3. If nothing is playing, the widget should not invent fallback content. Ambient/gallery content remains a separate dashboard or widget decision.

## Approved Behavior

Only Home Assistant entities with `state == "playing"` are eligible.

Entities in `paused`, `idle`, `standby`, `off`, `unavailable`, or `unknown` states are ignored. This prevents a paused Apple TV or Sonos session from blocking a lower-priority device that is actively playing.

## Chosen Approach

Create a new widget plugin named `ha_media_priority`.

This keeps the existing `ha_media` widget stable and gives the E1004 project a focused priority selector without requiring Home Assistant template entities or a larger Tesserae dashboard scheduler.

Rejected alternatives:

- Home Assistant template or universal media player: workable, but it moves priority logic into HA YAML and makes Tesserae harder to reason about.
- Dashboard switching from HA automations: useful later, but too coarse for a reusable now-playing tile.
- Extending `ha_media` directly: simpler initially, but it would mix single-entity and multi-entity behavior in one plugin.

## User Configuration

The widget accepts an ordered list of Home Assistant `media_player` entity IDs.

Example priority:

```text
media_player.living_room_apple_tv
media_player.emby_theater
media_player.living_room_sonos
```

The order is meaningful. The widget selects the first entity in that list whose HA state is exactly `playing`.

The widget should keep the same display options as `ha_media` where practical:

- Show title, artist, album, source, and cover art when HA provides them.
- Show progress only when HA provides valid position and duration values.
- Use the HA `entity_picture` URL as the artwork source, resolved through the existing HA core helper behavior.

## Data Flow

```text
Tesserae render cycle
  -> ha_media_priority server plugin
  -> ha_core.get_states()
  -> choose first configured media_player with state == playing
  -> normalize media attributes into the same shape as ha_media
  -> ha_media_priority client plugin renders the now-playing card
```

The plugin should fetch HA states once per render cycle and make the selection in Tesserae. It should not call Home Assistant once per configured entity.

## Empty State

When no configured entity is playing, the plugin returns a non-error empty state.

The client renders a quiet idle tile instead of showing stale media. This is intentionally distinct from ambient mode: ambient/gallery is handled by placing a separate widget on the dashboard or switching dashboards later.

## Error Handling

Home Assistant setup errors should continue to surface as visible widget errors, matching existing HA widgets.

Missing configured entities should not fail the whole widget. The widget should ignore missing entities and continue checking the rest of the priority list.

If every configured entity is missing or not playing, the widget returns the empty state.

## Testing

Tests should be written before implementation and cover:

- Selecting the first `playing` entity by configured priority.
- Ignoring a higher-priority `paused` entity when a lower-priority entity is `playing`.
- Returning an empty state when no configured entity is `playing`.
- Tolerating missing configured entities.
- Delegating entity choices to Home Assistant `media_player` entities.
- Rendering through the plugin test endpoint without crashing.

## Non-Goals

This version does not:

- Adapt Seeed E1004 firmware.
- Switch Tesserae dashboards.
- Generate cinema-style posters beyond the metadata/artwork HA already exposes.
- Fetch artwork directly from Emby.
- Implement paused-media fallback.
- Implement automatic source-type detection for movie versus music.

Those can be added after the priority widget proves the core HA media selection flow.

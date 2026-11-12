from __future__ import annotations

import logging
from typing import Any, Optional
from homeassistant.util import dt as dt_util

from homeassistant.components.media_player import (
    BrowseMedia,
    MediaClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.exceptions import HomeAssistantError
from .const import player_key, CONF_ENABLE_BROWSE, DEFAULT_ENABLE_BROWSE
from .client import XScheduleClient
from .coordinator import XScheduleCoordinator
from .const import DOMAIN, INTEGRATION_VERSION, slugify_entry_title

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client: XScheduleClient = data["client"]
    coordinator: XScheduleCoordinator = data["coordinator"]

    async_add_entities([XScheduleMediaPlayer(client, coordinator, entry)])


class XScheduleMediaPlayer(CoordinatorEntity[XScheduleCoordinator], MediaPlayerEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "xlights"

    def __init__(
        self,
        client: XScheduleClient,
        coordinator: XScheduleCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{player_key(entry)}:media_player"
        device_slug = slugify_entry_title(entry)
        # media_player.xlights_scheduler_<user_device_name>_xlights
        self.entity_id = f"media_player.{DOMAIN}_{device_slug}_xlights"
        self._last_volume_pct: int | None = None
        self._last_playlist: str | None = None
        self._attr_supported_features = (
            MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.STOP
            | MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_MUTE
            | MediaPlayerEntityFeature.SEEK
            | MediaPlayerEntityFeature.PLAY_MEDIA
            | MediaPlayerEntityFeature.SELECT_SOURCE
        )

    @property
    def supported_features(self):
        features = self._attr_supported_features
        if self._entry.options.get(CONF_ENABLE_BROWSE, DEFAULT_ENABLE_BROWSE):
            features |= MediaPlayerEntityFeature.BROWSE_MEDIA
        return features

    @property
    def device_info(self):
        xs_ver = (
            (self.coordinator.data or {}).get("version") if self.coordinator else None
        )
        return {
            "identifiers": {(DOMAIN, f"{player_key(self._entry)}")},
            "name": "xLights Scheduler",
            "manufacturer": "xLights",
            "model": "xSchedule",
            # Report xSchedule version as firmware; fall back to integration version
            "sw_version": xs_ver or INTEGRATION_VERSION,
        }

    @property
    def state(self):
        data = self.coordinator.data or {}
        status = (data.get("status") or "idle").lower()
        if status == "playing":
            return "playing"
        if status == "paused":
            return "paused"
        return "idle"

    @property
    def volume_level(self) -> Optional[float]:
        data = self.coordinator.data or {}
        vol = data.get("volume")
        try:
            v = int(vol)
            # Track last non-zero volume for reliable unmute
            if v > 0:
                self._last_volume_pct = v
            return max(0.0, min(1.0, v / 100.0))
        except Exception:
            return None

    @property
    def is_volume_muted(self) -> Optional[bool]:
        v = self.volume_level
        return v is not None and v <= 0.0

    @property
    def media_duration(self) -> Optional[int]:
        data = self.coordinator.data or {}
        try:
            return int(data.get("lengthms", 0)) / 1000
        except Exception:
            return None

    @property
    def media_position(self) -> Optional[int]:
        data = self.coordinator.data or {}
        try:
            return int(data.get("positionms", 0)) / 1000
        except Exception:
            return None

    @property
    def extra_state_attributes(self):
        data = self.coordinator.data or {}
        return {
            "config_entry_id": self._entry.entry_id,
            "playback_source": data.get("trigger", "idle"),
            "playlist_id": data.get("playlistid"),
            "step_id": data.get("stepid"),
            "schedule_id": data.get("scheduleid"),
            "schedule": data.get("schedulename"),
            "list_refresh_error": data.get("_lists_error"),
        }

    @property
    def media_title(self) -> Optional[str]:
        data = self.coordinator.data or {}
        step = data.get("step")
        playlist = data.get("playlist")
        if step and playlist:
            return f"{playlist}:  {step}"
        return step or playlist

    @property
    def source(self) -> Optional[str]:
        data = self.coordinator.data or {}
        return data.get("playlist")

    @property
    def source_list(self) -> Optional[list[str]]:
        playlists = (
            self.coordinator.data.get("_playlists") if self.coordinator.data else None
        )
        if not playlists:
            return None
        return [pl.get("name") for pl in playlists if pl.get("name")]

    async def async_select_source(self, source: str) -> None:
        # Treat source selection as queueing the playlist; user presses Play to start
        hass = self.hass
        if hass and DOMAIN in hass.data and self._entry.entry_id in hass.data[DOMAIN]:
            store = hass.data[DOMAIN][self._entry.entry_id]
            store["selected_playlist"] = source
            store.pop("selected_step", None)
        await self.coordinator.async_request_refresh()

    async def async_set_volume_level(self, volume: float) -> None:
        await self._client.set_volume(int(volume * 100))
        await self.coordinator.async_request_refresh()

    async def async_mute_volume(self, mute: bool) -> None:
        # Prefer deterministic behavior: set volume to 0 to mute; restore prior volume to unmute
        current = self.volume_level
        if mute:
            # Remember last non-zero volume
            if current is not None and current > 0.0:
                self._last_volume_pct = int(current * 100)
            await self._client.set_volume(0)
        else:
            restore = self._last_volume_pct if self._last_volume_pct is not None else 50
            await self._client.set_volume(restore)
        await self.coordinator.async_request_refresh()

    async def async_media_pause(self) -> None:
        async with self._client.control_lock:
            status = await self._client.get_playing_status()
            if status.get("status") == "playing":
                await self._client.pause_toggle()
            await self.coordinator.async_request_refresh()

    async def async_media_play(self) -> None:
        async with self._client.control_lock:
            status = await self._client.get_playing_status()
            await self._async_media_play(status)

    async def _async_media_play(self, data: dict[str, Any]) -> None:
        store = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        selected_playlist = None
        selected_step = None
        if isinstance(store, dict):
            selected_playlist = store.get("selected_playlist")
            selected_step = store.get("selected_step")

        current_playlist = data.get("playlist")

        if data.get("status") == "playing":
            return

        # If paused, prefer starting a newly selected playlist (or step) over resuming
        if data.get("status") == "paused":
            if selected_playlist and selected_playlist != current_playlist:
                playlist = selected_playlist
                if selected_step:
                    await self._client.play_step(playlist, selected_step)
                    if isinstance(store, dict):
                        store.pop("selected_step", None)
                else:
                    await self._client.play_playlist(playlist)
                await self.coordinator.async_request_refresh()
                return

            # No new playlist queued; just resume current playback
            status = await self._client.get_playing_status()
            if status.get("status") == "paused":
                await self._client.pause_toggle()
            await self.coordinator.async_request_refresh()
            return

        # If idle, try to start the selected playlist/step:
        # preferred queued playlist/step, then last known playlist, then first available

        playlist = selected_playlist or self._last_playlist
        if not playlist:
            playlists = (self.coordinator.data or {}).get("_playlists") or []
            if playlists:
                playlist = playlists[0].get("name")

        if not playlist:
            return

        if selected_step:
            await self._client.play_step(playlist, selected_step)
            if isinstance(store, dict):
                store.pop("selected_step", None)
        else:
            await self._client.play_playlist(playlist)

        await self.coordinator.async_request_refresh()

    async def async_media_stop(self) -> None:
        # Use Stop all now per requested behavior
        await self._client.stop_all_now()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        # Map power off to stop all now so a stop/power icon is always available in UI
        await self.async_media_stop()

    async def async_turn_on(self) -> None:
        # Map power on to play/resume behavior
        await self.async_media_play()

    async def async_media_seek(self, position: float) -> None:
        await self._client.seek_ms(int(position * 1000))
        await self.coordinator.async_request_refresh()

    @property
    def media_position_updated_at(self):
        # Provide timestamp so HA animates progress between polls
        if self.state != "playing":
            return None
        # Prefer coordinator-stamped fetch time; fallback to now
        ts = None
        try:
            ts = (self.coordinator.data or {}).get("_ts")
        except Exception:
            ts = None
        return ts or dt_util.utcnow()

    async def async_browse_media(
        self,
        media_content_type: Optional[str] = None,
        media_content_id: Optional[str] = None,
    ) -> BrowseMedia:
        if not self._entry.options.get(CONF_ENABLE_BROWSE, DEFAULT_ENABLE_BROWSE):
            raise HomeAssistantError(
                "Media browsing is disabled in integration options."
            )
        playlists = (
            self.coordinator.data.get("_playlists") if self.coordinator.data else []
        )

        if not media_content_id:
            root = BrowseMedia(
                title="xSchedule",
                media_class=MediaClass.DIRECTORY,
                media_content_type="xlights_root",
                media_content_id="root",
                can_play=False,
                can_expand=True,
                children=[],
            )
            pls_node = BrowseMedia(
                title="Playlists",
                media_class=MediaClass.DIRECTORY,
                media_content_type="xlights_playlists",
                media_content_id="playlists",
                can_play=False,
                can_expand=True,
                children=[],
            )
            # Do not embed children here; handle in the dedicated branch below
            root.children.append(pls_node)
            return root

        # Expand the Playlists directory node
        if media_content_type == "xlights_playlists":
            node = BrowseMedia(
                title="Playlists",
                media_class=MediaClass.DIRECTORY,
                media_content_type="xlights_playlists",
                media_content_id="playlists",
                can_play=False,
                can_expand=True,
                children=[
                    BrowseMedia(
                        title=pl.get("name", ""),
                        media_class=MediaClass.DIRECTORY,
                        media_content_type="xlights_playlist",
                        media_content_id=f"id:{pl['id']}",
                        can_play=True,
                        can_expand=True,
                    )
                    for pl in playlists or []
                ],
            )
            return node

        if media_content_type == "xlights_playlist":
            pl_ref = await self._client.playlist_reference(media_content_id)
            pl_name = next(
                (
                    p.get("name")
                    for p in playlists or []
                    if str(p.get("id")) == pl_ref[3:]
                ),
                media_content_id,
            )
            steps = await self._client.get_steps(pl_ref)
            node = BrowseMedia(
                title=pl_name,
                media_class=MediaClass.DIRECTORY,
                media_content_type="xlights_playlist",
                media_content_id=pl_ref,
                can_play=True,
                can_expand=True,
                children=[
                    BrowseMedia(
                        title=st.get("name", ""),
                        media_class=MediaClass.MUSIC,
                        media_content_type="xlights_step",
                        media_content_id=f"{pl_ref}|id:{st['id']}",
                        can_play=True,
                        can_expand=False,
                    )
                    for st in steps
                ],
            )
            return node

        if media_content_type == "xlights_step":
            title = "Step"
            if media_content_id and "|" in media_content_id:
                pl_ref, step_ref = media_content_id.split("|", 1)
                steps = await self._client.get_steps(pl_ref)
                title = next(
                    (
                        s.get("name")
                        for s in steps
                        if step_ref == f"id:{s.get('id')}" or step_ref == s.get("name")
                    ),
                    step_ref,
                )
            return BrowseMedia(
                title=title,
                media_class=MediaClass.MUSIC,
                media_content_type="xlights_step",
                media_content_id=media_content_id,
                can_play=True,
                can_expand=False,
            )

        return await self.async_browse_media()

    async def async_play_media(
        self, media_type: str, media_id: str, **kwargs: Any
    ) -> None:
        if media_type == "xlights_playlist":
            await self._client.play_playlist(media_id)
        elif media_type == "xlights_step":
            try:
                pl, step = media_id.split("|", 1)
            except ValueError:
                _LOGGER.warning("Invalid media_id for xlights_step: %s", media_id)
                return
            await self._client.play_step(pl, step)
        await self.coordinator.async_request_refresh()

    def _handle_coordinator_update(self) -> None:
        # Track last known playlist for play-from-idle convenience
        data = self.coordinator.data or {}
        pl = data.get("playlist")
        if pl:
            self._last_playlist = pl
        super()._handle_coordinator_update()

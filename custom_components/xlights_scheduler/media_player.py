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

from .client import XScheduleClient
from .coordinator import XScheduleCoordinator
from .const import DOMAIN, INTEGRATION_VERSION

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client: XScheduleClient = data["client"]
    coordinator: XScheduleCoordinator = data["coordinator"]

    async_add_entities([XScheduleMediaPlayer(client, coordinator, entry)])


class XScheduleMediaPlayer(CoordinatorEntity[XScheduleCoordinator], MediaPlayerEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "xlights"

    def __init__(self, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.data['host']}:{entry.data['port']}:media_player"
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
            | MediaPlayerEntityFeature.BROWSE_MEDIA
            | MediaPlayerEntityFeature.PLAY_MEDIA
            | MediaPlayerEntityFeature.SELECT_SOURCE
        )

    @property
    def device_info(self):
        xs_ver = (self.coordinator.data or {}).get("version") if self.coordinator else None
        return {
            "identifiers": {(DOMAIN, f"{self._entry.data['host']}:{self._entry.data['port']}")},
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
            return int(data.get("lengthms", 0)) // 1000
        except Exception:
            return None

    @property
    def media_position(self) -> Optional[int]:
        data = self.coordinator.data or {}
        try:
            return int(data.get("positionms", 0)) // 1000
        except Exception:
            return None

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
        playlists = self.coordinator.data.get("_playlists") if self.coordinator.data else None
        if not playlists:
            return None
        return [pl.get("name") for pl in playlists if pl.get("name")]

    async def async_select_source(self, source: str) -> None:
        await self._client.play_playlist(source)
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
        await self._client.pause_toggle()
        await self.coordinator.async_request_refresh()

    async def async_media_play(self) -> None:
        if self.state == "paused":
            await self._client.pause_toggle()
            await self.coordinator.async_request_refresh()
            return

        # If idle, try to start a playlist: preferred selected playlist, then last known, then first available
        sel = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get("selected_playlist")
        playlist = sel or self._last_playlist
        if not playlist:
            playlists = (self.coordinator.data or {}).get("_playlists") or []
            if playlists:
                playlist = playlists[0].get("name")
        if playlist:
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
        self, media_content_type: Optional[str] = None, media_content_id: Optional[str] = None
    ) -> BrowseMedia:
        playlists = self.coordinator.data.get("_playlists") if self.coordinator.data else []

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
                        media_content_id=pl.get("name", ""),
                        can_play=True,
                        can_expand=True,
                    )
                    for pl in playlists or []
                ],
            )
            return node

        if media_content_type == "xlights_playlist":
            pl_name = media_content_id
            steps = await self._client.get_steps(pl_name)
            node = BrowseMedia(
                title=pl_name,
                media_class=MediaClass.DIRECTORY,
                media_content_type="xlights_playlist",
                media_content_id=pl_name,
                can_play=True,
                can_expand=True,
                children=[
                    BrowseMedia(
                        title=st.get("name", ""),
                        media_class=MediaClass.MUSIC,
                        media_content_type="xlights_step",
                        media_content_id=f"{pl_name}|{st.get('name','')}",
                        can_play=True,
                        can_expand=False,
                    )
                    for st in steps
                ],
            )
            return node

        if media_content_type == "xlights_step":
            return BrowseMedia(
                title=media_content_id.split("|")[-1] if media_content_id else "Step",
                media_class=MediaClass.MUSIC,
                media_content_type="xlights_step",
                media_content_id=media_content_id,
                can_play=True,
                can_expand=False,
            )

        return await self.async_browse_media()

    async def async_play_media(self, media_type: str, media_id: str, **kwargs: Any) -> None:
        if media_type == "xlights_playlist":
            await self._client.play_playlist(media_id)
        elif media_type == "xlights_step":
            try:
                pl, step = media_id.split("|", 1)
            except ValueError:
                _LOGGER.warning("Invalid media_id for xlights_step: %s", media_id)
                return
            await self._client.command("Play playlist step", parameters=f"{pl},{step}")
        await self.coordinator.async_request_refresh()

    def _handle_coordinator_update(self) -> None:
        # Track last known playlist for play-from-idle convenience
        data = self.coordinator.data or {}
        pl = data.get("playlist")
        if pl:
            self._last_playlist = pl
        super()._handle_coordinator_update()

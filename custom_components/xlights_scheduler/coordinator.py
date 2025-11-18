from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict
from homeassistant.util import dt as dt_util

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import XScheduleClient
from .const import (
    CONF_POLL_IDLE,
    CONF_POLL_PLAYING,
    CONF_LISTS_REFRESH_SECS,
    DEFAULT_POLL_IDLE,
    DEFAULT_POLL_PLAYING,
    DEFAULT_LISTS_REFRESH_SECS,
    DOMAIN,
    EVENT_SCHEDULE_ENDED,
    EVENT_SCHEDULE_STARTED,
    EVENT_PLAYLIST_STARTED,
    EVENT_PLAYLIST_ENDED,
    EVENT_STEP_CHANGED,
    EVENT_OUTPUT_TOGGLED,
    EVENT_PLAYLIST_LOOP_CHANGED,
    EVENT_VERSION_CHANGED,
)

_LOGGER = logging.getLogger(__name__)


class XScheduleCoordinator(DataUpdateCoordinator[Dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, client: XScheduleClient, options: dict[str, Any]) -> None:
        self.client = client
        self._options = options or {}

        interval = dt.timedelta(seconds=self._options.get(CONF_POLL_IDLE, DEFAULT_POLL_IDLE))
        super().__init__(
            hass,
            _LOGGER,
            name="xlights_scheduler_coordinator",
            update_interval=interval,
        )

        self._last_playlists: list[dict[str, Any]] | None = None
        self._last_playlists_ts: dt.datetime | None = None
        self._lists_refresh_secs: int = self._options.get(
            CONF_LISTS_REFRESH_SECS, DEFAULT_LISTS_REFRESH_SECS
        )
        self._last_schedule_id: str | None = None
        self._last_version: str | None = None
        self._last_status: str | None = None
        self._last_playlist: str | None = None
        self._last_playlist_id: str | None = None
        self._last_step: str | None = None
        self._last_output: bool | None = None
        self._last_playlist_loop: bool | None = None

    def _apply_interval_for_status(self, status: str) -> None:
        playing = status in ("playing", "paused")
        seconds = (
            self._options.get(CONF_POLL_PLAYING, DEFAULT_POLL_PLAYING)
            if playing
            else self._options.get(CONF_POLL_IDLE, DEFAULT_POLL_IDLE)
        )
        interval = dt.timedelta(seconds=seconds)
        # HA versions before async_set_update_interval supported setting the attribute directly
        setter = getattr(self, "async_set_update_interval", None)
        if callable(setter):
            setter(interval)
        else:
            self.update_interval = interval

    async def _async_update_data(self) -> Dict[str, Any]:
        try:
            status = await self.client.get_playing_status()
        except Exception as err:
            raise UpdateFailed(err) from err

        if isinstance(status, dict) and status.get("status"):
            self._apply_interval_for_status(status.get("status", "idle"))
        else:
            self._apply_interval_for_status("idle")

        # If version changes (server restart/upgrade), force immediate refresh and fire event
        try:
            ver = status.get("version")
        except Exception:
            ver = None
        if ver and ver != self._last_version:
            self._last_playlists_ts = None
            self._last_version = ver
            self.hass.bus.async_fire(
                EVENT_VERSION_CHANGED,
                {
                    "version": ver,
                    "device": f"{DOMAIN}:{id(self)}",
                },
            )

        # Refresh playlists on first run and then periodically
        now = dt_util.utcnow()
        if (
            self._last_playlists is None
            or self._last_playlists_ts is None
            or (now - self._last_playlists_ts).total_seconds() > self._lists_refresh_secs
        ):
            try:
                self._last_playlists = await self.client.get_playlists()
                self._last_playlists_ts = now
            except Exception:
                pass

        status["_playlists"] = self._last_playlists or []
        # Stamp the time this payload was fetched so entities can animate progress
        status["_ts"] = dt_util.utcnow()

        # Fetch next scheduled playlist info (lightweight single query)
        try:
            next_sched = await self.client.query("GetNextScheduledPlayList")
            status["_next_scheduled"] = next_sched
        except Exception:
            status["_next_scheduled"] = None

        # Fire HA events on schedule start/stop
        cur_sched_id: str | None = None
        raw_id = str(status.get("scheduleid", "")) if isinstance(status, dict) else ""
        if status.get("status") in ("playing", "paused") and raw_id and raw_id.upper() != "N/A":
            cur_sched_id = raw_id

        if cur_sched_id and cur_sched_id != self._last_schedule_id:
            # schedule started (or changed)
            self.hass.bus.async_fire(
                EVENT_SCHEDULE_STARTED,
                {
                    "scheduleid": cur_sched_id,
                    "schedulename": status.get("schedulename"),
                    "playlistid": status.get("playlistid"),
                    "playlist": status.get("playlist"),
                    "scheduleend": status.get("scheduleend"),
                    "trigger": status.get("trigger"),
                    "device": f"{DOMAIN}:{id(self)}",
                },
            )

        if self._last_schedule_id and not cur_sched_id:
            # schedule ended
            self.hass.bus.async_fire(
                EVENT_SCHEDULE_ENDED,
                {
                    "scheduleid": self._last_schedule_id,
                },
            )

        self._last_schedule_id = cur_sched_id

        # Derived state for playlist/step/events
        cur_status = str(status.get("status") or "idle").lower()
        cur_playlist = status.get("playlist")
        cur_playlist_id = status.get("playlistid")
        cur_step = status.get("step")
        cur_step_id = status.get("stepid")
        cur_output = str(status.get("outputtolights") or "false").lower() == "true"
        cur_loop = str(status.get("playlistlooping") or "false").lower() == "true"

        # Playlist start/end (covers idle<->playing and playlist changes while playing)
        if self._last_playlist and (
            cur_playlist != self._last_playlist or cur_status not in ("playing", "paused")
        ):
            self.hass.bus.async_fire(
                EVENT_PLAYLIST_ENDED,
                {
                    "playlist": self._last_playlist,
                    "playlistid": self._last_playlist_id,
                    "status": cur_status,
                    "device": f"{DOMAIN}:{id(self)}",
                },
            )

        if cur_status in ("playing", "paused"):
            if cur_playlist and (
                self._last_status not in ("playing", "paused")
                or cur_playlist != self._last_playlist
            ):
                self.hass.bus.async_fire(
                    EVENT_PLAYLIST_STARTED,
                    {
                        "playlist": cur_playlist,
                        "playlistid": cur_playlist_id,
                        "status": cur_status,
                        "trigger": status.get("trigger"),
                        "device": f"{DOMAIN}:{id(self)}",
                    },
                )

        # Step changed
        if cur_step != self._last_step:
            if cur_step or self._last_step:
                self.hass.bus.async_fire(
                    EVENT_STEP_CHANGED,
                    {
                        "playlist": cur_playlist,
                        "playlistid": cur_playlist_id,
                        "step": cur_step,
                        "stepid": cur_step_id,
                        "previous_step": self._last_step,
                        "status": cur_status,
                        "device": f"{DOMAIN}:{id(self)}",
                    },
                )

        # Output to lights toggled
        if self._last_output is not None and cur_output != self._last_output:
            self.hass.bus.async_fire(
                EVENT_OUTPUT_TOGGLED,
                {
                    "state": cur_output,
                    "playlist": cur_playlist,
                    "playlistid": cur_playlist_id,
                    "status": cur_status,
                    "device": f"{DOMAIN}:{id(self)}",
                },
            )

        # Playlist loop state changed
        if self._last_playlist_loop is not None and cur_loop != self._last_playlist_loop:
            self.hass.bus.async_fire(
                EVENT_PLAYLIST_LOOP_CHANGED,
                {
                    "loop": cur_loop,
                    "playlist": cur_playlist,
                    "playlistid": cur_playlist_id,
                    "status": cur_status,
                    "device": f"{DOMAIN}:{id(self)}",
                },
            )

        # Update last-known state for next cycle
        self._last_status = cur_status
        self._last_playlist = cur_playlist
        self._last_playlist_id = cur_playlist_id
        self._last_step = cur_step
        self._last_output = cur_output
        self._last_playlist_loop = cur_loop

        return status

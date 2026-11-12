from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Dict
from homeassistant.util import dt as dt_util

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from homeassistant.exceptions import ConfigEntryAuthFailed
from .client import XScheduleClient, XScheduleAuthError
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
    def __init__(
        self,
        hass: HomeAssistant,
        client: XScheduleClient,
        options: dict[str, Any],
        entry_id: str | None = None,
    ) -> None:
        self.client = client
        self.entry_id = entry_id or f"{client.host}:{client.port}"
        self.event_context = {
            "device": f"{DOMAIN}:{self.entry_id}",
            "config_entry_id": self.entry_id,
            "host": client.host,
            "port": client.port,
            "base_url": client.base_url,
        }
        # Upstream's status API does not expose these states.
        self.test_mode: bool | None = None
        self.background_playlist: str | None = None
        self.list_error: str | None = None
        self._options = dict(options or {})

        interval = dt.timedelta(
            seconds=self._options.get(CONF_POLL_IDLE, DEFAULT_POLL_IDLE)
        )
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
        self._last_schedule_name: str | None = None
        self._last_schedule_end: str | None = None
        self._last_version: str | None = None
        self._last_status: str | None = None
        self._last_playlist: str | None = None
        self._last_playlist_id: str | None = None
        self._last_step: str | None = None
        self._last_step_key = None
        self._last_output: bool | None = None
        self._last_playlist_loop: bool | None = None

        self._last_next_scheduled: Dict[str, Any] | None = None
        self._last_next_scheduled_ts: dt.datetime | None = None

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

    async def _async_compute_next_scheduled(self) -> Dict[str, Any] | None:
        now = dt_util.utcnow()
        if (
            self._last_next_scheduled is not None
            and self._last_next_scheduled_ts is not None
            and (now - self._last_next_scheduled_ts).total_seconds()
            <= self._lists_refresh_secs
        ):
            return self._last_next_scheduled

        playlists = self._last_playlists or []
        best: Dict[str, Any] | None = None
        best_start: dt.datetime | None = None

        for pl in playlists:
            name = pl.get("name")
            if not name:
                continue
            try:
                js = await self.client.query(
                    "GetPlayListSchedules",
                    parameters=f"id:{pl['id']}" if pl.get("id") is not None else name,
                )
            except Exception as error:
                self.list_error = str(error)
                _LOGGER.warning("Cannot refresh schedules for %s: %s", name, error)
                continue
            schedules = js.get("schedules") or []
            for sch in schedules:
                enabled = str(sch.get("enabled", "")).upper()
                active = str(sch.get("active", "")).upper()
                if enabled != "TRUE" or active == "TRUE":
                    continue
                next_active = str(sch.get("nextactive") or "").strip()
                if not next_active:
                    continue
                na_upper = next_active.upper()
                if na_upper in ("NEVER", "NOW!", "DONE") or "LONG TIME" in na_upper:
                    continue
                try:
                    dt_start = dt_util.parse_datetime(next_active)
                except Exception:
                    dt_start = None
                if dt_start is None:
                    continue
                dt_start = dt_util.as_utc(dt_start)
                if dt_start <= now:
                    continue
                if best_start is None or dt_start < best_start:
                    best_start = dt_start
                    best = {
                        "playlistname": name,
                        "playlistid": pl.get("id"),
                        "schedulename": sch.get("name"),
                        "scheduleid": sch.get("id"),
                        "start": next_active,
                        "end": sch.get("scheduleend") or "",
                    }

        if best is None:
            result: Dict[str, Any] = {
                "playlistname": "",
                "playlistid": "",
                "schedulename": "",
                "scheduleid": "",
                "start": "Never",
                "end": "",
            }
        else:
            result = best

        self._last_next_scheduled = result
        self._last_next_scheduled_ts = now
        return result

    async def _async_update_data(self) -> Dict[str, Any]:
        try:
            status = await self.client.get_playing_status()
        except XScheduleAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except Exception as err:
            raise UpdateFailed(str(err)) from err

        fetched_at = dt_util.utcnow()
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
            self._last_next_scheduled = None
            self._last_next_scheduled_ts = None
            self.hass.bus.async_fire(
                EVENT_VERSION_CHANGED,
                {
                    "version": ver,
                    **self.event_context,
                },
            )

        # Refresh playlists on first run and then periodically
        now = dt_util.utcnow()
        if (
            self._last_playlists is None
            or self._last_playlists_ts is None
            or (now - self._last_playlists_ts).total_seconds()
            > self._lists_refresh_secs
        ):
            try:
                self._last_playlists = await self.client.get_playlists()
                self.list_error = None
                self._last_playlists_ts = now
                self._last_next_scheduled = None
                self._last_next_scheduled_ts = None
            except Exception as error:
                self.list_error = str(error)
                _LOGGER.warning(
                    "Cannot refresh playlists; retaining last successful list: %s",
                    error,
                )

        status["_lists_error"] = self.list_error
        status["_playlists"] = self._last_playlists or []
        # Stamp the time this payload was fetched so entities can animate progress
        status["_ts"] = fetched_at

        try:
            next_sched = await self._async_compute_next_scheduled()
            status["_next_scheduled"] = next_sched
        except Exception:
            status["_next_scheduled"] = None
        status["_lists_error"] = self.list_error

        # Fire HA events on schedule start/stop
        cur_sched_id: str | None = None
        raw_id = str(status.get("scheduleid") or "") if isinstance(status, dict) else ""
        if (
            status.get("status") in ("playing", "paused")
            and raw_id
            and raw_id.upper() != "N/A"
        ):
            cur_sched_id = raw_id

        if self._last_schedule_id and cur_sched_id != self._last_schedule_id:
            # schedule ended
            self.hass.bus.async_fire(
                EVENT_SCHEDULE_ENDED,
                {
                    "scheduleid": self._last_schedule_id,
                    "schedulename": self._last_schedule_name,
                    "scheduleend": self._last_schedule_end,
                    "playlistid": self._last_playlist_id,
                    "playlist": self._last_playlist,
                    **self.event_context,
                    "host": self.client.host,
                    "port": self.client.port,
                    "base_url": self.client.base_url,
                },
            )
            self._last_schedule_name = None
            self._last_schedule_end = None

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
                    **self.event_context,
                    "host": self.client.host,
                    "port": self.client.port,
                    "base_url": self.client.base_url,
                },
            )
            # Remember schedule context for matching ended event
            self._last_schedule_name = status.get("schedulename")
            self._last_schedule_end = status.get("scheduleend")

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
            cur_playlist != self._last_playlist
            or cur_status not in ("playing", "paused")
        ):
            self.hass.bus.async_fire(
                EVENT_PLAYLIST_ENDED,
                {
                    "playlist": self._last_playlist,
                    "playlistid": self._last_playlist_id,
                    "status": cur_status,
                    **self.event_context,
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
                        **self.event_context,
                    },
                )

        # Step changed
        step_key = (cur_playlist_id or cur_playlist, cur_step_id or cur_step)
        if step_key != self._last_step_key:
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
                        **self.event_context,
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
                    **self.event_context,
                },
            )

        # Playlist loop state changed
        if (
            self._last_playlist_loop is not None
            and cur_loop != self._last_playlist_loop
        ):
            self.hass.bus.async_fire(
                EVENT_PLAYLIST_LOOP_CHANGED,
                {
                    "loop": cur_loop,
                    "playlist": cur_playlist,
                    "playlistid": cur_playlist_id,
                    "status": cur_status,
                    **self.event_context,
                },
            )

        # Update last-known state for next cycle
        self._last_status = cur_status
        self._last_playlist = cur_playlist
        self._last_playlist_id = cur_playlist_id
        self._last_step = cur_step
        self._last_step_key = step_key
        self._last_output = cur_output
        self._last_playlist_loop = cur_loop

        return status

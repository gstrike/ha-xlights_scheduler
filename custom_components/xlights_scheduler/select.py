from __future__ import annotations

import logging
from typing import Any
from homeassistant.util import dt as dt_util

from homeassistant.components.select import SelectEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import XScheduleClient
from .coordinator import XScheduleCoordinator
from .const import DOMAIN, INTEGRATION_VERSION, slugify_entry_title

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client: XScheduleClient = data["client"]
    coordinator: XScheduleCoordinator = data["coordinator"]

    async_add_entities([
        PlaylistSelect(hass, client, coordinator, entry),
        StepSelect(hass, client, coordinator, entry),
        BackgroundPlaylistSelect(hass, client, coordinator, entry),
    ])


class PlaylistSelect(CoordinatorEntity[XScheduleCoordinator], SelectEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "playlist"
    _attr_icon = "mdi:playlist-music"

    def __init__(self, hass: HomeAssistant, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.hass = hass
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.data['host']}:{entry.data['port']}:select_playlist"
        device_slug = slugify_entry_title(entry)
        self.entity_id = f"select.{DOMAIN}_{device_slug}_playlist"

    @property
    def device_info(self):
        xs_ver = (self.coordinator.data or {}).get("version") if self.coordinator else None
        return {
            "identifiers": {(DOMAIN, f"{self._entry.data['host']}:{self._entry.data['port']}")},
            "name": "xLights Scheduler",
            "manufacturer": "xLights",
            "model": "xSchedule",
            "sw_version": xs_ver or INTEGRATION_VERSION,
        }

    @property
    def options(self) -> list[str]:
        playlists = self.coordinator.data.get("_playlists") if self.coordinator.data else []
        return [pl.get("name") for pl in playlists or [] if pl.get("name")]

    @property
    def current_option(self) -> str | None:
        sel = self.hass.data[DOMAIN][self._entry.entry_id].get("selected_playlist")
        if sel:
            return sel
        data = self.coordinator.data or {}
        return data.get("playlist")

    async def async_select_option(self, option: str) -> None:
        store = self.hass.data[DOMAIN][self._entry.entry_id]
        store["selected_playlist"] = option
        # Clearing any queued step avoids an inconsistent combination
        store.pop("selected_step", None)
        await self.coordinator.async_request_refresh()


class StepSelect(CoordinatorEntity[XScheduleCoordinator], SelectEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "step"
    _attr_icon = "mdi:format-list-numbered"

    def __init__(self, hass: HomeAssistant, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.hass = hass
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.data['host']}:{entry.data['port']}:select_step"
        device_slug = slugify_entry_title(entry)
        self.entity_id = f"select.{DOMAIN}_{device_slug}_step"
        self._cached_steps: dict[str, list[str]] = {}
        self._last_playlist: str | None = None
        self._steps_cache_ts: dict[str, Any] = {}
        # Shorter TTL so step lists keep fresh more quickly after changes
        self._steps_ttl_secs: int = 15

    @property
    def device_info(self):
        xs_ver = (self.coordinator.data or {}).get("version") if self.coordinator else None
        return {
            "identifiers": {(DOMAIN, f"{self._entry.data['host']}:{self._entry.data['port']}")},
            "name": "xLights Scheduler",
            "manufacturer": "xLights",
            "model": "xSchedule",
            "sw_version": xs_ver or INTEGRATION_VERSION,
        }

    def _get_active_playlist(self) -> str | None:
        sel = self.hass.data[DOMAIN][self._entry.entry_id].get("selected_playlist")
        if sel:
            return sel
        data = self.coordinator.data or {}
        return data.get("playlist")

    @property
    def options(self) -> list[str]:
        pl = self._get_active_playlist()
        if not pl:
            return []
        if pl in self._cached_steps:
            return self._cached_steps[pl]
        return []

    @property
    def available(self) -> bool:
        return bool(self._get_active_playlist())

    @property
    def current_option(self) -> str | None:
        data = self.coordinator.data or {}
        return data.get("step")

    async def async_update(self) -> None:
        pl = self._get_active_playlist()
        if pl:
            need_refresh = False
            if pl not in self._cached_steps:
                need_refresh = True
            else:
                ts = self._steps_cache_ts.get(pl)
                if not ts or (dt_util.utcnow() - ts).total_seconds() > self._steps_ttl_secs:
                    need_refresh = True
            if need_refresh:
                steps = await self._client.get_steps(pl)
                self._cached_steps[pl] = [s.get("name") for s in steps if s.get("name")]
                self._steps_cache_ts[pl] = dt_util.utcnow()

    def _handle_coordinator_update(self) -> None:
        pl = self._get_active_playlist()
        if pl:
            expired = False
            if pl in self._steps_cache_ts:
                expired = (dt_util.utcnow() - self._steps_cache_ts[pl]).total_seconds() > self._steps_ttl_secs
            if pl != self._last_playlist or expired or pl not in self._cached_steps:
                self._last_playlist = pl
                self.hass.async_create_task(self.async_update())
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        pl = self._get_active_playlist()
        if not pl:
            return
        store = self.hass.data[DOMAIN][self._entry.entry_id]
        store["selected_playlist"] = pl
        store["selected_step"] = option
        await self._client.command("Play playlist step", parameters=f"{pl},{option}")
        await self.coordinator.async_request_refresh()


class BackgroundPlaylistSelect(CoordinatorEntity[XScheduleCoordinator], SelectEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "background_playlist"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:playlist-music-outline"

    def __init__(self, hass: HomeAssistant, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.hass = hass
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.data['host']}:{entry.data['port']}:select_background_playlist"
        device_slug = slugify_entry_title(entry)
        self.entity_id = f"select.{DOMAIN}_{device_slug}_background_playlist"

    @property
    def device_info(self):
        xs_ver = (self.coordinator.data or {}).get("version") if self.coordinator else None
        return {
            "identifiers": {(DOMAIN, f"{self._entry.data['host']}:{self._entry.data['port']}")},
            "name": "xLights Scheduler",
            "manufacturer": "xLights",
            "model": "xSchedule",
            "sw_version": xs_ver or INTEGRATION_VERSION,
        }

    @property
    def options(self) -> list[str]:
        playlists = self.coordinator.data.get("_playlists") if self.coordinator.data else []
        names = [pl.get("name") for pl in playlists or [] if pl.get("name")]
        return ["Clear background"] + names

    @property
    def current_option(self) -> str | None:
        return self.hass.data[DOMAIN][self._entry.entry_id].get("background_playlist")

    async def async_select_option(self, option: str) -> None:
        if option == "Clear background":
            await self._client.command("Clear background playlist")
            self.hass.data[DOMAIN][self._entry.entry_id]["background_playlist"] = None
        else:
            await self._client.command("Set playlist as background", parameters=option)
            self.hass.data[DOMAIN][self._entry.entry_id]["background_playlist"] = option
        await self.coordinator.async_request_refresh()

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
try:
    # Newer HA exposes SensorDeviceClass.VERSION; older builds may not
    from homeassistant.components.sensor import SensorDeviceClass  # type: ignore[attr-defined]
except Exception:  # pragma: no cover - compatibility fallback
    SensorDeviceClass = None  # type: ignore[assignment]
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

    async_add_entities(
        [
            PlaylistStepCountSensor(hass, client, coordinator, entry),
            CurrentPlaylistStepSensor(client, coordinator, entry),
            NextScheduledSensor(client, coordinator, entry),
            NextScheduledPlaylistSensor(client, coordinator, entry),
            XScheduleVersionSensor(client, coordinator, entry),
        ]
    )


class PlaylistStepCountSensor(CoordinatorEntity[XScheduleCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "playlist_step_count"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:counter"

    def __init__(self, hass: HomeAssistant, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self.hass = hass
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.data['host']}:{entry.data['port']}:sensor_playlist_step_count"
        device_slug = slugify_entry_title(entry)
        self.entity_id = f"sensor.{DOMAIN}_{device_slug}_playlist_step_count"
        self._count: int = 0
        self._last_playlist: str | None = None
        self._cache_ts: Any = None
        self._ttl_secs: int = 15

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
    def native_value(self):
        return self._count

    async def async_update(self) -> None:
        pl = self._get_active_playlist()
        if not pl:
            self._count = 0
            return
        steps = await self._client.get_steps(pl)
        self._count = len([s for s in steps if s.get("name")])

    def _handle_coordinator_update(self) -> None:
        from homeassistant.util import dt as dt_util  # local import to avoid top-level dependency

        pl = self._get_active_playlist()
        need = False
        if pl != self._last_playlist:
            need = True
        else:
            if self._cache_ts is None or (dt_util.utcnow() - self._cache_ts).total_seconds() > self._ttl_secs:
                need = True
        if need:
            self._last_playlist = pl
            self._cache_ts = dt_util.utcnow()
            self.hass.async_create_task(self.async_update())
        self.async_write_ha_state()


class CurrentPlaylistStepSensor(CoordinatorEntity[XScheduleCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "current_playlist_step"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:playlist-play"

    def __init__(self, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.data['host']}:{entry.data['port']}:sensor_current_playlist_step"
        device_slug = slugify_entry_title(entry)
        self.entity_id = f"sensor.{DOMAIN}_{device_slug}_current_playlist_step"

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
    def native_value(self):
        data = self.coordinator.data or {}
        return data.get("step") or None


class NextScheduledSensor(CoordinatorEntity[XScheduleCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "next_scheduled_start"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.data['host']}:{entry.data['port']}:sensor_next_scheduled"
        self._attr_icon = "mdi:calendar-clock"
        self._state: Any = None
        self._attrs: dict[str, Any] = {}
        device_slug = slugify_entry_title(entry)
        self.entity_id = f"sensor.{DOMAIN}_{device_slug}_next_scheduled_start"

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
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attrs

    @property
    def native_value(self):
        return self._state

    def _handle_coordinator_update(self) -> None:
        js = (self.coordinator.data or {}).get("_next_scheduled") or {}
        start = js.get("start")
        end = js.get("end")
        playlistname = js.get("playlistname")
        schedulename = js.get("schedulename")

        self._state = start
        self._attrs = {
            "playlist": playlistname,
            "schedule": schedulename,
            "end": end,
        }
        self.async_write_ha_state()


class NextScheduledPlaylistSensor(CoordinatorEntity[XScheduleCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "next_scheduled_playlist"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:playlist-music"

    def __init__(self, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.data['host']}:{entry.data['port']}:sensor_next_scheduled_playlist"
        self._state: Any = None
        self._attrs: dict[str, Any] = {}
        device_slug = slugify_entry_title(entry)
        self.entity_id = f"sensor.{DOMAIN}_{device_slug}_next_scheduled_playlist"

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
    def extra_state_attributes(self) -> dict[str, Any]:
        return self._attrs

    @property
    def native_value(self):
        return self._state

    def _handle_coordinator_update(self) -> None:
        js = (self.coordinator.data or {}).get("_next_scheduled") or {}
        playlistname = js.get("playlistname")
        schedulename = js.get("schedulename")
        start = js.get("start")
        end = js.get("end")

        self._state = playlistname
        self._attrs = {
            "schedule": schedulename,
            "start": start,
            "end": end,
        }
        self.async_write_ha_state()


class XScheduleVersionSensor(CoordinatorEntity[XScheduleCoordinator], SensorEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "xschedule_version"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = True
    # Set device class only if supported in this HA version
    if SensorDeviceClass is not None and hasattr(SensorDeviceClass, "VERSION"):
        _attr_device_class = SensorDeviceClass.VERSION

    def __init__(self, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.data['host']}:{entry.data['port']}:sensor_xschedule_version"
        self._attr_icon = "mdi:information-outline"
        device_slug = slugify_entry_title(entry)
        self.entity_id = f"sensor.{DOMAIN}_{device_slug}_xschedule_version"

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
    def native_value(self):
        return (self.coordinator.data or {}).get("version") or "Unknown"

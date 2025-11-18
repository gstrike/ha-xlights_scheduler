from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .client import XScheduleClient
from .coordinator import XScheduleCoordinator
from .const import (
    DOMAIN,
    INTEGRATION_VERSION,
    EVENT_TEST_MODE_STARTED,
    EVENT_TEST_MODE_STOPPED,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    client: XScheduleClient = data["client"]
    coordinator: XScheduleCoordinator = data["coordinator"]

    async_add_entities(
        [
            OutputToLightsSwitch(client, coordinator, entry),
            PlaylistLoopSwitch(client, coordinator, entry),
            TestModeSwitch(client, coordinator, entry),
        ]
    )


class OutputToLightsSwitch(CoordinatorEntity[XScheduleCoordinator], SwitchEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "output_to_lights"

    def __init__(self, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.data['host']}:{entry.data['port']}:switch_output_to_lights"
    
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
    def is_on(self) -> bool:
        data = self.coordinator.data or {}
        return (data.get("outputtolights") or "false") == "true"

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not self.is_on:
            await self._client.toggle_output_to_lights()
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.is_on:
            await self._client.toggle_output_to_lights()
            await self.coordinator.async_request_refresh()


class PlaylistLoopSwitch(CoordinatorEntity[XScheduleCoordinator], SwitchEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "playlist_loop"

    def __init__(self, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.data['host']}:{entry.data['port']}:switch_playlist_loop"
    
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
    def available(self) -> bool:
        data = self.coordinator.data or {}
        return data.get("status") in ("playing", "paused")

    @property
    def is_on(self) -> bool:
        data = self.coordinator.data or {}
        return (data.get("playlistlooping") or "false") == "true"

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not self.is_on:
            await self._client.toggle_playlist_loop()
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.is_on:
            await self._client.toggle_playlist_loop()
            await self.coordinator.async_request_refresh()


class TestModeSwitch(CoordinatorEntity[XScheduleCoordinator], SwitchEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "test_mode"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.data['host']}:{entry.data['port']}:switch_test_mode"

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
    def is_on(self) -> bool:
        # Optimistic: remember last requested state
        return bool(self.hass.data[DOMAIN][self._entry.entry_id].get("test_mode", False))

    async def async_turn_on(self, **kwargs: Any) -> None:
        # xSchedule requires at least one parameter: test mode name
        # Valid modes: Alternate, Foreground, A-B-C, A-B-C-All, A-B-C-All-None, A, B, C
        mode = "Alternate"
        res = await self._client.command("Start test mode", parameters=mode)
        if res.get("result") == "ok":
            self.hass.data[DOMAIN][self._entry.entry_id]["test_mode"] = True
            self.hass.bus.async_fire(
                EVENT_TEST_MODE_STARTED,
                {
                    "mode": mode,
                    "device": f"{DOMAIN}:{self._entry.data['host']}:{self._entry.data['port']}",
                },
            )
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        res = await self._client.command("Stop test mode")
        if res.get("result") == "ok":
            self.hass.data[DOMAIN][self._entry.entry_id]["test_mode"] = False
            self.hass.bus.async_fire(
                EVENT_TEST_MODE_STOPPED,
                {
                    "device": f"{DOMAIN}:{self._entry.data['host']}:{self._entry.data['port']}",
                },
            )
            await self.coordinator.async_request_refresh()

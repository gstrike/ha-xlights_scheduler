from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity
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

    async_add_entities([BrightnessNumber(client, coordinator, entry)])


class BrightnessNumber(CoordinatorEntity[XScheduleCoordinator], NumberEntity):
    _attr_has_entity_name = True
    _attr_translation_key = "brightness"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_icon = "mdi:brightness-6"
    _attr_native_unit_of_measurement = "%"

    def __init__(self, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.data['host']}:{entry.data['port']}:number_brightness"

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
        try:
            return int(data.get("brightness"))
        except Exception:
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self._client.command("Set brightness to n%", parameters=str(int(value)))
        await self.coordinator.async_request_refresh()

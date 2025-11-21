from __future__ import annotations

import logging
from homeassistant.components.button import ButtonEntity
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
            NextStepButton(client, coordinator, entry),
            PriorStepButton(client, coordinator, entry),
            RestartStepButton(client, coordinator, entry),
            StopAllNowButton(client, coordinator, entry),
            CloseXScheduleButton(client, coordinator, entry),
        ]
    )


class BaseXScheduleButton(CoordinatorEntity[XScheduleCoordinator], ButtonEntity):
    def __init__(self, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._client = client
        self._entry = entry

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


class NextStepButton(BaseXScheduleButton):
    _attr_has_entity_name = True
    _attr_translation_key = "next_step"
    _attr_icon = "mdi:skip-next"

    def __init__(self, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(client, coordinator, entry)
        device_slug = slugify_entry_title(entry)
        self.entity_id = f"button.{DOMAIN}_{device_slug}_next_step"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.data['host']}:{self._entry.data['port']}:button_next"

    async def async_press(self) -> None:
        await self._client.next_step()
        await self.coordinator.async_request_refresh()


class PriorStepButton(BaseXScheduleButton):
    _attr_has_entity_name = True
    _attr_translation_key = "prior_step"
    _attr_icon = "mdi:skip-previous"

    def __init__(self, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(client, coordinator, entry)
        device_slug = slugify_entry_title(entry)
        self.entity_id = f"button.{DOMAIN}_{device_slug}_prior_step"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.data['host']}:{self._entry.data['port']}:button_prior"

    async def async_press(self) -> None:
        await self._client.prior_step()
        await self.coordinator.async_request_refresh()


class RestartStepButton(BaseXScheduleButton):
    _attr_has_entity_name = True
    _attr_translation_key = "restart_step"
    _attr_icon = "mdi:restart"

    def __init__(self, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(client, coordinator, entry)
        device_slug = slugify_entry_title(entry)
        self.entity_id = f"button.{DOMAIN}_{device_slug}_restart_step"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.data['host']}:{self._entry.data['port']}:button_restart_step"

    async def async_press(self) -> None:
        await self._client.restart_step()
        await self.coordinator.async_request_refresh()


class StopAllNowButton(BaseXScheduleButton):
    _attr_has_entity_name = True
    _attr_translation_key = "stop_all_now"
    _attr_icon = "mdi:stop-circle"

    def __init__(self, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(client, coordinator, entry)
        device_slug = slugify_entry_title(entry)
        self.entity_id = f"button.{DOMAIN}_{device_slug}_stop_all_now"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.data['host']}:{self._entry.data['port']}:button_stop_all_now"

    async def async_press(self) -> None:
        await self._client.stop_all_now()
        await self.coordinator.async_request_refresh()


class CloseXScheduleButton(BaseXScheduleButton):
    _attr_has_entity_name = True
    _attr_translation_key = "close_xschedule"
    _attr_icon = "mdi:close-circle"

    def __init__(self, client: XScheduleClient, coordinator: XScheduleCoordinator, entry: ConfigEntry) -> None:
        super().__init__(client, coordinator, entry)
        device_slug = slugify_entry_title(entry)
        self.entity_id = f"button.{DOMAIN}_{device_slug}_close_xschedule"

    @property
    def unique_id(self) -> str:
        return f"{self._entry.data['host']}:{self._entry.data['port']}:button_close_xschedule"

    async def async_press(self) -> None:
        # Request xSchedule to close; after this, the server will go away, so skip refresh
        try:
            await self._client.command("Close xSchedule")
        except Exception:
            # Server may terminate before responding; ignore
            pass

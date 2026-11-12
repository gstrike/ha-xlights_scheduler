from __future__ import annotations

import logging
from functools import partial
import voluptuous as vol
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from homeassistant.exceptions import HomeAssistantError
from .client import XScheduleClient
from .coordinator import XScheduleCoordinator
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    DOMAIN,
    PLATFORMS,
    EVENT_TEST_MODE_STARTED,
    EVENT_TEST_MODE_STOPPED,
)

_LOGGER = logging.getLogger(__name__)

type XLightsData = dict[str, Any]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)
    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    password = entry.data.get(CONF_PASSWORD, "")

    client = XScheduleClient(session, host, port, password)
    coordinator = XScheduleCoordinator(
        hass, client, entry.options, entry_id=entry.entry_id
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


def _get_integration_objects(hass: HomeAssistant, entry_id: str | None = None):
    data = hass.data.get(DOMAIN) or {}
    if entry_id is None:
        if len(data) != 1:
            raise HomeAssistantError(
                "Specify config_entry_id when there is not exactly one loaded xSchedule player."
            )
        entry_id = next(iter(data))
    if entry_id not in data:
        raise HomeAssistantError("The selected xSchedule player is not loaded.")
    entry_data = data[entry_id]
    return entry_data["client"], entry_data["coordinator"]


def _register_services(hass: HomeAssistant) -> None:
    async def _service_wrapper(call, handler):
        client, coordinator = _get_integration_objects(
            hass, call.data.get("config_entry_id")
        )
        if not client:
            return
        async with client.control_lock:
            await handler(client, coordinator, call.data)
            await coordinator.async_request_refresh()

    async def svc_play_playlist(client: XScheduleClient, _, data: dict):
        playlist = data.get("playlist")
        looped = data.get("looped", False)
        if playlist:
            await client.play_playlist(playlist, looped=bool(looped))

    async def svc_stop_playlist(client: XScheduleClient, _, data: dict):
        await client.stop()

    async def svc_play_step(client: XScheduleClient, _, data: dict):
        playlist = data.get("playlist")
        step = data.get("step")
        looped = data.get("looped", False)
        if playlist and step:
            await client.play_step(playlist, step, looped=bool(looped))

    async def svc_seek_ms(client: XScheduleClient, _, data: dict):
        pos = int(data.get("position_ms", 0))
        await client.seek_ms(pos)

    async def svc_toggle_playlist_loop(client: XScheduleClient, __, ___):
        await client.toggle_playlist_loop()

    async def svc_set_playlist_loop(
        client: XScheduleClient, coordinator: XScheduleCoordinator | None, data: dict
    ):
        desired = bool(data.get("state", False))
        status = await client.get_playing_status()
        if status.get("status") not in ("playing", "paused"):
            raise HomeAssistantError("Playlist loop requires an active playlist.")
        current = str(status.get("playlistlooping", "false")).lower() == "true"
        if desired != current:
            await client.toggle_playlist_loop()

    async def svc_toggle_output(client: XScheduleClient, __, ___):
        await client.toggle_output_to_lights()

    async def svc_set_output(
        client: XScheduleClient, coordinator: XScheduleCoordinator | None, data: dict
    ):
        desired = bool(data.get("state", False))
        status = await client.get_playing_status()
        current = str(status.get("outputtolights", "false")).lower() == "true"
        if desired != current:
            await client.toggle_output_to_lights()

    async def svc_set_volume(client: XScheduleClient, __, data: dict):
        vol = int(data.get("volume", 0))
        await client.set_volume(vol)

    async def svc_adjust_volume(client: XScheduleClient, __, data: dict):
        delta = int(data.get("delta", 0))
        await client.adjust_volume(delta)

    async def svc_start_test_mode(client: XScheduleClient, coordinator, data: dict):
        mode = data.get("mode") or "Alternate"
        model = data.get("model")
        interval = data.get("interval")
        foreground = data.get("foreground")
        background = data.get("background")
        parts = [str(mode)]
        if model not in (None, ""):
            parts.append(str(model))
        if interval not in (None, ""):
            parts.append(str(int(interval)))
        if foreground not in (None, ""):
            parts.append(str(int(foreground)))
        if background not in (None, ""):
            parts.append(str(int(background)))
        params = "|".join(parts)
        res = await client.command("Start test mode", parameters=params)
        if res.get("result") == "ok":
            coordinator.test_mode = True
            hass.bus.async_fire(
                EVENT_TEST_MODE_STARTED,
                {
                    "mode": mode,
                    **coordinator.event_context,
                },
            )

    async def svc_stop_test_mode(client: XScheduleClient, coordinator, data: dict):
        res = await client.command("Stop test mode")
        if res.get("result") == "ok":
            coordinator.test_mode = False
            hass.bus.async_fire(
                EVENT_TEST_MODE_STOPPED,
                {
                    **coordinator.event_context,
                },
            )

    target = {vol.Optional("config_entry_id"): str}
    fields = {
        "play_playlist": {
            vol.Required("playlist"): str,
            vol.Optional("looped", default=False): bool,
        },
        "play_step": {
            vol.Required("playlist"): str,
            vol.Required("step"): str,
            vol.Optional("looped", default=False): bool,
        },
        "seek_ms": {
            vol.Required("position_ms"): vol.All(vol.Coerce(int), vol.Range(min=0))
        },
        "set_playlist_loop": {vol.Required("state"): bool},
        "set_output_to_lights": {vol.Required("state"): bool},
        "set_volume": {
            vol.Required("volume"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100))
        },
        "adjust_volume": {
            vol.Required("delta"): vol.All(
                vol.Coerce(int), vol.Range(min=-100, max=100)
            )
        },
        "start_test_mode": {
            vol.Optional("mode"): str,
            vol.Optional("model"): str,
            vol.Optional("interval"): vol.All(vol.Coerce(int), vol.Range(min=1)),
            vol.Optional("foreground"): vol.Coerce(int),
            vol.Optional("background"): vol.Coerce(int),
        },
    }
    handlers = {
        "play_playlist": svc_play_playlist,
        "stop_playlist": svc_stop_playlist,
        "play_step": svc_play_step,
        "seek_ms": svc_seek_ms,
        "toggle_playlist_loop": svc_toggle_playlist_loop,
        "set_playlist_loop": svc_set_playlist_loop,
        "toggle_output_to_lights": svc_toggle_output,
        "set_output_to_lights": svc_set_output,
        "set_volume": svc_set_volume,
        "adjust_volume": svc_adjust_volume,
        "start_test_mode": svc_start_test_mode,
        "stop_test_mode": svc_stop_test_mode,
    }
    for name, handler in handlers.items():
        hass.services.async_register(
            DOMAIN,
            name,
            partial(_service_wrapper, handler=handler),
            schema=vol.Schema({**target, **fields.get(name, {})}),
        )

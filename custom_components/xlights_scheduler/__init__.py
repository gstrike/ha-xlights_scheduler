from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import XScheduleClient
from .coordinator import XScheduleCoordinator
from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_POLL_IDLE,
    CONF_POLL_PLAYING,
    CONF_PORT,
    DEFAULT_POLL_IDLE,
    DEFAULT_POLL_PLAYING,
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
    coordinator = XScheduleCoordinator(hass, client, entry.options)

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    # Schedule platform setups to avoid blocking import warnings inside the event loop
    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    )

    _register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


def _get_integration_objects(hass: HomeAssistant) -> tuple[XScheduleClient | None, XScheduleCoordinator | None]:
    data = hass.data.get(DOMAIN) or {}
    if not data:
        return None, None
    # single instance for now – just take the first
    entry_id = next(iter(data))
    entry_data = data[entry_id]
    return entry_data.get("client"), entry_data.get("coordinator")


def _register_services(hass: HomeAssistant) -> None:
    async def _service_wrapper(call, handler):
        client, coordinator = _get_integration_objects(hass)
        if not client:
            return
        await handler(client, coordinator, call.data)
        if coordinator:
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
            if looped:
                await client.command(
                    "Play specified step in specified playlist looped",
                    parameters=f"{playlist},{step}",
                )
            else:
                await client.command("Play playlist step", parameters=f"{playlist},{step}")

    async def svc_seek_ms(client: XScheduleClient, _, data: dict):
        pos = int(data.get("position_ms", 0))
        await client.seek_ms(pos)

    async def svc_toggle_playlist_loop(client: XScheduleClient, __, ___):
        await client.toggle_playlist_loop()

    async def svc_set_playlist_loop(client: XScheduleClient, coordinator: XScheduleCoordinator | None, data: dict):
        desired = bool(data.get("state", False))
        current = False
        if coordinator and coordinator.data:
            current = coordinator.data.get("playlistlooping", "false") == "true"
        if desired != current:
            await client.toggle_playlist_loop()

    async def svc_toggle_output(client: XScheduleClient, __, ___):
        await client.toggle_output_to_lights()

    async def svc_set_output(client: XScheduleClient, coordinator: XScheduleCoordinator | None, data: dict):
        desired = bool(data.get("state", False))
        current = False
        if coordinator and coordinator.data:
            current = coordinator.data.get("outputtolights", "false") == "true"
        if desired != current:
            await client.toggle_output_to_lights()

    async def svc_set_volume(client: XScheduleClient, __, data: dict):
        vol = int(data.get("volume", 0))
        await client.set_volume(vol)

    async def svc_adjust_volume(client: XScheduleClient, __, data: dict):
        delta = int(data.get("delta", 0))
        await client.adjust_volume(delta)

    async def svc_start_test_mode(client: XScheduleClient, __, data: dict):
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
            hass.bus.async_fire(
                EVENT_TEST_MODE_STARTED,
                {
                    "mode": mode,
                    "device": f"{DOMAIN}:{client.base_url}",
                },
            )

    async def svc_stop_test_mode(client: XScheduleClient, __, data: dict):
        res = await client.command("Stop test mode")
        if res.get("result") == "ok":
            hass.bus.async_fire(
                EVENT_TEST_MODE_STOPPED,
                {
                    "device": f"{DOMAIN}:{client.base_url}",
                },
            )


    hass.services.async_register(DOMAIN, "play_playlist", lambda call: _service_wrapper(call, svc_play_playlist))
    hass.services.async_register(DOMAIN, "stop_playlist", lambda call: _service_wrapper(call, svc_stop_playlist))
    hass.services.async_register(DOMAIN, "play_step", lambda call: _service_wrapper(call, svc_play_step))
    hass.services.async_register(DOMAIN, "seek_ms", lambda call: _service_wrapper(call, svc_seek_ms))
    hass.services.async_register(DOMAIN, "toggle_playlist_loop", lambda call: _service_wrapper(call, svc_toggle_playlist_loop))
    hass.services.async_register(DOMAIN, "set_playlist_loop", lambda call: _service_wrapper(call, svc_set_playlist_loop))
    hass.services.async_register(DOMAIN, "toggle_output_to_lights", lambda call: _service_wrapper(call, svc_toggle_output))
    hass.services.async_register(DOMAIN, "set_output_to_lights", lambda call: _service_wrapper(call, svc_set_output))
    hass.services.async_register(DOMAIN, "set_volume", lambda call: _service_wrapper(call, svc_set_volume))
    hass.services.async_register(DOMAIN, "adjust_volume", lambda call: _service_wrapper(call, svc_adjust_volume))
    hass.services.async_register(DOMAIN, "start_test_mode", lambda call: _service_wrapper(call, svc_start_test_mode))
    hass.services.async_register(DOMAIN, "stop_test_mode", lambda call: _service_wrapper(call, svc_stop_test_mode))

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import XScheduleClient
from .const import (
    CONF_ENABLE_BROWSE,
    CONF_HOST,
    CONF_LISTS_REFRESH_SECS,
    CONF_PASSWORD,
    CONF_POLL_IDLE,
    CONF_POLL_PLAYING,
    CONF_PORT,
    DEFAULT_ENABLE_BROWSE,
    DEFAULT_LISTS_REFRESH_SECS,
    DEFAULT_POLL_IDLE,
    DEFAULT_POLL_PLAYING,
    DEFAULT_PORT,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


class XScheduleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input.get(CONF_PORT, DEFAULT_PORT)
            password = user_input.get(CONF_PASSWORD, "")

            session = async_get_clientsession(self.hass)
            client = XScheduleClient(session, host, port, password)
            try:
                if password:
                    await client.async_login()
                await client.get_playing_status()
            except Exception as ex:
                _LOGGER.debug("Connection/auth failed: %s", ex)
                errors["base"] = "cannot_connect"

            if not errors:
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"xSchedule ({host}:{port})",
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_PASSWORD: password,
                    },
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Optional(CONF_PASSWORD, default=""): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return XScheduleOptionsFlow(config_entry)


class XScheduleOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Options", data=user_input)

        current = self._entry.options
        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_POLL_PLAYING, default=current.get(CONF_POLL_PLAYING, DEFAULT_POLL_PLAYING)
                ): int,
                vol.Optional(CONF_POLL_IDLE, default=current.get(CONF_POLL_IDLE, DEFAULT_POLL_IDLE)): int,
                vol.Optional(
                    CONF_ENABLE_BROWSE, default=current.get(CONF_ENABLE_BROWSE, DEFAULT_ENABLE_BROWSE)
                ): bool,
                vol.Optional(
                    CONF_LISTS_REFRESH_SECS,
                    default=current.get(CONF_LISTS_REFRESH_SECS, DEFAULT_LISTS_REFRESH_SECS),
                ): int,
            }
        )
        return self.async_show_form(step_id="init", data_schema=data_schema)

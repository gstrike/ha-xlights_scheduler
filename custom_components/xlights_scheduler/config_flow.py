from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import XScheduleClient, XScheduleAuthError, XScheduleError
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
    player_key,
)

_LOGGER = logging.getLogger(__name__)


def connection_schema(defaults):
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(
                CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
            vol.Optional(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): str,
        }
    )


class XScheduleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _validate_connection(self, data):
        data = connection_schema({})(data)
        data[CONF_HOST] = data[CONF_HOST].strip()
        if not data[CONF_HOST]:
            raise vol.Invalid("Host must not be empty")
        client = XScheduleClient(
            async_get_clientsession(self.hass),
            data[CONF_HOST],
            data[CONF_PORT],
            data.get(CONF_PASSWORD, ""),
        )
        await client.get_playing_status()
        return data

    async def _connection_step(self, step, user_input, entry=None):
        errors = {}
        if user_input is not None:
            try:
                data = await self._validate_connection(user_input)
                if any(
                    e.entry_id != (entry.entry_id if entry else None)
                    and e.data.get(CONF_HOST) == data[CONF_HOST]
                    and e.data.get(CONF_PORT) == data[CONF_PORT]
                    for e in self._async_current_entries()
                ):
                    return self.async_abort(reason="already_configured")
                if entry:
                    # Preserve entity/device identity separately from connection
                    # uniqueness, allowing the old address to be reused later.
                    data["_player_key"] = player_key(entry)
                    return self.async_update_reload_and_abort(
                        entry,
                        data_updates=data,
                        unique_id=f"{data[CONF_HOST]}:{data[CONF_PORT]}",
                        title=f"xSchedule ({data[CONF_HOST]}:{data[CONF_PORT]})",
                    )
                await self.async_set_unique_id(f"{data[CONF_HOST]}:{data[CONF_PORT]}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"xSchedule ({data[CONF_HOST]}:{data[CONF_PORT]})", data=data
                )
            except XScheduleAuthError:
                errors["base"] = "invalid_auth"
            except vol.Invalid:
                errors["base"] = "invalid_connection"
            except XScheduleError:
                errors["base"] = "cannot_connect"
        defaults = entry.data if entry else (user_input or {})
        return self.async_show_form(
            step_id=step, data_schema=connection_schema(defaults), errors=errors
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return await self._connection_step("user", user_input)

    async def async_step_reconfigure(self, user_input=None):
        return await self._connection_step(
            "reconfigure", user_input, self._get_reconfigure_entry()
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        return await self._connection_step(
            "reauth_confirm", user_input, self._get_reauth_entry()
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return XScheduleOptionsFlow()


class XScheduleOptionsFlow(config_entries.OptionsFlowWithReload):
    async def async_step_init(self, user_input=None):
        current = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_POLL_PLAYING,
                    default=current.get(CONF_POLL_PLAYING, DEFAULT_POLL_PLAYING),
                ): vol.All(vol.Coerce(int), vol.Range(min=1)),
                vol.Optional(
                    CONF_POLL_IDLE,
                    default=current.get(CONF_POLL_IDLE, DEFAULT_POLL_IDLE),
                ): vol.All(vol.Coerce(int), vol.Range(min=1)),
                vol.Optional(
                    CONF_ENABLE_BROWSE,
                    default=current.get(CONF_ENABLE_BROWSE, DEFAULT_ENABLE_BROWSE),
                ): bool,
                vol.Optional(
                    CONF_LISTS_REFRESH_SECS,
                    default=current.get(
                        CONF_LISTS_REFRESH_SECS, DEFAULT_LISTS_REFRESH_SECS
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=1)),
            }
        )
        errors = {}
        if user_input is not None:
            try:
                return self.async_create_entry(title="Options", data=schema(user_input))
            except vol.Invalid:
                errors["base"] = "invalid_interval"
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

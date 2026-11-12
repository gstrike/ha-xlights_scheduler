from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Any, Dict, List, Optional

from aiohttp import ClientSession, ClientError
from homeassistant.exceptions import HomeAssistantError
from urllib.parse import quote

from .const import REFERENCE_PREFIX

_LOGGER = logging.getLogger(__name__)


class XScheduleError(HomeAssistantError):
    """An xSchedule request was rejected or returned invalid data."""


class XScheduleAuthError(XScheduleError):
    """xSchedule authentication failed."""


class XScheduleClient:
    def __init__(
        self, session: ClientSession, host: str, port: int, password: str | None
    ) -> None:
        self._session = session
        self._host = host
        self._port = port
        self._password = password or ""
        self._base = f"http://{host}:{port}"
        self._server_seen_ip: Optional[str] = None
        self._logged_in: bool = False
        self._lock = asyncio.Lock()
        self.control_lock = asyncio.Lock()

        # caches
        self._playlists: List[Dict[str, Any]] | None = None
        self._steps_cache: Dict[str, List[Dict[str, Any]]] = {}

    @property
    def base_url(self) -> str:
        return self._base

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def server_seen_ip(self) -> Optional[str]:
        return self._server_seen_ip

    async def async_login(self) -> bool:
        # If no password configured, considered always logged in
        if not self._password:
            self._logged_in = True
            return True

        async with self._lock:
            # First try with known IP if we have one
            if self._server_seen_ip:
                cred = self._md5(f"{self._server_seen_ip}{self._password}")
                ok = await self._login_with_credential(cred)
                if ok:
                    return True

            # Intentionally send a bad credential to get the hinted IP back
            hinted_ip = await self._get_hinted_ip()
            if hinted_ip:
                self._server_seen_ip = hinted_ip
                cred = self._md5(f"{hinted_ip}{self._password}")
                ok = await self._login_with_credential(cred)
                return ok

            return False

    async def _get_hinted_ip(self) -> Optional[str]:
        url = f"{self._base}/xScheduleLogin"
        params = {"Credential": "bad", "Reference": REFERENCE_PREFIX}
        try:
            async with self._session.get(url, params=params, timeout=10) as resp:
                js = await resp.json(content_type=None)
        except Exception as ex:  # broad catch to surface connection issues
            _LOGGER.debug("Login hint failed: %s", ex)
            return None
        ip = js.get("ip")
        _LOGGER.debug("Server hinted client IP: %s", ip)
        return ip

    async def _login_with_credential(self, credential: str) -> bool:
        url = f"{self._base}/xScheduleLogin"
        params = {"Credential": credential, "Reference": REFERENCE_PREFIX}
        try:
            async with self._session.get(url, params=params, timeout=10) as resp:
                js = await resp.json(content_type=None)
        except Exception as ex:
            _LOGGER.debug("Login attempt failed: %s", ex)
            return False

        if js.get("result") == "ok":
            self._logged_in = True
            # Clear caches on new login/session so lists refresh
            self._playlists = None
            self._steps_cache.clear()
            _LOGGER.debug("Login succeeded")
            return True
        _LOGGER.debug("Login failed response: %s", js)
        return False

    def _md5(self, text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    async def _ensure_login(self) -> None:
        if self._password and not self._logged_in:
            if not await self.async_login():
                raise XScheduleAuthError(
                    "xSchedule authentication failed. Check the configured password."
                )

    async def _request(
        self, endpoint: str, arguments: dict[str, str], data: str = ""
    ) -> Dict[str, Any]:
        # xSchedule expects %20, not form-style '+' for spaces. Encode values
        # once; IDs below solve the API's separate comma-delimiter problem.
        qs = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in arguments.items())
        url = f"{self._base}/{endpoint}?{qs}"
        try:
            async with self._session.get(url, data=data, timeout=15) as response:
                response.raise_for_status()
                js = await response.json(content_type=None)
        except (ClientError, asyncio.TimeoutError, ValueError) as error:
            raise XScheduleError(f"xSchedule request failed: {error}") from error
        if not isinstance(js, dict):
            raise XScheduleError("xSchedule returned an invalid response.")
        return js

    async def _authenticated_request(
        self, endpoint: str, arguments: dict[str, str], data: str = ""
    ) -> Dict[str, Any]:
        await self._ensure_login()
        js = await self._request(endpoint, arguments, data)
        if js.get("result") == "not logged in":
            self._logged_in = False
            if not self._password:
                raise XScheduleAuthError(
                    "xSchedule requires a password. Configure it in the integration."
                )
            await self._ensure_login()
            js = await self._request(endpoint, arguments, data)
        result = js.get("result")
        if result == "not logged in":
            self._logged_in = False
            raise XScheduleAuthError(
                "xSchedule rejected authentication after logging in again."
            )
        if result is not None and result != "ok":
            raise XScheduleError(str(js.get("message") or result))
        return js

    async def query(
        self, query: str, parameters: str = "", reference: str | None = None
    ) -> Dict[str, Any]:
        return await self._authenticated_request(
            "xScheduleQuery",
            {
                "Query": query,
                "Parameters": parameters,
                "Reference": reference or REFERENCE_PREFIX,
            },
        )

    async def command(
        self,
        command: str,
        parameters: str = "",
        data: str = "",
        reference: str | None = None,
    ) -> Dict[str, Any]:
        js = await self._authenticated_request(
            "xScheduleCommand",
            {
                "Command": command,
                "Parameters": parameters,
                "Reference": reference or REFERENCE_PREFIX,
            },
            data,
        )
        if js.get("result") != "ok":
            raise XScheduleError("xSchedule did not confirm the command succeeded.")
        return js

    @staticmethod
    def _id_reference(value: str) -> str | None:
        if re.fullmatch(r"id:[0-9]+", value, flags=re.IGNORECASE):
            return f"id:{int(value[3:])}"
        return None

    @staticmethod
    def _reference_for(items: list[dict[str, Any]], value: str, kind: str) -> str:
        reference = XScheduleClient._id_reference(value)
        matches = [
            item
            for item in items
            if (
                str(item.get("id")) == reference[3:]
                if reference
                else item.get("name") == value
            )
        ]
        if len(matches) != 1 or not str(matches[0].get("id", "")).isdigit():
            raise XScheduleError(
                f"{kind} {value!r} was not found uniquely. Refresh the list or use an id: reference."
            )
        return f"id:{matches[0]['id']}"

    async def playlist_reference(self, playlist: str) -> str:
        reference = self._id_reference(playlist)
        if reference:
            return reference
        # Refresh at selection time: IDs may change after a scheduler restart.
        return self._reference_for(await self.get_playlists(), playlist, "Playlist")

    async def get_playlists(self) -> List[Dict[str, Any]]:
        js = await self.query("GetPlayLists")
        pls = js.get("playlists")
        if not isinstance(pls, list) or not all(isinstance(p, dict) for p in pls):
            raise XScheduleError("xSchedule returned an invalid playlist list.")
        self._playlists = pls
        return pls

    async def get_steps(self, playlist_name_or_id: str) -> List[Dict[str, Any]]:
        reference = await self.playlist_reference(playlist_name_or_id)
        js = await self.query("GetPlayListSteps", parameters=reference)
        steps = js.get("steps")
        if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps):
            raise XScheduleError("xSchedule returned an invalid step list.")
        self._steps_cache[reference] = steps
        return steps

    async def get_playing_status(self) -> Dict[str, Any]:
        js = await self.query("GetPlayingStatus")
        if not isinstance(js.get("status"), str) or not js["status"]:
            raise XScheduleError(
                "xSchedule returned a response without playback status."
            )
        return js

    async def play_playlist(
        self, playlist: str, looped: bool = False
    ) -> Dict[str, Any]:
        command = (
            "Play specified playlist looped" if looped else "Play specified playlist"
        )
        return await self.command(
            command, parameters=await self.playlist_reference(playlist)
        )

    async def play_step(
        self, playlist: str, step: str, looped: bool = False
    ) -> Dict[str, Any]:
        playlist_id = await self.playlist_reference(playlist)
        step_id = self._reference_for(await self.get_steps(playlist_id), step, "Step")
        command = (
            "Play specified step in specified playlist looped"
            if looped
            else "Play playlist step"
        )
        return await self.command(command, parameters=f"{playlist_id},{step_id}")

    async def set_background(self, playlist: str) -> Dict[str, Any]:
        return await self.command(
            "Set playlist as background",
            parameters=await self.playlist_reference(playlist),
        )

    async def stop(self) -> Dict[str, Any]:
        return await self.command("Stop")

    async def stop_all_now(self) -> Dict[str, Any]:
        return await self.command("Stop all now")

    async def pause_toggle(self) -> Dict[str, Any]:
        return await self.command("Pause")

    async def next_step(self) -> Dict[str, Any]:
        return await self.command("Next step in current playlist")

    async def prior_step(self) -> Dict[str, Any]:
        return await self.command("Prior step in current playlist")

    async def restart_step(self) -> Dict[str, Any]:
        return await self.command("Restart step in current playlist")

    async def toggle_playlist_loop(self) -> Dict[str, Any]:
        return await self.command("Toggle current playlist loop")

    async def toggle_output_to_lights(self) -> Dict[str, Any]:
        return await self.command("Toggle output to lights")

    async def set_volume(self, value_0_100: int) -> Dict[str, Any]:
        value_0_100 = max(0, min(100, int(value_0_100)))
        return await self.command("Set volume to", parameters=str(value_0_100))

    async def adjust_volume(self, delta: int) -> Dict[str, Any]:
        delta = max(-100, min(100, int(delta)))
        return await self.command("Adjust volume by", parameters=str(delta))

    async def seek_ms(self, pos_ms: int) -> Dict[str, Any]:
        pos_ms = max(0, int(pos_ms))
        return await self.command("Set step position ms", parameters=str(pos_ms))

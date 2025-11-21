from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Dict, List, Optional

from aiohttp import ClientSession
from urllib.parse import quote

from .const import REFERENCE_PREFIX

_LOGGER = logging.getLogger(__name__)


class XScheduleClient:
    def __init__(self, session: ClientSession, host: str, port: int, password: str | None) -> None:
        self._session = session
        self._host = host
        self._port = port
        self._password = password or ""
        self._base = f"http://{host}:{port}"
        self._server_seen_ip: Optional[str] = None
        self._logged_in: bool = False
        self._lock = asyncio.Lock()

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
        if not self._password:
            return
        if not self._logged_in:
            await self.async_login()

    async def query(self, query: str, parameters: str = "", reference: str | None = None) -> Dict[str, Any]:
        await self._ensure_login()
        base = f"{self._base}/xScheduleQuery"
        # Manually build query string to ensure spaces become %20 (not '+')
        qp = {
            "Query": query,
            "Parameters": parameters,
            "Reference": reference or REFERENCE_PREFIX,
        }
        safe_chars = ",:+|-_:."
        qs = "&".join(f"{k}={quote(str(v), safe=safe_chars)}" for k, v in qp.items())
        url = f"{base}?{qs}"
        async with self._session.get(url, timeout=15) as resp:
            js = await resp.json(content_type=None)
        # Handle not logged in (password enabled)
        if js.get("result") == "not logged in":
            self._logged_in = False
            await self._ensure_login()
            async with self._session.get(url, timeout=15) as resp:
                js = await resp.json(content_type=None)
        return js

    async def command(self, command: str, parameters: str = "", data: str = "", reference: str | None = None) -> Dict[str, Any]:
        await self._ensure_login()
        base = f"{self._base}/xScheduleCommand"
        qp = {
            "Command": command,
            "Parameters": parameters,
            "Reference": reference or REFERENCE_PREFIX,
        }
        safe_chars = ",:+|-_:."
        qs = "&".join(f"{k}={quote(str(v), safe=safe_chars)}" for k, v in qp.items())
        url = f"{base}?{qs}"
        async with self._session.get(url, data=data, timeout=15) as resp:
            js = await resp.json(content_type=None)
        if js.get("result") == "not logged in":
            self._logged_in = False
            await self._ensure_login()
            async with self._session.get(url, data=data, timeout=15) as resp:
                js = await resp.json(content_type=None)
        return js

    # Convenience wrappers
    async def get_playlists(self) -> List[Dict[str, Any]]:
        js = await self.query("GetPlayLists")
        pls = js.get("playlists", [])
        self._playlists = pls
        return pls

    async def get_steps(self, playlist_name_or_id: str) -> List[Dict[str, Any]]:
        js = await self.query("GetPlayListSteps", parameters=playlist_name_or_id)
        steps = js.get("steps", [])
        self._steps_cache[playlist_name_or_id] = steps
        return steps

    async def get_playing_status(self) -> Dict[str, Any]:
        return await self.query("GetPlayingStatus")

    async def play_playlist(self, playlist: str, looped: bool = False) -> Dict[str, Any]:
        cmd = "Play specified playlist looped" if looped else "Play specified playlist"
        return await self.command(cmd, parameters=playlist)

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

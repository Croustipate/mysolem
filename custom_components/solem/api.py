"""Solem REST API client for mysolem.com."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import API_URL, TOKEN_URL

_LOGGER = logging.getLogger(__name__)

# Headers required by the Solem mobile app (confirmed via Proxyman)
APP_HEADERS = {
    "Accept": "version=2.8",
    "User-Agent": "Solem/6.10 (iPhone; iOS 26.3.1; Scale/3.00)",
    "Cache-Control": "no-cache, no-transform",
}


class SolemAuthError(Exception):
    """Raised when authentication fails."""


class SolemAPIError(Exception):
    """Raised when an API call fails."""


class SolemAPI:
    """Client for the mysolem.com REST API.

    Architecture:
      HA → HTTPS REST → mysolem.com cloud
        → long-polling → LRMB10 relay (WiFi)
          → LoRa radio → LRIS6 controller (6 zones)

    Two types of commands:
      - /api/module/{relay_sn}/manual/{ctrl_suffix}  → direct, real-time via LoRa
      - /api/updateModule with statusToSend          → queued, ~2-5 min delay

    The app uses the /manual/ endpoint for user-triggered actions.
    Session cookie (solem-irrigation-platform.sid) is required for /manual/.
    It is set automatically by the server during authentication and stored
    in the aiohttp.ClientSession cookie jar.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._token: str | None = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def authenticate(self, username: str, password: str) -> str:
        """Obtain a Bearer token + session cookie via OAuth2 password grant.

        Confirmed request format (Proxyman):
          POST /oauth2/token
          Accept: version=2.8
          Content-Type: application/json
          Body: {"grant_type": "password", "username": "...", "password": "...", "scope": "email"}

        The server returns the Bearer token AND sets the session cookie
        solem-irrigation-platform.sid in the response, which aiohttp stores
        in the session's cookie jar automatically.
        Token expires in 5184000 s (~60 days).
        """
        payload = {
            "grant_type": "password",
            "username": username,
            "password": password,
            "scope": "email",
        }
        try:
            async with self._session.post(
                TOKEN_URL, json=payload, headers=APP_HEADERS
            ) as resp:
                if resp.status == 401:
                    raise SolemAuthError("Invalid username or password")
                if resp.status != 200:
                    body = await resp.text()
                    raise SolemAuthError(
                        f"Authentication failed with HTTP {resp.status}: {body[:100]}"
                    )
                result = await resp.json()
                self._token = result["access_token"]
                _LOGGER.debug("Solem authentication successful, cookie jar updated")
                return self._token
        except aiohttp.ClientError as err:
            raise SolemAPIError(f"Connection error during authentication: {err}") from err

    @property
    def is_authenticated(self) -> bool:
        return self._token is not None

    @property
    def _headers(self) -> dict[str, str]:
        return {**APP_HEADERS, "Authorization": f"Bearer {self._token}"}

    # ------------------------------------------------------------------
    # Read endpoints
    # ------------------------------------------------------------------

    async def get_user_with_modules(self) -> dict[str, Any]:
        """GET /api/getUserWithHisModules."""
        return await self._get("getUserWithHisModules")

    async def get_programs(self, module_id: str) -> dict[str, Any]:
        """GET /api/getPrograms?id={module_id}."""
        return await self._get("getPrograms", params={"id": module_id})

    async def get_module_inventory(self, relay_id: str) -> dict[str, Any]:
        """GET /api/getModuleInventory — full status including programs."""
        return await self._get(
            "getModuleInventory",
            params={"module": relay_id, "data": "1"},
        )

    # ------------------------------------------------------------------
    # Control — direct via LoRa (real-time, confirmed working)
    # ------------------------------------------------------------------

    async def manual_start_zone(
        self,
        relay_serial: str,
        controller_suffix: str,
        zone: int,
        duration_minutes: int,
        controller_id: str,
    ) -> dict[str, Any]:
        """Start a zone manually (zone is 1-based).

        Confirmed working via Proxyman + live test.
        Requires session cookie (set during authenticate()).
        """
        hours, mins = divmod(duration_minutes, 60)
        watering = {"action": 2, "station": zone, "time": f"{hours:02d}:{mins:02d}"}
        result = await self._manual_command(relay_serial, controller_suffix, watering)
        await self._report_command(controller_id, {"watering": watering})
        return result

    async def manual_stop(
        self,
        relay_serial: str,
        controller_suffix: str,
        controller_id: str,
    ) -> dict[str, Any]:
        """Stop all active watering.

        action: 0 = stop (confirmed via Proxyman — body is just {"action": 0}).
        """
        watering = {"action": 0}
        result = await self._manual_command(relay_serial, controller_suffix, watering)
        await self._report_command(controller_id, {"watering": watering})
        return result

    async def manual_run_program(
        self,
        relay_serial: str,
        controller_suffix: str,
        program: int,
        controller_id: str,
    ) -> dict[str, Any]:
        """Run a program (program is 1-based).

        action: 1 = run program (to confirm by capturing app in Proxyman).
        """
        watering = {"action": 1, "program": program, "time": "00:00"}
        result = await self._manual_command(relay_serial, controller_suffix, watering)
        await self._report_command(controller_id, {"watering": watering})
        return result

    async def _manual_command(
        self,
        relay_serial: str,
        controller_suffix: str,
        watering: dict[str, Any],
    ) -> dict[str, Any]:
        """POST /api/module/{relay_serial}/manual/{controller_suffix}

        Requires session cookie. Body: {"watering": {...}}.
        Response: real-time state from controller including temperature.
        """
        path = f"module/{relay_serial}/manual/{controller_suffix}"
        return await self._post_path(path, json={"watering": watering})

    async def _report_command(
        self, controller_id: str, command: dict[str, Any]
    ) -> None:
        """POST /api/reportManualCommandSent — notify cloud (confirmed required)."""
        try:
            await self._post(
                "reportManualCommandSent",
                json={"route": "http", "command": command, "id": controller_id},
            )
        except SolemAPIError as err:
            # Non-critical — log and continue
            _LOGGER.warning("reportManualCommandSent failed: %s", err)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _get(self, endpoint: str, params: dict | None = None) -> Any:
        return await self._request("GET", f"{API_URL}/{endpoint}", params=params)

    async def _post(self, endpoint: str, json: Any = None) -> Any:
        return await self._request("POST", f"{API_URL}/{endpoint}", json=json)

    async def _post_path(self, path: str, json: Any = None) -> Any:
        return await self._request("POST", f"{API_URL}/{path}", json=json)

    async def _request(
        self,
        method: str,
        url: str,
        params: dict | None = None,
        json: Any = None,
    ) -> Any:
        if not self._token:
            raise SolemAuthError("Not authenticated")
        try:
            async with self._session.request(
                method, url,
                headers=self._headers,
                params=params,
                json=json,
            ) as resp:
                if resp.status == 401:
                    raise SolemAuthError("Token expired or invalid")
                if resp.status >= 400:
                    body = await resp.text()
                    raise SolemAPIError(
                        f"API error {resp.status} for {url}: {body[:200]}"
                    )
                return await resp.json()
        except aiohttp.ClientError as err:
            raise SolemAPIError(f"Connection error: {err}") from err

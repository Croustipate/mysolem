"""DataUpdateCoordinator for Solem irrigation."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import SolemAPI, SolemAPIError, SolemAuthError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class SolemCoordinator(DataUpdateCoordinator):
    """Polls mysolem.com for the current irrigation state.

    Uses two endpoints:
    - getUserWithHisModules  → module structure (outputs/zones, static data)
    - getModuleInventory     → current status + programs (live data)

    Note: getModuleInventory with Accept: version=2.8 does not return outputs,
    so we fetch outputs from getUserWithHisModules instead.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        api: SolemAPI,
        relay_id: str,
        relay_serial: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.api = api
        self.relay_id = relay_id
        self.relay_serial = relay_serial
        # Cached static data (outputs don't change)
        self._outputs: list[dict[str, Any]] = []
        self._controller_id: str = ""
        self._controller_suffix: str = ""
        # Last program run tracking
        self._program_running: int = 0          # program number currently detected as running
        self._program_start: datetime | None = None
        self._last_program_name: str | None = None
        self._last_program_start: datetime | None = None
        self._last_program_duration_minutes: int | None = None
        # Per-zone last run tracking (zone_number → datetime/duration)
        self._zone_running: int = 0             # zone number currently running (1-based)
        self._zone_start: datetime | None = None
        self._zone_last_run: dict[int, datetime] = {}           # zone_number → start time
        self._zone_last_duration: dict[int, int] = {}           # zone_number → minutes

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            # Always fetch inventory for live status + programs
            inventory = await self.api.get_module_inventory(self.relay_id)

            # Fetch outputs from getUserWithHisModules on first run or if empty
            if not self._outputs:
                await self._fetch_outputs()

        except SolemAuthError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
        except SolemAPIError as err:
            raise UpdateFailed(f"API error: {err}") from err

        children = inventory.get("children", [])
        if not children:
            raise UpdateFailed("No irrigation controller found under relay")

        controller = children[0]
        status = controller.get("status", {}).get("watering", {})

        # Cache controller identifiers on first successful call
        if not self._controller_id:
            self._controller_id = controller.get("id", "")
        if not self._controller_suffix:
            mac = controller.get("macAddress", "")
            self._controller_suffix = mac.replace(":", "")[-6:].upper()

        # Track program start / end to compute last-run history
        programs = controller.get("programs", [])
        now = datetime.now(timezone.utc)
        running_prog = status.get("runningProgram", 0)

        if running_prog and not self._program_running:
            self._program_running = running_prog
            self._program_start = now
        elif not running_prog and self._program_running:
            prog = next(
                (p for p in programs if p.get("index") == self._program_running - 1),
                None,
            )
            self._last_program_name = (
                prog.get("name", f"Program {self._program_running}") if prog
                else f"Program {self._program_running}"
            )
            self._last_program_start = self._program_start
            if self._program_start:
                elapsed = now - self._program_start
                self._last_program_duration_minutes = max(1, round(elapsed.total_seconds() / 60))
            self._program_running = 0
            self._program_start = None

        # Track per-zone last run (manual or via program)
        running_station = status.get("runningStation", 0)
        if running_station and running_station != self._zone_running:
            # New zone started
            self._zone_running = running_station
            self._zone_start = now
        elif not running_station and self._zone_running:
            # Zone just stopped — record history
            if self._zone_start:
                elapsed = now - self._zone_start
                self._zone_last_duration[self._zone_running] = max(1, round(elapsed.total_seconds() / 60))
            self._zone_last_run[self._zone_running] = self._zone_start or now
            self._zone_running = 0
            self._zone_start = None

        return {
            "relay": inventory,
            "controller": controller,
            "programs": programs,
            "outputs": self._outputs,
            "status": status,
            "controller_id": self._controller_id,
            "controller_suffix": self._controller_suffix,
            "controller_online": inventory.get("isOnline", False),
            "last_program_name": self._last_program_name,
            "last_program_start": self._last_program_start,
            "last_program_duration_minutes": self._last_program_duration_minutes,
            "zone_last_run": dict(self._zone_last_run),
            "zone_last_duration": dict(self._zone_last_duration),
        }

    async def _fetch_outputs(self) -> None:
        """Fetch zone outputs from getUserWithHisModules (always includes outputs)."""
        try:
            data = await self.api.get_user_with_modules()
            modules = data.get("modules", [])
            # Find the irrigation controller (lr-is type)
            controller = next(
                (m for m in modules if m.get("type") == "lr-is"), None
            )
            if controller:
                self._outputs = controller.get("outputs", [])
                if not self._controller_id:
                    self._controller_id = controller.get("id", "")
                if not self._controller_suffix:
                    mac = controller.get("macAddress", "")
                    self._controller_suffix = mac.replace(":", "")[-6:].upper()
                _LOGGER.info(
                    "Solem: fetched %d zone outputs from getUserWithHisModules",
                    len(self._outputs),
                )
            else:
                _LOGGER.warning("Solem: no lr-is controller found in modules")
        except SolemAPIError as err:
            _LOGGER.warning("Solem: could not fetch outputs: %s", err)

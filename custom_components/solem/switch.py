"""Switch entities: one per irrigation zone + one per program."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_ZONE_DURATION, DOMAIN, WATERING_STATE_ON
from .coordinator import SolemCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SolemCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SwitchEntity] = []

    for output in coordinator.data.get("outputs", []):
        entities.append(SolemZoneSwitch(coordinator, output))

    for program in coordinator.data.get("programs", []):
        entities.append(SolemProgramSwitch(coordinator, program))

    async_add_entities(entities)


def _device_info(coordinator: SolemCoordinator) -> DeviceInfo:
    ctrl = coordinator.data.get("controller", {})
    return DeviceInfo(
        identifiers={(DOMAIN, ctrl.get("id", ""))},
        name=ctrl.get("name", "Solem Controller"),
        manufacturer="Solem",
        model=ctrl.get("type", "lr-is").upper(),
        sw_version=ctrl.get("softwareVersion"),
        hw_version=ctrl.get("hardwareVersion"),
        serial_number=ctrl.get("serialNumber"),
    )


class SolemZoneSwitch(CoordinatorEntity[SolemCoordinator], SwitchEntity):
    """Switch for a single irrigation zone.

    ON  → start zone manually for configured duration (default 10 min)
    OFF → stop all watering
    """

    _attr_icon = "mdi:sprinkler"

    def __init__(self, coordinator: SolemCoordinator, output: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._output = output
        self._zone_index = output["index"]          # 0-based in the API
        self._zone_number = self._zone_index + 1    # 1-based on the device
        self._attr_unique_id = f"solem_zone_{output['id']}"
        self._attr_name = output.get("name", f"Zone {self._zone_number}")
        self._attr_device_info = _device_info(coordinator)

    @property
    def is_on(self) -> bool:
        status = self.coordinator.data.get("status", {})
        return (
            status.get("state") == WATERING_STATE_ON
            and status.get("runningStation") == self._zone_number
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        duration = self.hass.data.get(f"{DOMAIN}_durations", {}).get(
            self._zone_index, DEFAULT_ZONE_DURATION
        )
        return {
            "zone_index": self._zone_index,
            "zone_number": self._zone_number,
            "duration_minutes": duration,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        duration = int(
            self.hass.data.get(f"{DOMAIN}_durations", {}).get(
                self._zone_index, DEFAULT_ZONE_DURATION
            )
        )
        await self.coordinator.api.manual_start_zone(
            relay_serial=self.coordinator.relay_serial,
            controller_suffix=self.coordinator.data["controller_suffix"],
            zone=self._zone_number,
            duration_minutes=duration,
            controller_id=self.coordinator.data["controller_id"],
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.api.manual_stop(
            relay_serial=self.coordinator.relay_serial,
            controller_suffix=self.coordinator.data["controller_suffix"],
            controller_id=self.coordinator.data["controller_id"],
        )
        await self.coordinator.async_request_refresh()


class SolemProgramSwitch(CoordinatorEntity[SolemCoordinator], SwitchEntity):
    """Switch to run/stop a watering program."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: SolemCoordinator, program: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._program = program
        self._program_index = program["index"]          # 0-based
        self._program_number = self._program_index + 1  # 1-based on the device
        self._attr_unique_id = f"solem_program_{program['id']}"
        self._attr_name = program.get("name", f"Programme {chr(65 + self._program_index)}")
        self._attr_device_info = _device_info(coordinator)

    @property
    def is_on(self) -> bool:
        status = self.coordinator.data.get("status", {})
        return (
            status.get("state") == WATERING_STATE_ON
            and status.get("runningProgram") == self._program_number
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self._program
        starts = [f"{t // 60:02d}:{t % 60:02d}" for t in p.get("startTimes", []) if t != -1]
        return {
            "program_index": self._program_index,
            "water_budget": p.get("waterBudget"),
            "start_times": starts,
            "stations_duration_s": p.get("stationsDuration", []),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.api.manual_run_program(
            relay_serial=self.coordinator.relay_serial,
            controller_suffix=self.coordinator.data["controller_suffix"],
            program=self._program_number,
            controller_id=self.coordinator.data["controller_id"],
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.api.manual_stop(
            relay_serial=self.coordinator.relay_serial,
            controller_suffix=self.coordinator.data["controller_suffix"],
            controller_id=self.coordinator.data["controller_id"],
        )
        await self.coordinator.async_request_refresh()

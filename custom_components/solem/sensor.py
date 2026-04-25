"""Sensor entities for Solem irrigation status."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, WATERING_STATE_ON
from .coordinator import SolemCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SolemCoordinator = hass.data[DOMAIN][entry.entry_id]
    ctrl_id = coordinator.data.get("controller_id", entry.entry_id)

    entities: list[SensorEntity] = [
        SolemWateringStateSensor(coordinator, ctrl_id),
        SolemRunningStationSensor(coordinator, ctrl_id),
        SolemRunningProgramSensor(coordinator, ctrl_id),
        SolemLastCommunicationSensor(coordinator, ctrl_id),
        SolemLastProgramSensor(coordinator, ctrl_id),
    ]

    for output in coordinator.data.get("outputs", []):
        entities.append(SolemZoneLastRunSensor(coordinator, output))

    async_add_entities(entities)


def _device_info(coordinator: SolemCoordinator) -> DeviceInfo:
    ctrl = coordinator.data.get("controller", {})
    return DeviceInfo(
        identifiers={(DOMAIN, ctrl.get("id", ""))},
        name=ctrl.get("name", "Solem Controller"),
        manufacturer="Solem",
        model=ctrl.get("type", "lr-is").upper(),
        sw_version=ctrl.get("softwareVersion"),
    )


class _SolemSensorBase(CoordinatorEntity[SolemCoordinator], SensorEntity):
    def __init__(self, coordinator: SolemCoordinator, ctrl_id: str) -> None:
        super().__init__(coordinator)
        self._ctrl_id = ctrl_id
        self._attr_device_info = _device_info(coordinator)

    @property
    def _status(self) -> dict[str, Any]:
        return self.coordinator.data.get("status", {})


class SolemWateringStateSensor(_SolemSensorBase):
    """Human-readable watering state."""

    _attr_icon = "mdi:water"

    def __init__(self, coordinator: SolemCoordinator, ctrl_id: str) -> None:
        super().__init__(coordinator, ctrl_id)
        self._attr_unique_id = f"solem_{ctrl_id}_watering_state"
        self._attr_name = "Solem Watering State"

    @property
    def native_value(self) -> str:
        status = self._status
        if status.get("state") == WATERING_STATE_ON:
            station = status.get("runningStation", 0)
            program = status.get("runningProgram", 0)
            if station:
                return f"Zone {station} active"
            if program:
                return f"Program {program} running"
            return "Watering"
        rain_delay = status.get("rainDelay", 0)
        if rain_delay:
            return f"Rain delay ({rain_delay}d)"
        return "Idle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {**self._status}


class SolemRunningStationSensor(_SolemSensorBase):
    """Which zone (station) is currently active. 0 = none."""

    _attr_icon = "mdi:sprinkler"
    _attr_native_unit_of_measurement = None

    def __init__(self, coordinator: SolemCoordinator, ctrl_id: str) -> None:
        super().__init__(coordinator, ctrl_id)
        self._attr_unique_id = f"solem_{ctrl_id}_running_station"
        self._attr_name = "Solem Running Zone"

    @property
    def native_value(self) -> int:
        return self._status.get("runningStation", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        station = self._status.get("runningStation", 0)
        if station:
            outputs = self.coordinator.data.get("outputs", [])
            zone = next(
                (o for o in outputs if o.get("index") == station - 1), None
            )
            if zone:
                return {"zone_name": zone.get("name")}
        return {}


class SolemRunningProgramSensor(_SolemSensorBase):
    """Which program is currently running. 0 = none."""

    _attr_icon = "mdi:calendar-check"

    def __init__(self, coordinator: SolemCoordinator, ctrl_id: str) -> None:
        super().__init__(coordinator, ctrl_id)
        self._attr_unique_id = f"solem_{ctrl_id}_running_program"
        self._attr_name = "Solem Running Program"

    @property
    def native_value(self) -> str | None:
        prog_idx = self._status.get("runningProgram", 0)
        if not prog_idx:
            return "None"
        programs = self.coordinator.data.get("programs", [])
        prog = next(
            (p for p in programs if p.get("index") == prog_idx - 1), None
        )
        if prog:
            return prog.get("name", f"Program {prog_idx}")
        return f"Program {prog_idx}"


class SolemLastCommunicationSensor(_SolemSensorBase):
    """Timestamp of the last successful LoRa radio communication."""

    _attr_icon = "mdi:radio-tower"

    def __init__(self, coordinator: SolemCoordinator, ctrl_id: str) -> None:
        super().__init__(coordinator, ctrl_id)
        self._attr_unique_id = f"solem_{ctrl_id}_last_radio"
        self._attr_name = "Solem Last Radio Communication"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.get("controller", {}).get(
            "lastRadioCommunication"
        )


class SolemLastProgramSensor(_SolemSensorBase):
    """Name of the last program that completed, with start time and duration."""

    _attr_icon = "mdi:history"

    def __init__(self, coordinator: SolemCoordinator, ctrl_id: str) -> None:
        super().__init__(coordinator, ctrl_id)
        self._attr_unique_id = f"solem_{ctrl_id}_last_program"
        self._attr_name = "Solem Last Program"

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.get("last_program_name")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        start: datetime | None = self.coordinator.data.get("last_program_start")
        duration: int | None = self.coordinator.data.get("last_program_duration_minutes")
        attrs: dict[str, Any] = {}
        if start:
            attrs["started_at"] = start.astimezone(timezone.utc).isoformat()
        if duration is not None:
            attrs["duration_minutes"] = duration
        return attrs


class SolemZoneLastRunSensor(CoordinatorEntity[SolemCoordinator], SensorEntity):
    """Timestamp of the last time this zone was watered (manual or program)."""

    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: SolemCoordinator, output: dict[str, Any]) -> None:
        super().__init__(coordinator)
        self._zone_index = output["index"]
        self._zone_number = self._zone_index + 1
        zone_name = output.get("name", f"Zone {self._zone_number}")
        self._attr_unique_id = f"solem_zone_{output['id']}_last_run"
        self._attr_name = f"{zone_name} Dernier arrosage"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> datetime | None:
        last_run = self.coordinator.data.get("zone_last_run", {})
        ts = last_run.get(self._zone_number)
        if ts and ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        duration = self.coordinator.data.get("zone_last_duration", {}).get(self._zone_number)
        if duration is not None:
            return {"duration_minutes": duration}
        return {}

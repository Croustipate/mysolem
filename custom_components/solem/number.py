"""Number entities for Solem: zone duration and rain delay."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_ZONE_DURATION, DOMAIN, ORIGIN_SCHEDULED, WATERING_STATE_OFF
from .coordinator import SolemCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SolemCoordinator = hass.data[DOMAIN][entry.entry_id]
    ctrl_id = coordinator.data.get("controller_id", entry.entry_id)

    entities: list[NumberEntity] = []

    # One duration number per zone
    for output in coordinator.data.get("outputs", []):
        entities.append(SolemZoneDurationNumber(coordinator, output))

    # Global rain delay number
    entities.append(SolemRainDelayNumber(coordinator, ctrl_id))

    async_add_entities(entities)


def _device_info(coordinator: SolemCoordinator) -> DeviceInfo:
    ctrl = coordinator.data.get("controller", {})
    return DeviceInfo(
        identifiers={(DOMAIN, ctrl.get("id", ""))},
        name=ctrl.get("name", "Solem Controller"),
        manufacturer="Solem",
        model=ctrl.get("type", "lr-is").upper(),
    )


class SolemZoneDurationNumber(CoordinatorEntity[SolemCoordinator], NumberEntity):
    """Number entity to configure how many minutes a zone runs when turned on.

    This is a local preference stored in HA — it is used by the zone switch
    when manually started.  It does NOT persist to the Solem cloud.
    """

    _attr_icon = "mdi:timer"
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 1
    _attr_native_max_value = 240
    _attr_native_step = 1

    def __init__(
        self, coordinator: SolemCoordinator, output: dict[str, Any]
    ) -> None:
        super().__init__(coordinator)
        self._output = output
        self._zone_index = output["index"]
        self._attr_unique_id = f"solem_duration_{output['id']}"
        self._attr_name = f"{output.get('name', f'Zone {self._zone_index + 1}')} Duration"
        self._attr_device_info = _device_info(coordinator)
        self._value: float = DEFAULT_ZONE_DURATION

    @property
    def native_value(self) -> float:
        return self._value

    async def async_set_native_value(self, value: float) -> None:
        """Store the new duration locally and propagate to the zone switch."""
        self._value = value
        # Update all zone switches that reference this zone
        for entity in self.hass.data.get("entity_registry", {}).values() if False else []:
            pass
        # The switch reads duration_minutes from itself; we update via coordinator data
        # Since HA doesn't have a native way to wire entities, we store it in hass.data
        durations: dict[int, int] = self.hass.data.setdefault(
            f"{DOMAIN}_durations", {}
        )
        durations[self._zone_index] = int(value)
        self.async_write_ha_state()


class SolemRainDelayNumber(CoordinatorEntity[SolemCoordinator], NumberEntity):
    """Set a rain delay (suspend all watering for N days).

    Setting to 0 cancels any active rain delay.
    """

    _attr_icon = "mdi:weather-rainy"
    _attr_native_unit_of_measurement = UnitOfTime.DAYS
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0
    _attr_native_max_value = 365
    _attr_native_step = 1

    def __init__(self, coordinator: SolemCoordinator, ctrl_id: str) -> None:
        super().__init__(coordinator)
        self._ctrl_id = ctrl_id
        self._attr_unique_id = f"solem_{ctrl_id}_rain_delay"
        self._attr_name = "Solem Rain Delay"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> float:
        return float(self.coordinator.data.get("status", {}).get("rainDelay", 0))

    async def async_set_native_value(self, value: float) -> None:
        """Send rain delay command via the manual endpoint.

        action for rain delay is unknown — needs Proxyman capture of the
        app's "suspend watering" action to confirm the exact payload.
        Placeholder: action 5, days in the time field as "DD:00".
        """
        days = int(value)
        await self.coordinator.api._manual_command(
            relay_serial=self.coordinator.relay_serial,
            controller_suffix=self.coordinator.data["controller_suffix"],
            watering={"action": 5, "days": days, "time": "00:00"},
        )
        await self.coordinator.async_request_refresh()

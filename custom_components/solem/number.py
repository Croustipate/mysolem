"""Number entities for Solem: per-zone manual watering duration."""
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

from .const import DEFAULT_ZONE_DURATION, DOMAIN
from .coordinator import SolemCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SolemCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[NumberEntity] = []

    # One duration number per zone
    for output in coordinator.data.get("outputs", []):
        entities.append(SolemZoneDurationNumber(coordinator, output))

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


"""Button entity: global stop for all active watering."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SolemCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SolemCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SolemStopButton(coordinator)])


class SolemStopButton(CoordinatorEntity[SolemCoordinator], ButtonEntity):
    """Bouton d'arrêt global — stoppe tout arrosage en cours, quelle qu'en soit l'origine."""

    _attr_icon = "mdi:stop-circle-outline"
    _attr_has_entity_name = True
    _attr_translation_key = "stop_watering"

    def __init__(self, coordinator: SolemCoordinator) -> None:
        super().__init__(coordinator)
        ctrl = coordinator.data.get("controller", {})
        self._attr_unique_id = f"solem_stop_{ctrl.get('id', 'all')}"
        self._attr_name = "Arrêter l'arrosage"
        ctrl_id = ctrl.get("id", "")
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ctrl_id)},
            name=ctrl.get("name", "Solem Controller"),
            manufacturer="Solem",
            model=ctrl.get("type", "lr-is").upper(),
            sw_version=ctrl.get("softwareVersion"),
            hw_version=ctrl.get("hardwareVersion"),
            serial_number=ctrl.get("serialNumber"),
        )

    async def async_press(self, **kwargs: Any) -> None:
        _LOGGER.debug("Stop all watering button pressed")
        try:
            await self.coordinator.api.manual_stop(
                relay_serial=self.coordinator.relay_serial,
                controller_suffix=self.coordinator.data["controller_suffix"],
                controller_id=self.coordinator.data["controller_id"],
            )
            _LOGGER.debug("Stop command sent successfully")
        except Exception as err:
            _LOGGER.error("Failed to stop watering: %s", err)
            raise
        await self.coordinator.async_request_refresh()

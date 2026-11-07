"""Base entity for the Deye Power Bridge."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL
from .coordinator import DeyeCoordinator


class DeyeEntity(CoordinatorEntity[DeyeCoordinator]):
    """Common device info and unique-id handling."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DeyeCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

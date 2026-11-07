"""Switch entities: master enable and battery-export permission."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import DeyeCoordinator
from .entity import DeyeEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DeyeCoordinator = entry.runtime_data
    async_add_entities(
        [
            DeyeBridgeEnabledSwitch(coordinator),
            DeyeBatteryExportSwitch(coordinator),
        ]
    )


class DeyeBridgeEnabledSwitch(DeyeEntity, SwitchEntity, RestoreEntity):
    """Turns the whole translation on or off (off = restore the snapshot)."""

    _attr_name = "Bridge enabled"
    _attr_icon = "mdi:connection"

    def __init__(self, coordinator: DeyeCoordinator) -> None:
        super().__init__(coordinator, "enabled")

    @property
    def is_on(self) -> bool:
        return self.coordinator.runtime.enabled

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state != "on":
            return
        if not self.coordinator.has_snapshot:
            try:
                await self.coordinator.async_snapshot()
            except Exception as exc:  # noqa: BLE001 - never block startup
                _LOGGER.warning("Could not take a snapshot on startup: %s", exc)
                return
        self.coordinator.runtime.enabled = True
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        if not self.coordinator.has_snapshot:
            await self.coordinator.async_snapshot()
        self.coordinator.runtime.enabled = True
        self.async_write_ha_state()
        await self.coordinator.async_apply_now()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.runtime.enabled = False
        self.async_write_ha_state()
        try:
            await self.coordinator.async_restore()
        except Exception as exc:  # noqa: BLE001 - keep the switch usable
            _LOGGER.warning("Restore failed: %s", exc)


class DeyeBatteryExportSwitch(DeyeEntity, SwitchEntity, RestoreEntity):
    """Whether the battery may discharge into the export."""

    _attr_name = "Allow battery export"
    _attr_icon = "mdi:battery-arrow-up-outline"

    def __init__(self, coordinator: DeyeCoordinator) -> None:
        super().__init__(coordinator, "allow_battery_export")

    @property
    def is_on(self) -> bool:
        return self.coordinator.runtime.allow_battery_export

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state in ("on", "off"):
            self.coordinator.runtime.allow_battery_export = last_state.state == "on"
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        self.coordinator.runtime.allow_battery_export = True
        self.async_write_ha_state()
        await self.coordinator.async_apply_now()

    async def async_turn_off(self, **kwargs) -> None:
        self.coordinator.runtime.allow_battery_export = False
        self.async_write_ha_state()
        await self.coordinator.async_apply_now()

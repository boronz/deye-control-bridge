"""Number entities: the two power sliders and the SOC limits."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import DeyeCoordinator
from .entity import DeyeEntity


@dataclass(frozen=True, kw_only=True)
class DeyeNumberDescription(NumberEntityDescription):
    """A number that maps to a field of the runtime object."""

    runtime_attr: str


NUMBERS: tuple[DeyeNumberDescription, ...] = (
    DeyeNumberDescription(
        key="input_power",
        name="Grid charge power",
        icon="mdi:battery-charging",
        native_min_value=0.0,
        native_max_value=12000.0,
        native_step=100.0,
        native_unit_of_measurement=UnitOfPower.WATT,
        mode=NumberMode.BOX,
        runtime_attr="input_power",
    ),
    DeyeNumberDescription(
        key="export_power",
        name="Export power",
        icon="mdi:transmission-tower-export",
        native_min_value=0.0,
        native_max_value=12000.0,
        native_step=100.0,
        native_unit_of_measurement=UnitOfPower.WATT,
        mode=NumberMode.BOX,
        runtime_attr="export_power",
    ),
    DeyeNumberDescription(
        key="min_soc",
        name="Discharge floor SOC",
        icon="mdi:battery-arrow-down",
        native_min_value=0.0,
        native_max_value=90.0,
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        runtime_attr="min_soc",
    ),
    DeyeNumberDescription(
        key="max_soc",
        name="Charge ceiling SOC",
        icon="mdi:battery-arrow-up",
        native_min_value=10.0,
        native_max_value=100.0,
        native_step=1.0,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        runtime_attr="max_soc",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DeyeCoordinator = entry.runtime_data
    async_add_entities(DeyeNumber(coordinator, description) for description in NUMBERS)


class DeyeNumber(DeyeEntity, NumberEntity, RestoreEntity):
    """A runtime setpoint exposed as a native HA number."""

    entity_description: DeyeNumberDescription

    def __init__(
        self,
        coordinator: DeyeCoordinator,
        description: DeyeNumberDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_native_min_value = description.native_min_value
        self._attr_native_max_value = description.native_max_value
        self._attr_native_step = description.native_step
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_mode = description.mode or NumberMode.BOX

    @property
    def native_value(self) -> float:
        return float(getattr(self.coordinator.runtime, self.entity_description.runtime_attr))

    async def async_set_native_value(self, value: float) -> None:
        setattr(
            self.coordinator.runtime,
            self.entity_description.runtime_attr,
            float(value),
        )
        self.async_write_ha_state()
        await self.coordinator.async_apply_now()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state in (None, "unknown", "unavailable"):
            return
        try:
            value = float(last_state.state)
        except (TypeError, ValueError):
            return
        setattr(self.coordinator.runtime, self.entity_description.runtime_attr, value)
        self.async_write_ha_state()

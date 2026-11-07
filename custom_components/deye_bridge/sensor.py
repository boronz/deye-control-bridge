"""Sensor entities: measurements plus the state of the translation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import DeyeCoordinator, DeyeData
from .entity import DeyeEntity

BRIDGE_STATES = [
    "charging",
    "exporting",
    "self_consumption",
    "blocked",
    "disabled",
    "idle",
]


@dataclass(frozen=True, kw_only=True)
class DeyeSensorDescription(SensorEntityDescription):
    """A sensor whose value comes from the coordinator data."""

    options: list[str] | None = None
    value_fn: Callable[[DeyeData], float | str | None]


SENSORS: tuple[DeyeSensorDescription, ...] = (
    DeyeSensorDescription(
        key="battery_soc",
        name="Battery SOC",
        icon="mdi:battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.battery_soc,
    ),
    DeyeSensorDescription(
        key="battery_voltage",
        name="Battery voltage",
        icon="mdi:battery",
        native_unit_of_measurement="V",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.battery_voltage,
    ),
    DeyeSensorDescription(
        key="battery_power",
        name="Battery power",
        icon="mdi:battery",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.battery_power,
    ),
    DeyeSensorDescription(
        key="grid_power",
        name="Grid power",
        icon="mdi:transmission-tower",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.grid_power,
    ),
    DeyeSensorDescription(
        key="pv_power",
        name="PV power",
        icon="mdi:solar-power",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.pv_power,
    ),
    DeyeSensorDescription(
        key="load_power",
        name="Load power",
        icon="mdi:home-lightning-bolt",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.load_power,
    ),
    DeyeSensorDescription(
        key="bridge_state",
        name="Bridge state",
        icon="mdi:state-machine",
        device_class=SensorDeviceClass.ENUM,
        options=BRIDGE_STATES,
        value_fn=lambda data: data.state if data.state in BRIDGE_STATES else None,
    ),
    DeyeSensorDescription(
        key="applied_charge_power",
        name="Applied charge power",
        icon="mdi:battery-charging",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.applied_charge_power,
    ),
    DeyeSensorDescription(
        key="applied_export_power",
        name="Applied export power",
        icon="mdi:transmission-tower-export",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.export_power_w,
    ),
)



def _energy(key: str, name: str, icon: str) -> DeyeSensorDescription:
    return DeyeSensorDescription(
        key=key,
        name=name,
        icon=icon,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda data: data.energy.get(key),
    )


SENSORS = SENSORS + (
    _energy("pv_today", "PV energy today", "mdi:solar-power"),
    _energy("pv_total", "PV energy total", "mdi:solar-power"),
    _energy("grid_buy_today", "Grid import today", "mdi:transmission-tower-import"),
    _energy("grid_buy_total", "Grid import total", "mdi:transmission-tower-import"),
    _energy("grid_sell_today", "Grid export today", "mdi:transmission-tower-export"),
    _energy("grid_sell_total", "Grid export total", "mdi:transmission-tower-export"),
    _energy("battery_charge_today", "Battery charge today", "mdi:battery-plus"),
    _energy("battery_charge_total", "Battery charge total", "mdi:battery-plus"),
    _energy("battery_discharge_today", "Battery discharge today", "mdi:battery-minus"),
    _energy("battery_discharge_total", "Battery discharge total", "mdi:battery-minus"),
    _energy("load_today", "Load energy today", "mdi:home-lightning-bolt"),
    _energy("load_total", "Load energy total", "mdi:home-lightning-bolt"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DeyeCoordinator = entry.runtime_data
    async_add_entities(DeyeSensor(coordinator, description) for description in SENSORS)


class DeyeSensor(DeyeEntity, SensorEntity):
    """Read-only view of the coordinator data."""

    entity_description: DeyeSensorDescription

    def __init__(
        self,
        coordinator: DeyeCoordinator,
        description: DeyeSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class
        self._attr_options = description.options

    @property
    def native_value(self) -> float | str | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data)

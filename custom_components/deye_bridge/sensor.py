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
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER
from .coordinator import BatteryData, DeyeCoordinator, DeyeData
from .entity import DeyeEntity

BRIDGE_STATES = [
    "absorbing",
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


def _grid(
    key: str,
    name: str,
    unit: str | None,
    device_class: SensorDeviceClass | None,
    icon: str,
) -> DeyeSensorDescription:
    return DeyeSensorDescription(
        key=key,
        name=name,
        icon=icon,
        native_unit_of_measurement=unit,
        device_class=device_class,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda data: data.grid_detail.get(key),
    )


SENSORS = SENSORS + (
    _grid("grid_voltage_l1", "Grid voltage L1", "V", SensorDeviceClass.VOLTAGE, "mdi:transmission-tower"),
    _grid("grid_voltage_l2", "Grid voltage L2", "V", SensorDeviceClass.VOLTAGE, "mdi:transmission-tower"),
    _grid("grid_voltage_l3", "Grid voltage L3", "V", SensorDeviceClass.VOLTAGE, "mdi:transmission-tower"),
    _grid("grid_power_l1", "Grid power L1", UnitOfPower.WATT, SensorDeviceClass.POWER, "mdi:transmission-tower"),
    _grid("grid_power_l2", "Grid power L2", UnitOfPower.WATT, SensorDeviceClass.POWER, "mdi:transmission-tower"),
    _grid("grid_power_l3", "Grid power L3", UnitOfPower.WATT, SensorDeviceClass.POWER, "mdi:transmission-tower"),
    _grid("external_ct_l1", "External CT power L1", UnitOfPower.WATT, SensorDeviceClass.POWER, "mdi:current-ac"),
    _grid("external_ct_l2", "External CT power L2", UnitOfPower.WATT, SensorDeviceClass.POWER, "mdi:current-ac"),
    _grid("external_ct_l3", "External CT power L3", UnitOfPower.WATT, SensorDeviceClass.POWER, "mdi:current-ac"),
    _grid("external_ct_total", "External CT power total", UnitOfPower.WATT, SensorDeviceClass.POWER, "mdi:current-ac"),
    _grid("external_ct_current_l1", "External CT current L1", "A", SensorDeviceClass.CURRENT, "mdi:current-ac"),
    _grid("external_ct_current_l2", "External CT current L2", "A", SensorDeviceClass.CURRENT, "mdi:current-ac"),
    _grid("external_ct_current_l3", "External CT current L3", "A", SensorDeviceClass.CURRENT, "mdi:current-ac"),
    _grid("frequency", "Grid frequency", "Hz", SensorDeviceClass.FREQUENCY, "mdi:sine-wave"),
)


@dataclass(frozen=True, kw_only=True)
class DeyeBatterySensorDescription(SensorEntityDescription):
    """A sensor whose value comes from one BatteryData entry."""

    value_fn: Callable[[BatteryData], float | str | None]


BATTERY_SENSORS: tuple[DeyeBatterySensorDescription, ...] = (
    DeyeBatterySensorDescription(
        key="soc", name="SOC", icon="mdi:battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda b: b.soc,
    ),
    DeyeBatterySensorDescription(
        key="voltage", name="Voltage", icon="mdi:current-dc",
        native_unit_of_measurement="V",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda b: b.voltage,
    ),
    DeyeBatterySensorDescription(
        key="current", name="Current", icon="mdi:current-dc",
        native_unit_of_measurement="A",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda b: b.current,
    ),
    DeyeBatterySensorDescription(
        key="power", name="Power", icon="mdi:flash",
        native_unit_of_measurement=UnitOfPower.WATT,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda b: b.power,
    ),
    DeyeBatterySensorDescription(
        key="temperature", name="Temperature", icon="mdi:thermometer",
        native_unit_of_measurement="°C",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda b: b.temperature,
    ),
    DeyeBatterySensorDescription(
        key="soh", name="State of health", icon="mdi:heart-pulse",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda b: b.soh,
    ),
    DeyeBatterySensorDescription(
        key="capacity", name="Rated capacity", icon="mdi:battery-plus",
        native_unit_of_measurement="Ah",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda b: b.capacity_ah,
    ),
    DeyeBatterySensorDescription(
        key="charge_voltage", name="Charge voltage", icon="mdi:battery-arrow-up",
        native_unit_of_measurement="V",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda b: b.charge_voltage,
    ),
    DeyeBatterySensorDescription(
        key="discharge_voltage", name="Discharge voltage", icon="mdi:battery-arrow-down",
        native_unit_of_measurement="V",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda b: b.discharge_voltage,
    ),
    DeyeBatterySensorDescription(
        key="charge_current_limit", name="Charge current limit", icon="mdi:current-dc",
        native_unit_of_measurement="A",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda b: b.charge_current_limit,
    ),
    DeyeBatterySensorDescription(
        key="discharge_current_limit", name="Discharge current limit", icon="mdi:current-dc",
        native_unit_of_measurement="A",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda b: b.discharge_current_limit,
    ),
    DeyeBatterySensorDescription(
        key="max_charge_current", name="Max charge current", icon="mdi:current-dc",
        native_unit_of_measurement="A",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda b: b.max_charge_current,
    ),
    DeyeBatterySensorDescription(
        key="max_discharge_current", name="Max discharge current", icon="mdi:current-dc",
        native_unit_of_measurement="A",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda b: b.max_discharge_current,
    ),
    DeyeBatterySensorDescription(
        key="alarm", name="Alarm flags", icon="mdi:alert",
        value_fn=lambda b: b.alarm,
    ),
    DeyeBatterySensorDescription(
        key="fault", name="Fault flags", icon="mdi:alert-octagon",
        value_fn=lambda b: b.fault,
    ),
    DeyeBatterySensorDescription(
        key="battery_type", name="Battery type", icon="mdi:identifier",
        value_fn=lambda b: b.battery_type,
    ),
    DeyeBatterySensorDescription(
        key="brand", name="Brand", icon="mdi:factory",
        value_fn=lambda b: b.brand_name,
    ),
    DeyeBatterySensorDescription(
        key="software_version", name="Software version", icon="mdi:chip",
        value_fn=lambda b: b.software_version,
    ),
    DeyeBatterySensorDescription(
        key="hardware_version", name="Hardware version", icon="mdi:chip",
        value_fn=lambda b: b.hardware_version,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DeyeCoordinator = entry.runtime_data
    async_add_entities(DeyeSensor(coordinator, description) for description in SENSORS)

    # If a battery device was created earlier but the input is empty now,
    # drop it so the device list matches the hardware.
    data = coordinator.data
    if data is not None and data.battery_count >= 2:
        parsed = {battery.index: battery for battery in data.batteries}
        if 2 in parsed and not parsed[2].online:
            _remove_battery_device(hass, entry, 2)

    # Battery 1 is always created so an offline pack still has a device.
    added: set[int] = {1}
    async_add_entities(
        DeyeBatterySensor(coordinator, description, 1)
        for description in BATTERY_SENSORS
    )

    def add_present_batteries() -> None:
        """Create battery devices only for inputs that report a real pack.

        Register 24 reports how many inputs the inverter is *configured* for,
        which is not the same as how many batteries are wired.  A battery's own
        voltage is the reliable signal, and a second pack that comes online later
        gets its entities added on the next poll.
        """
        data = coordinator.data
        if data is None:
            return
        for battery in data.batteries:
            if battery.index in added or not battery.online:
                continue
            added.add(battery.index)
            async_add_entities(
                DeyeBatterySensor(coordinator, description, battery.index)
                for description in BATTERY_SENSORS
            )

    add_present_batteries()
    entry.async_on_unload(coordinator.async_add_listener(add_present_batteries))


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


class DeyeBatterySensor(DeyeEntity, SensorEntity):
    """A battery sensor attached to its own HA device."""

    entity_description: DeyeBatterySensorDescription

    def __init__(
        self,
        coordinator: DeyeCoordinator,
        description: DeyeBatterySensorDescription,
        index: int,
    ) -> None:
        super().__init__(coordinator, f"battery{index}_{description.key}")
        self.entity_description = description
        self.index = index
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{coordinator.entry.entry_id}_battery{index}")},
            name=f"Deye battery {index}",
            manufacturer=MANUFACTURER,
            model="Battery",
            via_device=(DOMAIN, coordinator.entry.entry_id),
        )

    def _battery(self) -> BatteryData | None:
        data = self.coordinator.data
        if data is None:
            return None
        return next((b for b in data.batteries if b.index == self.index), None)

    @property
    def available(self) -> bool:
        if not self.coordinator.last_update_success:
            return False
        battery = self._battery()
        return bool(battery and battery.online)

    @property
    def native_value(self) -> float | str | None:
        battery = self._battery()
        if battery is None:
            return None
        return self.entity_description.value_fn(battery)


def _remove_battery_device(hass: HomeAssistant, entry: ConfigEntry, index: int) -> None:
    """Remove a battery device whose input no longer has a pack on it."""
    registry = dr.async_get(hass)
    device = registry.async_get_device(
        identifiers={(DOMAIN, f"{entry.entry_id}_battery{index}")}
    )
    if device is not None:
        registry.async_remove_device(device.id)

"""Smoke-test that every integration module imports and entities construct.

Home Assistant is not installed in a bare test runner, so tests/ha_stub contains
minimal stand-ins for the HA classes the integration touches.  They are not a
substitute for `hassfest`, but they catch syntax errors, bad imports, MRO
problems and dataclass mistakes.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent / "ha_stub"))
sys.path.insert(0, str(ROOT))

import importlib  # noqa: E402

MODULES = [
    "custom_components.deye_bridge.const",
    "custom_components.deye_bridge.core",
    "custom_components.deye_bridge.runtime",
    "custom_components.deye_bridge.transport",
    "custom_components.deye_bridge.coordinator",
    "custom_components.deye_bridge.entity",
    "custom_components.deye_bridge.number",
    "custom_components.deye_bridge.switch",
    "custom_components.deye_bridge.select",
    "custom_components.deye_bridge.sensor",
    "custom_components.deye_bridge.binary_sensor",
    "custom_components.deye_bridge.config_flow",
    "custom_components.deye_bridge.diagnostics",
    "custom_components.deye_bridge",
]


def test_modules_import():
    for name in MODULES:
        importlib.import_module(name)


def test_entities_construct():
    from custom_components.deye_bridge.binary_sensor import DeyeConnectedBinarySensor
    from custom_components.deye_bridge.coordinator import BatteryData, DeyeData
    from custom_components.deye_bridge.number import NUMBERS, DeyeNumber
    from custom_components.deye_bridge.runtime import DeyeRuntime
    from custom_components.deye_bridge.select import DeyeConflictPolicySelect
    from custom_components.deye_bridge.sensor import (
        BATTERY_SENSORS,
        SENSORS,
        DeyeBatterySensor,
        DeyeSensor,
    )
    from custom_components.deye_bridge.switch import (
        DeyeBatteryExportSwitch,
        DeyeControlEnabledSwitch,
    )

    class FakeEntry:
        entry_id = "e1"
        title = "Deye inverter"

    class FakeCoordinator:
        entry = FakeEntry()
        runtime = DeyeRuntime()
        data = DeyeData(
            50.0, 52.0, -1000.0, 500.0, 2000.0, 1200.0,
            "charging", "test", 96.0, 0.0,
            batteries=[BatteryData(
                index=1, soc=60.0, voltage=53.0, current=10.0, power=-500.0,
                temperature=25.0, charge_voltage=56.0, discharge_voltage=46.0,
                charge_current_limit=100.0, discharge_current_limit=100.0,
                max_charge_current=120.0, max_discharge_current=120.0,
                soh=99.0, capacity_ah=280.0, alarm=0, fault=0,
                battery_type=14, brand=14, software_version=1,
                hardware_version=2, online=True,
            )],
            battery_count=1,
        )
        last_update_success = True

    coordinator = FakeCoordinator()

    numbers = [DeyeNumber(coordinator, description) for description in NUMBERS]
    assert [n.native_value for n in numbers] == [0.0, 0.0, 20.0, 100.0]

    sensors = [DeyeSensor(coordinator, description) for description in SENSORS]
    values = {s.entity_description.key: s.native_value for s in sensors}
    assert values["battery_soc"] == 50.0
    assert values["bridge_state"] == "charging"
    assert values["applied_charge_power"] == 4992

    assert DeyeControlEnabledSwitch(coordinator).is_on is False
    assert DeyeBatteryExportSwitch(coordinator).is_on is True
    assert DeyeConflictPolicySelect(coordinator).current_option == "charge_priority"
    assert DeyeConnectedBinarySensor(coordinator).is_on is True

    battery_sensors = [
        DeyeBatterySensor(coordinator, description, 1)
        for description in BATTERY_SENSORS
    ]
    battery_values = {
        sensor.entity_description.key: sensor.native_value
        for sensor in battery_sensors
    }
    assert battery_values["soc"] == 60.0
    assert battery_values["voltage"] == 53.0
    assert battery_values["soh"] == 99.0
    assert battery_values["brand"] == "Deye"
    assert battery_sensors[0].unique_id.endswith("_battery1_soc")
    assert battery_sensors[0].device_info["name"] == "Deye battery 1"


if __name__ == "__main__":
    test_modules_import()
    test_entities_construct()
    print("import + entity smoke tests passed")

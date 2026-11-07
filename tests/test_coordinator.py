"""The control interlock must keep the integration read-only until enabled."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent / "ha_stub"))
sys.path.insert(0, str(ROOT))

import asyncio  # noqa: E402

from custom_components.deye_bridge.coordinator import DeyeCoordinator  # noqa: E402
from custom_components.deye_bridge.core import (  # noqa: E402
    MODE_SELF_CONSUMPTION,
    Inputs,
    build_plan,
)
from custom_components.deye_bridge.runtime import DeyeRuntime  # noqa: E402


class FakeEntry:
    entry_id = "e1"
    title = "Deye inverter"
    data = {}
    options = {"verify_every": 0}


class FakeHass:
    async def async_add_executor_job(self, target, *args):
        return target(*args)


class FakeTransport:
    def __init__(self) -> None:
        self.writes: list[tuple[int, list[int]]] = []

    def read_holding(self, address: int, count: int) -> list[int]:
        return [0] * count

    def write_holding(self, address: int, values: list[int]) -> None:
        self.writes.append((address, list(values)))

    def close(self) -> None:
        pass


def _coordinator(enabled: bool) -> tuple[DeyeCoordinator, FakeTransport]:
    runtime = DeyeRuntime()
    runtime.enabled = enabled
    runtime.input_power = 4000
    transport = FakeTransport()
    coordinator = DeyeCoordinator(FakeHass(), FakeEntry(), transport, runtime)
    return coordinator, transport


def test_disabled_never_writes():
    coordinator, transport = _coordinator(enabled=False)
    plan = build_plan(
        coordinator._config(),
        Inputs(
            charge_power_w=4000,
            soc=50,
            battery_voltage=52.0,
            enabled=False,
        ),
    )
    assert plan.writes == []          # the translation itself already refuses
    assert coordinator._execute(plan) == 0
    assert transport.writes == []


def test_disabled_blocks_even_a_plan_built_while_enabled():
    """Defence in depth: a stale plan must not bypass the interlock."""
    coordinator, transport = _coordinator(enabled=False)
    plan = build_plan(
        coordinator._config(),
        Inputs(
            charge_power_w=4000,
            soc=50,
            battery_voltage=52.0,
            enabled=True,
        ),
    )
    assert plan.writes                       # the plan would write ...
    assert coordinator._execute(plan) == 0   # ... but the interlock stops it
    assert transport.writes == []


class GridTransport(FakeTransport):
    """Returns a chosen grid power (positive import) and battery SOC."""

    def __init__(self, grid_power: int = 0, soc: int = 50, voltage: int = 5200) -> None:
        super().__init__()
        self.grid_power = grid_power
        self.soc = soc
        self.voltage = voltage

    def read_holding(self, address: int, count: int) -> list[int]:
        if address == 586:
            block = [0] * count
            block[0] = 1250            # temperature, 25.0 C
            block[1] = self.voltage     # 587 battery voltage
            block[2] = self.soc         # 588 battery SOC
            block[4] = 0                # 590 battery power
            return block
        if address == 598:
            block = [0] * count
            block[0] = 2300             # L1 voltage 230.0 V
            block[1] = 2310             # L2
            block[2] = 2290             # L3
            block[11] = 5000            # 609 grid frequency 50.00 Hz
            block[15] = 1000            # 613 external CT current L1 10 A
            block[16] = 1000
            block[17] = 1000
            block[18] = (-1000) & 0xFFFF  # 616 external CT power L1
            block[19] = (-1000) & 0xFFFF
            block[20] = (-1000) & 0xFFFF
            block[21] = (-3000) & 0xFFFF  # 619 external CT total
            block[24] = (-1000) & 0xFFFF  # 622 selected CT power L1
            block[25] = (-1000) & 0xFFFF
            block[26] = (-1000) & 0xFFFF
            block[27] = self.grid_power & 0xFFFF  # 625 grid total
            return block
        if address == 626:
            return [0] * count
        if address == 24:
            return [1]
        if address == 210:
            block = [0] * count
            block[0] = 5600             # charge voltage 56.00 V
            block[1] = 4600             # discharge voltage 46.00 V
            block[2] = 100              # charge current limit
            block[3] = 100              # discharge current limit
            block[4] = self.soc         # SOC
            block[5] = self.voltage     # voltage
            block[6] = 10               # current
            block[7] = 1250            # temperature
            block[8] = 120              # max charge current
            block[9] = 120              # max discharge current
            block[13] = 14              # type
            block[14] = 99              # SOH
            block[16] = 280             # rated Ah
            block[19] = 14              # brand: Deye
            return block
        return [0] * count


def _self_consumption(grid_power: int, enabled: bool = True):
    entry = FakeEntry()
    entry.options = {
        "verify_every": 0,
        "absorb_enter_hold": 0,
        "absorb_exit_hold": 0,
    }
    runtime = DeyeRuntime()
    runtime.enabled = enabled
    runtime.mode = MODE_SELF_CONSUMPTION
    transport = GridTransport(grid_power=grid_power)
    coordinator = DeyeCoordinator(FakeHass(), entry, transport, runtime)
    data = asyncio.run(coordinator._async_update_data())
    return coordinator, transport, data


def test_battery_block_is_parsed():
    runtime = DeyeRuntime()
    transport = GridTransport(grid_power=0, soc=60, voltage=5300)
    coordinator = DeyeCoordinator(FakeHass(), FakeEntry(), transport, runtime)
    data = asyncio.run(coordinator._async_update_data())

    assert data.battery_count == 1
    assert len(data.batteries) == 1

    battery = data.batteries[0]
    assert battery.soc == 60
    assert battery.voltage == 53.0
    assert battery.current == 10
    assert battery.temperature == 25.0
    assert battery.charge_voltage == 56.0
    assert battery.discharge_voltage == 46.0
    assert battery.max_charge_current == 120
    assert battery.soh == 99
    assert battery.capacity_ah == 280
    assert battery.brand == 14
    assert battery.brand_name == "Deye"
    assert battery.online is True


def test_ct_and_phase_values_are_parsed():
    runtime = DeyeRuntime()
    transport = GridTransport(grid_power=-3000, soc=50, voltage=5200)
    coordinator = DeyeCoordinator(FakeHass(), FakeEntry(), transport, runtime)
    data = asyncio.run(coordinator._async_update_data())

    assert data.grid_power == -3000
    assert data.grid_detail["voltage_l1"] == 230.0
    assert data.grid_detail["voltage_l2"] == 231.0
    assert data.grid_detail["voltage_l3"] == 229.0
    assert data.grid_detail["frequency"] == 50.0
    assert data.grid_detail["power_l1"] == -1000
    assert data.grid_detail["power_l2"] == -1000
    assert data.grid_detail["power_l3"] == -1000
    assert data.grid_detail["external_ct_l1"] == -1000
    assert data.grid_detail["external_ct_total"] == -3000
    assert data.grid_detail["external_ct_current_l1"] == 10.0


def test_absorption_uses_the_fast_poll_interval():
    runtime = DeyeRuntime()
    runtime.enabled = True
    runtime.mode = MODE_SELF_CONSUMPTION
    entry = FakeEntry()
    entry.options = {"verify_every": 0, "absorb_enter_hold": 0, "absorb_exit_hold": 0}
    transport = GridTransport(grid_power=-2000)
    coordinator = DeyeCoordinator(FakeHass(), entry, transport, runtime)

    asyncio.run(coordinator._async_update_data())
    assert coordinator.update_interval.total_seconds() == 10   # absorb default

    transport.grid_power = 500
    asyncio.run(coordinator._async_update_data())
    assert coordinator.update_interval.total_seconds() == 30   # back to normal


def test_absorption_interval_is_configurable():
    entry = FakeEntry()
    entry.options = {
        "verify_every": 0,
        "scan_interval": 60,
        "absorb_interval": 5,
        "absorb_enter_hold": 0,
        "absorb_exit_hold": 0,
    }
    runtime = DeyeRuntime()
    runtime.enabled = True
    runtime.mode = MODE_SELF_CONSUMPTION
    transport = GridTransport(grid_power=-2000)
    coordinator = DeyeCoordinator(FakeHass(), entry, transport, runtime)

    asyncio.run(coordinator._async_update_data())
    assert coordinator.update_interval.total_seconds() == 5

    transport.grid_power = 500
    asyncio.run(coordinator._async_update_data())
    assert coordinator.update_interval.total_seconds() == 60


def test_import_hands_back_to_self_consumption():
    entry = FakeEntry()
    entry.options = {
        "verify_every": 0,
        "absorb_enter_hold": 0,
        "absorb_exit_hold": 3600,   # would hold forever without the import rule
    }
    runtime = DeyeRuntime()
    runtime.enabled = True
    runtime.mode = MODE_SELF_CONSUMPTION
    transport = GridTransport(grid_power=-2000)
    coordinator = DeyeCoordinator(FakeHass(), entry, transport, runtime)

    data = asyncio.run(coordinator._async_update_data())
    assert data.state == "absorbing"
    assert (146, [0]) in transport.writes        # TOU off while charging

    transport.grid_power = 800                  # house is importing now
    coordinator._last_write.clear()             # pretend the poll interval passed
    data = asyncio.run(coordinator._async_update_data())
    assert data.state == "self_consumption"
    assert (146, [255]) in transport.writes      # TOU on: battery may discharge
    assert (145, [0]) in transport.writes        # no export
    assert (142, [2]) in transport.writes        # zero export to CT


class TwoBatteryTransport(GridTransport):
    """Register 24 says two inputs, but the second one is empty."""

    def read_holding(self, address: int, count: int) -> list[int]:
        if address == 24:
            return [2]
        if address == 241:
            return [0] * count
        return super().read_holding(address, count)


def test_absent_second_battery_is_offline():
    runtime = DeyeRuntime()
    transport = TwoBatteryTransport(grid_power=0, soc=50, voltage=5200)
    coordinator = DeyeCoordinator(FakeHass(), FakeEntry(), transport, runtime)
    data = asyncio.run(coordinator._async_update_data())

    assert data.battery_count == 2          # the inverter is configured for two
    assert len(data.batteries) == 2
    assert data.batteries[0].online is True
    assert data.batteries[1].online is False   # ...but nothing is wired there


def test_self_consumption_absorbs_export():
    _, transport, data = _self_consumption(grid_power=-2000)
    assert data.state == "absorbing"
    assert (130, [1]) in transport.writes          # grid charge enabled
    assert (146, [0]) in transport.writes          # TOU off while charging
    currents = [values[0] for address, values in transport.writes if address == 128]
    assert currents and currents[-1] > 0           # charging current set


def test_self_consumption_without_export_is_zero_export():
    _, transport, data = _self_consumption(grid_power=500)
    assert data.state == "self_consumption"
    assert (146, [255]) in transport.writes        # TOU on, discharge to floor
    assert (145, [0]) in transport.writes          # solar sell off
    assert (130, [0]) in transport.writes          # no grid charging


def test_self_consumption_does_nothing_when_disabled():
    _, transport, data = _self_consumption(grid_power=-2000, enabled=False)
    assert data.state == "disabled"
    assert transport.writes == []


def test_enabled_writes():
    coordinator, transport = _coordinator(enabled=True)
    plan = build_plan(
        coordinator._config(),
        Inputs(
            charge_power_w=4000,
            soc=50,
            battery_voltage=52.0,
            enabled=True,
        ),
    )
    assert coordinator._execute(plan) > 0
    assert transport.writes
    addresses = [address for address, _ in transport.writes]
    assert 130 in addresses   # grid charge enable
    assert 128 in addresses   # grid charge current


if __name__ == "__main__":
    failures = 0
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_")]
    for name, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {name}: {exc}")
        else:
            print(f"ok   {name}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)

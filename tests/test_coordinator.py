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
    ExcessConfig,
    ExcessController,
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
        if address == 625:
            block = [0] * count
            block[0] = self.grid_power & 0xFFFF
            return block
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
    runtime = DeyeRuntime()
    runtime.enabled = enabled
    runtime.mode = MODE_SELF_CONSUMPTION
    transport = GridTransport(grid_power=grid_power)
    coordinator = DeyeCoordinator(FakeHass(), FakeEntry(), transport, runtime)
    coordinator.excess = ExcessController(
        ExcessConfig(enter_hold_s=0, exit_hold_s=0)
    )
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

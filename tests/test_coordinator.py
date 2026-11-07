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
        if address == 587:
            return [self.voltage, self.soc, 0, 0, 0]
        if address == 625:
            block = [0] * count
            block[0] = self.grid_power & 0xFFFF
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

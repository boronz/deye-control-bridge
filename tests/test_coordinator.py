"""The control interlock must keep the integration read-only until enabled."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent / "ha_stub"))
sys.path.insert(0, str(ROOT))

from custom_components.deye_bridge.coordinator import DeyeCoordinator  # noqa: E402
from custom_components.deye_bridge.core import Inputs, build_plan  # noqa: E402
from custom_components.deye_bridge.runtime import DeyeRuntime  # noqa: E402


class FakeEntry:
    entry_id = "e1"
    title = "Deye inverter"
    data = {}
    options = {}


class FakeHass:
    pass


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
    test_disabled_never_writes()
    test_disabled_blocks_even_a_plan_built_while_enabled()
    test_enabled_writes()
    print("coordinator interlock tests passed")

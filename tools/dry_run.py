#!/usr/bin/env python3
"""Dry-run the translation: print the register writes for a few scenarios.

No Home Assistant, no inverter, no network — useful for reviewing the behaviour
before installing anything.

    python tools/dry_run.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_CORE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "deye_bridge"
    / "core.py"
)
_spec = importlib.util.spec_from_file_location("deye_bridge_core", _CORE_PATH)
_core = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _core
_spec.loader.exec_module(_core)

from deye_bridge_core import Config, Inputs, build_plan  # noqa: E402

NAMES = {
    108: "max charge current",
    109: "max discharge current",
    127: "grid charge start SOC",
    128: "grid charge current",
    130: "grid charge enable",
    142: "work mode",
    143: "max sell power",
    145: "solar sell",
    146: "TOU enable",
    154: "TOU power block",
    166: "TOU SOC block",
    172: "TOU charge block",
}

SCENARIOS = [
    ("idle / self-consumption", dict()),
    ("charge 4 kW from grid", dict(charge_power_w=4000)),
    ("charge 9 kW from grid", dict(charge_power_w=9000)),
    ("export 3 kW (battery allowed)", dict(export_power_w=3000)),
    ("export 3 kW (PV only)", dict(export_power_w=3000, allow_battery_export=False)),
    ("both set, charge wins", dict(charge_power_w=4000, export_power_w=3000)),
    ("both set, net", dict(charge_power_w=1000, export_power_w=4000, conflict_policy="net")),
    ("export near empty battery", dict(export_power_w=3000, soc=20.5)),
    ("charge near full battery", dict(charge_power_w=3000, soc=99.5)),
]


def main() -> int:
    cfg = Config()
    for title, kwargs in SCENARIOS:
        inputs = Inputs(**{"soc": 50, "battery_voltage": 52.0, **kwargs})
        plan = build_plan(cfg, inputs)
        print(f"\n=== {title} ===")
        print(f"    {plan.describe()}")
        for write in plan.writes:
            name = NAMES.get(write.address, "")
            if write.is_block:
                print(f"    {write.address:>3}..{write.address + len(write.values) - 1:<3} "
                      f"{str(list(write.values)):<40} {name}")
            else:
                print(f"    {write.address:>3}     {write.values[0]:<40} {name}")
    print("\nNote: register 109 is only written when entering or leaving the")
    print("'battery held' state (PV-only export); the adapter leaves the")
    print("installer's discharge current alone otherwise.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

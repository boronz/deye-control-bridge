"""Unit tests for the slider -> register translation.

Run with:  pytest tests/ -q
or:        python tests/test_core.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# The integration package imports Home Assistant, which is not available in a
# bare test runner, so load the pure logic module directly.
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

from deye_bridge_core import (  # noqa: E402
    Config,
    Inputs,
    REG_GRID_CHARGE_CURRENT,
    REG_GRID_CHARGE_ENABLE,
    REG_GRID_CHARGE_START_SOC,
    REG_MAX_CHARGE_CURRENT,
    REG_MAX_DISCHARGE_CURRENT,
    REG_MAX_SELL_POWER,
    REG_SOLAR_SELL,
    REG_TOU_CHARGE_BLOCK,
    REG_TOU_ENABLE,
    REG_TOU_POWER_BLOCK,
    REG_TOU_SOC_BLOCK,
    REG_WORK_MODE,
    MODE_SELLING_FIRST,
    MODE_ZERO_EXPORT_CT,
    ExcessConfig,
    ExcessController,
    build_plan,
)


def _cfg(**kw) -> Config:
    base = dict(max_grid_charge_power_w=9000, max_export_power_w=12000)
    base.update(kw)
    return Config(**base)


def _inputs(**kw) -> Inputs:
    base = dict(
        charge_power_w=0,
        export_power_w=0,
        soc=50,
        battery_voltage=52.0,
        enabled=True,
        allow_battery_export=True,
        min_soc=20,
        max_soc=100,
    )
    base.update(kw)
    return Inputs(**base)


def _writes(plan):
    """Flatten a plan into {address: values-tuple}."""
    return {w.address: w.values for w in plan.writes}


# --------------------------------------------------------------------------
# State selection
# --------------------------------------------------------------------------
def test_disabled_does_nothing():
    plan = build_plan(_cfg(), _inputs(enabled=False, charge_power_w=4000))
    assert plan.state == "disabled"
    assert plan.writes == []


def test_missing_measurements_blocks():
    plan = build_plan(_cfg(), _inputs(soc=None))
    assert plan.state == "blocked"
    assert plan.writes == []


def test_no_setpoints_is_self_consumption():
    plan = build_plan(_cfg(), _inputs())
    assert plan.state == "self_consumption"
    w = _writes(plan)
    assert w[REG_TOU_ENABLE] == (0x00FF,)
    assert w[REG_SOLAR_SELL] == (0,)
    assert w[REG_MAX_SELL_POWER] == (0,)
    assert w[REG_GRID_CHARGE_ENABLE] == (0,)
    assert w[REG_WORK_MODE] == (MODE_ZERO_EXPORT_CT,)
    assert w[REG_TOU_SOC_BLOCK] == (20,) * 6


# --------------------------------------------------------------------------
# Charging
# --------------------------------------------------------------------------
def test_charge_power_converts_to_current():
    plan = build_plan(_cfg(), _inputs(charge_power_w=4000, battery_voltage=50.0))
    assert plan.state == "charging"
    assert plan.charge_current_a == 80
    w = _writes(plan)
    assert w[REG_GRID_CHARGE_CURRENT] == (80,)
    assert w[REG_GRID_CHARGE_ENABLE] == (1,)
    assert w[REG_GRID_CHARGE_START_SOC] == (100,)
    assert w[REG_SOLAR_SELL] == (0,)
    assert w[REG_MAX_SELL_POWER] == (0,)
    # TOU must be switched off *before* grid charging is enabled.
    order = [w_.address for w_ in plan.writes]
    assert order.index(REG_TOU_ENABLE) < order.index(REG_GRID_CHARGE_ENABLE)


def test_charge_current_clamped_to_register_limit():
    plan = build_plan(_cfg(), _inputs(charge_power_w=9000, battery_voltage=48.0))
    # 9000 / 48 = 187.5 A -> clamp to 185 A
    assert plan.charge_current_a == 185


def test_charge_power_clamped_to_installation_limit():
    plan = build_plan(_cfg(), _inputs(charge_power_w=12000, battery_voltage=50.0))
    assert plan.charge_current_a == 180  # 9000 W / 50 V


def test_charge_allowed_at_high_soc_when_below_max():
    plan = build_plan(_cfg(), _inputs(charge_power_w=3000, soc=97, max_soc=100))
    assert plan.state == "charging"


def test_no_charge_at_max_soc():
    plan = build_plan(_cfg(), _inputs(charge_power_w=3000, soc=100, max_soc=100))
    assert plan.state == "self_consumption"


def test_tiny_charge_setpoint_is_ignored():
    plan = build_plan(_cfg(), _inputs(charge_power_w=50))
    assert plan.state == "self_consumption"


def test_charge_can_disable_global_current_management():
    cfg = _cfg(manage_max_charge_current=False)
    plan = build_plan(cfg, _inputs(charge_power_w=4000))
    assert REG_MAX_CHARGE_CURRENT not in _writes(plan)


def test_global_current_is_raised_when_managed():
    plan = build_plan(_cfg(manage_max_charge_current=True), _inputs(charge_power_w=4000))
    assert _writes(plan)[REG_MAX_CHARGE_CURRENT] == (185,)


# --------------------------------------------------------------------------
# Export / discharge
# --------------------------------------------------------------------------
def test_export_sets_sell_cap_and_mode():
    plan = build_plan(_cfg(), _inputs(export_power_w=3000))
    assert plan.state == "exporting"
    w = _writes(plan)
    assert w[REG_MAX_SELL_POWER] == (3000,)
    assert w[REG_SOLAR_SELL] == (1,)
    assert w[REG_WORK_MODE] == (MODE_SELLING_FIRST,)
    assert w[REG_GRID_CHARGE_ENABLE] == (0,)
    assert w[REG_TOU_ENABLE] == (0x00FF,)
    assert w[REG_TOU_SOC_BLOCK] == (20,) * 6
    assert w[REG_TOU_POWER_BLOCK] == (12000,) * 6
    assert w[REG_TOU_CHARGE_BLOCK] == (0,) * 6


def test_export_writes_slots_before_enabling_tou():
    plan = build_plan(_cfg(), _inputs(export_power_w=3000))
    order = [w.address for w in plan.writes]
    assert order.index(REG_TOU_SOC_BLOCK) < order.index(REG_TOU_ENABLE)
    assert order.index(REG_GRID_CHARGE_ENABLE) < order.index(REG_TOU_ENABLE)


def test_export_blocked_at_or_below_floor():
    plan = build_plan(_cfg(), _inputs(export_power_w=3000, soc=20.5, min_soc=20))
    assert plan.state != "exporting"
    assert plan.export_power_w == 0


def test_export_power_clamped():
    plan = build_plan(_cfg(), _inputs(export_power_w=20000))
    assert plan.export_power_w == 12000


def test_pv_only_export_holds_battery():
    plan = build_plan(_cfg(), _inputs(export_power_w=3000, soc=80, allow_battery_export=False))
    w = _writes(plan)
    assert w[REG_MAX_DISCHARGE_CURRENT] == (0,)    # hold the battery
    assert w[REG_TOU_POWER_BLOCK] == (0,) * 6      # belt and braces
    assert w[REG_WORK_MODE] == (MODE_SELLING_FIRST,)
    assert w[REG_MAX_SELL_POWER] == (3000,)


def test_battery_export_allows_discharge():
    plan = build_plan(_cfg(), _inputs(export_power_w=3000))
    assert _writes(plan)[REG_MAX_DISCHARGE_CURRENT] == (185,)


def test_charge_restores_discharge_current():
    plan = build_plan(_cfg(), _inputs(charge_power_w=3000))
    assert _writes(plan)[REG_MAX_DISCHARGE_CURRENT] == (185,)


# --------------------------------------------------------------------------
# Conflict resolution
# --------------------------------------------------------------------------
def test_conflict_charge_priority():
    plan = build_plan(_cfg(), _inputs(charge_power_w=4000, export_power_w=3000))
    assert plan.state == "charging"
    assert plan.export_power_w == 0


def test_conflict_export_priority():
    plan = build_plan(
        _cfg(conflict_policy="export_priority"),
        _inputs(charge_power_w=4000, export_power_w=3000),
    )
    assert plan.state == "exporting"
    assert plan.charge_current_a == 0


def test_conflict_net_charges_the_difference():
    plan = build_plan(
        _cfg(conflict_policy="net"),
        _inputs(charge_power_w=4000, export_power_w=1000, battery_voltage=50.0),
    )
    assert plan.state == "charging"
    assert plan.charge_current_a == 60  # 3000 W / 50 V


def test_conflict_net_exports_the_difference():
    plan = build_plan(
        _cfg(conflict_policy="net"),
        _inputs(charge_power_w=1000, export_power_w=4000),
    )
    assert plan.state == "exporting"
    assert plan.export_power_w == 3000


# --------------------------------------------------------------------------
# Safety and shape
# --------------------------------------------------------------------------
def test_all_writes_are_16_bit():
    for plan in (
        build_plan(_cfg(), _inputs(charge_power_w=9000)),
        build_plan(_cfg(), _inputs(export_power_w=12000)),
        build_plan(_cfg(), _inputs()),
    ):
        for write in plan.writes:
            assert all(0 <= v <= 0xFFFF for v in write.values)


def test_soc_inputs_are_sanitised():
    plan = build_plan(_cfg(), _inputs(soc=150))
    assert plan.state == "self_consumption"  # clamped to 100 -> no charge anyway


def test_soc_margin_blocks_export_near_floor():
    plan = build_plan(_cfg(), _inputs(export_power_w=3000, soc=21, min_soc=20))
    assert plan.state == "self_consumption"


def test_tou_floor_never_above_charge_target():
    plan = build_plan(_cfg(), _inputs(export_power_w=3000, min_soc=30))
    assert _writes(plan)[REG_TOU_SOC_BLOCK] == (30,) * 6




# --------------------------------------------------------------------------
# Self-consumption / AC-coupled export absorption
# --------------------------------------------------------------------------
def test_charge_hold_keeps_the_charge_path_open():
    plan = build_plan(
        _cfg(),
        _inputs(enabled=True, charge_power_w=0, charge_hold=True),
    )
    assert plan.state == "charging"
    w = _writes(plan)
    assert w[REG_GRID_CHARGE_ENABLE] == (1,)
    assert w[REG_GRID_CHARGE_CURRENT] == (0,)    # nothing drawn
    assert w[REG_TOU_ENABLE] == (0,)             # TOU off


def test_charge_hold_does_nothing_when_disabled():
    plan = build_plan(_cfg(), _inputs(enabled=False, charge_hold=True))
    assert plan.state == "disabled"
    assert plan.writes == []


def _controller(**kwargs) -> ExcessController:
    return ExcessController(ExcessConfig(**kwargs))


def test_absorb_starts_only_after_the_hold_time():
    controller = _controller(enter_hold_s=10, exit_hold_s=60)
    assert controller.update(0, -500, 50, 100) == 0.0
    assert controller.absorbing is False
    assert controller.update(5, -500, 50, 100) == 0.0
    assert controller.absorbing is False
    target = controller.update(10, -500, 50, 100)
    assert controller.absorbing is True
    assert target == 475.0            # 500 W * 0.95


def test_absorb_ignores_small_export():
    controller = _controller(enter_export_w=150, enter_hold_s=0)
    assert controller.update(0, -100, 50, 100) == 0.0
    assert controller.absorbing is False


def test_absorb_stops_after_the_exit_hold():
    controller = _controller(enter_hold_s=0, exit_hold_s=60)
    controller.update(0, -500, 50, 100)
    assert controller.absorbing is True

    # export gone: charge target is zero immediately, state only flips later
    assert controller.update(100, 0, 50, 100) == 0.0
    assert controller.absorbing is True
    assert controller.update(130, 0, 50, 100) == 0.0
    assert controller.absorbing is True
    controller.update(161, 0, 50, 100)
    assert controller.absorbing is False


def test_absorb_stops_at_the_charge_ceiling():
    controller = _controller(enter_hold_s=0)
    controller.update(0, -2000, 50, 100)
    assert controller.absorbing is True
    assert controller.update(1, -2000, 100, 100) == 0.0
    assert controller.absorbing is False


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

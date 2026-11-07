"""Pure translation logic for the Deye SUN-12K-SG05LP3-EU-SM2.

The inverter has no "charge at X watt" or "export at X watt" setpoint.  It has a
rule engine built around time-of-use slots, SOC targets and current limits.
This module turns two intuitive power setpoints into an ordered list of Modbus
register writes that make the inverter behave as if it had those setpoints.

Nothing in here talks to Home Assistant or to the inverter: the output is data,
so the rules can be unit-tested and reused by any front end (pyscript,
AppDaemon, Node-RED, a standalone service, ...).

Reference numbers are the Deye three-phase LV hybrid register map
(device type 0x0500), documented in docs/register-map.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# Register addresses (decimal)
# --------------------------------------------------------------------------
REG_INVERTER_ONOFF = 80
REG_ZERO_EXPORT_POWER = 104
REG_MAX_CHARGE_CURRENT = 108
REG_MAX_DISCHARGE_CURRENT = 109
REG_BATT_SHUTDOWN_SOC = 115
REG_BATT_RESTART_SOC = 116
REG_BATT_LOW_SOC = 117
REG_GRID_CHARGE_START_SOC = 127
REG_GRID_CHARGE_CURRENT = 128
REG_GEN_CHARGE_ENABLE = 129
REG_GRID_CHARGE_ENABLE = 130
REG_WORK_MODE = 142
REG_MAX_SELL_POWER = 143
REG_DEFAULT_MAX_SELL = 144
REG_SOLAR_SELL = 145
REG_TOU_ENABLE = 146
REG_TOU_TIME_BLOCK = 148          # 148..153, 6 x HHMM start time
REG_TOU_POWER_BLOCK = 154         # 154..159, 6 x max battery discharge W
REG_TOU_VOLTAGE_BLOCK = 160       # 160..165, 6 x target voltage 0.01 V
REG_TOU_SOC_BLOCK = 166           # 166..171, 6 x target SOC %
REG_TOU_CHARGE_BLOCK = 172        # 172..177, 6 x charge-source bit field
REG_MAX_PV_SELL_POWER = 340

# Work mode / "limit control function" (register 142)
MODE_SELLING_FIRST = 0            # sell electricity enabled
MODE_ZERO_EXPORT_LOAD = 1         # built-in CT enabled
MODE_ZERO_EXPORT_CT = 2           # external CT enabled

# TOU enable register (146): bit0 = enable, bit1..7 = Monday..Sunday.
TOU_ALL_DAYS = 0x00FF
TOU_DISABLED = 0x0000

# TOU charge-source bit field (172..177)
TOU_CHARGE_GRID = 0x0001
TOU_CHARGE_GEN = 0x0002

CONFLICT_POLICIES = ("charge_priority", "export_priority", "net")


# --------------------------------------------------------------------------
# Data types
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Write:
    """One FC16 write: one value, or a block of consecutive registers."""

    address: int
    values: Tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.values:
            raise ValueError("write must contain at least one value")
        for value in self.values:
            if not 0 <= value <= 0xFFFF:
                raise ValueError(f"value {value} does not fit in a 16-bit register")

    @property
    def is_block(self) -> bool:
        return len(self.values) > 1

    def __str__(self) -> str:
        if self.is_block:
            return f"{self.address}..{self.address + len(self.values) - 1}={list(self.values)}"
        return f"{self.address}={self.values[0]}"


@dataclass
class Config:
    """Settings that describe the installation, not the current request."""

    # Hardware / installation limits -------------------------------------
    max_grid_charge_power_w: int = 9000
    max_export_power_w: int = 12000
    max_charge_current_a: int = 185
    max_discharge_current_a: int = 185
    max_tou_discharge_w: int = 12000

    # Default/base behaviour ---------------------------------------------
    base_mode: int = MODE_ZERO_EXPORT_CT
    selling_mode: int = MODE_SELLING_FIRST
    tou_mask: int = TOU_ALL_DAYS

    # Safety margins ------------------------------------------------------
    soc_margin: float = 1.0          # keep the discharge floor this far away
    min_charge_power_w: int = 100    # ignore tiny setpoints
    min_export_power_w: int = 100

    # What to do when both sliders are above zero --------------------------
    conflict_policy: str = "charge_priority"

    # Write register 108 (global battery charge current) so a low value does
    # not silently cap the requested grid charge power.  Off by default: the
    # safe direction is to let the installer/BMS value rule, and only drive the
    # grid-charge current (128).
    manage_max_charge_current: bool = False

    def __post_init__(self) -> None:
        if self.conflict_policy not in CONFLICT_POLICIES:
            raise ValueError(
                f"conflict_policy must be one of {CONFLICT_POLICIES}, "
                f"got {self.conflict_policy!r}"
            )
        if self.base_mode not in (MODE_SELLING_FIRST, MODE_ZERO_EXPORT_LOAD, MODE_ZERO_EXPORT_CT):
            raise ValueError(f"invalid base_mode {self.base_mode}")
        if not 0 <= self.soc_margin < 50:
            raise ValueError("soc_margin must be in [0, 50)")


@dataclass
class Inputs:
    """The current request plus the few measurements the translation needs."""

    charge_power_w: float = 0.0
    export_power_w: float = 0.0
    soc: Optional[float] = None
    battery_voltage: Optional[float] = None

    enabled: bool = True
    allow_battery_export: bool = True
    min_soc: float = 20.0
    max_soc: float = 100.0
    conflict_policy: Optional[str] = None   # overrides Config.conflict_policy


@dataclass
class Plan:
    """The result: what the inverter should be told, in the right order."""

    state: str
    reason: str
    writes: list = field(default_factory=list)
    charge_current_a: float = 0.0
    export_power_w: float = 0.0
    tou_soc: Optional[float] = None

    @property
    def is_noop(self) -> bool:
        return not self.writes

    def describe(self) -> str:
        return (
            f"{self.state} ({self.reason}); "
            f"charge={self.charge_current_a:.0f} A, export={self.export_power_w:.0f} W, "
            f"writes={len(self.writes)}"
        )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _round_watts(value: float) -> int:
    """Round to int without banker's rounding surprises."""
    return int(value + 0.5) if value >= 0 else -int(-value + 0.5)


def _soc_from_inputs(inputs: Inputs) -> Tuple[float, float]:
    soc = _clamp(float(inputs.soc), 0.0, 100.0)
    min_soc = _clamp(float(inputs.min_soc), 0.0, 99.0)
    max_soc = _clamp(float(inputs.max_soc), min_soc + 1.0, 100.0)
    return soc, min_soc, max_soc


def _resolve_conflict(cfg: Config, inputs: Inputs, p_in: float, p_out: float) -> Tuple[float, float]:
    """Grid charging and grid export cannot both own the battery."""
    if p_in <= 0 or p_out <= 0:
        return p_in, p_out

    policy = inputs.conflict_policy or cfg.conflict_policy
    if policy == "charge_priority":
        return p_in, 0.0
    if policy == "export_priority":
        return 0.0, p_out
    # net: one signed battery power setpoint
    if p_out >= p_in:
        return 0.0, p_out - p_in
    return p_in - p_out, 0.0


def _tou_blocks(tou_power_w: int, tou_soc: int, charge_bits: int) -> list:
    """Rewrite all six TOU slots identically.

    Leaving the slot start times alone and giving every slot the same policy
    collapses the schedule into one continuous rule.  It keeps the inverter's
    state machine happy without needing to know which slot is active.
    """
    return [
        Write(REG_TOU_POWER_BLOCK, tuple([tou_power_w] * 6)),
        Write(REG_TOU_SOC_BLOCK, tuple([tou_soc] * 6)),
        Write(REG_TOU_CHARGE_BLOCK, tuple([charge_bits] * 6)),
    ]


# --------------------------------------------------------------------------
# The translation
# --------------------------------------------------------------------------
def build_plan(cfg: Config, inputs: Inputs) -> Plan:
    """Translate (charge power, export power) into ordered register writes."""

    if not inputs.enabled:
        return Plan("disabled", "bridge disabled", [])

    if inputs.soc is None or inputs.battery_voltage is None:
        return Plan("blocked", "missing battery SOC or voltage", [])

    soc, min_soc, max_soc = _soc_from_inputs(inputs)
    voltage = _clamp(float(inputs.battery_voltage), 30.0, 70.0)

    p_in = max(0.0, float(inputs.charge_power_w or 0.0))
    p_out = max(0.0, float(inputs.export_power_w or 0.0))
    p_in = min(p_in, float(cfg.max_grid_charge_power_w))
    p_out = min(p_out, float(cfg.max_export_power_w))

    if p_in < cfg.min_charge_power_w:
        p_in = 0.0
    if p_out < cfg.min_export_power_w:
        p_out = 0.0

    # Charging may use the full window up to max_soc (register 127 stops the
    # inverter there anyway); discharging keeps a margin above the floor.
    if soc >= max_soc:
        p_in = 0.0
    if soc <= min_soc + cfg.soc_margin:
        p_out = 0.0

    p_in, p_out = _resolve_conflict(cfg, inputs, p_in, p_out)

    # ---------------------------------------------------------------- charge
    if p_in > 0:
        current = _clamp(p_in / voltage, 1.0, float(cfg.max_charge_current_a))
        current = _round_watts(current)

        writes = [
            # Stop the schedule first: with TOU off the global grid-charge
            # switch (130), its start SOC (127) and its current (128) rule.
            Write(REG_TOU_ENABLE, (TOU_DISABLED,)),
            Write(REG_SOLAR_SELL, (0,)),
            Write(REG_MAX_SELL_POWER, (0,)),
            Write(REG_WORK_MODE, (cfg.base_mode,)),
            Write(REG_GRID_CHARGE_START_SOC, (_round_watts(max_soc),)),
        ]
        if cfg.manage_max_charge_current:
            writes.append(Write(REG_MAX_CHARGE_CURRENT, (cfg.max_charge_current_a,)))
        writes += [
            Write(REG_MAX_DISCHARGE_CURRENT, (cfg.max_discharge_current_a,)),
            Write(REG_GRID_CHARGE_CURRENT, (current,)),
            Write(REG_GRID_CHARGE_ENABLE, (1,)),
        ]
        return Plan(
            state="charging",
            reason=f"grid charge {p_in:.0f} W at {voltage:.1f} V",
            writes=writes,
            charge_current_a=float(current),
            export_power_w=0.0,
            tou_soc=None,
        )

    # ---------------------------------------------------------------- export
    if p_out > 0:
        hold_battery = not inputs.allow_battery_export
        tou_soc = _round_watts(min_soc)
        mode = cfg.selling_mode
        discharge_current = 0 if hold_battery else cfg.max_discharge_current_a
        tou_power = 0 if hold_battery else cfg.max_tou_discharge_w

        writes = [Write(REG_GRID_CHARGE_ENABLE, (0,))]
        writes += _tou_blocks(tou_power, tou_soc, 0)
        writes += [
            # 109 = 0 is the "hold the battery" switch (evcc uses the same trick);
            # it is robust where a moving SOC floor is not.
            Write(REG_MAX_DISCHARGE_CURRENT, (discharge_current,)),
            Write(REG_TOU_ENABLE, (cfg.tou_mask,)),
            Write(REG_WORK_MODE, (mode,)),
            Write(REG_SOLAR_SELL, (1,)),
            Write(REG_MAX_SELL_POWER, (_round_watts(p_out),)),
        ]
        reason = f"export cap {p_out:.0f} W"
        reason += ", battery held" if hold_battery else f", battery floor {tou_soc}%"
        return Plan(
            state="exporting",
            reason=reason,
            writes=writes,
            charge_current_a=0.0,
            export_power_w=float(p_out),
            tou_soc=float(tou_soc),
        )

    # ------------------------------------------------------- self-consumption
    tou_soc = _round_watts(min_soc)
    writes = [Write(REG_GRID_CHARGE_ENABLE, (0,))]
    writes += _tou_blocks(cfg.max_tou_discharge_w, tou_soc, 0)
    writes += [
        Write(REG_MAX_DISCHARGE_CURRENT, (cfg.max_discharge_current_a,)),
        Write(REG_TOU_ENABLE, (cfg.tou_mask,)),
        Write(REG_WORK_MODE, (cfg.base_mode,)),
        Write(REG_SOLAR_SELL, (0,)),
        Write(REG_MAX_SELL_POWER, (0,)),
    ]
    return Plan(
        state="self_consumption",
        reason=f"no setpoint, battery floor {tou_soc}%",
        writes=writes,
        charge_current_a=0.0,
        export_power_w=0.0,
        tou_soc=float(tou_soc),
    )


# --------------------------------------------------------------------------
# Convenience
# --------------------------------------------------------------------------
def registers_touched(cfg: Config) -> Sequence[int]:
    """Registers this module may write (used for snapshot/restore)."""
    regs = [
        REG_MAX_CHARGE_CURRENT,
        REG_MAX_DISCHARGE_CURRENT,
        REG_GRID_CHARGE_START_SOC,
        REG_GRID_CHARGE_CURRENT,
        REG_GRID_CHARGE_ENABLE,
        REG_WORK_MODE,
        REG_MAX_SELL_POWER,
        REG_SOLAR_SELL,
        REG_TOU_ENABLE,
        REG_TOU_POWER_BLOCK,
        REG_TOU_SOC_BLOCK,
        REG_TOU_CHARGE_BLOCK,
    ]
    return tuple(regs)


def restore_writes(snapshot: dict) -> list:
    """Build writes that put back a previous snapshot.

    ``snapshot`` maps register -> value for single registers and
    register -> list/tuple for blocks.  Unknown/incomplete snapshots are
    silently skipped: a partial restore is safer than writing a guess.
    """
    writes = []
    for address, value in sorted(snapshot.items()):
        if isinstance(value, (list, tuple)):
            values = tuple(int(v) for v in value)
        else:
            values = (int(value),)
        writes.append(Write(address, values))
    return writes

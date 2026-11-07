"""Deye power bridge — pyscript controller for the SUN-12K-SG05LP3-EU-SM2.

Copy this file to /config/pyscript/ and copy ``deye_bridge/core.py`` to
/config/pyscript/modules/deye_bridge_core.py (see README.md).

It exposes two sliders (created in helpers.yaml) as a small state machine that
writes the inverter's rule-engine registers.  All translation logic lives in
``deye_bridge_core``; this file only does I/O, snapshot/restore and supervision.
"""

import json
import time

from deye_bridge_core import (
    Config,
    Inputs,
    REG_GRID_CHARGE_CURRENT,
    REG_GRID_CHARGE_ENABLE,
    REG_MAX_DISCHARGE_CURRENT,
    REG_MAX_SELL_POWER,
    REG_SOLAR_SELL,
    REG_TOU_ENABLE,
    REG_WORK_MODE,
    build_plan,
)

# ==========================================================================
# Configuration — edit these
# ==========================================================================
CONFIG = {
    # "solarman"   -> home_assistant_solarman services over the stock dongle
    # "modbus"     -> Home Assistant built-in modbus integration (RS485 gateway)
    # "deye_modbus"-> Developer089/deye-modbus-ha integration
    "writer": "solarman",
    # The Solarman service field is called "device" and takes the HA device id
    # shown in Settings > Devices & Services > Solarman (also in the URL when
    # you open the device).
    "device_id": "",
    "modbus_hub": "deye",         # modbus hub name, for writer == "modbus"
    "modbus_unit": 1,

    "soc_entity": "sensor.deye_battery_soc",
    "voltage_entity": "sensor.deye_battery_voltage",

    "input_power_entity": "input_number.deye_input_power",
    "export_power_entity": "input_number.deye_export_power",
    "min_soc_entity": "input_number.deye_min_soc",
    "max_soc_entity": "input_number.deye_max_soc",
    "allow_battery_export_entity": "input_boolean.deye_allow_battery_export",
    "conflict_entity": "input_select.deye_conflict_policy",
    "enabled_entity": "input_boolean.deye_bridge_enabled",
    "status_entity": "input_text.deye_bridge_status",
    "snapshot_entity": "input_text.deye_bridge_snapshot",

    # Installation limits
    "max_grid_charge_power_w": 9000,
    "max_export_power_w": 12000,
    "max_charge_current_a": 185,
    "max_discharge_current_a": 185,
    "manage_max_charge_current": False,
    "max_tou_discharge_w": 12000,
    "base_mode": 2,               # 2 = zero export to CT (external CT)
    "selling_mode": 0,            # 0 = Selling First
    "tou_mask": 0x00FF,

    "cycle_seconds": 30,
    "verify_every_cycles": 10,
    "write_min_interval_s": 5,
    "current_deadband_a": 2,
    "export_deadband_w": 100,
}

# ==========================================================================
# Internal state
# ==========================================================================
_applied = {}          # register -> tuple(values) last written successfully
_last_write = {}       # register -> monotonic timestamp
_snapshot = None       # dict register -> tuple(values)
_cycle = 0
_last_state = None

SNAPSHOT_SINGLE = [108, 109, 127, 128, 130, 142, 143, 145, 146]
SNAPSHOT_BLOCKS = [(154, 6), (166, 6), (172, 6)]


# ==========================================================================
# Helpers
# ==========================================================================
def _num(entity_id, default=0.0):
    raw = state.get(entity_id)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def _num_optional(entity_id):
    raw = state.get(entity_id)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _bool(entity_id, default=False):
    raw = state.get(entity_id)
    if raw is None:
        return default
    return str(raw).lower() in ("on", "true", "1", "yes")


_last_status = None


def _status(text):
    global _last_status
    text = str(text)[:250]
    if text == _last_status:
        return
    _last_status = text
    try:
        input_text.set_value(entity_id=CONFIG["status_entity"], value=text)
    except Exception:
        pass


def _cfg():
    return Config(
        max_grid_charge_power_w=int(CONFIG["max_grid_charge_power_w"]),
        max_export_power_w=int(CONFIG["max_export_power_w"]),
        max_charge_current_a=int(CONFIG["max_charge_current_a"]),
        max_discharge_current_a=int(CONFIG["max_discharge_current_a"]),
        max_tou_discharge_w=int(CONFIG["max_tou_discharge_w"]),
        manage_max_charge_current=bool(CONFIG["manage_max_charge_current"]),
        base_mode=int(CONFIG["base_mode"]),
        selling_mode=int(CONFIG["selling_mode"]),
        tou_mask=int(CONFIG["tou_mask"]),
        conflict_policy=state.get(CONFIG["conflict_entity"]) or "charge_priority",
    )


def _inputs():
    return Inputs(
        charge_power_w=_num(CONFIG["input_power_entity"]),
        export_power_w=_num(CONFIG["export_power_entity"]),
        soc=_num_optional(CONFIG["soc_entity"]),
        battery_voltage=_num_optional(CONFIG["voltage_entity"]),
        enabled=_bool(CONFIG["enabled_entity"]),
        allow_battery_export=_bool(CONFIG["allow_battery_export_entity"], True),
        min_soc=_num(CONFIG["min_soc_entity"], 20),
        max_soc=_num(CONFIG["max_soc_entity"], 100),
    )


# ==========================================================================
# Transport
# ==========================================================================
def _write_register(address, values):
    values = [int(v) for v in values]
    writer = CONFIG["writer"]
    if writer == "solarman":
        service.call(
            "solarman", "write_multiple_holding_registers",
            device=CONFIG["device_id"], register=int(address),
            values=values, blocking=True,
        )
    elif writer == "modbus":
        service.call(
            "modbus", "write_registers",
            hub=CONFIG["modbus_hub"], unit=CONFIG["modbus_unit"],
            address=int(address), values=values, blocking=True,
        )
    elif writer == "deye_modbus":
        service.call(
            "deye_modbus", "write_registers",
            address=int(address), values=values, blocking=True,
        )
    else:
        raise ValueError(f"unknown writer {writer!r}")


def _read_block(start, count):
    resp = service.call(
        "solarman", "read_multiple_holding_registers",
        device=CONFIG["device_id"], register=int(start), count=int(count),
        return_response=True, blocking=True,
    )
    if isinstance(resp, dict) and "service_response" in resp:
        resp = resp["service_response"]
    return {int(k): int(v) for k, v in resp.items()}


# ==========================================================================
# Applying a plan
# ==========================================================================
def _deadband(address):
    if address == REG_GRID_CHARGE_CURRENT:
        return CONFIG["current_deadband_a"]
    if address == REG_MAX_SELL_POWER:
        return CONFIG["export_deadband_w"]
    return 0


def _apply_plan(plan):
    global _last_state
    writes = 0
    for write in plan.writes:
        address = write.address
        values = tuple(int(v) for v in write.values)
        previous = _applied.get(address)

        if previous == values:
            continue
        if previous is not None and len(previous) == len(values):
            band = _deadband(address)
            if band and all(abs(a - b) <= band for a, b in zip(previous, values)):
                continue

        # Only touch the global discharge current when holding the battery
        # (109 = 0) or when undoing a hold — never just to re-assert a limit.
        if address == REG_MAX_DISCHARGE_CURRENT and values != (0,):
            if _applied.get(address) != (0,):
                continue

        now = time.monotonic()
        if address in _last_write and now - _last_write[address] < CONFIG["write_min_interval_s"]:
            continue

        try:
            _write_register(address, values)
        except Exception as exc:
            log.error(f"deye_bridge: write {address}={list(values)} failed: {exc}")
            _applied.pop(address, None)
            _status(f"write failed @{address}: {exc}")
            continue

        _applied[address] = values
        _last_write[address] = now
        writes += 1

    if writes:
        log.info(f"deye_bridge: {plan.state} -> {writes} write(s); {plan.describe()}")
    _last_state = plan.state
    return writes


def _verify():
    """Read back the four critical registers and re-apply on drift."""
    if CONFIG["writer"] != "solarman":
        return
    try:
        regs = _read_block(127, 20)          # 127..146
    except Exception as exc:
        log.warning(f"deye_bridge: verify read failed: {exc}")
        return

    for address in (REG_GRID_CHARGE_CURRENT, REG_GRID_CHARGE_ENABLE,
                    REG_MAX_SELL_POWER, REG_SOLAR_SELL, REG_WORK_MODE, REG_TOU_ENABLE):
        applied = _applied.get(address)
        if applied is None:
            continue
        actual = (regs.get(address),)
        if actual != applied:
            log.warning(
                f"deye_bridge: drift at {address}: applied {applied} actual {actual}; re-applying"
            )
            _applied.pop(address, None)


# ==========================================================================
# Snapshot / restore
# ==========================================================================
def _snapshot_now():
    global _snapshot
    if CONFIG["writer"] != "solarman":
        log.warning("deye_bridge: snapshot needs the Solarman reader; skipped")
        return None
    snapshot = {}
    try:
        low = _read_block(108, 23)            # 108..130
        high = _read_block(142, 36)           # 142..177
    except Exception as exc:
        log.error(f"deye_bridge: snapshot read failed: {exc}")
        return None

    both = {**low, **high}
    for address in SNAPSHOT_SINGLE:
        if address in both:
            snapshot[address] = (both[address],)
    for start, count in SNAPSHOT_BLOCKS:
        values = tuple(both.get(start + i, 0) for i in range(count))
        snapshot[start] = values

    _snapshot = snapshot
    _save_snapshot(snapshot)
    log.info(f"deye_bridge: snapshot taken ({len(snapshot)} registers)")
    return snapshot


def _save_snapshot(snapshot):
    flat = []
    for address in SNAPSHOT_SINGLE:
        flat.extend(snapshot.get(address, (0,)))
    for start, count in SNAPSHOT_BLOCKS:
        flat.extend(snapshot.get(start, tuple([0] * count)))
    try:
        input_text.set_value(entity_id=CONFIG["snapshot_entity"], value=json.dumps(flat))
    except Exception as exc:
        log.warning(f"deye_bridge: could not persist snapshot: {exc}")


def _load_snapshot():
    global _snapshot
    raw = state.get(CONFIG["snapshot_entity"])
    if not raw:
        return None
    try:
        flat = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(flat, list) or len(flat) != len(SNAPSHOT_SINGLE) + sum(c for _, c in SNAPSHOT_BLOCKS):
        return None

    snapshot = {}
    index = 0
    for address in SNAPSHOT_SINGLE:
        snapshot[address] = (int(flat[index]),)
        index += 1
    for start, count in SNAPSHOT_BLOCKS:
        snapshot[start] = tuple(int(v) for v in flat[index:index + count])
        index += count
    _snapshot = snapshot
    return snapshot


def _restore():
    global _applied
    snapshot = _snapshot or _load_snapshot()
    if not snapshot:
        log.warning("deye_bridge: no snapshot to restore")
        return 0

    count = 0
    for address, values in snapshot.items():
        try:
            _write_register(address, values)
            count += 1
        except Exception as exc:
            log.error(f"deye_bridge: restore {address} failed: {exc}")
    _applied = {}
    log.info(f"deye_bridge: restored {count} register block(s)")
    _status("restored original settings")
    return count


# ==========================================================================
# Main loop
# ==========================================================================
@service("deye_bridge.apply")
def deye_apply(force=False):
    global _cycle
    if not _bool(CONFIG["enabled_entity"]):
        return {"state": "disabled"}

    if CONFIG["writer"] == "solarman" and not CONFIG["device_id"]:
        _status("error: device_id is empty")
        return {"state": "error", "reason": "device_id is empty"}

    plan = build_plan(_cfg(), _inputs())
    _apply_plan(plan)

    _cycle += 1
    if _cycle % int(CONFIG["verify_every_cycles"]) == 0:
        _verify()

    _status(plan.describe())
    return {
        "state": plan.state,
        "reason": plan.reason,
        "charge_current_a": plan.charge_current_a,
        "export_power_w": plan.export_power_w,
    }


@service("deye_bridge.enable")
def deye_enable():
    if not _snapshot:
        _load_snapshot()
    if not _snapshot:
        _snapshot_now()
    input_boolean.turn_on(entity_id=CONFIG["enabled_entity"])
    log.info("deye_bridge: enabled")
    return deye_apply(force=True)


@service("deye_bridge.disable")
def deye_disable():
    input_boolean.turn_off(entity_id=CONFIG["enabled_entity"])
    _restore()
    log.info("deye_bridge: disabled and restored")
    return {"state": "disabled"}


@service("deye_bridge.snapshot")
def deye_snapshot():
    snapshot = _snapshot_now()
    return {"registers": len(snapshot) if snapshot else 0}


@service("deye_bridge.restore")
def deye_restore():
    return {"restored": _restore()}


@service("deye_bridge.status")
def deye_status():
    return {
        "state": _last_state,
        "enabled": _bool(CONFIG["enabled_entity"]),
        "applied": {str(k): list(v) for k, v in _applied.items()},
        "snapshot": bool(_snapshot),
    }


# ==========================================================================
# Triggers
# ==========================================================================
@time_trigger("startup")
def deye_startup():
    if _bool(CONFIG["enabled_entity"]):
        if not _snapshot:
            _load_snapshot()
        if not _snapshot:
            _snapshot_now()
        deye_apply(force=True)


@time_trigger("shutdown")
def deye_shutdown():
    """Best-effort restore on a clean HA shutdown."""
    if _bool(CONFIG["enabled_entity"]):
        _restore()


@time_trigger(f"period(now, {CONFIG['cycle_seconds']}s)")
def deye_tick():
    if _bool(CONFIG["enabled_entity"]):
        deye_apply()


@state_trigger(
    "input_number.deye_input_power or input_number.deye_export_power "
    "or input_boolean.deye_bridge_enabled or input_boolean.deye_allow_battery_export "
    "or input_number.deye_min_soc or input_number.deye_max_soc "
    "or input_select.deye_conflict_policy",
    state_hold=2,
)
def deye_on_change(**kwargs):
    deye_apply()

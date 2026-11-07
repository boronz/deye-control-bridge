# The translation: two sliders → the inverter's rule engine

This is the specification that [`core.py`](../custom_components/deye_bridge/core.py)
implements and that `tests/test_core.py` checks.

---

## 1. The interface

Two writable numbers, both in watts, plus a small set of safety settings:

| Entity (device "Deye inverter") | Range | Meaning |
|---|---|---|
| `number.deye_inverter_grid_charge_power` | 0 … 12000 W | Power to **import from the grid to charge the battery** (0 = no grid charging) |
| `number.deye_inverter_export_power` | 0 … 12000 W | Ceiling for **power leaving to the grid** (0 = no export) |
| `number.deye_inverter_discharge_floor_soc` | 0 … 90 % | Discharge floor (safety) |
| `number.deye_inverter_charge_ceiling_soc` | 10 … 100 % | Charge ceiling (safety) |
| `switch.deye_inverter_allow_battery_export` | — | If off, only PV surplus may be exported; the battery holds |
| `select.deye_inverter_operating_mode` | — | `manual` (sliders) or `self_consumption` (absorb AC-coupled export) |
| `select.deye_inverter_both_sliders_policy` | — | What to do when both sliders are > 0 |
| `switch.deye_inverter_control_enabled` | — | Master interlock, off by default; off = read-only, on = control (and snapshot) |

The HEMS writes the two numbers (`number.set_value`) every price interval, or as
often as it likes. Nothing else is required from it.

### What "export to house" means here

The CT is on the grid incomer, so the physical order is always
**house loads → battery → grid**. The export slider is therefore a *grid* ceiling,
not a "battery discharge" command:

| Export slider | Behaviour |
|---|---|
| `0 W` | Zero export. PV and battery serve the house; surplus PV charges the battery; nothing leaves |
| `> 0 W` | House is served first, then the surplus leaves to the grid up to the ceiling |

That is exactly the "grid **or** house" behaviour: the same slider covers both,
because the inverter always prefers the house.

---

## 2. The states

A fourth state, `absorbing`, is the CHARGING state driven by the self-consumption
loop described in 2.4.

```
                    charge > 0
   ┌──────────────────────────────────────────►┌───────────┐
   │                                           │  CHARGING │
┌──┴──────────────────┐                        └─────┬─────┘
│  SELF-CONSUMPTION   │◄──── both 0 / blocked ──────┤
│  (TOU on, floor)    │◄────────────────────────────┤
└──┬──────────────────┘                        ┌─────▼─────┐
   │                    export > 0             │ EXPORTING │
   └──────────────────────────────────────────►└───────────┘
```

Charging and exporting are structurally incompatible: charging needs the TOU engine
**off** (so registers 130/127/128 rule), while exporting needs it **on** (so the
battery may discharge and be sold). The state machine therefore picks exactly one.

### 2.1 CHARGING — grid → battery

**When:** `input_power > 0`, SOC below `max_soc`, bridge enabled.

**Formula:** the inverter only knows current, not power:

```
I_grid_charge = round( P_in / V_battery )
```

with `V_battery` = register 587 (0.01 V), clamped to `[1, 185] A` and to
`max_grid_charge_power_w`. At 52 V, 5 kW ≈ 96 A.

**Writes, in this order:**

| # | Register | Value | Why this order |
|---|---|---|---|
| 1 | 146 | `0x0000` | Stop the schedule first, so no slot can interfere |
| 2 | 145 | `0` | Stop any export before importing |
| 3 | 143 | `0` | …including the export cap |
| 4 | 142 | `base_mode` | Back to zero-export/self-consumption |
| 5 | 127 | `max_soc` | Charge while SOC < max_soc (i.e. up to max_soc) |
| 6 | 108 | `max_charge_current_a` | *Optional* (`manage_max_charge_current`): remove a low global cap |
| 7 | 109 | `max_discharge_current_a` | Undo a previous "hold" (see 2.2) |
| 8 | 128 | `I_grid_charge` | The actual power setpoint |
| 9 | 130 | `1` | Enable grid charging **last** |

### 2.2 EXPORTING — battery/PV → grid, house first

**When:** `export_power > 0`, SOC above the floor, bridge enabled.

**Writes:**

| # | Register | Value | Why |
|---|---|---|---|
| 1 | 130 | `0` | No grid charging while exporting |
| 2 | 166–171 | `floor` × 6 | Discharge floor for every slot |
| 3 | 154–159 | `max_discharge` × 6 | Don't let the slot power cap bind |
| 4 | 172–177 | `0` | No grid/generator charging in any slot |
| 5 | 109 | `max_discharge_current_a`, or `0` | `0` holds the battery (PV-only export) |
| 6 | 146 | `0x00FF` | Enable the (now flat) schedule |
| 7 | 142 | `0` (Selling First) | Battery may be sold, and register 143 is authoritative |
| 8 | 145 | `1` | Allow export |
| 9 | 143 | `round(P_out)` | The export ceiling |

Slots are written **before** TOU is enabled, so the first active slot already has the
right floor; otherwise the inverter would briefly use the old schedule.

With `allow_battery_export = false`, register **109** (max discharge current) is set
to `0` and the slot power to `0` while exporting. That is the same "hold the battery"
trick evcc uses, and it is robust: a SOC floor that follows the current SOC would
keep moving down with the battery and never stop the discharge. Only PV surplus is
exported in that mode, capped by 143.

### 2.3 SELF-CONSUMPTION — no setpoints

**When:** both sliders are 0 (or the bridge is blocked by a SOC limit).

| # | Register | Value |
|---|---|---|
| 1 | 130 | `0` |
| 2 | 166–171 | `floor` × 6 |
| 3 | 154–159 | `max_discharge` × 6 |
| 4 | 172–177 | `0` |
| 5 | 109 | `max_discharge_current_a` | Undo a previous "hold" |
| 6 | 146 | `0x00FF` |
| 7 | 142 | `base_mode` |
| 8 | 145 | `0` |
| 9 | 143 | `0` |

The battery discharges to the floor for self-consumption, nothing is exported.

### 2.4 SELF-CONSUMPTION — absorb AC-coupled export

Selected by `operating_mode = self_consumption`; the two power sliders are ignored.

An AC-coupled PV inverter on the house side appears at the CT as export that the
Deye cannot curtail. The integration turns that into battery charging:

```
export_w = max(0, -grid_power)          # register 625, positive = import
```

`ExcessController` adds hysteresis so the plan does not flap:

| Condition | Result |
|---|---|
| export ≥ 150 W for 10 s | absorbing = true |
| export < 50 W for 30 s | absorbing = false |
| export between 50 and 150 W | keep the previous state |
| import > 100 W | absorbing = false immediately (no exit hold) |
| SOC ≥ charge ceiling | absorbing = false, target 0 |

While absorbing, the plan is the **CHARGING** plan of 2.1 with

```
P_in = export_w * 0.95
I    = P_in / battery_voltage
```

and `charge_hold = true`. The hold keeps TOU off and grid charging enabled even when
`P_in` momentarily drops to 0, so the plan does not flip between "charging" (TOU off)
and "self-consumption" (TOU on) on every cloud. While not absorbing, the plan is the
normal self-consumption plan of 2.3.

Consequences and tuning:

* While the loop is active — or export is present — the coordinator polls at
  `absorb_interval` (default 10 s); otherwise it uses the normal `scan_interval`
  (default 30 s). Both are options, so the fast reaction is not paid for all day.
* All five thresholds (`enter_export_w`, `exit_export_w`, `enter_hold_s`,
  `exit_hold_s`, `absorb_ratio`) are exposed in the options flow.
* The 5 % bias keeps a small export rather than importing to charge.
* Import cancels absorption at once. The discharge side is not driven by this
  controller: the self-consumption plan leaves the inverter's own zero-export CT
  loop in charge, which discharges the battery to keep the CT at zero down to the
  floor. The integration only has to hand over quickly, which the `import_exit_w`
  rule does.
* With the battery full there is nowhere for the surplus to go; it exports.

---

## 3. Flattening the schedule

The six TOU slots are always written with **identical** values; their start times
(148–153) are left untouched. Whatever slot is active, the behaviour is the same, so
the translation never needs to know the current time. This is the piece that removes
the time-slot complexity without removing the TOU engine's useful functions
(discharge floor, battery discharge, battery export).

---

## 4. Safety rules

| Rule | Effect |
|---|---|
| `P_in ≤ max_grid_charge_power_w` | Installation limit (default 9 kW) |
| `P_out ≤ max_export_power_w` | Installation/grid limit (default 12 kW) |
| Setpoints below 100 W are ignored | Avoids chattering around zero |
| `SOC ≥ max_soc − 1 %` → no charging | Prevents overcharge and micro-cycles |
| `SOC ≤ min_soc + 1 %` → no export | Protects the battery |
| Bridge disabled or data missing → **no writes** | The inverter keeps its last state; the supervisor restores the snapshot |
| Snapshot on enable, restore on disable | The bridge never leaves permanent changes behind |
| Write only changed values | Protects the inverter's settings memory |
| Read back 143 / 128 / 130 / 146 after a change | Detects rejected writes |

### Failure modes

* **HA goes down while charging.** The inverter keeps charging to `max_soc` and
  stops there; the BMS is the second line of defence. Nothing dangerous, but the
  schedule is not restored until HA is back.
* **HA goes down while exporting.** The export cap and the TOU floor stay in place,
  so the battery drains to the floor and stops. Again bounded.
* **A write is rejected.** The read-back check logs it and retries on the next cycle;
  the state machine does not assume success.

---

## 5. Conflict policy

When both sliders are above zero the layer must choose. Three options:

| Policy | Behaviour |
|---|---|
| `charge_priority` (default) | Charge wins, export is dropped. Charging is usually the time-critical, price-driven action |
| `export_priority` | Export wins, charging is dropped |
| `net` | One signed setpoint: `net = export − charge`; positive = export, negative = charge |

`net` is the most "physical" choice: the battery is either charging or discharging,
so the two numbers collapse into one. `charge_priority` is the safest choice for a
HEMS that occasionally sets both by mistake.

---

## 6. Commissioning procedure

Do this once, before letting a HEMS drive it. Keep the app/display handy.

1. **Read-only sanity check.** Compare register 588 (SOC), 587 (battery voltage) and
   590 (battery power) with the inverter display / Solarman app.
2. **Snapshot.** Read and save 108, 109, 127, 128, 130, 142, 143, 145, 146, 154–177.
   (Enabling the bridge does this automatically; `deye_bridge.snapshot` re-takes it.)
3. **Charge test.** Set `number.deye_inverter_grid_charge_power` to 1000 W, watch
   128 (≈ 20 A at 50 V), 130 = 1, and the grid power sensor. Confirm the battery
   charges and the house is still supplied.
4. **Charge stop.** Set it back to 0. Confirm 130 = 0 and 146 = 0x00FF.
5. **Export test.** Set `number.deye_inverter_export_power` to 1000 W, watch
   143 = 1000, 145 = 1, 142 = 0. Confirm ~1 kW leaves at the meter (or less, if the
   house is consuming).
6. **Export stop.** Set it back to 0. Confirm 145 = 0 and the meter settles at ~0.
7. **Restore.** Turn off `switch.deye_inverter_control_enabled` and confirm the
   snapshot values are back.

If step 5 does not export battery power, check in this order:
`142 = 0`, `145 = 1`, `146 = 0x00FF`, slot SOC below current SOC, slot power > 0,
and finally the "sell bit" caveat in
[01-solarman-and-deye-control.md](01-solarman-and-deye-control.md#5-firmware-differences-you-must-verify-on-your-unit).

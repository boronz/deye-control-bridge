# Deye Power Bridge

A Home Assistant custom integration (HACS) that gives a **Deye three-phase low-voltage
hybrid inverter** — SUN-5…12K-SG04LP3 / SG05LP3, including the
**SUN-12K-SG05LP3-EU-SM2** — the two controls a HEMS actually wants:

* **Grid charge power** — how much to import from the grid to charge the battery, in watts.
* **Export power** — how much may leave to the grid, in watts (`0` = zero export, the
  house is still served first).
* **Battery devices** — one HA device per battery input, with the full BMS data the
  inverter forwards.

Internally it drives the inverter's real rule engine (work mode, solar sell, max sell
power, grid-charge switch/current/SOC, and a *flattened* time-of-use schedule) with a
state machine that only writes what changed.

> **Status:** the translation logic is unit-tested (44 tests) and the integration code
> imports cleanly against Home Assistant stubs, but it has **not** been run against a
> live inverter yet. Do the commissioning steps in
> [docs/03-translation.md](docs/03-translation.md#6-commissioning-procedure) before
> letting a HEMS drive it.

---

## Why this exists

The stock Solarman integration gives you sensors and raw register access. It does not
give you a power setpoint, because the inverter has none: it has a six-slot
time-of-use schedule, a work mode, an export ceiling and a grid-charge current. That
model is awkward to drive from a price/forecast optimiser, which thinks in
"charge now / export now".

This integration is the missing translation. The research behind it — how Solarman
works, why the time slots are both necessary and awkward, and which registers do what —
is in [docs/01-solarman-and-deye-control.md](docs/01-solarman-and-deye-control.md).

```
   HEMS / automations                 this integration                  inverter
 ┌────────────────────┐        ┌──────────────────────────┐        ┌──────────────┐
 │ number.set_value   │───────►│ state machine            │───────►│ 146 TOU on/off│
 │ grid charge (W)    │        │ - SOC guards             │  FC16  │ 130 grid chg │
 │ export (W)         │        │ - conflict policy        │        │ 128 current  │
 │ SOC limits         │        │ - snapshot / restore     │        │ 127 start SOC│
 └────────────────────┘        │ - write only on change   │        │ 143 max sell │
                               └──────────────────────────┘        │ 142 mode     │
                                                                   │ 154..177 TOU │
                                                                   └──────────────┘
```

---

## Installation

### HACS (custom repository)

1. HACS → **⋮ → Custom repositories** → add this repository URL, category **Integration**.
2. Install **Deye Power Bridge**, then restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → Deye Power Bridge**.

### Manual

Copy `custom_components/deye_bridge` into `/config/custom_components/` and restart.

---

## CT clamps and the Energy dashboard

The inverter exposes three layers of grid data, all available as sensors:

| Layer | Registers | Sensors |
|---|---|---|
| Selected CT (what the inverter regulates on) | 622–625 | `grid_power_l1/l2/l3` + `grid_power` |
| External clamps (SM2 CT terminals) | 613–619 | `external_ct_power_l1/l2/l3`, `external_ct_power_total`, `external_ct_current_l1/l2/l3` |
| Grid voltages and frequency | 598–600, 609 | `grid_voltage_l1/l2/l3`, `grid_frequency` |

Sign convention: **positive = import, negative = export**, matching the inverter's
display. The per-phase values are signed the same way.

For the HA **Energy dashboard**, the grid counters are already there:
`sensor.deye_inverter_grid_import_total` and `sensor.deye_inverter_grid_export_total`
(plus the `_today` variants). If you want to replace a P1 meter with the CT clamps, those
two totals are the ones to configure — the live `grid_power`/`grid_power_l1..l3` sensors
are the same measurement in watts and can drive your own template/Riemann sensors.

> Phase mapping is physical: L1/L2/L3 follow the CT terminals. If a clamp is reversed,
> that phase will show the opposite sign — fix it at the clamp rather than in software.

## Battery devices

The inverter exposes a detail block for each battery input. The integration reads the
battery count (register 24), the first block at 210–230 and the second at 241–258, and
creates one HA device per battery:

| Device | Entities | Created when |
|---|---|---|
| `Deye battery 1` | `sensor.deye_battery_1_*` | always |
| `Deye battery 2` | `sensor.deye_battery_2_*` | register 24 reports two inputs |

Each battery gets SOC, voltage, current, power, temperature, state of health, rated
capacity, charge/discharge voltage, charge/discharge current limit, max charge/discharge
current, alarm flags, fault flags, battery type, brand, software version and hardware
version. The devices are linked to the inverter with `via_device`.

If the firmware does not expose the detail block, the integration keeps working and the
battery devices simply show as unavailable — the inverter-level `sensor.deye_inverter_*`
battery sensors still work. Reload the config entry after adding a second battery so
its entities are created.

## Safety: control is off by default

A fresh install is **read-only**. `switch.deye_inverter_control_enabled` starts off,
and while it is off the integration never writes to the inverter on its own — it only
polls measurements. Turning it on snapshots the current control registers first; turning it
off writes that snapshot back. Nothing on the inverter changes until you flip it.

## ⚠️ One Modbus master at a time

The inverter / Solarman dongle accepts a **single** Modbus connection. This integration
keeps a persistent connection, so **remove or disable any other integration polling the
same dongle** — the `home_assistant_solarman` entry for this inverter, Node-RED flows,
`deye-modbus-ha`, SolarAssistant, etc. Otherwise both will see timeouts.

This integration therefore also provides the measurements and energy counters you need
for dashboards and the Energy dashboard (see [Entities](#entities)). If you want to keep
the Solarman integration for monitoring, put it on a **separate** RS485 port/gateway.

---

## Setup

### Transport

| Transport | When | Port |
|---|---|---|
| **Solarman V5** | The stock Wi-Fi/LAN dongle. Needs the logger **serial number** (printed on the dongle, also in the SolarMAN app) | 8899 |
| **Plain Modbus TCP** | An RS485↔Ethernet gateway (Elfin, USR, Waveshare, …) | 502 |

Not sure which one your dongle speaks? Run the probe from this repository:

```bash
python tools/probe_transport.py 192.168.1.50
```

It sends a bare Modbus TCP request and reports whether the dongle answers it. A stock
Solarman stick will *not* answer plain Modbus TCP; it speaks Solarman V5, which is what
the `solarman_v5` transport uses.

### Options

After setup, **Configure** the entry:

| Option | Meaning |
|---|---|
| Maximum grid charge power | Installation limit, W (default 9000) |
| Maximum export power | Grid connection / contract limit, W (default 12000) |
| Battery max charge / discharge current | A, written by the bridge where needed (default 185) |
| Base work mode | `2` Zero Export to CT (external CT), `1` built-in CT, `0` Selling First |
| Let the bridge manage register 108 | Off by default: the installer/BMS value rules |
| Charge current / export deadband | Suppress tiny rewrites (±2 A, ±100 W) |
| Verify every N cycles | Read-back check interval (default 10) |
| Poll interval | Seconds (10–300, default 30) |
| Fast poll interval while absorbing | Seconds (0–60, default 10; `0` = use the normal interval) |
| Absorption ratio | Fraction of the export to charge (0.5–1.0, default 0.95) |
| Start absorbing above export | W (default 150) |
| Stop absorbing below export | W (default 50) |
| Export must persist before starting | Seconds (default 10) |
| No export must persist before stopping | Seconds (default 30) |

---

## Entities

Entity ids below assume the device is called **Deye inverter**; they follow the device
name if you rename it.

| Entity | Type | What it does |
|---|---|---|
| `number.deye_inverter_grid_charge_power` | number (W) | **Input power** — grid → battery |
| `number.deye_inverter_export_power` | number (W) | **Export power** — grid export ceiling |
| `number.deye_inverter_discharge_floor_soc` | number (%) | Discharge floor (default 20) |
| `number.deye_inverter_charge_ceiling_soc` | number (%) | Charge ceiling (default 100) |
| `switch.deye_inverter_control_enabled` | switch | **Master interlock, off by default**; off = read-only, on = control (and snapshot) |
| `switch.deye_inverter_allow_battery_export` | switch | Off = only PV surplus may be exported |
| `select.deye_inverter_operating_mode` | select | `manual` (sliders) / `self_consumption` (absorb AC-coupled export) |
| `select.deye_inverter_both_sliders_policy` | select | `charge_priority` / `export_priority` / `net` |
| `sensor.deye_inverter_bridge_state` | sensor | `absorbing` / `charging` / `exporting` / `self_consumption` / `blocked` / `disabled` |
| `sensor.deye_inverter_battery_soc` | sensor | Battery SOC |
| `sensor.deye_inverter_battery_voltage` | sensor | Battery voltage (used for W → A) |
| `sensor.deye_inverter_battery_power` | sensor | Battery power (W) |
| `sensor.deye_inverter_grid_power` | sensor | Grid power, positive = import, negative = export |
| `sensor.deye_inverter_grid_power_l1/l2/l3` | sensor | Per-phase grid power from the selected CT |
| `sensor.deye_inverter_grid_voltage_l1/l2/l3` | sensor | Per-phase grid voltage |
| `sensor.deye_inverter_external_ct_power_l1/l2/l3` | sensor | External CT clamp power per phase |
| `sensor.deye_inverter_external_ct_power_total` | sensor | External CT clamp total |
| `sensor.deye_inverter_external_ct_current_l1/l2/l3` | sensor | External CT clamp current per phase |
| `sensor.deye_inverter_grid_frequency` | sensor | Grid frequency |
| `sensor.deye_inverter_pv_power` | sensor | PV power |
| `sensor.deye_inverter_load_power` | sensor | Load power |
| `sensor.deye_inverter_applied_charge_power` | sensor | The charge power the plan asked for |
| `sensor.deye_inverter_applied_export_power` | sensor | The export cap the plan asked for |
| `sensor.deye_inverter_*_today` / `*_total` | sensor | PV, grid import/export, battery charge/discharge, load energy (kWh) |
| `binary_sensor.deye_inverter_connected` | binary sensor | Poll health |

### Services

| Service | Description |
|---|---|
| `deye_bridge.snapshot` | Save the current control registers (also done when you enable control) |
| `deye_bridge.restore` | Write the saved snapshot back |
| `deye_bridge.apply` | Re-run the translation now instead of waiting for the next poll |

All three accept an optional `entry_id` to target one inverter.

---

## Use

```yaml
# one-time: allow the integration to write to the inverter
- service: switch.turn_on
  target: { entity_id: switch.deye_inverter_control_enabled }

# charge 4 kW from the grid
- service: number.set_value
  target: { entity_id: number.deye_inverter_grid_charge_power }
  data: { value: 4000 }

# export up to 2 kW (house first)
- service: number.set_value
  target: { entity_id: number.deye_inverter_export_power }
  data: { value: 2000 }

# back to self-consumption
- service: number.set_value
  target: { entity_id: number.deye_inverter_grid_charge_power }
  data: { value: 0 }
- service: number.set_value
  target: { entity_id: number.deye_inverter_export_power }
  data: { value: 0 }
```

A minimal price-driven automation:

```yaml
alias: Deye price response
trigger:
  - platform: state
    entity_id: sensor.electricity_price
action:
  - choose:
      - conditions: "{{ states('sensor.electricity_price')|float < 0.10 }}"
        sequence:
          - service: number.set_value
            target: { entity_id: number.deye_inverter_grid_charge_power }
            data: { value: 6000 }
          - service: number.set_value
            target: { entity_id: number.deye_inverter_export_power }
            data: { value: 0 }
      - conditions: "{{ states('sensor.electricity_price')|float > 0.30 }}"
        sequence:
          - service: number.set_value
            target: { entity_id: number.deye_inverter_grid_charge_power }
            data: { value: 0 }
          - service: number.set_value
            target: { entity_id: number.deye_inverter_export_power }
            data: { value: 6000 }
    default:
      - service: number.set_value
        target: { entity_id: number.deye_inverter_grid_charge_power }
        data: { value: 0 }
      - service: number.set_value
        target: { entity_id: number.deye_inverter_export_power }
        data: { value: 0 }
mode: single
```

---

## How it works

| Slider | Registers | Conversion |
|---|---|---|
| Grid charge power | `128` + `130` + `127` | `A = W / battery_voltage`, clamped to 185 A |
| Export power | `143` + `145` + `142` + TOU floor | direct watts |

Three states:

* **Charging** — TOU off, grid charge on, target SOC = ceiling, current from the slider.
* **Exporting** — TOU on with all six slots flattened to "discharge to the floor",
  Selling First, solar sell, `143` = slider. The CT is on the incomer, so the house is
  always served before anything leaves.
* **Self-consumption** — both zero: TOU on with the floor, no export.

### Operating mode

`select.deye_inverter_operating_mode` chooses between:

* **`manual`** — the two number sliders drive the plan, as described above.
* **`self_consumption`** — the sliders are ignored and the integration runs a
  zero-export absorption loop for AC-coupled PV.

#### Self-consumption with an AC-coupled inverter

A second, AC-coupled PV inverter on the house side is invisible to the Deye's own
control: it cannot curtail it. The only way to keep that energy is to charge the
battery from the AC bus at (roughly) the exported power, so the CT settles near zero.

In `self_consumption` mode the coordinator reads grid power (register 625) every cycle:

| CT reading | Action |
|---|---|
| Export > 150 W for 10 s | Start absorbing. Charge the battery at ≈ 95 % of the export: TOU off, grid charge enabled, `128` = export / battery voltage |
| Export between 50–150 W | Keep the current state (hysteresis) |
| Export < 50 W for 30 s | Stop absorbing, return to normal zero-export self-consumption (TOU on, battery discharges to the floor) |
| **Import > 100 W** | **Cancel absorbing immediately** and hand back to self-consumption so the battery discharges |
| Battery at charge ceiling | Stop absorbing |

On the other side of zero, the discharge is already handled by the inverter's own
fast zero-export CT loop: the self-consumption plan (TOU on, discharge floor, zero
export) lets it discharge the battery until the CT is back at zero — as long as the
battery is above the floor. The integration's job is the hand-over: the moment the CT
reports import (> 100 W) absorption is cancelled immediately rather than waiting out
the exit hold, so the battery is never left idle while the house is importing.

The 95 % bias means the loop prefers a small export over importing. The ratio and the
four timing thresholds are all in **Configure**; while the loop is active (or export is
present) the integration polls at the **fast interval** (default 10 s) and otherwise
falls back to the normal scan interval (default 30 s), so the fast reaction does not
cost you a fast poll all day. If the battery is full there is nowhere for the
AC-coupled surplus to go — the Deye cannot curtail a house-side inverter, so it will
export.

> If the AC-coupled inverter is wired to the **GEN port** instead, use the Deye's own
> micro-inverter input mode (`133 = 2`); the inverter handles it natively and this loop
> is not needed.

Full specification: [docs/03-translation.md](docs/03-translation.md).
Register map: [docs/02-register-map.md](docs/02-register-map.md).

---

## Safety model

* **Snapshot on enable, restore on disable** (and on removal / clean shutdown). The
  snapshot is persisted in `.storage`, so it survives restarts.
* **SOC guards** on top of the battery's own BMS (charge stops at the ceiling, export
  stops one percent above the floor).
* **Write only on change**, with deadbands, so a noisy battery voltage does not produce
  a write every cycle.
* **Read-back verification** every N cycles; drift triggers a re-apply.
* **If HA dies**, the inverter keeps the last limits and stops at its SOC bounds.

---

## Commissioning

1. Add the integration and confirm `sensor.deye_inverter_battery_soc` matches the
   inverter display.
2. Turn on **Control enabled** — this takes the snapshot. Check `deye_bridge.snapshot`
   returns data (or look at the diagnostics).
3. Set **Grid charge power** to 1000 W and watch `sensor.deye_inverter_battery_power`
   and the register 128/130 values in the diagnostics.
4. Set it back to 0 and confirm charging stops.
5. Set **Export power** to 1000 W and watch the meter. If battery export does not start,
   check `142 = 0`, `145 = 1`, `146 = 0x00FF`, and the firmware caveat about the
   "sell" bit in registers 172–177.
6. Turn off **Control enabled** and confirm the original settings are back.

The long form is in [docs/03-translation.md](docs/03-translation.md#6-commissioning-procedure).

---

## Known limitations

* The charge slider is **amps underneath**: accurate to about ±50 W (one amp at ~52 V).
  Export is exact, because register 143 is in watts.
* The two sliders are **mutually exclusive** by design: the battery cannot charge and
  discharge at once. The conflict policy decides who wins.
* Firmware differs between Deye models and years. The translation assumes the stock
  three-phase LV semantics; see
  [the caveats](docs/01-solarman-and-deye-control.md#5-firmware-differences-you-must-verify-on-your-unit).
* Battery export in Selling First depends on the TOU engine and, on some firmware, on
  an undocumented "sell" bit in registers 172–177.
* AC-coupled absorption is a slow outer loop: it reacts once per poll, and it cannot
  stop a house-side inverter from exporting when the battery is full.

---

## Development

```bash
python tests/test_core.py        # 33 translation tests
python tests/test_coordinator.py # 11 interlock / self-consumption / battery / CT tests
python tests/test_imports.py     # imports the integration against HA stubs
python tools/dry_run.py          # prints the register plan for scenarios
python tools/probe_transport.py 192.168.1.50
```

### Publishing

1. Create a GitHub repository and push this tree.
2. Update `codeowners`, `documentation` and `issue_tracker` in
   `custom_components/deye_bridge/manifest.json`.
3. Create a release with tag `v0.1.0` — HACS installs from releases.
4. Add the repository to HACS as a custom **Integration** repository.

`tests/ha_stub` contains minimal stand-ins for the Home Assistant classes the
integration touches. They are not a substitute for `hassfest`, but they catch syntax,
import, MRO and dataclass mistakes in a bare Python environment.

Layout:

| Path | What it is |
|---|---|
| `custom_components/deye_bridge/` | The integration |
| `docs/` | Research, register map, translation spec |
| `tests/` | Translation tests + import smoke tests + HA stubs |
| `tools/` | Dry run and transport probe |
| `examples/` | Example Lovelace view |
| `legacy/pyscript/` | The earlier pyscript prototype (superseded by the integration) |
| `research/` | Protocol PDFs and integration sources the docs are based on |

---

## License

MIT — do whatever you want, but this thing writes registers to an inverter. Be careful.

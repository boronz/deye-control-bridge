# Register map used by this project

Scope: **Deye three-phase low-voltage hybrid, device type `0x0500`**
(SUN-5/6/8/10/12K-SG04LP3 and SUN-4/5/6/8/10/12K-SG05LP3, including the
`-EU-SM2` variants). Register numbers are decimal and are written **without** the
`40001` offset that some tools add.

Transport: Modbus RTU, **9600 8N1**, slave id 1 (default), **FC03 read / FC16 write**.
All values are holding registers — there is no separate input-register space.

---

## 1. Control registers

### 1.1 Work mode and export

| Reg | Name | Type | Scale | Range | Notes |
|---|---|---|---|---|---|
| 104 | Zero-export power | u16 | 1 W | 20–? | Hard offset in zero-export CT modes; recommended 20–100 W |
| 142 | Limit control ("work mode") | u16 | — | 0/1/2 | `0` sell enabled, `1` built-in CT, `2` external CT |
| 143 | **Max sell power** | u16 | 1 W (LV) | 0–12000 | Total export ceiling. The main export knob |
| 144 | Default max sell to grid | u16 | 1 W | 0–65535 | Value 143 resets to after a factory reset |
| 145 | **Solar sell** | u16 | — | 0/1 | Master export permission |
| 340 | Max solar sell power | u16 | 1 W (LV) | — | PV-only sell cap; **not** used here |

### 1.2 Battery and grid charging

| Reg | Name | Type | Scale | Range | Notes |
|---|---|---|---|---|---|
| 108 | Max battery charge current | u16 | 1 A | 0–185 | Global cap, applies to PV *and* grid charging |
| 109 | Max battery discharge current | u16 | 1 A | 0–185 | `0` stops discharge entirely (evcc "hold" trick) |
| 115 | Battery shutdown SOC | u16 | 1 % | 0–100 | Protection — do not use as a control knob |
| 116 | Battery restart SOC | u16 | 1 % | 0–100 | Protection |
| 117 | Battery low SOC | u16 | 1 % | 0–100 | Protection |
| 126 | Grid charge start voltage | u16 | 0.01 V | 0–6300 | Lead-acid control |
| 127 | **Grid charge start SOC** | u16 | 1 % | 0–100 | Grid charging runs while SOC < this value |
| 128 | **Grid charge current** | u16 | 1 A | 0–185 | Charge current taken from the grid |
| 129 | Generator charge enable | u16 | — | 0/1 | Not used here |
| 130 | **Grid charge enable** | u16 | — | 0/1 | Global switch when TOU is off |

### 1.3 Time of use

| Reg | Name | Type | Scale | Notes |
|---|---|---|---|---|
| 146 | TOU enable + weekday mask | u16 | bit field | bit0 enable, bits1–7 Mon–Sun, bit8 Spain mode |
| 148–153 | Slot 1–6 start time | u16 | `HHMM` | 0000–2355 (communication range) |
| 154–159 | Slot 1–6 max battery **discharge** power | u16 | 1 W | 0–8000/12000 depending on model |
| 160–165 | Slot 1–6 target battery voltage | u16 | 0.01 V | Lead-acid control only |
| 166–171 | Slot 1–6 target SOC | u16 | 1 % | Discharge floor / charge target for the slot |
| 172–177 | Slot 1–6 charge source | u16 | bit field | bit0 grid charge, bit1 generator, bits2–4 Spain |

`146 = 0x00FF` → enabled every day. `146 = 0x0000` → schedule off (battery holds).

### 1.4 Peak shaving (unused, but adjacent)

| Reg | Name | Notes |
|---|---|---|
| 190 | Generator peak-shaving power | W |
| 191 | Grid peak-shaving power | W |

---

## 2. Measurements the translation needs

| Reg | Name | Type | Scale | Notes |
|---|---|---|---|---|
| 587 | Battery voltage | u16 | 0.01 V | Used to convert watts → amps |
| 588 | Battery SOC | u16 | 1 % | |
| 590 | Battery power | **s16** | 1 W | Positive = discharging (verify once) |
| 591 | Battery current | s16 | 0.01 A | |
| 625 | Grid total power | **s16** | 1 W | Positive = import, negative = export |
| 653 | Load total power | s16 | 1 W | |
| 672 / 673 | PV1 / PV2 power | u16 | 1 W | |
| 676–679 | PV1/PV2 voltage and current | u16 | 0.1 V / 0.1 A | |
| 598–600 | Grid voltage L1–L3 | u16 | 0.1 V | |
| 636 | Inverter output total power | u16 | 1 W | |
| 514 / 515 | Battery charge / discharge today | u16 | 0.1 kWh | |
| 520 / 521 | Grid buy / sell today | u16 | 0.1 kWh | |
| 522 / 524 | Grid buy / sell total | u32 | 0.1 kWh | low word first |
| 529 / 534 | PV energy today / total | u16 / u32 | 0.1 kWh | |
| 586 | Battery temperature | u16 | 0.1 °C + 1000 | `(raw-1000)/10` |

### 32-bit values

Deye stores 32-bit energy counters **low word first**. For the three-phase map the
high words of the instantaneous powers live in a separate block at 687–709, not
next to the low word. If you read totals, make sure your tool uses the right word
order — a wrong order produces absurd kWh numbers.

### Signed values

Battery/grid/load power and current are two's complement (`s16`). Grid power:
positive = importing. Battery power: positive = discharging (confirm once on your
unit — the protocol only says "signed").

---

## 3. Battery data

The inverter forwards a detail block for each battery input. The integration uses it to
create one HA device per battery.

| Reg | Name | Scale | Notes |
|---|---|---|---|
| 24 | Battery input number | — | `0`/`1` = one input, `2` = two inputs |
| 210 | Battery 1 charge voltage | 0.01 V | BMS setting mirrored by the inverter |
| 211 | Battery 1 discharge voltage | 0.01 V | |
| 212 | Battery 1 charge current limit | 1 A | |
| 213 | Battery 1 discharge current limit | 1 A | |
| 214 | Battery 1 SOC | 1 % | live |
| 215 | Battery 1 voltage | 0.01 V | live |
| 216 | Battery 1 current | 1 A (s16) | live |
| 217 | Battery 1 temperature | 0.1 °C + 1000 | live |
| 218 | Battery 1 max charge current | 1 A | |
| 219 | Battery 1 max discharge current | 1 A | |
| 220 | Battery 1 alarm flags | bit field | |
| 221 | Battery 1 fault flags | bit field | |
| 223 | Battery 1 type | — | BMS protocol id |
| 224 | Battery 1 SOH | 1 % | |
| 225 | Battery 1 software version | — | |
| 226 | Battery 1 rated capacity | 1 Ah | |
| 227 | Battery 1 hardware version | — | |
| 229 / 230 | Battery 1 / 2 brand code | — | see the protocol appendix |
| 241–258 | Battery 2 | | same layout as 210–227 |
| 586 | Battery 1 temperature | 0.1 °C + 1000 | live summary |
| 587 | Battery 1 voltage | 0.01 V | |
| 588 | Battery 1 SOC | 1 % | |
| 589 | Battery 2 SOC | 1 % | |
| 590 | Battery 1 power | 1 W (s16) | |
| 591 | Battery 1 current | 0.01 A (s16) | |
| 592 | Corrected capacity | 1 Ah | |
| 593 | Battery 2 voltage | 0.01 V | |
| 594 | Battery 2 current | 0.01 A (s16) | |
| 595 | Battery 2 power | 1 W (s16) | |
| 596 | Battery 2 temperature | 0.1 °C + 1000 | |

> The detail block sits in the writable settings area. Reading is safe; the integration
> never writes it. If a firmware does not answer for 210+ the coordinator catches the
> error and keeps the rest of the poll working.
>
> Register 24 is the number of **configured** inputs, not of connected packs. Entity
> creation uses each battery's own voltage instead.

---

## 4. Grid and CT measurements

| Reg | Name | Scale | Notes |
|---|---|---|---|
| 598–600 | Grid phase voltage L1–L3 | 0.1 V | |
| 604–606 | Internal (built-in) CT power L1–L3 | 1 W (s16) | |
| 607 | Internal CT total power | 1 W (s16) | |
| 609 | Grid frequency | 0.01 Hz | |
| 610–612 | Internal CT current L1–L3 | 0.01 A (s16) | |
| 613–615 | External CT current L1–L3 | 0.01 A (s16) | |
| 616–618 | External CT power L1–L3 | 1 W (s16) | |
| 619 | External CT total power | 1 W (s16) | |
| 622–624 | **Selected** CT power L1–L3 | 1 W (s16) | internal or external, per register 142 |
| 625 | **Selected** CT total power | 1 W (s16) | what `sensor.deye_inverter_grid_power` uses |
| 626–629 | Inverter output phase voltage L1–L3 | 0.1 V | |
| 630–632 | Inverter output phase current L1–L3 | 0.01 A (s16) | |
| 636 | Inverter output total power | 1 W (s16) | |
| 653 | Load total power | 1 W (s16) | |

Positive power = import, negative = export. The per-phase powers at 622–624 are the
values the inverter's own control loop uses, so they are the right source for a
grid/P1 replacement. The external clamp group (613–619) is independent of the
selected CT and is useful when diagnosing a reversed clamp.

---

## 5. Register writes: rules of thumb

1. **Always use FC16** (`write_multiple_holding_registers`), even for a single
   register. The protocol only officially supports `03H` and `10H`.
2. **Write blocks in one transaction** where possible: 154–159, 166–171 and 172–177
   are three natural blocks.
3. **Only write when the value changes.** The inverter persists settings; hammering
   it is both slow and unnecessary.
4. **Never write** factory, calibration, grid-protection or battery-protection
   registers (e.g. 80, 81, 185–188, 115–120) from a control loop.
5. **Read back** the critical registers after a state change (143, 128, 130, 146).
   A silently rejected write is the most common failure mode.

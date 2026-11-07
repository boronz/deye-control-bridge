# How the Deye SUN-12K-SG05LP3-EU-SM2 is controlled — and where Solarman fits

This note answers two questions:

1. What does the Solarman integration actually do with this inverter?
2. How does the inverter *want* to be controlled, and why is that a bad fit for a HEMS?

The short version: **Solarman is only the transport.** The control model lives in the
inverter, and it is a rule engine (work mode + export cap + grid-charge limit +
a six-slot time-of-use schedule), not a power-following device. The time slots are
the only place where a battery discharge floor and a per-slot discharge limit exist,
so they cannot simply be switched off — they have to be *neutralised*.

---

## 1. There are two different things called "Solarman"

| Thing | What it is | What it gives you |
|---|---|---|
| Solarman / SolarMAN cloud + stick logger | The Wi-Fi/LAN dongle (IGEN/LSW-3 family) that ships with the inverter, plus the vendor cloud | Vendor app, cloud graphs, and a local TCP endpoint on port 8899 |
| `home_assistant_solarman` (StephanJoubert) | HACS integration that polls the logger locally (or via cloud) with `pysolarmanv5` | Sensors defined by a YAML profile, **plus** read/write register services |

The stock stick speaks **Solarman V5** on TCP 8899 — a vendor framing around Modbus
RTU. It is *not* a plain Modbus TCP server, and several users report that a port scan
of the stock logger shows no usable Modbus port at all. Run
`python tools/probe_transport.py <dongle-ip>` to see which of the two your unit
answers. Where plain Modbus TCP is
needed, people add an RS485↔TCP gateway (Elfin, USR, Waveshare, …) on the inverter's
RS485 port and talk to port 502.

The integration ships a profile for exactly this inverter family:
`deye_sg04lp3.yaml` ("SUN-8/12K-SG04LP3-EU, 8/12 kW, three phase, 2 MPPT, LV battery").
It reads holding registers with FC03 in a handful of blocks and creates sensors such as
`Battery SOC`, `Battery Voltage`, `Battery Power`, `Total Grid Power`, `PV1 Power`, …
(SOC = register 588, battery voltage = 587, battery power = 590, grid power = 625).

### Writing registers through the integration

`custom_components/solarman/services.py` registers four services:

| Service | Function code | Notes |
|---|---|---|
| `solarman.read_holding_register` | FC03 | returns a response |
| `solarman.read_multiple_holding_registers` | FC03 | returns a response, `count` registers |
| `solarman.write_holding_register` | FC06 | *single* register |
| `solarman.write_multiple_holding_registers` | FC16 | list of values at `register` |

All calls take `device_id` (the HA device of the inverter), and the integration
serialises polling and service calls with a lock, so they do not collide on the
single TCP connection.

> **Use FC16, not FC6.** Deye's three-phase protocol document says only function
> codes `03H` and `10H` are open. In practice many firmwares ignore or reject FC06.
> The working recipe reported on the Deye forums is: read with FC03, write with FC16.

Write throughput is the practical limit: each transaction goes over Wi-Fi to the
logger and then over RS485 at 9600 baud, so expect roughly 0.5–2 s per write.
That is fine for a HEMS (`15 min` or `1 min` control cadence), but it means the
translation must **batch** writes and **only write what changed** — both for speed
and to avoid wearing the inverter's settings memory.

---

## 2. The inverter's native control model

Everything below is a holding register, and all of it is documented in Deye's
three-phase energy-storage protocol (register numbers are decimal, no offset).

### The "front panel" settings

| Register | Name | Meaning |
|---|---|---|
| 142 | Limit control / work mode | `0` = Selling First, `1` = Zero Export to Load (built-in CT), `2` = Zero Export to CT (external CT) |
| 143 | Max sell power (W) | Soft ceiling on export. This is the register Deye support points at for feed-in limiting |
| 145 | Solar sell | `1` = export allowed, `0` = no export |
| 104 | Zero-export power (W) | Hard zero-export offset in CT modes; 20–100 W is the recommended value |
| 130 | Grid charge enable | Global "may the grid charge the battery" switch |
| 127 | Grid charge start SOC (%) | Grid charging runs while SOC is below this value |
| 128 | Grid charge current (A) | Charge current taken from the grid |
| 108 / 109 | Max battery charge / discharge current (A) | Global battery current limits, 0–185 A on the 12K |
| 115 / 116 / 117 | Shutdown / restart / low SOC | Protection thresholds — do not use these as control knobs |

### The time-of-use engine

Register **146** enables it: bit 0 = enable, bits 1–7 = Monday…Sunday, bit 8 = Spain mode.
`0x00FF` therefore means "enabled every day", `0x0000` means "off".

There are six slots. Each has:

| Registers | Field | Unit |
|---|---|---|
| 148–153 | Slot start time | `HHMM` (e.g. `2230`) |
| 154–159 | Max battery **discharge** power | W |
| 160–165 | Target battery voltage (lead-acid control) | 0.01 V |
| 166–171 | Target SOC | % |
| 172–177 | Charge source bit field: bit0 = grid, bit1 = generator, bits2–4 = Spain modes | — |

The manual describes the semantics clearly:

* *Power* = "maximum permitted discharge power of the battery" for that slot.
* *Batt* = the SOC (or voltage) at which the slot's action stops — i.e. discharge down
  to this value, or charge up to this value.
* With the grid present and **Time of Use enabled, the battery is discharged**;
  with Time of Use disabled the battery is **not** discharged, even when full.
* In **Selling First**, once Time of Use is enabled, *battery* energy can be sold to
  the grid as well as PV.

That last point is the key constraint for a HEMS: **you cannot have a discharge floor
(or battery export) without the TOU engine being on.** Turning TOU off is not
"manual mode", it is "hold the battery".

### How the pieces interact

```
                     ┌──────────────────────────────┐
   grid charge ──────┤ 130 enable                   │
                     │ 127 start SOC  +  128 amps   │  (TOU off)
                     │ or TOU slot bit 0            │  (TOU on)
                     └──────────────────────────────┘

   export ───────────┌──────────────────────────────┐
                     │ 145 solar sell               │
                     │ 143 max sell power (W)       │
                     │ 142 work mode                │
                     │ TOU on  →  battery may sell  │
                     └──────────────────────────────┘

   discharge floor ──┌──────────────────────────────┐
                     │ TOU slot SOC (166..171)      │
                     │ TOU slot power (154..159)    │
                     └──────────────────────────────┘
```

So the inverter has **three independent-ish axes**:

1. **Charge**: enabled/disabled, at a current, up to a start-SOC.
2. **Export**: allowed/not, capped in watts.
3. **Discharge floor and discharge power cap**: only expressible through the TOU slots.

---

## 3. Why the time-slot model is the wrong interface for a HEMS

A HEMS wants: *"charge 4 kW now"*, *"export at most 2 kW now"*, updated every price
interval. The inverter offers: *"between 22:00 and 06:00, charge with 60 A up to 100 %,
and between 06:00 and 22:00 discharge to 20 % at up to 3 kW"*.

Concretely, the problems are:

* **Boundary-triggered.** A slot only takes effect when its start time is reached.
  Changing behaviour "now" means rewriting the slot that contains "now" — and you
  must know which one that is.
* **Coupled to the clock, not to prices.** A price spike at 17:43 cannot be expressed
  without editing a slot at 17:43.
* **Many registers, no atomic write.** Six slots × four fields = 24 registers. A
  partial write can leave a schedule that is momentarily inconsistent.
* **The 6-slot UI is a poor fit for 96 quarter-hour prices.** You end up computing
  slots from prices anyway — exactly the complexity the HEMS is supposed to remove.

But the TOU engine is also the **only** place that provides a discharge floor and a
per-slot discharge power limit, and the only thing that lets the battery discharge at
all. So the translation cannot "disable TOU and take over". It has to keep TOU on and
make the schedule irrelevant.

---

## 4. The trick: flatten the schedule instead of fighting it

Keep the six slots, keep their start times, and **write the same policy into all six**.
The schedule then behaves as one continuous rule, and the only things that change
minute-to-minute are a handful of registers:

| Knob | Register | Why it is safe to change often |
|---|---|---|
| Grid charge on/off | 130 | plain switch |
| Grid charge current | 128 | plain number |
| Grid charge start SOC | 127 | plain number |
| Max sell power | 143 | plain number, designed for curtailment |
| Solar sell | 145 | plain switch |
| Work mode | 142 | plain enum |
| TOU enable | 146 | plain bit mask |

The slot blocks (154–159, 166–171, 172–177) are only rewritten when the *policy*
changes (e.g. moving from charging to exporting), in three FC16 writes.

That is the whole translation: **two sliders in, a small state machine, a handful of
registers out.** It is specified in [translation.md](translation.md).

---

## 5. Firmware differences you must verify on your unit

Deye's documentation and the community register maps disagree in a few places. The
translation is written so these can be changed in one place, but please verify:

1. **143 vs 340.** The protocol calls 143 *Max sell Power* and 340 *Max Solar Sell
   Power*. Deye support told a forum user to write 143 for feed-in limiting, and evcc
   uses 143 for curtailment. Some HA integrations label 340 as "Max sell power".
   This project uses **143** (total sell cap) and leaves 340 alone.
2. **142 values.** The protocol calls it "limit control": `0` = sell enabled,
   `1` = built-in CT, `2` = external CT. The community calls the same values
   Selling First / Zero Export to Load / Zero Export to CT. Your SM2 has CT terminals,
   so "external CT" (`2`) is the usual zero-export mode.
3. **TOU charge-source bits.** The protocol documents bits 0–4. A 2026 forum post for
   an 80 kW HV unit reports that writing `34` to a slot register enables selling.
   If battery export does not start with `145=1` + `142=0` + TOU on, this is the first
   thing to inspect; the bit can be added in the configuration.
4. **FC06.** Use FC16 (`write_multiple_holding_registers`) even for one register.
5. **Don't hammer the settings.** Write only when a value actually changes. The
   inverter stores settings in non-volatile memory; a 20 s rewrite loop would be
   thousands of writes per day.

---

## 6. Sources

* Deye, *MODBUS RTU 三相储能通信规约* (three-phase energy-storage protocol), V105 /
  V105.4 — register table for 108–177, 340, 500-series measurements. Copies:
  [V105](https://akkudoktor.net/uploads/short-url/ezKBX2l8uHmLk9qJyPxDfGLhYqP.pdf),
  [V105.1](https://akkudoktor.net/uploads/short-url/nbQbzSQaFFe3UdycjiVVVv5f7Y0.pdf).
* Deye, *SUN-4/5/6/8/10/12K-SG05LP3-EU-SM2 user manual* (German),
  [de.deyeinverter.com](https://de.deyeinverter.com/deyeinverter/2025/08/12/%E3%80%90b%E3%80%91%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E%E4%B9%A6-%E5%82%A8%E8%83%BD%E4%B8%89%E7%9B%B8-sun-4-12k-sg05lp3-eu-sm2.pdf) —
  System Work Mode and Time-of-Use section.
* `home_assistant_solarman` — profile `deye_sg04lp3.yaml`, services
  [`advanced.md`](https://github.com/StephanJoubert/home_assistant_solarman/blob/main/advanced.md),
  [`services.py`](https://github.com/StephanJoubert/home_assistant_solarman/blob/main/custom_components/solarman/services.py).
* [Deye/Sunsynk/Growatt Modbus register map](https://modbusmanager.com/deye-sunsynk-growatt-modbus.html)
  (three-phase table, scaling, word order, pitfalls).
* [deye-modbus-ha](https://github.com/Developer089/deye-modbus-ha) — a YAML register map for
  exactly this model, including writable control entities.
* [evcc `deye-hybrid-3p` template](https://github.com/evcc-io/evcc/blob/master/templates/definition/meter/deye-hybrid-3p.yaml) —
  reference implementation of battery charge/hold control via registers 127/130/146/109.
* Deye forum threads: [register 143 as feed-in limit](https://dy-support.org/community/technische-fragen/max-sell-power-einspeiseleistung-ueber-modustcp-steuern-fuer-tre-rundsteuerempraenger/),
  [TOU slot "sell" bit](https://dy-support.org/community/technische-fragen/einspeisesteuerung-ueber-modbus/).
* [Deye system work modes explained](https://hub.suncloudenergy.com.au/guides/deye-system-work-modes/) —
  Selling First vs Zero Export to Load vs Zero Export to CT, Solar Sell, Max Sell Power.
* [Modbus TCP through the Deye Wi-Fi logger?](https://dy-support.org/community/solarmann-app/modbus-tcp-abfragen-ueber-den-deye-wifi-datenlogger-moeglich/) —
  why the stock stick is not a Modbus TCP server.

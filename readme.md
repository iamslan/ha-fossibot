# Fossibot Home Assistant Integration

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/iamslan/ha-fossibot)](https://github.com/iamslan/ha-fossibot/releases)
[![License: MIT](https://img.shields.io/github/license/iamslan/ha-fossibot)](LICENSE)

Monitor and control **Fossibot / Sydpower** portable power stations from
[Home Assistant](https://www.home-assistant.io/) over your **own MQTT broker** —
no cloud MQTT in the data path.

Every register is decoded against the official Modbus protocol specification,
shared with this project by the Sydpower technical team
([thank you](#thank-you-sydpower)). What is implemented, what was found wrong
along the way, and what is deliberately left out is documented in
**[docs/PROTOCOL_AUDIT.md](docs/PROTOCOL_AUDIT.md)**.

> **Unofficial integration.** Not affiliated with Fossibot, Sydpower or
> BrightEMS. **Use at your own risk** — see [Writing to your device](#writing-to-your-device).

[Join the Discord](https://discord.gg/2jKxpxGg9D) to help with development,
report issues, or share results for your model.

---

## Contents

- [Requirements](#requirements)
- [Supported devices](#supported-devices)
- [Installation](#installation)
- [Configuration](#configuration)
- [Entities](#entities)
- [Writing to your device](#writing-to-your-device)
- [Troubleshooting](#troubleshooting)
- [Not supported](#not-supported)
- [For contributors](#for-contributors)
- [Thank you, Sydpower](#thank-you-sydpower)

---

## Requirements

| | |
|---|---|
| **BrightEMS app** | version **1.6.0** or later |
| **MQTT broker** | e.g. [Mosquitto](https://mosquitto.org/) or [EMQX](https://www.emqx.io/), reachable **by your power station** on TCP port 1883 |
| **Internet** | needed once at startup for the device list, and for online/offline state sync — the telemetry itself is local |

The broker must be reachable from the power station, not just from Home
Assistant. The device connects to it directly.

## Supported devices

Anything that pairs with the **BrightEMS** app runs on the same SYDPOWER
platform and should work:

| Brand | Models |
|-------|--------|
| **FOSSiBOT** | F1200, F2400, F3600, F3600 Pro |
| **AFERIY** | P210, P310 |
| **Eco Play (ECOPLAY)** | SYD2400, SYD3600, 3600 Pro |
| **ABOK Power** | Ark3600 |

The same hardware is sold under several names, so a model listed for one brand
usually confirms its siblings:

- **SYDPOWER N052** — 2400 W / 2048 Wh — FOSSiBOT F2400 · AFERIY P210 · Eco Play SYD2400
- **SYDPOWER N051 / N066** — 3600 W / 3840 Wh — FOSSiBOT F3600 Pro · AFERIY P310 · Eco Play SYD3600 · ABOK Ark3600

Not listed? It will most likely still work — please report the result on
Discord or in a GitHub issue so the table can grow. Expansion batteries are
picked up automatically (up to four).

## Installation

### HACS (recommended)

1. **HACS** → **Integrations** → **Custom Repositories**
2. Add `https://github.com/iamslan/ha-fossibot` as an **Integration**
3. Search for **Fossibot**, install it
4. Restart Home Assistant

### Manual

1. Copy `custom_components/fossibot-ha` into `<config>/custom_components/`
2. Restart Home Assistant

## Configuration

### 1. Point the device at your broker

In the **BrightEMS** app: **Me** → **Settings** → **Local MQTT Broker Settings**.
Enter your broker's host address, then copy the **API Token** shown on that
screen — you need it in the next step.

> Only the **master account** (whoever bound the device first) can change MQTT
> settings. Everyone sharing the device must use the same broker host.

### 2. Add the integration

**Settings** → **Devices & Services** → **+ Add Integration** → **Fossibot**:

| Field | Value |
|-------|-------|
| **API Token** | from the BrightEMS screen above |
| **MQTT Broker Host** | your broker's address |
| **MQTT Broker Port** | `1883` |
| **MQTT Username** | optional — only if your broker requires it |

The integration fetches your device list, connects to the broker and creates
every entity automatically.

### Upgrading to v3.0

No reconfiguration needed — restart Home Assistant and the new entities appear.
Three things change behaviour:

- **Discharge Lower Limit is now 0–50% and AC Charging Upper Limit is 60–100%**,
  matching the vendor specification. If you had either set outside those
  ranges, the device keeps its current value but you can no longer set a new
  one outside the documented range. See
  [Writing to your device](#writing-to-your-device).
- **"Maximum Charging Current" is now "DC Input Charging Current Limit"** — it
  always controlled the DC (solar / vehicle) input, not the AC one. The entity
  ID is unchanged, so automations keep working.
- **LED Mode reports the real mode from the device** instead of remembering the
  last option it set, so it can now show SOS and Flash, and it stays correct
  when the mode is changed on the unit itself.

Grid frequency also reads correctly now — earlier versions could report it
around 0.5 Hz.

### Upgrading from v1.x

v2.0 replaced the cloud connection with local MQTT, so the config entry format
changed. **Remove the integration and re-add it** with your broker settings and
API token.

## Entities

**107 entities per device, 55 enabled by default.** The rest — individual port
powers, BMS internals, static capability values — are created but disabled, so
a device page is not buried under two dozen mostly-zero readings. Enable any of
them from the device page when you actually need it.

Rows marked **†** are the disabled-by-default ones.

### Sensors

**Battery**

| Entity | Unit | Notes |
|--------|------|-------|
| State of Charge | % | Main pack |
| State of Charge Slave 1 – 4 | % | One per connected expansion battery |
| Battery Usable Capacity | Ah | As reported by the BMS |
| Average Charge SoC / Average Discharge SoC | % | Diagnostic |
| Battery Chemistry † | — | Capacity and cell topology in the attributes |

**Power in**

| Entity | Unit | Notes |
|--------|------|-------|
| AC Input | W | Charging from mains |
| DC Input | W | Solar / DC input |
| USB-C Input | W | Charging over USB-C |
| Total Input | W | All sources combined |

**Power out**

| Entity | Unit | Notes |
|--------|------|-------|
| Total Output | W | Everything combined |
| AC Output Power | W | |
| Inverter Output Power | W | Off-grid inverter |
| Inverter Apparent Power † | VA | |
| USB 1–3, QC 1–3, PD 1–5 Power † | W | Per-port breakdown |
| XT60, Cigarette Socket, DC 5521 Power † | W | Per-port breakdown |
| Wireless Charging Power †, LED Power † | W | |

**Electrical**

| Entity | Unit | Notes |
|--------|------|-------|
| AC Output Voltage / Frequency | V / Hz | Inverter side |
| AC Input Voltage / Frequency | V / Hz | Grid side |

**Energy and time**

| Entity | Unit | Notes |
|--------|------|-------|
| PV Energy Total | kWh | Lifetime total — ready for the Energy dashboard |
| Remaining Charge Time | min | BMS estimate to full |
| Remaining Discharge Time | min | BMS estimate to empty |
| Charge Schedule Remaining † | min | Time left on a scheduled charge |

**Diagnostic**

| Entity | Unit | Notes |
|--------|------|-------|
| Active Faults | count | Every decoded fault name is in the attributes |
| AC Charging Rate Active † | — | The level the device is really running at |
| AC Charge Max Power †, DC Input Max Power † | W | Device ratings |
| DC Input Max Current † | A | The ceiling the current-limit slider obeys |
| DC Input Min / Max Voltage † | V | Accepted DC input window |
| Protocol Version † | — | Should be `0` or `1` on a power station |

### Binary sensors

| Entity | Notes |
|--------|-------|
| **Fault** | `problem` class — on whenever any fault bit is set, names in the attributes |
| Grid Charging | Mains is actively charging |
| Grid Input Present | Mains detected |
| On Grid | The device's own on-grid / off-grid determination — not the same as mains being present |
| DC Charging / DC Input Present | Solar or DC input |
| AC Inverter Output | The inverter is actually running |
| DC Port Output | The DC section is powered |
| ECO Mode | |
| Battery Charging | Diagnostic |
| PV High Voltage Charging † / Present † | High-voltage PV input |
| Car Charging † / Car Charge Input Present † | Vehicle charging input |
| Wireless Charging Active † | |
| USB 1–2, QC 1–2, PD 1–5, XT60, Cigarette Socket, DC 5521, LED † | Individual port state |
| Battery Discharging †, Fully Charged †, Fully Discharged †, Overvoltage †, Balancing † | BMS state |
| Precharge / Charge / Discharge MOSFET On † | BMS internals |

### Switches

| Entity | Description |
|--------|-------------|
| USB Output | Toggle the USB ports |
| DC Output | Toggle the DC output |
| AC Output | Toggle the AC inverter |
| AC Silent Charging | Quieter, slower mains charging |
| Buzzer | Device beeper |
| Grid Mode AC Auto Output | Enable AC output automatically when mains appears |
| App Remote Shutdown | Allow the unit to be shut down remotely |
| Low Battery Notification | Enable the low-battery alert |

### Selects

| Entity | Options |
|--------|---------|
| LED Mode | Off · On · SOS · Flash |
| AC Charging Rate | Level 1 – 5 |
| DC Input Type | MPPT (PV) · DC source |
| USB Standby Time | Off · 3 min · 5 min · 10 min · 30 min |
| AC Standby Time | Off · 8 h · 16 h · 24 h |
| DC Standby Time | Off · 8 h · 16 h · 24 h |
| Screen Rest Time | Off · 3 min · 5 min · 10 min · 30 min |
| Sleep Time | 5 min · 10 min · 30 min · 8 h |

### Numbers

| Entity | Range | Unit | Description |
|--------|-------|------|-------------|
| DC Input Charging Current Limit | 1 – 20 | A | DC (solar / vehicle) charging current. The slider also narrows itself to whatever your device reports as its own maximum |
| Stop Charge After | 0 – 5000 | min | Scheduled charge duration; `0` disables it |
| Discharge Lower Limit | 0 – 50 | % | Stop discharging at this SoC |
| AC Charging Upper Limit | 60 – 100 | % | Stop charging at this SoC |
| Wi-Fi Upload Interval | 5 – 3600 | s | How often the device pushes data by itself |
| Low Battery Notification Threshold | 0 – 100 | % | Alert threshold |

Home Assistant also polls every 30 s independently of the upload interval, so
the two together decide how fresh the data is.

## Writing to your device

**This firmware does not validate register writes.** A value outside the
documented range can permanently brick the unit. That is not a theoretical
concern, so every write in this integration is checked against an allowlist of
values taken from the vendor specification, and a write that is not on the list
is refused before it reaches the broker.

Consequences worth knowing about:

- **The SoC sliders match the specification, not the full 0–100%.** The
  discharge floor is documented as 0–50% and the charge ceiling as 60–100%.
  Versions before 3.0 offered 0–100% for both, which was out of range.
- **Destructive and vendor-only registers are unreachable by design** — factory
  reset, debug mode, chip-type selector and timezone have no entity, and the
  code refuses them explicitly with a stated reason rather than by omission.
- **Firmware updates are not implemented.** Use the BrightEMS app.

If you think a range is wrong, the reasoning for each one is in
[docs/PROTOCOL_AUDIT.md](docs/PROTOCOL_AUDIT.md) with the register it came
from — please open an issue rather than widening the allowlist locally.

## Troubleshooting

### Enable debug logging

In `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.fossibot-ha: debug
```

The logger name follows the **folder** name (`fossibot-ha`), not the
integration domain (`fossibot`).

### Common problems

**Entities are all "unavailable" right after setup.**
The power station sleeps aggressively. The integration accepts the broker
connection anyway and recovers on its own once the device answers — wake the
unit by pressing a button on it, or wait for the next poll.

**A device is missing from Home Assistant.**
The device list comes from the SYDPOWER API. If a device has no `device_id`
there, it is skipped and logged with a warning; re-registering it in BrightEMS
fixes it.

**The integration loads but nothing ever updates.**
The device has to reach *your* broker. Check that the host you typed into
BrightEMS is reachable from the device's network, and that port 1883 is open to
it — Home Assistant being able to reach the broker is not sufficient.

**Slave battery sensors read "unknown".**
Expected when no expansion battery is attached; the register reports "not
connected" and the sensor stays empty rather than showing 0%.

## Not supported

- **Balcony grid-tie inverters.** These use protocol V1/V2, which reuses the
  same register numbers for entirely different values — holding register 41 is
  the battery pack layout on a power station and a grid-charge time window on
  an inverter. Supporting both needs a protocol-selected register profile;
  [docs/PROTOCOL_AUDIT.md](docs/PROTOCOL_AUDIT.md#not-implemented) lists what
  it would add.
- **Firmware updates** (Modbus function `0x26`) — documented, deliberately not
  implemented. A failed flash bricks hardware.
- **Wi-Fi provisioning** (function 7) — belongs to onboarding, which is the
  app's job.
- **Smart sockets and smart meters** — V1/V2 accessories.
- **Power/energy history charts** — V2 only.

## For contributors

```
custom_components/fossibot-ha/
  __init__.py          # Setup, platform loading
  config_flow.py       # UI configuration
  coordinator.py       # DataUpdateCoordinator, health check, reconnection
  entity.py            # Base entity + device registry info
  sensor.py            # ─┐
  binary_sensor.py     #  │ entity tables (plain lists of dicts)
  switch.py            #  │
  select.py            #  │
  number.py            # ─┘
  sydpower/
    const.py           # Register addresses, protocol enumerations
    registers.py       # V0 register map: decoders, bitfields, fault tables
    modbus.py          # Framing, CRC-16, write allowlist
    connector.py       # Connection orchestration
    mqtt_client.py     # MQTT over TCP (paho-mqtt)
    api_client.py      # REST API (device list, state sync)
    logger.py          # Rate-limited logger
```

The shape of the code follows a few decisions:

- **The register map is data, not code.** `registers.py` holds the decoders,
  bitfield tables and fault names, each annotated with the protocol section it
  came from, so a mapping can be checked against the document without reading
  any logic.
- **Entity definitions are plain lists of dicts.** Adding a sensor is one line;
  there is no per-entity class.
- **Decoding is index-driven.** Each field is read if the response is long
  enough to hold it, so a response of unexpected length still yields
  everything it does contain instead of being discarded.
- **The tests import the live entity tables** (`tests/conftest.py` stubs Home
  Assistant for this) and check them against the protocol layer. Every number
  slider is walked from minimum to maximum and each step asserted to encode to
  an allowed value, so a UI bound the allowlist would reject fails a test
  instead of reaching hardware.

Run the tests with:

```bash
python -m pytest tests/ -q
```

Contributions are welcome. If you have a model that is not in the table above,
sharing your results is genuinely useful — the compatibility list is built from
user reports.

## Thank you, Sydpower

This integration began as reverse engineering. It no longer has to be.

The **Sydpower technical team** reached out and shared their complete Modbus
protocol documentation — the full holding and input register maps, the fault
and status bitfields, the value ranges and unit scalings, and the firmware
upgrade specification. They did that voluntarily, for an unofficial
community project, with nothing asked in return.

That changed the quality of this integration in ways guessing never could:

- Faults are now reported by name instead of being silently discarded, because
  the documentation says what each of the eight fault words means — including
  which bits are normal operating state and must *not* be raised as alarms.
- Write ranges come from the specification rather than from whatever the app
  happened to offer. Two of the sliders had been able to write values outside
  the documented range, on firmware that does not validate writes. Nobody
  would have found that without the ranges in writing.
- Values that were subtly wrong — grid frequency, a mislabelled charging
  current — could be corrected against a source of truth instead of being
  argued about.
- Half of the device status field turned out to live in a register nobody knew
  to read.

A vendor helping the people who own their hardware understand it better is
rare, and worth saying out loud. **Thank you.**

## Credits

Created by [@iamslan](https://github.com/iamslan) and
[@alessandro-lac](https://github.com/alessandro-lac), originally by reverse
engineering the BrightEMS app, and now built on the official protocol
specification provided by Sydpower.

## License

[MIT](LICENSE)

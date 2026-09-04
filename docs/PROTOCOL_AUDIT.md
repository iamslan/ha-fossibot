# Protocol audit — vendor documentation vs. integration

> This audit exists because the **Sydpower technical team** shared their
> complete protocol documentation with this project, voluntarily and with
> nothing asked in return. Every finding below is a thing that could only be
> found by having the specification in writing. Thank you.

Audited against the Sydpower documentation set (`inverter-protocol-en`),
supplied by the Sydpower engineering team:

| Document | Revision | Covers |
|----------|----------|--------|
| `Inverter-Protocol-V0.docx` | V1.7, 2024-06-01 | **Portable power stations** — the devices this integration supports |
| `Inverter-Protocol-V1.docx` | V1.0, 2024-08-22 | Balcony grid-tie inverter, protocol version 1 |
| `Inverter-Protocol-V2.docx` | V1.0 | Balcony grid-tie inverter, protocol version 2 |
| `Firmware-Upgrade-Implementation-Details.docx` | — | Segmented firmware upload (function `0x26`) |

Everything below concerns **V0**. V1/V2 are a different device class and are
covered in [Not implemented](#not-implemented) at the end.

---

## Confirmed correct

The reverse-engineered foundation held up. These were checked line by line
against the document and needed no change:

- **Slave address 17 (0x11)** — matches the `Slave Address 11` hex examples used
  throughout section 1.
- **CRC-16/Modbus**, init `0xFFFF`, polynomial `0xA001`, appended **high byte
  first**. Matches `getCRC16_MODBUS` and `getModbusDataCRCLowFront(..., false)`
  in the firmware-upgrade document verbatim.
- **Function 3 / 4 / 6** framing, including the response layout: over MQTT the
  reply carries `addr, func, startHi, startLo, countHi, countLo` and then the
  data, with no serial-number block. This is why a 6-byte offset lands exactly
  on register 0, and why an 80-register read decodes as 81 words — the last
  one is the frame CRC.
- **Battery SOC** — input 56, 0.1% per count.
- **Slave battery SOC** — inputs 53/55, encoded `SOC + 10` over 10..1010 with
  0 meaning "no pack connected". The existing `raw / 1000 * 100 - 1` is
  algebraically identical to the documented `(raw - 10) / 10`.
- **Output button registers** — holding 24/25/26/27 for USB/DC/AC/LED.
- **Settings registers** — holding 13, 20, 57, 59, 60, 61, 62, 63, 66, 67, 68.
- **System-state bit positions** for the four bits that were being read
  (28 LED, 27 AC, 26 DC, 25 USB) — the old string-slicing arithmetic was
  correct, just very narrow.

---

## Defects found and fixed

### 1. Charge/discharge limits accepted out-of-spec values — *safety*

`WRITABLE_REGISTERS` allowed `0..1000` for both SOC limits.

| Register | Documented range | Was allowed | Now |
|----------|------------------|-------------|-----|
| Holding 66 — minimum discharge SOC | `0~500` (0-50%) | 0-100% | 0-50% |
| Holding 67 — maximum charge SOC, UPS mode | `600~1000` (60-100%) | 0-100% | 60-100% |

`modbus.py` opens with the warning that this firmware does not validate writes
and that an out-of-range value can brick a device — and then shipped sliders
that could write values the vendor never documented. The number entities now
expose 0-50% and 60-100% respectively.

**Behaviour change:** a charge ceiling below 60% is no longer selectable.

### 2. Grid frequency was reported ~100× low

Input 22 is documented as 0.1 Hz, the same as the AC output frequency in input
19. The code scaled input 19 by 1/10 and input 22 by 1/100 — one of the two had
to be wrong, and the document says it is the grid one.

Rather than swap one guess for another, `decode_frequency()` now picks the
scale from the magnitude. Mains frequency is always near 50 or 60 Hz, so 0.1 Hz
encoding yields ~500-600 and 0.01 Hz yields ~5000-6000; the ranges cannot
overlap, so the decision is unambiguous on either firmware.

### 3. Half the system-state field was unreachable

Inputs 41 and 42 form **one 32-bit field**: 41 holds bits 31..16 ("System
State H") and 42 holds bits 15..0 ("System State L"). The integration read
register 41 alone and extracted 4 bits from it. Register 42 was never looked
at, so the entire low half — every individual port, ECO mode, the 12 V outputs
— was invisible.

All 28 documented bits are now decoded and exposed via the new
`binary_sensor` platform.

### 4. No fault reporting at all

Eight fault/status words were being read off the wire and discarded:

| Register | Word |
|----------|------|
| input 43 | AC fault code (appendix &\*9) |
| input 44 | AC fault code 2 |
| input 45 | PV fault code (&\*10) |
| input 46 | High-voltage PV fault flags |
| input 47 | BMS AFE status (&\*11) |
| input 48 | BMS user status (&\*12) |
| input 50/51 | Panel fault code, 32-bit (&\*13) |

All are decoded into named faults, aggregated onto a `problem` binary sensor
and an "Active Faults" count with the fault names as attributes.

The bits the protocol marks **"do not parse"** are excluded from the fault
lists — in the BMS words those bits carry normal operating state (MOSFET
closed, charging, balancing), and treating them as faults would raise a
permanent false alarm. The genuinely useful ones are surfaced separately as
diagnostic binary sensors.

### 5. LED mode could not be read back

The LED select wrote holding 27 but had no way to read the current mode, so it
cached the last option it had set and reported `Off`/`On` only — SOS and Flash
were unrepresentable, and the state was wrong after any change made on the
device itself.

Input register 25 (`L8:LightMode`, `0=off 1=steady 2=SOS 3=strobe`) reports it
directly. The select is now an ordinary register select reading that value, and
the guessing is gone.

### 6. "Maximum Charging Current" was mislabelled as AC

Holding 20 is `DC Input Max Curr SET` — the **DC** (PV / vehicle) charging
current. The entity was named "Maximum Charging Current" and the README
documented it as "AC charging current limit". Renamed to "DC Input Charging
Current Limit"; the `unique_id` is unchanged, so existing entity IDs and
automations keep working.

### 7. The device's own current limit was never enforced

The protocol constrains holding 20 to "< DC Input Max Curr", which is holding
17 and varies per model — so it cannot live in a static allowlist. Holding 17
was not being read. It is now decoded, the slider maximum narrows to it, and
`run_command()` re-checks it so a service call that bypasses the UI is still
rejected.

### 8. Parsing was locked to one exact response length

`parse_registers` required `len(registers) == 81` for full decoding and
otherwise fell back to SOC-only. Since the read count comes from the API
(`productInfo.modbus_count`), any device reporting something other than 80
would have silently lost every sensor but SOC.

Decoding is now index-driven: each field is read if the response is long enough
to contain it. A short response yields everything it does carry, and the
trailing CRC word is simply never indexed. The read count from the API is also
clamped to the protocol's 100-word maximum.

### 9. Unknown-topic responses were decoded inconsistently

The old length-based fallback meant an unrecognised topic yielded `{}` at full
length but a SOC value at partial length. The same register number means
different things in the holding and input groups, so a response whose group is
unknown cannot be decoded safely either way — it now returns nothing in both
cases.

### 10. The test suite mirrored the entity tables by hand

`tests/test_entity_definitions.py` contained copies of the definition dicts
because the platform modules import Home Assistant. The copies had drifted, so
the coverage tests were passing against stale data.

`conftest.py` now installs Home Assistant / paho / aiohttp stubs (as real
classes, since the platform modules subclass them) and the tests import the
live tables. Two genuine gaps surfaced immediately: the LED on/off state bit
had lost its entity in the LED-select rework, and the serial-number decoder was
never exercised.

---

## Features added

Registers that were documented, already arriving in every poll, and being
thrown away.

### Measurements — `sensor`

| Register | Entity |
|----------|--------|
| input 03 | AC Input power |
| input 05 | USB-C Input power |
| input 08/09/10 | XT60 / cigarette / 5521 port power |
| input 13 | Wireless charging power |
| input 15 | LED power |
| input 16/17 | Inverter output power / apparent power |
| input 20 | AC output power |
| input 26-28 | USB 1-3 power |
| input 30-32 | QC 1-3 power |
| input 34-38 | PD 1-5 power |
| input 54 | Battery usable capacity (Ah) |
| input 57/58/59 | Charge schedule remaining, remaining charge / discharge time |
| input 60 | PV lifetime energy — `TOTAL_INCREASING`, so it feeds the HA energy dashboard |
| input 66/67 | Slave battery 3 and 4 SOC |
| input 70/71 | Average discharge / charge SOC |
| holding 14/16/17/18/19 | AC charge max power, DC input max power / current / voltage window |
| holding 40/41 | Battery chemistry, capacity, cell topology |
| holding 5 | Protocol version |

Input register 60 carries a `+1` offset so that 0 can mean "no counter
fitted"; the decoder removes it, so the sensor is a true lifetime total rather
than being 100 Wh high forever.

Per-port breakdowns are created disabled — they are there when you need to
diagnose one socket, without adding two dozen mostly-zero entities.

### State — `binary_sensor` (new platform)

Grid / DC / PV / car charging and input presence, on-grid vs off-grid, AC
inverter output, DC port output, wireless charging, ECO mode, all individual
USB / QC / PD / 12 V ports, BMS charge and discharge MOSFET state, charging /
discharging / full / balancing, and the aggregate fault sensor.

### Controls

| Register | Entity | Type |
|----------|--------|------|
| holding 13 | AC Charging Rate (levels 1-5) | select — was read-only before |
| holding 15 | DC Input Type (MPPT / DC source) | select |
| holding 54 | Wi-Fi Upload Interval | number |
| holding 56 | Buzzer | switch |
| holding 64 | App Remote Shutdown | switch |
| holding 69 | Low Battery Notification + threshold | switch + number |
| holding 70 | Grid Mode AC Auto Output | switch |

Holding 69 packs two independent 8-bit settings into one word. The protocol's
convention is to write `0xFF` into the half that should stay unchanged, which
is exactly how the enable switch and the threshold slider write it, so setting
one never clobbers the other.

### Device identity

Holding 11 (market type + model code), 47-51 (AC / BMS / PV / Panel / Com
board versions) and 72-79 (serial number, two ASCII characters per register)
now populate the HA device registry, so a device page shows real model,
firmware and serial number rather than just a MAC address.

### Registers deliberately left unwritable

`INTENTIONALLY_NOT_WRITABLE` records these with reasons, so the decision is
visible and testable rather than an accident of omission:

| Register | Reason |
|----------|--------|
| holding 0 | Factory reset (device and wireless module) — destructive |
| holding 1 | Debug / version query mode — vendor diagnostics |
| holding 2 | Chip type selector — vendor diagnostics |
| holding 3 | Debug variable address — vendor diagnostics |
| holding 4 | Timezone — the document gives no encoding for the offset field |

---

## Deviations from the document

Two places where the shipped allowlist is not a literal copy of the spec:

1. **Holding 62 (screen dim time)** — documented `1~5000`, but 0 is allowed
   because the vendor app itself offers an "off" option for this setting,
   which is evidence the firmware accepts it. Same reasoning applies to 0 on
   holding 63 and 68, which the document also starts at 1.
2. **Holding 54 (Wi-Fi upload interval)** — the document gives the unit (1 s)
   but no range. Bounded to 5 s..1 h, comfortably inside any plausible
   firmware limit.

---

## Not implemented

### Balcony grid-tie inverters (protocol V1 / V2)

A different device class that reuses the same register numbers for entirely
different meanings — holding 41 is `Battery Pack Frame` in V0 and
`Grid Charge time 2` in V2. Supporting both needs a protocol-version-selected
register profile, keyed on holding 7 (`L4:Protocol Version`) for V1/V2 versus
holding 5 for V0.

What a V2 profile would add: 3 custom + 3 AI grid-charge windows, 12 grid-tie
discharge windows with per-window power and day-of-week masks, immediate
force-charge / force-export, load-following (anti-backflow) and PV
self-consumption modes, up to 8 smart sockets and a 3-phase smart meter with
per-socket and per-phase power and energy, lifetime battery charge/discharge
and household-load energy counters, SOH, battery temperatures, negative
electricity price windows, and charge-priority mode.

Holding register 5 is decoded and exposed as a "Protocol Version" diagnostic
sensor so a mismatched device can be identified from the HA UI.

### Firmware upload (function `0x26`)

Fully documented, including the segmentation rules (192 bytes/frame for
`DSP_AC`, 200 otherwise; skip the first 16 KB for `AC` firmware, 10 KB
otherwise; 20 KB for DSP157; drop the last 16 KB for DSP28034), the
`packNum`-echo handshake and the 7 s / 6-retry timeout policy.

Not implemented deliberately: a botched flash bricks hardware, the process
needs vendor firmware images this integration has no source for, and Home
Assistant is the wrong place to run it. Use the BrightEMS app.

### Other unimplemented documented surfaces

- **Function 7 (Wi-Fi provisioning)** — belongs to onboarding, which happens
  in the app.
- **Smart socket / meter protocol** (addresses 100-113, functions 100/101/102/105)
  — V1/V2 accessories.
- **Chart requests** (input addresses 10001+, 288-point series) — V2 only, and
  the document notes they are MQTT-only because of the Bluetooth MTU.
- **HTTP endpoints** `emqx.pub_5min` / `emqx.pub_device` — these are how the
  *device* pushes to the vendor cloud, not something a client calls.

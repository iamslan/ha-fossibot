"""V0 register decoding for Fossibot / Sydpower portable power stations.

Every mapping in this module is traceable to the Sydpower "Modbus RTU
Protocol" document (``Inverter-Protocol-V0.docx``, revision V1.7, 2024-06-01).
Section references are given per block so a reader can check the source.

Scope note: the same folder also documents the balcony grid-tie inverter
(``Inverter-Protocol-V1/V2.docx``), which uses a *different* register map at
the same addresses. This module decodes V0 only. Holding register 5
(``HREG_PROTOCOL_VERSION``) is surfaced as a diagnostic so a mis-matched
device can be spotted.
"""

from typing import Any, Dict, List, Optional, Tuple

from .const import (
    BATTERY_TYPES, DC_INPUT_TYPES, DEVICE_MARKET_TYPES, FREQ_TYPES,
    LIGHT_MODES, VOLTAGE_TYPE_BITS, WIRELESS_COM_BITS,
    HREG_AC_CHARGE_LEVEL, HREG_AC_CHARGE_MAX_POWER,
    HREG_AC_CHARGE_APPOINTMENT, HREG_AC_SLEEP_TIME, HREG_APP_CONTROL_SLEEP,
    HREG_BATTERY_INFO, HREG_BATTERY_PACK_FRAME, HREG_BUZZER,
    HREG_CHARGE_SOC_MAX, HREG_DC_INPUT_CURRENT_SET, HREG_DC_INPUT_MAX_CURRENT,
    HREG_DC_INPUT_MAX_POWER, HREG_DC_INPUT_MAX_VOLTAGE,
    HREG_DC_INPUT_MIN_VOLTAGE, HREG_DC_INPUT_TYPE, HREG_DC_SLEEP_TIME,
    HREG_DEVICE_TYPE_MODEL, HREG_DISCHARGE_SOC_MIN, HREG_GRID_AC_AUTO_OUTPUT,
    HREG_LCD_DIM_TIME, HREG_LOW_BATTERY_NOTIFY, HREG_PROTOCOL_VERSION,
    HREG_SERIAL_FIRST, HREG_SERIAL_LAST, HREG_SHUTDOWN_WAIT_TIME,
    HREG_SILENT_CHARGING, HREG_USB_SLEEP_TIME, HREG_VERSION_AC,
    HREG_VERSION_BMS, HREG_VERSION_EXTERNAL_COM, HREG_VERSION_PANEL,
    HREG_VERSION_PV, HREG_VOLTAGE_FREQ_TYPE, HREG_WIFI_UPLOAD_INTERVAL,
    HREG_WIRELESS_COM,
    IREG_5521_POWER, IREG_AC_CHARGE_LEVEL, IREG_AC_CHARGE_POWER,
    IREG_AC_OUTPUT_FREQUENCY, IREG_AC_OUTPUT_POWER, IREG_AC_OUTPUT_VOLTAGE,
    IREG_BATTERY_SOC, IREG_BATTERY_USABLE_CAPACITY, IREG_BMS_AFE_STATUS,
    IREG_BMS_USER_STATUS, IREG_CHARGE_APPOINTMENT_REMAINING,
    IREG_CHARGE_SOC_AVG, IREG_CIGARETTE_POWER, IREG_DC_CHARGE_POWER,
    IREG_DISCHARGE_SOC_AVG, IREG_FAULT_AC, IREG_FAULT_AC_2,
    IREG_FAULT_HIGH_PV, IREG_FAULT_PANEL_H, IREG_FAULT_PANEL_L, IREG_FAULT_PV,
    IREG_GRID_FREQUENCY, IREG_GRID_VOLTAGE, IREG_INV_OUTPUT_POWER,
    IREG_INV_OUTPUT_VA, IREG_LED_POWER, IREG_LIGHT_MODE, IREG_PD1_POWER,
    IREG_PD2_POWER, IREG_PD3_POWER, IREG_PD4_POWER, IREG_PD5_POWER,
    IREG_PV_ENERGY_TOTAL, IREG_QC1_POWER, IREG_QC2_POWER, IREG_QC3_POWER,
    IREG_REMAINING_CHARGE_TIME, IREG_REMAINING_DISCHARGE_TIME,
    IREG_SLAVE_BATTERY_1, IREG_SLAVE_BATTERY_2, IREG_SLAVE_BATTERY_3,
    IREG_SLAVE_BATTERY_4, IREG_STORAGE_FLAG, IREG_SYSTEM_STATE_H,
    IREG_SYSTEM_STATE_L, IREG_TOTAL_CHARGE_POWER, IREG_TOTAL_DISCHARGE_POWER,
    IREG_TYPEC_CHARGE_POWER, IREG_USB1_POWER, IREG_USB2_POWER,
    IREG_USB3_POWER, IREG_WIRELESS_POWER, IREG_XT60_POWER,
)

# ---------------------------------------------------------------------------
# System state — appendix &*8
#
# Input registers 41 and 42 together form one 32-bit field: register 41 holds
# bits 31..16 ("System State H") and register 42 bits 15..0 ("System State L").
# The integration previously read register 41 alone, which left every bit
# below 16 — the whole port-state half — unreachable.
#
# Keys are the documented bit numbers of the combined 32-bit value.
# ---------------------------------------------------------------------------

SYSTEM_STATE_BITS: Dict[int, str] = {
    31: "pvHighVoltageCharging",
    30: "pvHighVoltagePresent",
    29: "carCharging",
    28: "ledOutput",
    27: "acOutput",
    26: "dcOutput",
    25: "usbOutput",
    24: "carChargeVoltagePresent",
    23: "dcPortOutput",
    22: "dcCharging",
    21: "dcChargeVoltagePresent",
    20: "gridCharging",
    19: "gridVoltagePresent",
    18: "acInverterOutput",
    17: "gridConnected",
    16: "wirelessCharging",
    15: "port5521Output",
    14: "portCigaretteOutput",
    13: "portXt60Output",
    12: "ecoMode",
    10: "pd5Output",
    9: "pd4Output",
    8: "pd3Output",
    7: "pd2Output",
    6: "pd1Output",
    4: "qc2Output",
    3: "qc1Output",
    1: "usb2Output",
    0: "usb1Output",
}

# ---------------------------------------------------------------------------
# Fault / status bitfields
#
# Each entry maps a bit number to a human-readable fault name. Bits the
# protocol marks "do not parse" are deliberately absent: for the BMS words
# those bits carry normal operating state (MOSFET on, charging, balancing),
# not faults, and reporting them as faults would produce constant false alarms.
# ---------------------------------------------------------------------------

# Appendix &*9 — input register 43
FAULT_AC_BITS: Dict[int, str] = {
    15: "Temperature fault",
    14: "Battery voltage abnormal",
    13: "System fault",
    12: "Relay fault",
    11: "Grid voltage abnormal (240V)",
    10: "Grid frequency abnormal (240V)",
    9: "Grid voltage abnormal (120V)",
    8: "Grid frequency abnormal (120V)",
    7: "UPS short circuit (phase A)",
    6: "Off-grid output overcurrent (phase A)",
    5: "Off-grid output voltage abnormal (phase A)",
    4: "Overload level 3 (phase A)",
    3: "Overload level 2 (phase A)",
    2: "Overload level 1 (phase A)",
    1: "BUS overvoltage",
    0: "Output short circuit (phase A)",
}

# Appendix &*9 — input register 44 ("AC Fault code_2")
FAULT_AC2_BITS: Dict[int, str] = {
    8: "Current sensor fault",
    6: "Off-grid output overcurrent (phase B)",
    5: "UPS short circuit (phase B)",
    4: "Off-grid output voltage abnormal (phase B)",
    3: "Overload level 3 (phase B)",
    2: "Overload level 2 (phase B)",
    1: "Overload level 1 (phase B)",
    0: "Output short circuit (phase B)",
}

# Appendix &*10 — input register 45
FAULT_PV_BITS: Dict[int, str] = {
    5: "Battery overvoltage",
    4: "DC 12V channel 3 overcurrent",
    3: "DC 12V channel 1/2 overcurrent",
    2: "DC input overcurrent",
    1: "DC input overvoltage",
    0: "PV board temperature abnormal",
}

# Appendix &*9 — input register 46 ("HighPVFaultFlag")
FAULT_HIGH_PV_BITS: Dict[int, str] = {
    3: "High-voltage PV overpower",
    2: "High-voltage PV short circuit",
    1: "BUS overvoltage",
    0: "High-voltage PV input overvoltage",
}

# Appendix &*11 — input register 47. Bits 15, 14, 13, 12, 6 and 0 are marked
# "do not parse" in the protocol and are omitted.
FAULT_BMS_AFE_BITS: Dict[int, str] = {
    11: "AFE discharge over-temperature",
    10: "AFE discharge under-temperature",
    9: "AFE charge over-temperature",
    8: "AFE charge under-temperature",
    5: "AFE output short circuit",
    4: "AFE charge overcurrent",
    3: "AFE discharge overcurrent (level 2)",
    2: "AFE discharge overcurrent (level 1)",
    1: "AFE cell undervoltage",
}

# Appendix &*12 — input register 48. Bits 15..12, 9, 8, 7 and 6 are marked
# "do not parse" (they report charging/discharging/balancing state).
FAULT_BMS_USER_BITS: Dict[int, str] = {
    5: "AFE fault",
    4: "Battery MOSFET over-temperature",
    3: "Battery charge under-temperature",
    2: "Battery charge over-temperature",
    1: "Battery discharge under-temperature",
    0: "Battery discharge over-temperature",
}

# Appendix &*13 — input registers 50 (bits 31..16) and 51 (bits 15..0),
# combined into one 32-bit value. Keys are bit numbers of the combined value.
FAULT_PANEL_BITS: Dict[int, str] = {
    21: "PD4 output overcurrent",
    20: "PD3 output overcurrent",
    18: "Wireless charging fault",
    17: "PD2 output overcurrent",
    16: "PD1 output overcurrent",
    7: "Panel board temperature abnormal",
    4: "DC 24V output overcurrent",
    3: "DC 12V output overcurrent",
    2: "QC2 output overcurrent",
    1: "QC1 output overcurrent",
    0: "USB1 output overcurrent",
}

# Informational BMS state bits — the ones the protocol says not to treat as
# faults. Exposed as attributes on the battery-status sensor instead.
BMS_AFE_STATE_BITS: Dict[int, str] = {
    14: "prechargeMosfetOn",
    13: "chargeMosfetOn",
    12: "dischargeMosfetOn",
}

BMS_USER_STATE_BITS: Dict[int, str] = {
    15: "charging",
    14: "discharging",
    13: "fullyDischarged",
    12: "fullyCharged",
    7: "batteryOvervoltage",
    6: "balancing",
}


# ---------------------------------------------------------------------------
# Primitive decoders
# ---------------------------------------------------------------------------

def high_byte(value: int) -> int:
    """Return the high byte of a 16-bit register."""
    return (value >> 8) & 0xFF


def low_byte(value: int) -> int:
    """Return the low byte of a 16-bit register."""
    return value & 0xFF


def combine_words(high: int, low: int) -> int:
    """Combine two 16-bit registers into one 32-bit value, high word first."""
    return ((high & 0xFFFF) << 16) | (low & 0xFFFF)


def decode_bits(value: int, table: Dict[int, str]) -> List[str]:
    """Return the labels of every set bit in ``value`` that ``table`` names."""
    return [name for bit, name in sorted(table.items(), reverse=True)
            if value & (1 << bit)]


def decode_frequency(raw: int) -> float:
    """Decode a frequency register, tolerating both documented scalings.

    The protocol gives 0.1 Hz for both the AC output (input 19) and the grid
    (input 22), but the app this integration was originally reverse-engineered
    from scaled the grid register by 1/100. Mains frequency is always near
    50 Hz or 60 Hz, so the two encodings cannot be confused: 0.1 Hz yields
    ~500-600 and 0.01 Hz yields ~5000-6000. Pick the scale from the magnitude
    rather than committing to one and being wrong on half the fleet.
    """
    if raw >= 1000:
        return round(raw / 100, 2)
    return round(raw / 10, 2)


def decode_soc_permille(raw: int) -> float:
    """Decode a 0.1%-per-count SOC register into whole percent."""
    return round(raw / 10, 1)


def decode_slave_soc(raw: int) -> Optional[float]:
    """Decode a slave-battery SOC register (input 53/55/66/67).

    The protocol encodes these as ``SOC + 10`` over a 10..1010 range in units
    of 0.1%, with 0 meaning "no battery pack connected".
    """
    if raw <= 0:
        return None
    return round((raw - 10) / 10, 1)


def decode_version(raw: int) -> Optional[Tuple[int, int]]:
    """Split a board version register into ``(hardware, software)``.

    The protocol packs two independent version numbers into one word
    (``H8:HardWare L8:SoftWare``). They are kept separate rather than joined
    with a dot, because "1.20" would read as a single dotted version the
    device does not actually report.
    """
    if raw == 0:
        return None
    return high_byte(raw), low_byte(raw)


def decode_serial(registers: List[int]) -> Optional[str]:
    """Decode the serial number from holding registers 72..79.

    Each register carries two characters, most significant first ("SN 16 SN
    15" down to "SN 2 SN 1"). Non-printable bytes are treated as padding.

    Note on ordering: the document lists the bytes as SN 16 down to SN 1, and
    that is also the order they arrive in, so they are read lowest register
    first. If a device ever reports a serial that reads backwards against the
    label on its case, reverse ``chars`` here — the numbering in the document
    is descending and does not by itself say which end of the string SN 16 is.
    """
    if len(registers) <= HREG_SERIAL_LAST:
        return None

    chars = []
    for idx in range(HREG_SERIAL_FIRST, HREG_SERIAL_LAST + 1):
        for byte in (high_byte(registers[idx]), low_byte(registers[idx])):
            if 0x20 <= byte <= 0x7E:
                chars.append(chr(byte))
            elif byte != 0:
                # A non-ASCII byte means this is not a text serial number.
                return None

    serial = "".join(chars).strip()
    return serial or None


def _flag_names(bits: Dict[int, str], value: int) -> Dict[str, bool]:
    """Expand a bitfield into a ``{name: bool}`` mapping."""
    return {name: bool(value & (1 << bit)) for bit, name in bits.items()}


# ---------------------------------------------------------------------------
# Holding registers (function 03) — settings and identity
# ---------------------------------------------------------------------------

def decode_holding_registers(registers: List[int]) -> Dict[str, Any]:
    """Decode a holding-register (function 03) response.

    Only registers actually present in ``registers`` are decoded, so a short
    response degrades gracefully instead of being discarded.
    """
    out: Dict[str, Any] = {}

    def reg(index: int) -> Optional[int]:
        return registers[index] if index < len(registers) else None

    # --- Controls the integration can write back -------------------------
    _set(out, "acChargingRate", reg(HREG_AC_CHARGE_LEVEL))
    _set(out, "maximumChargingCurrent",
         _map(reg(HREG_DC_INPUT_CURRENT_SET), low_byte))
    _set(out, "acSilentCharging", _map(reg(HREG_SILENT_CHARGING),
                                       lambda v: low_byte(v) == 1))
    _set(out, "buzzerEnabled", _map(reg(HREG_BUZZER),
                                    lambda v: low_byte(v) == 1))
    _set(out, "appControlSleep", _map(reg(HREG_APP_CONTROL_SLEEP),
                                      lambda v: low_byte(v) == 1))
    _set(out, "gridAcAutoOutput", _map(reg(HREG_GRID_AC_AUTO_OUTPUT),
                                       lambda v: v == 1))
    _set(out, "usbStandbyTime", reg(HREG_USB_SLEEP_TIME))
    _set(out, "acStandbyTime", reg(HREG_AC_SLEEP_TIME))
    _set(out, "dcStandbyTime", reg(HREG_DC_SLEEP_TIME))
    _set(out, "screenRestTime", reg(HREG_LCD_DIM_TIME))
    _set(out, "stopChargeAfter", reg(HREG_AC_CHARGE_APPOINTMENT))
    _set(out, "wholeMachineUnusedTime", reg(HREG_SHUTDOWN_WAIT_TIME))
    _set(out, "wifiUploadInterval", reg(HREG_WIFI_UPLOAD_INTERVAL))
    _set(out, "dischargeLowerLimit",
         _map(reg(HREG_DISCHARGE_SOC_MIN), decode_soc_permille))
    _set(out, "acChargingUpperLimit",
         _map(reg(HREG_CHARGE_SOC_MAX), decode_soc_permille))

    dc_input_type = reg(HREG_DC_INPUT_TYPE)
    if dc_input_type is not None:
        code = low_byte(dc_input_type)
        out["dcInputType"] = DC_INPUT_TYPES.get(code, "Unknown (%d)" % code)
        out["dcInputTypeRaw"] = code

    # Register 69 packs the enable flag and the threshold into one word.
    low_battery = reg(HREG_LOW_BATTERY_NOTIFY)
    if low_battery is not None:
        enable = high_byte(low_battery)
        threshold = low_byte(low_battery)
        if enable != 0xFF:
            out["lowBatteryNotifyEnabled"] = enable == 1
        if threshold != 0xFF:
            out["lowBatteryNotifyThreshold"] = threshold

    # --- Static capability / identity data -------------------------------
    _set(out, "acChargeMaxPower", reg(HREG_AC_CHARGE_MAX_POWER))
    _set(out, "dcInputMaxPower", reg(HREG_DC_INPUT_MAX_POWER))
    _set(out, "dcInputMaxCurrent",
         _map(reg(HREG_DC_INPUT_MAX_CURRENT), low_byte))
    _set(out, "dcInputMinVoltage",
         _map(reg(HREG_DC_INPUT_MIN_VOLTAGE), lambda v: round(v / 10, 1)))
    _set(out, "dcInputMaxVoltage",
         _map(reg(HREG_DC_INPUT_MAX_VOLTAGE), lambda v: round(v / 10, 1)))
    _set(out, "protocolVersion",
         _map(reg(HREG_PROTOCOL_VERSION), lambda v: v & 0x0F))

    device_type = reg(HREG_DEVICE_TYPE_MODEL)
    if device_type:
        market = high_byte(device_type)
        out["deviceMarketType"] = DEVICE_MARKET_TYPES.get(
            market, "Unknown (%d)" % market
        )
        out["deviceModelCode"] = "%03d" % low_byte(device_type)

    voltage_freq = reg(HREG_VOLTAGE_FREQ_TYPE)
    if voltage_freq:
        voltages = [
            label for bit, label in sorted(VOLTAGE_TYPE_BITS.items(),
                                           reverse=True)
            if voltage_freq & (1 << bit)
        ]
        if voltages:
            out["deviceVoltageType"] = ", ".join(voltages)
        freq_code = voltage_freq & 0x07
        if freq_code in FREQ_TYPES:
            out["deviceFrequencyType"] = FREQ_TYPES[freq_code]

    battery_info = reg(HREG_BATTERY_INFO)
    if battery_info:
        chemistry = high_byte(battery_info)
        out["batteryChemistry"] = BATTERY_TYPES.get(
            chemistry, "Unknown (%d)" % chemistry
        )
        out["batteryCapacityAh"] = low_byte(battery_info)

    pack_frame = reg(HREG_BATTERY_PACK_FRAME)
    if pack_frame:
        out["batteryCellsSeries"] = high_byte(pack_frame)
        out["batteryCellsParallel"] = low_byte(pack_frame)

    wireless_com = reg(HREG_WIRELESS_COM)
    if wireless_com:
        radios = [
            label for bit, label in sorted(WIRELESS_COM_BITS.items(),
                                           reverse=True)
            if wireless_com & (1 << bit)
        ]
        if radios:
            out["wirelessModules"] = ", ".join(radios)

    for key, index in (
        ("versionAc", HREG_VERSION_AC),
        ("versionBms", HREG_VERSION_BMS),
        ("versionPv", HREG_VERSION_PV),
        ("versionPanel", HREG_VERSION_PANEL),
        ("versionExternalCom", HREG_VERSION_EXTERNAL_COM),
    ):
        version = _map(reg(index), decode_version)
        if version is not None:
            out["%sHardware" % key] = version[0]
            out["%sSoftware" % key] = version[1]

    _set(out, "serialNumber", decode_serial(registers))

    return out


# ---------------------------------------------------------------------------
# Input registers (function 04) — live measurements
# ---------------------------------------------------------------------------

# (key, register index, scale) for the plain scalar measurements.
_INPUT_SCALARS: Tuple[Tuple[str, int, float], ...] = (
    ("acChargeLevelActive", IREG_AC_CHARGE_LEVEL, 1),
    ("acInput", IREG_AC_CHARGE_POWER, 1),
    ("dcInput", IREG_DC_CHARGE_POWER, 1),
    ("typecInput", IREG_TYPEC_CHARGE_POWER, 1),
    ("totalInput", IREG_TOTAL_CHARGE_POWER, 1),
    ("xt60Power", IREG_XT60_POWER, 0.1),
    ("cigarettePower", IREG_CIGARETTE_POWER, 0.1),
    ("port5521Power", IREG_5521_POWER, 0.1),
    ("wirelessChargingPower", IREG_WIRELESS_POWER, 0.1),
    ("ledPower", IREG_LED_POWER, 1),
    ("inverterOutputPower", IREG_INV_OUTPUT_POWER, 1),
    ("inverterOutputApparentPower", IREG_INV_OUTPUT_VA, 1),
    ("acOutputPower", IREG_AC_OUTPUT_POWER, 1),
    ("usb1Power", IREG_USB1_POWER, 0.1),
    ("usb2Power", IREG_USB2_POWER, 0.1),
    ("usb3Power", IREG_USB3_POWER, 0.1),
    ("qc1Power", IREG_QC1_POWER, 0.1),
    ("qc2Power", IREG_QC2_POWER, 0.1),
    ("qc3Power", IREG_QC3_POWER, 0.1),
    ("pd1Power", IREG_PD1_POWER, 0.1),
    ("pd2Power", IREG_PD2_POWER, 0.1),
    ("pd3Power", IREG_PD3_POWER, 0.1),
    ("pd4Power", IREG_PD4_POWER, 0.1),
    ("pd5Power", IREG_PD5_POWER, 0.1),
    ("totalOutput", IREG_TOTAL_DISCHARGE_POWER, 1),
    ("batteryUsableCapacity", IREG_BATTERY_USABLE_CAPACITY, 1),
    ("chargeAppointmentRemaining", IREG_CHARGE_APPOINTMENT_REMAINING, 1),
    ("remainingChargeTime", IREG_REMAINING_CHARGE_TIME, 1),
    ("remainingDischargeTime", IREG_REMAINING_DISCHARGE_TIME, 1),
    ("averageDischargeSoc", IREG_DISCHARGE_SOC_AVG, 1),
    ("averageChargeSoc", IREG_CHARGE_SOC_AVG, 1),
)

_SLAVE_SOC_REGISTERS: Tuple[Tuple[str, int], ...] = (
    ("soc_s1", IREG_SLAVE_BATTERY_1),
    ("soc_s2", IREG_SLAVE_BATTERY_2),
    ("soc_s3", IREG_SLAVE_BATTERY_3),
    ("soc_s4", IREG_SLAVE_BATTERY_4),
)


def decode_input_registers(registers: List[int]) -> Dict[str, Any]:
    """Decode an input-register (function 04) response."""
    out: Dict[str, Any] = {}

    def reg(index: int) -> Optional[int]:
        return registers[index] if index < len(registers) else None

    for key, index, scale in _INPUT_SCALARS:
        raw = reg(index)
        if raw is None:
            continue
        out[key] = raw if scale == 1 else round(raw * scale, 1)

    _set(out, "soc", _map(reg(IREG_BATTERY_SOC), decode_soc_permille))
    for key, index in _SLAVE_SOC_REGISTERS:
        raw = reg(index)
        if raw is None:
            continue
        value = decode_slave_soc(raw)
        if value is not None:
            out[key] = value

    _set(out, "acOutputVoltage",
         _map(reg(IREG_AC_OUTPUT_VOLTAGE), lambda v: round(v / 10, 1)))
    _set(out, "acOutputFrequency",
         _map(reg(IREG_AC_OUTPUT_FREQUENCY), decode_frequency))
    _set(out, "acInputVoltage",
         _map(reg(IREG_GRID_VOLTAGE), lambda v: round(v / 10, 1)))
    _set(out, "acInputFrequency",
         _map(reg(IREG_GRID_FREQUENCY), decode_frequency))

    _set(out, "storageFlag", _map(reg(IREG_STORAGE_FLAG),
                                  lambda v: low_byte(v) == 1))

    light_mode = reg(IREG_LIGHT_MODE)
    if light_mode is not None:
        code = low_byte(light_mode)
        out["lightModeRaw"] = code
        out["lightMode"] = LIGHT_MODES.get(code, "Unknown (%d)" % code)

    # PV lifetime energy: the register is offset by one so that 0 can mean
    # "this device has no PV energy counter" (protocol note on input 60:
    # "1~(65500-1), 0: no accumulation function ... upload N+1").
    pv_energy = reg(IREG_PV_ENERGY_TOTAL)
    if pv_energy:
        out["pvEnergyTotal"] = round((pv_energy - 1) * 100 / 1000, 1)

    out.update(_decode_system_state(reg(IREG_SYSTEM_STATE_H),
                                    reg(IREG_SYSTEM_STATE_L)))
    out.update(_decode_faults(registers))

    return out


def _decode_system_state(
    state_high: Optional[int], state_low: Optional[int]
) -> Dict[str, Any]:
    """Decode the 32-bit system-state field (input registers 41 + 42)."""
    if state_high is None:
        return {}

    # A device that does not populate "System State L" simply reports zero
    # there; the low-half flags then read as off, which is the safe default.
    combined = combine_words(state_high, state_low or 0)

    out: Dict[str, Any] = _flag_names(SYSTEM_STATE_BITS, combined)
    out["systemStateRaw"] = combined
    return out


def _decode_faults(registers: List[int]) -> Dict[str, Any]:
    """Decode every fault/status word into named fault lists."""

    def reg(index: int) -> int:
        return registers[index] if index < len(registers) else 0

    ac_faults = (decode_bits(reg(IREG_FAULT_AC), FAULT_AC_BITS)
                 + decode_bits(reg(IREG_FAULT_AC_2), FAULT_AC2_BITS))
    pv_faults = (decode_bits(reg(IREG_FAULT_PV), FAULT_PV_BITS)
                 + decode_bits(reg(IREG_FAULT_HIGH_PV), FAULT_HIGH_PV_BITS))
    bms_faults = (decode_bits(reg(IREG_BMS_AFE_STATUS), FAULT_BMS_AFE_BITS)
                  + decode_bits(reg(IREG_BMS_USER_STATUS),
                                FAULT_BMS_USER_BITS))
    panel_faults = decode_bits(
        combine_words(reg(IREG_FAULT_PANEL_H), reg(IREG_FAULT_PANEL_L)),
        FAULT_PANEL_BITS,
    )

    all_faults = ac_faults + pv_faults + bms_faults + panel_faults

    out: Dict[str, Any] = {
        "faultsAc": ac_faults,
        "faultsPv": pv_faults,
        "faultsBms": bms_faults,
        "faultsPanel": panel_faults,
        "faults": all_faults,
        "faultCount": len(all_faults),
        "hasFault": bool(all_faults),
    }

    out.update(_flag_names(BMS_AFE_STATE_BITS, reg(IREG_BMS_AFE_STATUS)))
    out.update(_flag_names(BMS_USER_STATE_BITS, reg(IREG_BMS_USER_STATUS)))

    return out


# ---------------------------------------------------------------------------
# Small helpers used by the decoders above
# ---------------------------------------------------------------------------

def _set(target: Dict[str, Any], key: str, value: Any) -> None:
    """Assign ``key`` only when a value was actually decoded."""
    if value is not None:
        target[key] = value


def _map(value: Optional[int], fn) -> Any:
    """Apply ``fn`` to ``value`` unless it is missing."""
    return None if value is None else fn(value)

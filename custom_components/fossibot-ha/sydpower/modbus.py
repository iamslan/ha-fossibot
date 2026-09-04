# modbus.py
"""Modbus command conversion functions for Fossibot devices.

SAFETY NOTE: Fossibot firmware does NOT validate register write values.
Writing an out-of-range value can permanently brick a device.  Every write
MUST go through ``get_write_modbus()``, which validates against the
WRITABLE_REGISTERS allowlist before encoding.

Allowed ranges are taken from the Sydpower "Modbus RTU Protocol" document
(``Inverter-Protocol-V0.docx``) section 3.1. Where that document gives an
explicit range, the allowlist matches it exactly; the few deviations are
called out in comments with the reason.
"""

from typing import Dict, FrozenSet, List, Union

# Several register constants below are re-exported rather than used directly:
# scripts/ and external tooling import them from this module, so they are kept
# in the namespace even though this file does not reference them all.
from .const import (
    MODBUS_READ_COUNT,
    REGISTER_MODBUS_ADDRESS, REGISTER_TOTAL_INPUT, REGISTER_DC_INPUT,
    REGISTER_MAXIMUM_CHARGING_CURRENT, REGISTER_USB_OUTPUT, REGISTER_DC_OUTPUT,
    REGISTER_AC_OUTPUT, REGISTER_LED, REGISTER_TOTAL_OUTPUT,
    REGISTER_ACTIVE_OUTPUT_LIST, REGISTER_STATE_OF_CHARGE,
    REGISTER_AC_SILENT_CHARGING, REGISTER_USB_STANDBY_TIME,
    REGISTER_AC_STANDBY_TIME, REGISTER_DC_STANDBY_TIME,
    REGISTER_SCREEN_REST_TIME, REGISTER_STOP_CHARGE_AFTER,
    REGISTER_DISCHARGE_LIMIT, REGISTER_CHARGING_LIMIT, REGISTER_SLEEP_TIME,
    HREG_AC_CHARGE_LEVEL, HREG_APP_CONTROL_SLEEP, HREG_BUZZER,
    HREG_DC_INPUT_TYPE, HREG_GRID_AC_AUTO_OUTPUT, HREG_LOW_BATTERY_NOTIFY,
    HREG_WIFI_UPLOAD_INTERVAL,
)
from .registers import decode_holding_registers, decode_input_registers


# ---------------------------------------------------------------------------
# Writable-register safety map
#
# Each entry maps a register number to a frozenset of allowed integer values.
# ``get_write_modbus()`` refuses to encode a value that is not in this set.
# ---------------------------------------------------------------------------

# Register 69 packs two independent 8-bit settings into one word:
#   high byte = low-battery notification enable (0 or 1)
#   low byte  = notification threshold in percent (0..100)
# Writing 0xFF into either byte tells the device to leave that half alone,
# which is how a single 16-bit write can change one setting in isolation.
NOT_SET = 0xFF
_LOW_BATTERY_VALUES = frozenset(
    (enable << 8) | threshold
    for enable in (0, 1, NOT_SET)
    for threshold in list(range(0, 101)) + [NOT_SET]
)

WRITABLE_REGISTERS: Dict[int, FrozenSet[int]] = {
    # Holding 13 — AC charge power level. Protocol: "Range: 1-5".
    HREG_AC_CHARGE_LEVEL: frozenset(range(1, 6)),

    # Holding 15 — DC input type. Protocol: "0:MPPT 1:DC source".
    HREG_DC_INPUT_TYPE: frozenset({0, 1}),

    # Holding 20 — DC (PV / vehicle) charging current limit, 1 A per count.
    # The protocol constrains this to "< DC Input Max Curr" (holding 17)
    # rather than an absolute maximum, so the allowlist keeps a conservative
    # 20 A ceiling and the number entity narrows it further using the value
    # the device reports in holding 17.
    REGISTER_MAXIMUM_CHARGING_CURRENT: frozenset(range(1, 21)),

    # Holding 24/25/26 — USB / DC / AC output button state.
    REGISTER_USB_OUTPUT: frozenset({0, 1}),
    REGISTER_DC_OUTPUT: frozenset({0, 1}),
    REGISTER_AC_OUTPUT: frozenset({0, 1}),

    # Holding 27 — LED button. Modes per input register 25:
    # 0=Off, 1=steady, 2=SOS, 3=strobe.
    REGISTER_LED: frozenset({0, 1, 2, 3}),

    # Holding 54 — Wi-Fi automatic upload interval, 1 s per count.
    # The protocol documents the unit but no range; bounded here to
    # 5 s..1 h, comfortably inside any plausible firmware limit.
    HREG_WIFI_UPLOAD_INTERVAL: frozenset(range(5, 3601)),

    # Holding 56 — buzzer enable. Protocol: "Range: 0 and 1".
    HREG_BUZZER: frozenset({0, 1}),

    # Holding 57 — silent charging mode. Protocol: "Range: 0 and 1".
    REGISTER_AC_SILENT_CHARGING: frozenset({0, 1}),

    # Holding 59/60/61 — no-load sleep timers, 1 min per count.
    # Protocol: "Range: 1~5000 (0:no sleep)".
    REGISTER_USB_STANDBY_TIME: frozenset(range(0, 5001)),
    REGISTER_AC_STANDBY_TIME: frozenset(range(0, 5001)),
    REGISTER_DC_STANDBY_TIME: frozenset(range(0, 5001)),

    # Holding 62 — screen dim time, 1 s per count. Protocol: "Range: 1~5000".
    # 0 is additionally allowed because the vendor app itself offers an "off"
    # option for this setting, which is evidence the firmware accepts it.
    REGISTER_SCREEN_REST_TIME: frozenset(range(0, 5001)),

    # Holding 63 — AC scheduled charging time, 1 min per count.
    # Protocol: "Range: 1~5000"; 0 disables the schedule.
    REGISTER_STOP_CHARGE_AFTER: frozenset(range(0, 5001)),

    # Holding 64 — app remote-shutdown function enable.
    HREG_APP_CONTROL_SLEEP: frozenset({0, 1}),

    # Holding 66 — minimum discharge SOC, 0.1% per count.
    # Protocol: "Range: 0~500", i.e. a 0-50% floor. Values above 500 are
    # refused; the integration previously allowed the full 0-100%.
    REGISTER_DISCHARGE_LIMIT: frozenset(range(0, 501)),

    # Holding 67 — maximum charge SOC in UPS mode, 0.1% per count.
    # Protocol: "Range: 600~1000", i.e. a 60-100% ceiling. Values below 600
    # are refused; the integration previously allowed the full 0-100%.
    REGISTER_CHARGING_LIMIT: frozenset(range(600, 1001)),

    # Holding 68 — whole-unit idle auto-shutdown, 1 min per count.
    # Protocol: "Range: 1~5000"; 0 disables auto-shutdown.
    REGISTER_SLEEP_TIME: frozenset(range(0, 5001)),

    # Holding 69 — low-battery notification enable + threshold.
    HREG_LOW_BATTERY_NOTIFY: _LOW_BATTERY_VALUES,

    # Holding 70 — automatically enable AC output in grid mode.
    HREG_GRID_AC_AUTO_OUTPUT: frozenset({0, 1}),
}

# Registers the protocol documents as writable but this integration refuses
# to touch, with the reason. Kept as data so the intent is testable and a
# future contributor does not "helpfully" add them back.
INTENTIONALLY_NOT_WRITABLE: Dict[int, str] = {
    0: "Factory reset (device and wireless module) — destructive",
    1: "Debug mode / version query mode — vendor diagnostics only",
    2: "Chip type selector — vendor diagnostics only",
    3: "Debug variable address — vendor diagnostics only",
    4: "Timezone — no documented encoding for the offset field",
}


class ModbusValidationError(ValueError):
    """Raised when a register write value is not in the allowed set."""


# ---------------------------------------------------------------------------
# Encoding helpers (names kept from original JS for traceability)
# ---------------------------------------------------------------------------

def int_to_high_low(value: int) -> Dict[str, int]:
    """Convert an integer to a high/low dictionary (16-bit)."""
    return {'low': value & 0xff, 'high': (value >> 8) & 0xff}


def high_low_to_int(high: int, low: int) -> int:
    """Convert high and low parts to a 16-bit integer."""
    return ((high & 0xff) << 8) | (low & 0xff)


def zi(e: int) -> Dict[str, int]:
    """Convert integer to high/low dict (alias for int_to_high_low)."""
    return {'low': e & 0xff, 'high': (e >> 8) & 0xff}


def ta(arr: List[int]) -> int:
    """CRC-16 checksum (Modbus variant)."""
    t = 0xffff
    for byte in arr:
        t ^= byte
        for _ in range(8):
            if t & 1:
                t = (t >> 1) ^ 40961
            else:
                t >>= 1
    return t & 0xffff


def sa(e: int, t: int, n: List[int], o: bool) -> List[int]:
    """Build the command array and append the checksum."""
    r = [e, t] + n
    cs = zi(ta(r))
    if o:
        r += [cs['low'], cs['high']]
    else:
        r += [cs['high'], cs['low']]
    return r


def aa(e: int, t: int, n: List[int], o: bool) -> List[int]:
    """Wrap getWriteModbus: convert feature number into two bytes and build command."""
    r = zi(t)
    return sa(e, 6, [r['high'], r['low']] + n, o)


def ia(e: int, t: int, n: int, o: bool) -> List[int]:
    """Wrap getReadModbus: prepare a read holding registers command (func 03)."""
    r = zi(t)
    i_val = n & 0xff
    a_val = n >> 8
    return sa(e, 3, [r['high'], r['low'], a_val, i_val], o)


def ia_input(e: int, t: int, n: int, o: bool) -> List[int]:
    """Wrap getReadInputModbus: read input registers command (func 04)."""
    r = zi(t)
    i_val = n & 0xff
    a_val = n >> 8
    return sa(e, 4, [r['high'], r['low'], a_val, i_val], o)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_write_modbus(address: int, feature: int, value: int) -> List[int]:
    """Encode a validated Modbus write command.

    Raises ModbusValidationError if the register is unknown or the value
    is not in the allowed set.
    """
    allowed = WRITABLE_REGISTERS.get(feature)
    if allowed is None:
        reason = INTENTIONALLY_NOT_WRITABLE.get(feature)
        if reason:
            raise ModbusValidationError(
                "Register %d is not in WRITABLE_REGISTERS — refusing to "
                "write: %s" % (feature, reason)
            )
        raise ModbusValidationError(
            "Register %d is not in WRITABLE_REGISTERS — refusing to write" % feature
        )
    if value not in allowed:
        raise ModbusValidationError(
            "Value %d is not allowed for register %d. Allowed: %s"
            % (value, feature, _format_allowed(allowed))
        )
    a = int_to_high_low(value)
    return aa(address, feature, [a['high'], a['low']], False)


def pack_byte_pair(high: int, low: int) -> int:
    """Pack two 8-bit settings into one register value.

    Several holding registers carry two independent 8-bit settings (for
    example register 69's notification enable and threshold). The protocol's
    convention is to write 0xFF into the half that should stay unchanged.
    """
    return ((high & 0xFF) << 8) | (low & 0xFF)


def get_read_modbus(address: int, count: int = MODBUS_READ_COUNT) -> List[int]:
    """Encode a Modbus read holding registers command (function code 03).

    Returns settings data on the ``client/data`` MQTT topic.
    """
    return ia(address, 0, count, False)


def get_read_input_modbus(
    address: int, count: int = MODBUS_READ_COUNT
) -> List[int]:
    """Encode a Modbus read input registers command (function code 04).

    Returns sensor data (SoC, power, outputs) on the ``client/04`` topic.
    """
    return ia_input(address, 0, count, False)


def _format_allowed(allowed: FrozenSet[int]) -> str:
    """Format an allowed-values set for error messages."""
    if len(allowed) <= 20:
        return "{%s}" % ", ".join(str(v) for v in sorted(allowed))
    lo, hi = min(allowed), max(allowed)
    return "{%d..%d} (%d values)" % (lo, hi, len(allowed))


# ---------------------------------------------------------------------------
# Pre-defined commands (validated at import time)
# ---------------------------------------------------------------------------

REGRequestSettings      = get_read_modbus(REGISTER_MODBUS_ADDRESS)
REGRequestSensors       = get_read_input_modbus(REGISTER_MODBUS_ADDRESS)
REGDisableUSBOutput     = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_USB_OUTPUT, 0)
REGEnableUSBOutput      = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_USB_OUTPUT, 1)
REGDisableDCOutput      = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_DC_OUTPUT, 0)
REGEnableDCOutput       = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_DC_OUTPUT, 1)
REGDisableACOutput      = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_AC_OUTPUT, 0)
REGEnableACOutput       = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_AC_OUTPUT, 1)
REGDisableLED           = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_LED, 0)
REGEnableLEDAlways      = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_LED, 1)
REGEnableLEDSOS         = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_LED, 2)
REGEnableLEDFlash       = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_LED, 3)
REGDisableACSilentChg   = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_AC_SILENT_CHARGING, 0)
REGEnableACSilentChg    = get_write_modbus(REGISTER_MODBUS_ADDRESS, REGISTER_AC_SILENT_CHARGING, 1)


# ---------------------------------------------------------------------------
# Register parsing
# ---------------------------------------------------------------------------

# Minimum register count worth decoding. Anything shorter is a write
# acknowledgement rather than a data response.
MIN_DATA_REGISTERS = 57


def parse_registers(
    registers: List[int], topic: str
) -> Dict[str, Union[int, float, bool, str, list]]:
    """Parse device registers based on topic and return structured data.

    The response payload carries the requested registers followed by the
    frame's CRC word, so ``registers`` is one entry longer than the requested
    count. Decoding is index-driven and every documented register lives below
    index 72, so the trailing CRC word is simply never read — and a response
    of an unexpected length still decodes everything it does contain.
    """
    # Anything shorter than this is a write acknowledgement echoing back a
    # single register, not a data response.
    if len(registers) < MIN_DATA_REGISTERS:
        return {}

    if 'device/response/client/04' in topic:
        return decode_input_registers(registers)

    if 'device/response/client/data' in topic:
        return decode_holding_registers(registers)

    # Unrecognised topic: the same register numbers mean different things in
    # the holding and input groups, so there is no safe way to decode a
    # response whose group is unknown.
    return {}

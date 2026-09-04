"""Tests for entity definitions across the sensor, binary_sensor, switch,
select and number platforms.

These verify that:
- Every definition can actually construct its entity: the keys of the dict
  match the entity's ``__init__`` signature
- Every key ``parse_registers`` emits is either exposed by an entity or
  explicitly accounted for as attribute-only / internal
- Every command a switch references exists in the connector's COMMANDS dict
- Every writable register is reachable from a controllable entity
- Every select option and number bound is accepted by WRITABLE_REGISTERS
- unique_id suffixes do not collide across platforms

The definitions are imported from the platform modules themselves (see
``conftest.py`` for the Home Assistant stubs that makes that possible), so a
change to an entity table is checked against the protocol layer rather than
against a hand-written copy that can silently drift.
"""

import inspect

from fossibot_ha.sydpower.modbus import (
    WRITABLE_REGISTERS,
    parse_registers,
)
from fossibot_ha.sydpower.connector import COMMANDS as CONNECTOR_COMMANDS
from fossibot_ha.sydpower.const import (
    REGISTER_AC_OUTPUT,
    REGISTER_AC_SILENT_CHARGING,
    REGISTER_DC_OUTPUT,
    REGISTER_LED,
    REGISTER_USB_OUTPUT,
)

from fossibot_ha.binary_sensor import (
    BINARY_SENSOR_DEFINITIONS,
    FossibotBinarySensor,
)
from fossibot_ha.number import NUMBER_DEFINITIONS, FossibotNumber
from fossibot_ha.select import SELECT_DEFINITIONS, FossibotRegisterSelect
from fossibot_ha.sensor import SENSOR_DEFINITIONS, FossibotSensor
from fossibot_ha.switch import (
    REGISTER_SWITCH_DEFINITIONS,
    SWITCH_DEFINITIONS,
    FossibotRegisterSwitch,
    FossibotSwitch,
)

SENSOR_KEYS = [d["key"] for d in SENSOR_DEFINITIONS]
BINARY_SENSOR_KEYS = [d["key"] for d in BINARY_SENSOR_DEFINITIONS]
SWITCH_KEYS = [d["key"] for d in SWITCH_DEFINITIONS]
REGISTER_SWITCH_KEYS = [d["key"] for d in REGISTER_SWITCH_DEFINITIONS]
SELECT_KEYS = [d["key"] for d in SELECT_DEFINITIONS]
NUMBER_KEYS = [d["key"] for d in NUMBER_DEFINITIONS]

# Each entity is constructed as ``Entity(coordinator, device_id, **defn)``, so
# every definition table is paired with the class it feeds.
DEFINITION_TABLES = [
    ("sensor", "SENSOR_DEFINITIONS", SENSOR_DEFINITIONS, FossibotSensor),
    ("binary_sensor", "BINARY_SENSOR_DEFINITIONS", BINARY_SENSOR_DEFINITIONS,
     FossibotBinarySensor),
    ("switch", "SWITCH_DEFINITIONS", SWITCH_DEFINITIONS, FossibotSwitch),
    ("switch", "REGISTER_SWITCH_DEFINITIONS", REGISTER_SWITCH_DEFINITIONS,
     FossibotRegisterSwitch),
    ("select", "SELECT_DEFINITIONS", SELECT_DEFINITIONS,
     FossibotRegisterSelect),
    ("number", "NUMBER_DEFINITIONS", NUMBER_DEFINITIONS, FossibotNumber),
]


# ---------------------------------------------------------------------------
# Constructability
#
# A platform builds its entity list in one comprehension, so a single
# definition whose keys do not match the entity's ``__init__`` raises before
# ``async_add_entities`` is called and takes the *whole* platform down with
# it -- the symptom being a pile of missing entities and one terse
# "missing 1 required positional argument" line in the log. Binding the
# definitions against the signatures catches that at test time.
# ---------------------------------------------------------------------------

class TestDefinitionsMatchEntitySignatures:
    """Every definition must satisfy the signature of the entity it feeds."""

    def test_definitions_bind_to_their_entity(self):
        errors = []
        for platform, table_name, definitions, entity_class in DEFINITION_TABLES:
            signature = inspect.signature(entity_class.__init__)
            for defn in definitions:
                try:
                    # self, coordinator and device_id are supplied positionally
                    # by the platform; the definition provides the rest.
                    signature.bind(None, None, "device-id", **defn)
                except TypeError as err:
                    errors.append(
                        "%s.%s entry %r does not match %s.__init__: %s"
                        % (platform, table_name, defn.get("name"),
                           entity_class.__name__, err)
                    )
        assert errors == [], "\n".join(errors)


# Keys that are decoded but deliberately have no entity of their own.
# Each must have a stated reason, so that adding a decoded field without
# deciding how to surface it fails this test rather than passing silently.
UNEXPOSED_KEYS = {
    # Shown as attributes of the fault sensors.
    "faults": "attribute of the Active Faults / Fault entities",
    "faultsAc": "attribute of the Active Faults / Fault entities",
    "faultsPv": "attribute of the Active Faults / Fault entities",
    "faultsBms": "attribute of the Active Faults / Fault entities",
    "faultsPanel": "attribute of the Active Faults / Fault entities",
    # Shown as attributes of the Battery Chemistry sensor.
    "batteryCapacityAh": "attribute of the Battery Chemistry sensor",
    "batteryCellsSeries": "attribute of the Battery Chemistry sensor",
    "batteryCellsParallel": "attribute of the Battery Chemistry sensor",
    # Raw backing values for a select's decoded state.
    "lightModeRaw": "backs the LED Mode select",
    "dcInputTypeRaw": "backs the DC Input Type select",
    "lightMode": "human-readable form of lightModeRaw",
    "dcInputType": "human-readable form of dcInputTypeRaw",
    # Raw 32-bit field; every meaningful bit has its own binary sensor.
    "systemStateRaw": "decomposed into individual binary sensors",
    # Surfaced through the device registry rather than as entities.
    "serialNumber": "device_info serial_number",
    "versionAcHardware": "device_info hw_version",
    "versionBmsHardware": "device_info hw_version",
    "versionPvHardware": "device_info hw_version",
    "versionPanelHardware": "device_info hw_version",
    "versionExternalComHardware": "device_info hw_version",
    "versionAcSoftware": "device_info sw_version",
    "versionBmsSoftware": "device_info sw_version",
    "versionPvSoftware": "device_info sw_version",
    "versionPanelSoftware": "device_info sw_version",
    "versionExternalComSoftware": "device_info sw_version",
    "deviceMarketType": "device_info model",
    "deviceModelCode": "device_info model",
    # Static hardware descriptors with no actionable use yet.
    "deviceVoltageType": "static hardware descriptor",
    "deviceFrequencyType": "static hardware descriptor",
    "wirelessModules": "static hardware descriptor",
    "storageFlag": "internal device data-storage flag",
}


# ---------------------------------------------------------------------------
# Full entity coverage: every parse_registers key is accounted for
# ---------------------------------------------------------------------------

class TestEntityCoverage:
    """Every key emitted by parse_registers should be exposed or explained."""

    @staticmethod
    def _all_parsed_keys():
        """Collect every key parse_registers can produce.

        The register array is filled so that optional fields (slave
        batteries, PV energy counter, packed identity words) all decode.
        """
        keys = set()
        regs = [0] * 81
        for index in range(81):
            regs[index] = 0x0101
        regs[41] = 0xFFFF          # every system-state high bit set
        regs[42] = 0xFFFF          # every system-state low bit set
        for slave in (53, 55, 66, 67):
            regs[slave] = 500      # slave batteries present
        for index in range(72, 80):
            regs[index] = 0x4142   # printable serial-number characters
        keys.update(parse_registers(regs, "device/response/client/04").keys())
        keys.update(parse_registers(regs, "device/response/client/data").keys())
        return keys

    @staticmethod
    def _all_entity_keys():
        """Collect all data keys covered by any entity type."""
        return (
            set(SENSOR_KEYS)
            | set(BINARY_SENSOR_KEYS)
            | set(SWITCH_KEYS)
            | set(REGISTER_SWITCH_KEYS)
            | set(SELECT_KEYS)
            | set(NUMBER_KEYS)
        )

    def test_all_parsed_keys_have_entities(self):
        missing = self._all_parsed_keys() - self._all_entity_keys()
        missing -= set(UNEXPOSED_KEYS)
        assert missing == set(), (
            "Decoded keys with neither an entity nor an UNEXPOSED_KEYS "
            "entry: %s" % sorted(missing)
        )

    def test_unexposed_keys_are_actually_decoded(self):
        """UNEXPOSED_KEYS should not accumulate entries for dead fields."""
        stale = set(UNEXPOSED_KEYS) - self._all_parsed_keys()
        assert stale == set(), (
            "UNEXPOSED_KEYS lists keys parse_registers never emits: %s"
            % sorted(stale)
        )

    def test_no_entity_references_an_undecoded_key(self):
        unknown = self._all_entity_keys() - self._all_parsed_keys()
        assert unknown == set(), (
            "Entities bound to keys parse_registers never emits: %s"
            % sorted(unknown)
        )

    def test_no_entity_key_collisions(self):
        """A key should be claimed by exactly one platform."""
        groups = {
            "sensor": set(SENSOR_KEYS),
            "binary_sensor": set(BINARY_SENSOR_KEYS),
            "switch": set(SWITCH_KEYS) | set(REGISTER_SWITCH_KEYS),
            "select": set(SELECT_KEYS),
            "number": set(NUMBER_KEYS),
        }
        seen: dict[str, str] = {}
        collisions = []
        for platform, keys in groups.items():
            for key in keys:
                if key in seen:
                    collisions.append((key, seen[key], platform))
                seen[key] = platform
        assert collisions == [], "Keys claimed by two platforms: %s" % collisions

    def test_no_unique_id_collisions(self):
        """unique_id suffixes must be distinct across every platform."""
        suffixes = (
            SENSOR_KEYS
            + BINARY_SENSOR_KEYS
            + SWITCH_KEYS
            + REGISTER_SWITCH_KEYS
            + NUMBER_KEYS
            + [d.get("unique_id_suffix") or d["key"] for d in SELECT_DEFINITIONS]
        )
        duplicates = {s for s in suffixes if suffixes.count(s) > 1}
        assert duplicates == set(), (
            "Duplicate unique_id suffixes: %s" % sorted(duplicates)
        )


# ---------------------------------------------------------------------------
# Sensor
# ---------------------------------------------------------------------------

class TestSensorDefinitions:
    def test_no_duplicate_sensor_keys(self):
        assert len(SENSOR_KEYS) == len(set(SENSOR_KEYS))

    def test_every_sensor_has_a_name(self):
        for defn in SENSOR_DEFINITIONS:
            assert defn["name"], defn

    def test_no_duplicate_sensor_names(self):
        names = [d["name"] for d in SENSOR_DEFINITIONS]
        assert len(names) == len(set(names))


# ---------------------------------------------------------------------------
# Binary sensor
# ---------------------------------------------------------------------------

class TestBinarySensorDefinitions:
    def test_no_duplicate_keys(self):
        assert len(BINARY_SENSOR_KEYS) == len(set(BINARY_SENSOR_KEYS))

    def test_no_duplicate_names(self):
        names = [d["name"] for d in BINARY_SENSOR_DEFINITIONS]
        assert len(names) == len(set(names))

    def test_every_system_state_bit_is_exposed(self):
        """Each named bit of the 32-bit system-state field needs an entity.

        This is the gap the platform was added to close: the integration used
        to read only register 41 and surface four of the bits.
        """
        from fossibot_ha.sydpower.registers import SYSTEM_STATE_BITS

        covered = (
            set(BINARY_SENSOR_KEYS)
            | set(SWITCH_KEYS)
            | set(REGISTER_SWITCH_KEYS)
        )
        missing = set(SYSTEM_STATE_BITS.values()) - covered
        assert missing == set(), (
            "System-state bits with no entity: %s" % sorted(missing)
        )


# ---------------------------------------------------------------------------
# Switch
# ---------------------------------------------------------------------------

class TestSwitchCommands:
    def test_all_switch_commands_in_connector(self):
        for defn in SWITCH_DEFINITIONS:
            for field in ("on_command", "off_command"):
                assert defn[field] in CONNECTOR_COMMANDS, (
                    "Switch '%s' references unknown command '%s'"
                    % (defn["key"], defn[field])
                )

    def test_register_switch_values_are_writable(self):
        for defn in REGISTER_SWITCH_DEFINITIONS:
            allowed = WRITABLE_REGISTERS.get(defn["register"])
            assert allowed is not None, (
                "Switch '%s' writes register %d, which is not writable"
                % (defn["key"], defn["register"])
            )
            for field in ("on_value", "off_value"):
                assert defn[field] in allowed, (
                    "Switch '%s' %s=%d is not allowed for register %d"
                    % (defn["key"], field, defn[field], defn["register"])
                )

    def test_no_duplicate_switch_keys(self):
        keys = SWITCH_KEYS + REGISTER_SWITCH_KEYS
        assert len(keys) == len(set(keys))


# ---------------------------------------------------------------------------
# Select
# ---------------------------------------------------------------------------

class TestSelectDefinitions:
    def test_every_select_option_is_writable(self):
        """Every offered option must be a value the safety map accepts.

        The previous invariant required the option count to equal the number
        of allowed register values, which no longer holds: the protocol allows
        a 0~5000 range on the timer registers while the dropdowns offer a
        handful of useful presets.
        """
        for defn in SELECT_DEFINITIONS:
            allowed = WRITABLE_REGISTERS.get(defn["register"])
            assert allowed is not None, (
                "Select '%s' writes register %d, which is not writable"
                % (defn["key"], defn["register"])
            )
            for label, value in defn["options"].items():
                assert value in allowed, (
                    "Select '%s' option '%s' (%d) is not allowed for "
                    "register %d" % (defn["key"], label, value, defn["register"])
                )

    def test_led_mode_covers_every_allowed_value(self):
        led = next(d for d in SELECT_DEFINITIONS if d["register"] == REGISTER_LED)
        assert set(led["options"].values()) == set(WRITABLE_REGISTERS[REGISTER_LED])

    def test_led_mode_reads_back_from_the_device(self):
        """LED mode is set through holding 27 but reported by input 25.

        Reading it back is what lets the select show SOS and Flash; the
        earlier command-based select had to remember the last choice and
        could only ever report Off or On.
        """
        led = next(d for d in SELECT_DEFINITIONS if d["register"] == REGISTER_LED)
        assert led["key"] == "lightModeRaw"

    def test_no_duplicate_select_keys(self):
        assert len(SELECT_KEYS) == len(set(SELECT_KEYS))

    def test_option_values_unique_within_a_select(self):
        for defn in SELECT_DEFINITIONS:
            values = list(defn["options"].values())
            assert len(values) == len(set(values)), defn["key"]


# ---------------------------------------------------------------------------
# Number
# ---------------------------------------------------------------------------

class TestNumberDefinitions:
    def test_all_number_registers_in_writable(self):
        for defn in NUMBER_DEFINITIONS:
            assert defn["register"] in WRITABLE_REGISTERS, (
                "Number '%s' register %d not in WRITABLE_REGISTERS"
                % (defn["key"], defn["register"])
            )

    def test_number_bounds_are_writable(self):
        """The slider extremes must encode to values the safety map accepts.

        This is what would have caught the discharge/charge limit sliders
        offering 0-100% while the protocol documents 0-50% and 60-100%.
        """
        for defn in NUMBER_DEFINITIONS:
            allowed = WRITABLE_REGISTERS[defn["register"]]
            pack_high = defn.get("pack_high")
            for bound in ("min_value", "max_value"):
                raw = int(round(defn[bound] * defn["multiplier"]))
                if pack_high is not None:
                    raw = (pack_high << 8) | raw
                assert raw in allowed, (
                    "Number '%s' %s=%s encodes to %d, which register %d does "
                    "not allow"
                    % (defn["key"], bound, defn[bound], raw, defn["register"])
                )

    def test_number_step_stays_within_allowed_values(self):
        """Walking the slider must never produce a rejected value."""
        for defn in NUMBER_DEFINITIONS:
            allowed = WRITABLE_REGISTERS[defn["register"]]
            pack_high = defn.get("pack_high")
            value = defn["min_value"]
            while value <= defn["max_value"]:
                raw = int(round(value * defn["multiplier"]))
                if pack_high is not None:
                    raw = (pack_high << 8) | raw
                assert raw in allowed, (
                    "Number '%s' value %s encodes to %d, which register %d "
                    "does not allow"
                    % (defn["key"], value, raw, defn["register"])
                )
                value += defn["step"]

    def test_no_duplicate_number_keys(self):
        assert len(NUMBER_KEYS) == len(set(NUMBER_KEYS))


# ---------------------------------------------------------------------------
# Writable register ↔ entity mapping
# ---------------------------------------------------------------------------

class TestWritableRegisterEntityMapping:
    """Every writable register should be reachable from some entity."""

    @staticmethod
    def _all_entity_registers():
        regs = {
            # Command-based switches write these through the connector's
            # pre-encoded COMMANDS rather than naming a register.
            REGISTER_USB_OUTPUT,
            REGISTER_DC_OUTPUT,
            REGISTER_AC_OUTPUT,
            REGISTER_AC_SILENT_CHARGING,
        }
        regs.update(d["register"] for d in REGISTER_SWITCH_DEFINITIONS)
        regs.update(d["register"] for d in SELECT_DEFINITIONS)
        regs.update(d["register"] for d in NUMBER_DEFINITIONS)
        return regs

    def test_every_writable_register_has_entity(self):
        missing = set(WRITABLE_REGISTERS) - self._all_entity_registers()
        assert missing == set(), (
            "Writable registers with no entity: %s" % sorted(missing)
        )

    def test_boolean_registers_have_switches(self):
        for reg in (REGISTER_USB_OUTPUT, REGISTER_DC_OUTPUT,
                    REGISTER_AC_OUTPUT, REGISTER_AC_SILENT_CHARGING):
            assert WRITABLE_REGISTERS[reg] == frozenset({0, 1})

    def test_led_register_has_select_not_switch(self):
        assert "ledOutput" not in SWITCH_KEYS
        assert REGISTER_LED in {d["register"] for d in SELECT_DEFINITIONS}

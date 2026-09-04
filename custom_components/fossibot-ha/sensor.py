"""Support for Fossibot sensors."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import FossibotDataUpdateCoordinator
from .entity import FossibotEntity

# ---------------------------------------------------------------------------
# Sensor definitions
#
# Every entry maps to a register documented in the Sydpower "Modbus RTU
# Protocol" (Inverter-Protocol-V0), noted as "input NN" / "holding NN".
#
# ``default_enabled: False`` keeps per-port breakdowns out of the way — they
# are useful for diagnosing a specific socket but would otherwise add two
# dozen mostly-zero entities per device. Users can enable them individually.
# ---------------------------------------------------------------------------

POWER = SensorDeviceClass.POWER
ENERGY = SensorDeviceClass.ENERGY
VOLTAGE = SensorDeviceClass.VOLTAGE
FREQUENCY = SensorDeviceClass.FREQUENCY
BATTERY = SensorDeviceClass.BATTERY
DURATION = SensorDeviceClass.DURATION
DIAGNOSTIC = EntityCategory.DIAGNOSTIC

SENSOR_DEFINITIONS = [
    # --- Battery ---------------------------------------------------------
    {"name": "State of Charge", "key": "soc", "unit": "%", "device_class": BATTERY},  # input 56
    {"name": "State of Charge Slave 1", "key": "soc_s1", "unit": "%", "device_class": BATTERY},  # input 53
    {"name": "State of Charge Slave 2", "key": "soc_s2", "unit": "%", "device_class": BATTERY},  # input 55
    {"name": "State of Charge Slave 3", "key": "soc_s3", "unit": "%", "device_class": BATTERY},  # input 66
    {"name": "State of Charge Slave 4", "key": "soc_s4", "unit": "%", "device_class": BATTERY},  # input 67
    {"name": "Battery Usable Capacity", "key": "batteryUsableCapacity", "unit": "Ah",
     "state_class": SensorStateClass.MEASUREMENT},  # input 54
    {"name": "Average Discharge SoC", "key": "averageDischargeSoc", "unit": "%",
     "state_class": SensorStateClass.MEASUREMENT, "category": DIAGNOSTIC},  # input 70
    {"name": "Average Charge SoC", "key": "averageChargeSoc", "unit": "%",
     "state_class": SensorStateClass.MEASUREMENT, "category": DIAGNOSTIC},  # input 71

    # --- Input power -----------------------------------------------------
    {"name": "AC Input", "key": "acInput", "unit": "W", "device_class": POWER},  # input 03
    {"name": "DC Input", "key": "dcInput", "unit": "W", "device_class": POWER},  # input 04
    {"name": "USB-C Input", "key": "typecInput", "unit": "W", "device_class": POWER},  # input 05
    {"name": "Total Input", "key": "totalInput", "unit": "W", "device_class": POWER},  # input 06

    # --- Output power ----------------------------------------------------
    {"name": "Total Output", "key": "totalOutput", "unit": "W", "device_class": POWER},  # input 39
    {"name": "AC Output Power", "key": "acOutputPower", "unit": "W", "device_class": POWER},  # input 20
    {"name": "Inverter Output Power", "key": "inverterOutputPower", "unit": "W",
     "device_class": POWER},  # input 16
    {"name": "Inverter Apparent Power", "key": "inverterOutputApparentPower", "unit": "VA",
     "device_class": SensorDeviceClass.APPARENT_POWER, "default_enabled": False},  # input 17

    # --- AC electrical ---------------------------------------------------
    {"name": "AC Output Voltage", "key": "acOutputVoltage", "unit": "V", "device_class": VOLTAGE},  # input 18
    {"name": "AC Output Frequency", "key": "acOutputFrequency", "unit": "Hz", "device_class": FREQUENCY},  # input 19
    {"name": "AC Input Voltage", "key": "acInputVoltage", "unit": "V", "device_class": VOLTAGE},  # input 21
    {"name": "AC Input Frequency", "key": "acInputFrequency", "unit": "Hz", "device_class": FREQUENCY},  # input 22

    # --- Energy ----------------------------------------------------------
    # Input 60 is offset by one so that 0 can mean "no counter fitted"; the
    # decoder removes the offset, so the sensor is a true lifetime total.
    {"name": "PV Energy Total", "key": "pvEnergyTotal", "unit": "kWh", "device_class": ENERGY,
     "state_class": SensorStateClass.TOTAL_INCREASING},  # input 60

    # --- Timers ----------------------------------------------------------
    {"name": "Remaining Charge Time", "key": "remainingChargeTime", "unit": "min",
     "device_class": DURATION, "state_class": SensorStateClass.MEASUREMENT},  # input 58
    {"name": "Remaining Discharge Time", "key": "remainingDischargeTime", "unit": "min",
     "device_class": DURATION, "state_class": SensorStateClass.MEASUREMENT},  # input 59
    {"name": "Charge Schedule Remaining", "key": "chargeAppointmentRemaining", "unit": "min",
     "device_class": DURATION, "state_class": SensorStateClass.MEASUREMENT,
     "default_enabled": False},  # input 57

    # --- Settings readback ----------------------------------------------
    # The AC charge level, LED mode and DC input type are exposed as selects
    # (which both report and set them), so they have no duplicate sensor.
    # Input 02 is the level the device is *actually* running at, which can
    # lag the holding-13 setting, so it gets its own diagnostic sensor.
    {"name": "AC Charging Rate Active", "key": "acChargeLevelActive", "unit": None,
     "device_class": None, "category": DIAGNOSTIC, "default_enabled": False},  # input 02

    # --- Faults ----------------------------------------------------------
    {"name": "Active Faults", "key": "faultCount", "unit": None, "device_class": None,
     "category": DIAGNOSTIC, "attribute_keys": (
         "faults", "faultsAc", "faultsPv", "faultsBms", "faultsPanel")},

    # --- Device capability / identity (diagnostic) -----------------------
    {"name": "AC Charge Max Power", "key": "acChargeMaxPower", "unit": "W", "device_class": POWER,
     "category": DIAGNOSTIC, "default_enabled": False},  # holding 14
    {"name": "DC Input Max Power", "key": "dcInputMaxPower", "unit": "W", "device_class": POWER,
     "category": DIAGNOSTIC, "default_enabled": False},  # holding 16
    {"name": "DC Input Max Current", "key": "dcInputMaxCurrent", "unit": "A",
     "device_class": SensorDeviceClass.CURRENT, "category": DIAGNOSTIC,
     "default_enabled": False},  # holding 17
    {"name": "Battery Chemistry", "key": "batteryChemistry", "unit": None, "device_class": None,
     "category": DIAGNOSTIC, "default_enabled": False,
     "attribute_keys": ("batteryCapacityAh", "batteryCellsSeries",
                        "batteryCellsParallel")},  # holding 40/41
    {"name": "Protocol Version", "key": "protocolVersion", "unit": None, "device_class": None,
     "category": DIAGNOSTIC, "default_enabled": False},  # holding 5
    {"name": "DC Input Min Voltage", "key": "dcInputMinVoltage", "unit": "V",
     "device_class": VOLTAGE, "category": DIAGNOSTIC,
     "default_enabled": False},  # holding 18
    {"name": "DC Input Max Voltage", "key": "dcInputMaxVoltage", "unit": "V",
     "device_class": VOLTAGE, "category": DIAGNOSTIC,
     "default_enabled": False},  # holding 19

    # --- Per-port power breakdown (off by default) -----------------------
    {"name": "USB 1 Power", "key": "usb1Power", "unit": "W", "device_class": POWER,
     "default_enabled": False},  # input 26
    {"name": "USB 2 Power", "key": "usb2Power", "unit": "W", "device_class": POWER,
     "default_enabled": False},  # input 27
    {"name": "USB 3 Power", "key": "usb3Power", "unit": "W", "device_class": POWER,
     "default_enabled": False},  # input 28
    {"name": "QC 1 Power", "key": "qc1Power", "unit": "W", "device_class": POWER,
     "default_enabled": False},  # input 30
    {"name": "QC 2 Power", "key": "qc2Power", "unit": "W", "device_class": POWER,
     "default_enabled": False},  # input 31
    {"name": "QC 3 Power", "key": "qc3Power", "unit": "W", "device_class": POWER,
     "default_enabled": False},  # input 32
    {"name": "PD 1 Power", "key": "pd1Power", "unit": "W", "device_class": POWER,
     "default_enabled": False},  # input 34
    {"name": "PD 2 Power", "key": "pd2Power", "unit": "W", "device_class": POWER,
     "default_enabled": False},  # input 35
    {"name": "PD 3 Power", "key": "pd3Power", "unit": "W", "device_class": POWER,
     "default_enabled": False},  # input 36
    {"name": "PD 4 Power", "key": "pd4Power", "unit": "W", "device_class": POWER,
     "default_enabled": False},  # input 37
    {"name": "PD 5 Power", "key": "pd5Power", "unit": "W", "device_class": POWER,
     "default_enabled": False},  # input 38
    {"name": "XT60 Power", "key": "xt60Power", "unit": "W", "device_class": POWER,
     "default_enabled": False},  # input 08
    {"name": "Cigarette Socket Power", "key": "cigarettePower", "unit": "W", "device_class": POWER,
     "default_enabled": False},  # input 09
    {"name": "DC 5521 Power", "key": "port5521Power", "unit": "W", "device_class": POWER,
     "default_enabled": False},  # input 10
    {"name": "Wireless Charging Power", "key": "wirelessChargingPower", "unit": "W",
     "device_class": POWER, "default_enabled": False},  # input 13
    {"name": "LED Power", "key": "ledPower", "unit": "W", "device_class": POWER,
     "default_enabled": False},  # input 15
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Fossibot sensors."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = [
        FossibotSensor(coordinator, device_id, **defn)
        for device_id in coordinator.data
        for defn in SENSOR_DEFINITIONS
    ]

    async_add_entities(entities)


class FossibotSensor(FossibotEntity, SensorEntity):
    """Representation of a Fossibot sensor."""

    def __init__(
        self,
        coordinator: FossibotDataUpdateCoordinator,
        device_id: str,
        name: str,
        key: str,
        unit: str | None,
        device_class: SensorDeviceClass | None,
        state_class: SensorStateClass | None = None,
        category: EntityCategory | None = None,
        default_enabled: bool = True,
        attribute_keys: tuple[str, ...] = (),
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, device_id)
        self._key = key
        self._attribute_keys = attribute_keys
        self._attr_name = f"Fossibot {device_id} {name}"
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_entity_category = category
        self._attr_entity_registry_enabled_default = default_enabled

        if state_class is not None:
            self._attr_state_class = state_class
        elif device_class in (
            SensorDeviceClass.POWER,
            SensorDeviceClass.APPARENT_POWER,
            SensorDeviceClass.VOLTAGE,
            SensorDeviceClass.FREQUENCY,
            SensorDeviceClass.CURRENT,
            SensorDeviceClass.BATTERY,
        ):
            self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self._device_id not in self.coordinator.data:
            return None
        return self.coordinator.data[self._device_id].get(self._key)

    @property
    def extra_state_attributes(self):
        """Expose the supporting registers this sensor summarises."""
        if not self._attribute_keys:
            return None
        device_data = self.coordinator.data.get(self._device_id, {})
        attributes = {
            key: device_data[key]
            for key in self._attribute_keys
            if key in device_data
        }
        return attributes or None

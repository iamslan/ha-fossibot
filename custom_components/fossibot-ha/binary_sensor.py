"""Support for Fossibot binary sensors.

These expose the 32-bit system-state field (input registers 41 + 42,
appendix &*8) and the aggregated fault state. Before this platform existed
only four of the thirty-two state bits were reachable, and register 42 —
the whole low half, carrying the per-port and grid-presence flags — was
never read at all.
"""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import FossibotDataUpdateCoordinator
from .entity import FossibotEntity

DIAGNOSTIC = EntityCategory.DIAGNOSTIC

# (name, data key, device_class, entity_category, default_enabled)
BINARY_SENSOR_DEFINITIONS = [
    # --- Charging sources (bits 30..19) ----------------------------------
    {"name": "Grid Charging", "key": "gridCharging",
     "device_class": BinarySensorDeviceClass.BATTERY_CHARGING},  # bit 20
    # Bit 19 is "AC input voltage presence"; bit 17 is the device's
    # on-grid/off-grid determination. They are not the same thing — mains can
    # be present while the unit runs off-grid.
    {"name": "Grid Input Present", "key": "gridVoltagePresent",
     "device_class": BinarySensorDeviceClass.PLUG},  # bit 19
    {"name": "On Grid", "key": "gridConnected"},  # bit 17
    {"name": "DC Charging", "key": "dcCharging",
     "device_class": BinarySensorDeviceClass.BATTERY_CHARGING},  # bit 22
    {"name": "DC Input Present", "key": "dcChargeVoltagePresent",
     "device_class": BinarySensorDeviceClass.PLUG},  # bit 21
    {"name": "PV High Voltage Charging", "key": "pvHighVoltageCharging",
     "device_class": BinarySensorDeviceClass.BATTERY_CHARGING,
     "default_enabled": False},  # bit 31
    {"name": "PV High Voltage Present", "key": "pvHighVoltagePresent",
     "device_class": BinarySensorDeviceClass.PLUG,
     "default_enabled": False},  # bit 30
    {"name": "Car Charging", "key": "carCharging",
     "device_class": BinarySensorDeviceClass.BATTERY_CHARGING,
     "default_enabled": False},  # bit 29
    {"name": "Car Charge Input Present", "key": "carChargeVoltagePresent",
     "device_class": BinarySensorDeviceClass.PLUG,
     "default_enabled": False},  # bit 24

    # --- Output state ----------------------------------------------------
    {"name": "AC Inverter Output", "key": "acInverterOutput",
     "device_class": BinarySensorDeviceClass.POWER},  # bit 18
    {"name": "DC Port Output", "key": "dcPortOutput",
     "device_class": BinarySensorDeviceClass.POWER},  # bit 23
    {"name": "Wireless Charging Active", "key": "wirelessCharging",
     "device_class": BinarySensorDeviceClass.POWER,
     "default_enabled": False},  # bit 16
    {"name": "ECO Mode", "key": "ecoMode"},  # bit 12
    # The LED button's on/off bit. The LED Mode select already reports the
    # richer four-state mode, so this stays off by default.
    {"name": "LED Output", "key": "ledOutput",
     "device_class": BinarySensorDeviceClass.POWER,
     "default_enabled": False},  # bit 28

    # --- Individual ports (off by default) -------------------------------
    {"name": "XT60 Port", "key": "portXt60Output",
     "device_class": BinarySensorDeviceClass.POWER, "default_enabled": False},  # bit 13
    {"name": "Cigarette Socket", "key": "portCigaretteOutput",
     "device_class": BinarySensorDeviceClass.POWER, "default_enabled": False},  # bit 14
    {"name": "DC 5521 Port", "key": "port5521Output",
     "device_class": BinarySensorDeviceClass.POWER, "default_enabled": False},  # bit 15
    {"name": "USB 1 Port", "key": "usb1Output",
     "device_class": BinarySensorDeviceClass.POWER, "default_enabled": False},  # bit 0
    {"name": "USB 2 Port", "key": "usb2Output",
     "device_class": BinarySensorDeviceClass.POWER, "default_enabled": False},  # bit 1
    {"name": "QC 1 Port", "key": "qc1Output",
     "device_class": BinarySensorDeviceClass.POWER, "default_enabled": False},  # bit 3
    {"name": "QC 2 Port", "key": "qc2Output",
     "device_class": BinarySensorDeviceClass.POWER, "default_enabled": False},  # bit 4
    {"name": "PD 1 Port", "key": "pd1Output",
     "device_class": BinarySensorDeviceClass.POWER, "default_enabled": False},  # bit 6
    {"name": "PD 2 Port", "key": "pd2Output",
     "device_class": BinarySensorDeviceClass.POWER, "default_enabled": False},  # bit 7
    {"name": "PD 3 Port", "key": "pd3Output",
     "device_class": BinarySensorDeviceClass.POWER, "default_enabled": False},  # bit 8
    {"name": "PD 4 Port", "key": "pd4Output",
     "device_class": BinarySensorDeviceClass.POWER, "default_enabled": False},  # bit 9
    {"name": "PD 5 Port", "key": "pd5Output",
     "device_class": BinarySensorDeviceClass.POWER, "default_enabled": False},  # bit 10

    # --- Battery state (BMS words, informational bits) -------------------
    {"name": "Battery Charging", "key": "charging",
     "device_class": BinarySensorDeviceClass.BATTERY_CHARGING,
     "category": DIAGNOSTIC},  # input 48 bit 15
    {"name": "Battery Discharging", "key": "discharging",
     "category": DIAGNOSTIC, "default_enabled": False},  # input 48 bit 14
    {"name": "Battery Fully Charged", "key": "fullyCharged",
     "category": DIAGNOSTIC, "default_enabled": False},  # input 48 bit 12
    {"name": "Battery Fully Discharged", "key": "fullyDischarged",
     "category": DIAGNOSTIC, "default_enabled": False},  # input 48 bit 13
    {"name": "Battery Overvoltage", "key": "batteryOvervoltage",
     "category": DIAGNOSTIC, "default_enabled": False},  # input 48 bit 7
    {"name": "Battery Balancing", "key": "balancing",
     "category": DIAGNOSTIC, "default_enabled": False},  # input 48 bit 6
    {"name": "Precharge MOSFET On", "key": "prechargeMosfetOn",
     "category": DIAGNOSTIC, "default_enabled": False},  # input 47 bit 14
    {"name": "Charge MOSFET On", "key": "chargeMosfetOn",
     "category": DIAGNOSTIC, "default_enabled": False},  # input 47 bit 13
    {"name": "Discharge MOSFET On", "key": "dischargeMosfetOn",
     "category": DIAGNOSTIC, "default_enabled": False},  # input 47 bit 12

    # --- Faults ----------------------------------------------------------
    {"name": "Fault", "key": "hasFault",
     "device_class": BinarySensorDeviceClass.PROBLEM,
     "category": DIAGNOSTIC, "attribute_keys": (
         "faults", "faultsAc", "faultsPv", "faultsBms", "faultsPanel")},
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Fossibot binary sensors."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = [
        FossibotBinarySensor(coordinator, device_id, **defn)
        for device_id in coordinator.data
        for defn in BINARY_SENSOR_DEFINITIONS
    ]

    async_add_entities(entities)


class FossibotBinarySensor(FossibotEntity, BinarySensorEntity):
    """A single bit of the Fossibot system-state or fault field."""

    def __init__(
        self,
        coordinator: FossibotDataUpdateCoordinator,
        device_id: str,
        name: str,
        key: str,
        device_class: BinarySensorDeviceClass | None = None,
        category: EntityCategory | None = None,
        default_enabled: bool = True,
        attribute_keys: tuple[str, ...] = (),
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, device_id)
        self._key = key
        self._attribute_keys = attribute_keys
        self._attr_name = f"Fossibot {device_id} {name}"
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_device_class = device_class
        self._attr_entity_category = category
        self._attr_entity_registry_enabled_default = default_enabled

    @property
    def is_on(self) -> bool | None:
        """Return the state of the bit."""
        if self._device_id not in self.coordinator.data:
            return None
        return self.coordinator.data[self._device_id].get(self._key)

    @property
    def extra_state_attributes(self):
        """Expose the decoded fault names behind an aggregate sensor."""
        if not self._attribute_keys:
            return None
        device_data = self.coordinator.data.get(self._device_id, {})
        attributes = {
            key: device_data[key]
            for key in self._attribute_keys
            if key in device_data
        }
        return attributes or None

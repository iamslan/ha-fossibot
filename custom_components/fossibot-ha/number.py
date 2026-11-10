"""Support for Fossibot number entities."""

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import FossibotDataUpdateCoordinator
from .entity import FossibotEntity, device_profile
from .sydpower.registers_v1 import (
    FUNC_WRITE_HOLDING, HREG_V1_AC_SLEEP_TIME, HREG_V1_CHARGE_SOC_MAX,
    HREG_V1_DC_INPUT_CURRENT_SET, HREG_V1_DC_SLEEP_TIME, HREG_V1_DISCHARGE_SOC_MIN,
    HREG_V1_LCD_DIM_TIME, HREG_V1_SHUTDOWN_WAIT_TIME, HREG_V1_USB_SLEEP_TIME,
)
from .sydpower.modbus import NOT_SET, pack_byte_pair
from .sydpower.const import (
    HREG_LOW_BATTERY_NOTIFY,
    HREG_WIFI_UPLOAD_INTERVAL,
    REGISTER_CHARGING_LIMIT,
    REGISTER_DISCHARGE_LIMIT,
    REGISTER_MAXIMUM_CHARGING_CURRENT,
    REGISTER_STOP_CHARGE_AFTER,
)

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Number definitions
#
# ``min_value``/``max_value`` are in the entity's display unit; ``multiplier``
# converts that to the raw register value. Ranges follow the Sydpower
# "Modbus RTU Protocol" (Inverter-Protocol-V0) section 3.1 exactly:
#
#   holding 20 — DC charging current, 1 A/count, "< DC Input Max Curr" (h17)
#   holding 63 — AC scheduled charge time, 1 min/count, "Range: 1~5000"
#   holding 66 — minimum discharge SOC, 0.1%/count, "Range: 0~500"   → 0-50%
#   holding 67 — maximum charge SOC,    0.1%/count, "Range: 600~1000" → 60-100%
#   holding 54 — Wi-Fi upload interval, 1 s/count
#   holding 69 — low-battery notification threshold, 1%/count, 0~100
# ---------------------------------------------------------------------------

NUMBER_DEFINITIONS = [
    {
        # Register 20 is the *DC* (PV / vehicle) charging current limit, not
        # the AC one. It was previously presented as "Maximum Charging
        # Current" and documented as an AC limit, which is wrong.
        "name": "DC Input Charging Current Limit",
        "key": "maximumChargingCurrent",
        "register": REGISTER_MAXIMUM_CHARGING_CURRENT,
        "min_value": 1,
        "max_value": 20,
        "step": 1,
        "unit": "A",
        "mode": NumberMode.SLIDER,
        "multiplier": 1,
        # Narrow the slider to what this device says it supports (holding 17).
        "max_from_key": "dcInputMaxCurrent",
    },
    {
        "name": "Stop Charge After",
        "key": "stopChargeAfter",
        "register": REGISTER_STOP_CHARGE_AFTER,
        "min_value": 0,
        "max_value": 5000,
        "step": 1,
        "unit": "min",
        "mode": NumberMode.BOX,
        "multiplier": 1,
    },
    {
        "name": "Discharge Lower Limit",
        "key": "dischargeLowerLimit",
        "register": REGISTER_DISCHARGE_LIMIT,
        "min_value": 0,
        "max_value": 50,     # protocol: register range 0~500 at 0.1%/count
        "step": 1,
        "unit": "%",
        "mode": NumberMode.SLIDER,
        "multiplier": 10,    # UI shows %, register stores permille
    },
    {
        "name": "AC Charging Upper Limit",
        "key": "acChargingUpperLimit",
        "register": REGISTER_CHARGING_LIMIT,
        "min_value": 60,     # protocol: register range 600~1000 at 0.1%/count
        "max_value": 100,
        "step": 1,
        "unit": "%",
        "mode": NumberMode.SLIDER,
        "multiplier": 10,    # UI shows %, register stores permille
    },
    {
        "name": "Wi-Fi Upload Interval",
        "key": "wifiUploadInterval",
        "register": HREG_WIFI_UPLOAD_INTERVAL,
        "min_value": 5,
        "max_value": 3600,
        "step": 1,
        "unit": "s",
        "mode": NumberMode.BOX,
        "multiplier": 1,
        "category": EntityCategory.CONFIG,
    },
    {
        "name": "Low Battery Notification Threshold",
        "key": "lowBatteryNotifyThreshold",
        "register": HREG_LOW_BATTERY_NOTIFY,
        "min_value": 0,
        "max_value": 100,
        "step": 1,
        "unit": "%",
        "mode": NumberMode.SLIDER,
        "multiplier": 1,
        "category": EntityCategory.CONFIG,
        # Register 69 also holds the notification enable flag in its high
        # byte; write 0xFF there so the enable state is left untouched.
        "pack_high": NOT_SET,
    },
]

# Protocol V1 holding registers (registers_v1); written with func 6 through
# the connector's write_v1 command, ranges from WRITABLE_REGISTERS_V1.
V1_NUMBER_DEFINITIONS = [
    {"name": "DC Input Charging Current Limit", "key": "maximumChargingCurrent",
     "register": HREG_V1_DC_INPUT_CURRENT_SET, "min_value": 1, "max_value": 20, "step": 1,
     "unit": "A", "mode": NumberMode.SLIDER, "multiplier": 1, "max_from_key": "dcInputMaxCurrent",
     "category": EntityCategory.CONFIG},
    {"name": "Discharge Lower Limit", "key": "dischargeLowerLimit",
     "register": HREG_V1_DISCHARGE_SOC_MIN, "min_value": 0, "max_value": 50, "step": 1,
     "unit": "%", "mode": NumberMode.SLIDER, "multiplier": 10, "category": EntityCategory.CONFIG},
    {"name": "AC Charging Upper Limit", "key": "acChargingUpperLimit",
     "register": HREG_V1_CHARGE_SOC_MAX, "min_value": 60, "max_value": 100, "step": 1,
     "unit": "%", "mode": NumberMode.SLIDER, "multiplier": 10, "category": EntityCategory.CONFIG},
    {"name": "Screen Rest Time", "key": "screenRestTime",
     "register": HREG_V1_LCD_DIM_TIME, "min_value": 0, "max_value": 5000, "step": 1,
     "unit": "s", "mode": NumberMode.BOX, "multiplier": 1, "category": EntityCategory.CONFIG},
    {"name": "AC Standby Time", "key": "acStandbyTime",
     "register": HREG_V1_AC_SLEEP_TIME, "min_value": 0, "max_value": 5000, "step": 1,
     "unit": "min", "mode": NumberMode.BOX, "multiplier": 1, "category": EntityCategory.CONFIG},
    {"name": "USB Standby Time", "key": "usbStandbyTime",
     "register": HREG_V1_USB_SLEEP_TIME, "min_value": 0, "max_value": 5000, "step": 1,
     "unit": "min", "mode": NumberMode.BOX, "multiplier": 1, "category": EntityCategory.CONFIG},
    {"name": "DC Standby Time", "key": "dcStandbyTime",
     "register": HREG_V1_DC_SLEEP_TIME, "min_value": 0, "max_value": 5000, "step": 1,
     "unit": "min", "mode": NumberMode.BOX, "multiplier": 1, "category": EntityCategory.CONFIG},
    {"name": "Whole Machine Unused Time", "key": "wholeMachineUnusedTime",
     "register": HREG_V1_SHUTDOWN_WAIT_TIME, "min_value": 0, "max_value": 5000, "step": 1,
     "unit": "min", "mode": NumberMode.BOX, "multiplier": 1, "category": EntityCategory.CONFIG},
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Fossibot number entities."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    for device_id in coordinator.data:
        if device_profile(coordinator, device_id) == 0:
            entities.extend(FossibotNumber(coordinator, device_id, **defn)
                            for defn in NUMBER_DEFINITIONS)
        else:
            entities.extend(FossibotNumber(coordinator, device_id, v1=True, **defn)
                            for defn in V1_NUMBER_DEFINITIONS)

    async_add_entities(entities)


class FossibotNumber(FossibotEntity, NumberEntity):
    """Representation of a Fossibot number entity."""

    def __init__(
        self,
        coordinator: FossibotDataUpdateCoordinator,
        device_id: str,
        name: str,
        key: str,
        register: int,
        min_value: float,
        max_value: float,
        step: float,
        unit: str,
        mode: NumberMode,
        multiplier: int,
        category: EntityCategory | None = None,
        max_from_key: str | None = None,
        pack_high: int | None = None,
        v1: bool = False,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, device_id)
        self._v1 = v1
        self._key = key
        self._register = register
        self._multiplier = multiplier
        self._max_from_key = max_from_key
        self._pack_high = pack_high
        self._declared_max = max_value
        self._attr_name = f"Fossibot {device_id} {name}"
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_native_min_value = min_value
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_mode = mode
        self._attr_entity_category = category

    @property
    def native_value(self):
        """Return the current value."""
        if self._device_id not in self.coordinator.data:
            return None
        return self.coordinator.data[self._device_id].get(self._key)

    @property
    def native_max_value(self) -> float:
        """Return the maximum, narrowed by the device's own reported limit."""
        if not self._max_from_key:
            return self._declared_max

        reported = self.coordinator.data.get(self._device_id, {}).get(
            self._max_from_key
        )
        if not isinstance(reported, (int, float)) or reported <= 0:
            return self._declared_max
        return min(self._declared_max, float(reported))

    async def async_set_native_value(self, value: float) -> None:
        """Set a new value."""
        reg_value = int(round(value * self._multiplier))
        if self._pack_high is not None:
            reg_value = pack_byte_pair(self._pack_high, reg_value)

        if self._v1:
            await self.coordinator.connector.run_command(
                self._device_id, "write_v1", (FUNC_WRITE_HOLDING, self._register, reg_value)
            )
        else:
            await self.coordinator.connector.run_command(
                self._device_id, "write_register", (self._register, reg_value)
            )
        await self.coordinator.async_request_refresh()

"""Support for Fossibot switches."""

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import FossibotDataUpdateCoordinator
from .entity import FossibotEntity
from .sydpower.modbus import pack_byte_pair, NOT_SET
from .sydpower.const import (
    HREG_APP_CONTROL_SLEEP,
    HREG_BUZZER,
    HREG_GRID_AC_AUTO_OUTPUT,
    HREG_LOW_BATTERY_NOTIFY,
)

_LOGGER = logging.getLogger(__name__)

# Switches driven by a pre-encoded command constant in the connector.
SWITCH_DEFINITIONS = [
    {"name": "USB Output", "key": "usbOutput", "on_command": "REGEnableUSBOutput", "off_command": "REGDisableUSBOutput"},
    {"name": "DC Output", "key": "dcOutput", "on_command": "REGEnableDCOutput", "off_command": "REGDisableDCOutput"},
    {"name": "AC Output", "key": "acOutput", "on_command": "REGEnableACOutput", "off_command": "REGDisableACOutput"},
    {"name": "AC Silent Charging", "key": "acSilentCharging", "on_command": "REGEnableACSilentChg", "off_command": "REGDisableACSilentChg"},
]

# Switches that write a register value directly.
#
# The low-battery notification enable (holding 69) shares its register with
# the notification threshold, so each write sets the other half to 0xFF —
# the protocol's "leave this item alone" marker.
REGISTER_SWITCH_DEFINITIONS = [
    {
        "name": "Buzzer",
        "key": "buzzerEnabled",
        "register": HREG_BUZZER,
        "on_value": 1,
        "off_value": 0,
    },
    {
        "name": "Grid Mode AC Auto Output",
        "key": "gridAcAutoOutput",
        "register": HREG_GRID_AC_AUTO_OUTPUT,
        "on_value": 1,
        "off_value": 0,
    },
    {
        "name": "App Remote Shutdown",
        "key": "appControlSleep",
        "register": HREG_APP_CONTROL_SLEEP,
        "on_value": 1,
        "off_value": 0,
        "category": EntityCategory.CONFIG,
    },
    {
        "name": "Low Battery Notification",
        "key": "lowBatteryNotifyEnabled",
        "register": HREG_LOW_BATTERY_NOTIFY,
        "on_value": pack_byte_pair(1, NOT_SET),
        "off_value": pack_byte_pair(0, NOT_SET),
        "category": EntityCategory.CONFIG,
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Fossibot switches."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[SwitchEntity] = []
    for device_id in coordinator.data:
        entities.extend(
            FossibotSwitch(coordinator, device_id, **defn)
            for defn in SWITCH_DEFINITIONS
        )
        entities.extend(
            FossibotRegisterSwitch(coordinator, device_id, **defn)
            for defn in REGISTER_SWITCH_DEFINITIONS
        )

    async_add_entities(entities)


class _FossibotSwitchBase(FossibotEntity, SwitchEntity):
    """Shared state handling for Fossibot switches."""

    def __init__(
        self,
        coordinator: FossibotDataUpdateCoordinator,
        device_id: str,
        name: str,
        key: str,
        category: EntityCategory | None = None,
    ) -> None:
        super().__init__(coordinator, device_id)
        self._key = key
        self._attr_name = f"Fossibot {device_id} {name}"
        self._attr_unique_id = f"{device_id}_{key}"
        self._attr_entity_category = category

    @property
    def is_on(self):
        """Return true if switch is on."""
        if self._device_id not in self.coordinator.data:
            return None
        return self.coordinator.data[self._device_id].get(self._key)


class FossibotSwitch(_FossibotSwitchBase):
    """A Fossibot switch backed by a pre-encoded connector command."""

    def __init__(
        self,
        coordinator: FossibotDataUpdateCoordinator,
        device_id: str,
        name: str,
        key: str,
        on_command: str,
        off_command: str,
        category: EntityCategory | None = None,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, device_id, name, key, category)
        self._on_command = on_command
        self._off_command = off_command

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        await self.coordinator.connector.run_command(
            self._device_id, self._on_command
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        await self.coordinator.connector.run_command(
            self._device_id, self._off_command
        )
        await self.coordinator.async_request_refresh()


class FossibotRegisterSwitch(_FossibotSwitchBase):
    """A Fossibot switch that writes a holding register directly."""

    def __init__(
        self,
        coordinator: FossibotDataUpdateCoordinator,
        device_id: str,
        name: str,
        key: str,
        register: int,
        on_value: int,
        off_value: int,
        category: EntityCategory | None = None,
    ) -> None:
        """Initialize the register-backed switch."""
        super().__init__(coordinator, device_id, name, key, category)
        self._register = register
        self._on_value = on_value
        self._off_value = off_value

    async def _write(self, value: int) -> None:
        await self.coordinator.connector.run_command(
            self._device_id, "write_register", (self._register, value)
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        await self._write(self._on_value)

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        await self._write(self._off_value)

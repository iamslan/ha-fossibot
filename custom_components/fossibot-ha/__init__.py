"""The Fossibot integration."""

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.storage import Store

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL
from .coordinator import FossibotDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Fossibot from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = FossibotDataUpdateCoordinator(
        hass,
        config=entry.data,
        update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        config_entry=entry,
    )

    store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.devices")
    cached = await store.async_load()
    coordinator.connector.load_cached_devices(cached)
    coordinator.connector.on_device_list = store.async_save
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        if not (coordinator.connector.devices and coordinator.connector.is_connected()):
            await coordinator.async_shutdown()
            raise
        # Identities let platforms register while the device is off. The
        # failed refresh/last_update_success=False keeps entities unavailable;
        # no cached readings or guessed zeroes are published.
        coordinator.data = {mac: {} for mac in coordinator.connector.devices}
    except BaseException:
        await coordinator.async_shutdown()
        raise

    hass.data[DOMAIN][entry.entry_id] = coordinator

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        await coordinator.async_shutdown()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if coordinator is None:
        return True
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await coordinator.async_shutdown()
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove saved identities when the integration entry is deleted."""
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.devices").async_remove()

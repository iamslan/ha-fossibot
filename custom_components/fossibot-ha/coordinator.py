"""Coordinate local telemetry without reconnecting a healthy MQTT broker."""

import asyncio
import logging
import time
from datetime import timedelta
from typing import Any, Dict

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_API_TOKEN,
    CONF_MQTT_HOST,
    CONF_MQTT_PORT,
    CONF_MQTT_USERNAME,
    DEFAULT_MQTT_PORT,
)
from .sydpower.connector import SydpowerConnector

_LOGGER = logging.getLogger(__name__)


class FossibotDataUpdateCoordinator(DataUpdateCoordinator):
    def __init__(
        self,
        hass: HomeAssistant,
        config: Dict[str, Any],
        update_interval: timedelta,
        config_entry=None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
            config_entry=config_entry,
        )
        self.connector = SydpowerConnector(
            api_token=config[CONF_API_TOKEN],
            mqtt_host=config[CONF_MQTT_HOST],
            mqtt_port=config.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT),
            mqtt_username=config.get(CONF_MQTT_USERNAME, ""),
        )
        self.connector.on_device_available = self._device_available
        self._shutdown_event = asyncio.Event()
        self._reconnection_task = None
        self._reconnection_in_progress = False
        self._failed_updates_count = 0
        self._last_successful_update = 0

    @callback
    def _device_available(self):
        if not self._shutdown_event.is_set():
            self.hass.async_create_background_task(
                self.async_request_refresh(), name="fossibot_device_available"
            )

    async def _async_update_data(self):
        if self._shutdown_event.is_set():
            raise UpdateFailed("Integration is shutting down")
        if self._reconnection_in_progress:
            raise UpdateFailed("MQTT transport recovery in progress")
        try:
            data = await asyncio.wait_for(self.connector.get_data(), timeout=30)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            self._failed_updates_count += 1
            if not self.connector.is_connected():
                self._trigger_reconnection()
            raise UpdateFailed(f"Fresh device read failed: {err}") from err
        if not data:
            self._failed_updates_count += 1
            if not self.connector.is_connected():
                self._trigger_reconnection()
            raise UpdateFailed("No fresh input-register response from device")
        self._failed_updates_count = 0
        self._last_successful_update = time.time()
        return data

    def _trigger_reconnection(self):
        if self._shutdown_event.is_set() or self._reconnection_in_progress:
            return
        self._reconnection_in_progress = True
        self._reconnection_task = self.hass.async_create_background_task(
            self._handle_reconnection(), name="fossibot_reconnection"
        )

    async def _handle_reconnection(self):
        success = False
        try:
            success = await self.connector.reconnect()
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("MQTT transport recovery failed")
        finally:
            self._reconnection_in_progress = False
        # Release the guard before requesting a fresh read, or that read
        # would reject its own successful recovery.
        if success and not self._shutdown_event.is_set():
            await self.async_request_refresh()

    async def async_shutdown(self):
        if self._shutdown_event.is_set():
            return
        self._shutdown_event.set()
        await super().async_shutdown()
        self.connector.on_device_available = None
        if self._reconnection_task and not self._reconnection_task.done():
            self._reconnection_task.cancel()
            await asyncio.gather(self._reconnection_task, return_exceptions=True)
        await self.connector.disconnect()

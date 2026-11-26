"""Main connector for Fossibot/Sydpower integration via local MQTT broker."""

import asyncio
import time

from .logger import SmartLogger
from .api_client import APIClient
from .mqtt_client import MQTTClient
from .modbus import (
    REGRequestSettings,
    REGDisableUSBOutput,
    REGEnableUSBOutput,
    REGDisableDCOutput,
    REGEnableDCOutput,
    REGDisableACOutput,
    REGEnableACOutput,
    REGDisableLED,
    REGEnableLEDAlways,
    REGEnableLEDSOS,
    REGEnableLEDFlash,
    REGDisableACSilentChg,
    REGEnableACSilentChg,
    get_read_modbus,
    get_read_input_modbus,
    get_write_modbus,
    ModbusValidationError,
)
from .const import (
    REGISTER_MODBUS_ADDRESS,
    REGISTER_MAXIMUM_CHARGING_CURRENT,
    DEFAULT_MQTT_PORT,
    MODBUS_READ_COUNT,
    MODBUS_MAX_READ_COUNT,
)

COMMANDS = {
    "REGRequestSettings": REGRequestSettings,
    "REGDisableUSBOutput": REGDisableUSBOutput,
    "REGEnableUSBOutput": REGEnableUSBOutput,
    "REGDisableDCOutput": REGDisableDCOutput,
    "REGEnableDCOutput": REGEnableDCOutput,
    "REGDisableACOutput": REGDisableACOutput,
    "REGEnableACOutput": REGEnableACOutput,
    "REGDisableLED": REGDisableLED,
    "REGEnableLEDAlways": REGEnableLEDAlways,
    "REGEnableLEDSOS": REGEnableLEDSOS,
    "REGEnableLEDFlash": REGEnableLEDFlash,
    "REGDisableACSilentChg": REGDisableACSilentChg,
    "REGEnableACSilentChg": REGEnableACSilentChg,
}


class SydpowerConnector:
    """Keep broker transport separate from fresh power-station telemetry."""

    def __init__(
        self, api_token, mqtt_host, mqtt_port=DEFAULT_MQTT_PORT, mqtt_username=""
    ):
        self.api_token = api_token
        self.mqtt_host = mqtt_host
        self.mqtt_port = mqtt_port
        self.mqtt_username = mqtt_username
        self._logger = SmartLogger(__name__)
        self.api_client = None
        self.mqtt_client = None
        self.loop = None
        self.devices = {}
        self.on_device_list = None
        self.on_device_available = None
        self._connection_lock = asyncio.Lock()
        self._io_lock = asyncio.Lock()
        self._reconnect_task = None
        self._background_tasks = set()
        self._closing = False
        self._last_successful_communication = 0

    @staticmethod
    def device_descriptors(devices):
        """Persist identity and protocol addressing only, never measurements."""
        result = {}
        if not isinstance(devices, dict):
            return result
        for mac, record in devices.items():
            if (
                not isinstance(mac, str)
                or len(mac) != 12
                or any(c not in "0123456789abcdefABCDEF" for c in mac)
                or not isinstance(record, dict)
            ):
                continue
            address = record.get("_modbus_address", REGISTER_MODBUS_ADDRESS)
            count = record.get("_modbus_count", MODBUS_READ_COUNT)
            if (
                type(address) is not int
                or not 1 <= address <= 247
                or type(count) is not int
                or count < 57
            ):
                continue
            count = min(count, MODBUS_MAX_READ_COUNT)
            result[mac] = {
                "_modbus_address": address,
                "_modbus_count": count,
                "_raw_device_id": ":".join(mac[i : i + 2] for i in range(0, 12, 2)),
            }
            raw_id = record.get("_raw_device_id")
            if (
                isinstance(raw_id, str)
                and raw_id.replace(":", "").lower() == mac.lower()
            ):
                result[mac]["_raw_device_id"] = raw_id
            name = record.get("device_name")
            if isinstance(name, str):
                result[mac]["device_name"] = name
            product = record.get("productInfo")
            if isinstance(product, dict):
                result[mac]["productInfo"] = {
                    key: product[key]
                    for key in ("product_name", "model", "device_model")
                    if isinstance(product.get(key), (str, int))
                }
        return result

    async def connect(self):
        """Serialize broker setup; an offline device does not invalidate it."""
        async with self._connection_lock:
            if self._closing:
                return False
            if self.is_connected():
                return True
            try:
                self.loop = asyncio.get_running_loop()
                if not self.devices:
                    if self.api_client is None:
                        self.api_client = APIClient(self.api_token)
                    devices = await asyncio.wait_for(
                        self.api_client.get_devices(), timeout=15
                    )
                    descriptors = self.device_descriptors(devices)
                    if not descriptors:
                        raise ValueError("No valid device identities available")
                    self.devices = descriptors
                    if self.on_device_list:
                        try:
                            await self.on_device_list(descriptors)
                        except Exception as err:
                            self._logger.warning(
                                "Cannot persist device identities: %s", err
                            )
                await self._cleanup_transport()
                client = MQTTClient(self.loop)
                client.on_disconnect_callback = self._handle_mqtt_disconnect
                client.on_device_state_callback = self._handle_device_state
                self.mqtt_client = client
                await asyncio.wait_for(
                    client.connect(
                        list(self.devices),
                        self.mqtt_host,
                        self.mqtt_port,
                        self.mqtt_username,
                    ),
                    timeout=20,
                )
                return self.is_connected()
            except asyncio.CancelledError:
                await self._cleanup_transport()
                raise
            except Exception as err:
                self._logger.warning("Broker connection failed: %s", err)
                await self._cleanup_transport()
                return False

    def _start_background(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_done)

    def _background_done(self, task):
        self._background_tasks.discard(task)
        if not task.cancelled():
            error = task.exception()
            if error:
                self._logger.debug("Optional cloud state sync failed: %s", error)

    async def _handle_device_state(self, device_mac, online):
        if self._closing or device_mac not in self.devices:
            return
        # Notify HA before any optional cloud traffic. The callback schedules
        # a fresh read; an online marker is never accepted as telemetry.
        if online and self.on_device_available:
            self.on_device_available()
        if self.api_client is None:
            self.api_client = APIClient(self.api_token)
        if self.api_client:
            self._start_background(
                asyncio.wait_for(
                    self.api_client.update_mqtt_state(
                        self.devices[device_mac]["_raw_device_id"], online
                    ),
                    timeout=10,
                )
            )

    async def get_data(self):
        if not await self.connect():
            return {}
        async with self._io_lock:
            return await self._poll_devices()

    async def _request_responses(self, client, func):
        # All stations share one response window. An offline station must
        # not consume the entire coordinator timeout before others are read.
        events = {}
        for mac in self.devices:
            key = (mac, func)
            event = client.response_events.setdefault(key, asyncio.Event())
            event.clear()
            client.responses.pop(key, None)
            events[mac] = event
        client.clear_message_cache()
        for mac in self.devices:
            self._send_read_request(mac, func)
        try:
            await asyncio.wait_for(
                asyncio.gather(*(event.wait() for event in events.values())),
                timeout=5,
            )
        except asyncio.TimeoutError:
            pass
        return {
            mac: client.responses[(mac, func)].copy()
            for mac, event in events.items()
            if event.is_set() and client.responses.get((mac, func))
        }

    async def _poll_devices(self):
        client = self.mqtt_client
        if not client or not client.connected.is_set():
            return {}
        fresh = {}
        settings = await self._request_responses(client, 3)
        sensors = await self._request_responses(client, 4)
        for mac in self.devices:
            self.devices[mac].update(settings.get(mac, {}))
            # A settings reply, retained packet or another device's reply
            # cannot make stale SoC/power available again.
            if mac in sensors:
                self.devices[mac].update(sensors[mac])
                fresh[mac] = self.devices[mac].copy()
                self._last_successful_communication = time.time()
        return fresh

    def _send_read_request(self, device_mac: str, func: int = 3) -> None:
        """Send either Modbus func 03 (holding) or func 04 (input) read using per-device address and count from API."""
        if not self.mqtt_client:
            return

        device_info = self.devices.get(device_mac, {})
        modbus_addr = device_info.get("_modbus_address", REGISTER_MODBUS_ADDRESS)
        modbus_count = device_info.get("_modbus_count", MODBUS_READ_COUNT)

        # The protocol caps a single read at 100 words and requires the range
        # to stay inside one 100-register block, so a larger count from the
        # API would produce a request the device cannot answer.
        if modbus_count > MODBUS_MAX_READ_COUNT:
            self._logger.warning(
                "API reported modbus_count=%d for %s, clamping to protocol "
                "maximum of %d",
                modbus_count,
                device_mac,
                MODBUS_MAX_READ_COUNT,
            )
            modbus_count = MODBUS_MAX_READ_COUNT

        if func == 3:
            # Send func 03 (holding registers)
            command_bytes_03 = get_read_modbus(modbus_addr, modbus_count)
            self.mqtt_client.publish_command(device_mac, command_bytes_03)
            self._logger.debug(
                "Sent func 03 to %s (addr=%d, count=%d)",
                device_mac,
                modbus_addr,
                modbus_count,
            )
        elif func == 4:
            # Send func 04 (input registers)
            command_bytes_04 = get_read_input_modbus(modbus_addr, modbus_count)
            self.mqtt_client.publish_command(device_mac, command_bytes_04)
            self._logger.debug(
                "Sent func 04 to %s (addr=%d, count=%d)",
                device_mac,
                modbus_addr,
                modbus_count,
            )
        else:
            self._logger.error("Invalid Modbus func: %d", func)

    async def run_command(self, device_id, command, value=None):
        if not await self.connect():
            return False
        async with self._io_lock:
            if not self.is_connected() or device_id not in self.devices:
                return False
            return await self._run_command_locked(device_id, command, value)

    async def _run_command_locked(
        self, device_id: str, command: str, value=None
    ) -> bool:
        """Run a command on a device. Returns True if successful."""
        # Resolve command bytes
        if command in COMMANDS:
            command_bytes = COMMANDS[command]
        elif command == "write_register" and value is not None:
            register, reg_value = value
            device_info = self.devices.get(device_id, {})
            modbus_addr = device_info.get("_modbus_address", REGISTER_MODBUS_ADDRESS)

            # Holding 20 is bounded by holding 17 ("DC Input Max Curr"), which
            # is device-specific and therefore cannot live in the static
            # allowlist. Enforce it here as well as in the number entity, so
            # a service call that bypasses the UI is still checked.
            if register == REGISTER_MAXIMUM_CHARGING_CURRENT:
                device_max = device_info.get("dcInputMaxCurrent")
                if isinstance(device_max, int) and 0 < device_max < reg_value:
                    self._logger.error(
                        "Refused to write %d A to register %d: device reports "
                        "a maximum DC charging current of %d A",
                        reg_value,
                        register,
                        device_max,
                    )
                    return False

            try:
                command_bytes = get_write_modbus(
                    modbus_addr,
                    register,
                    reg_value,
                )
            except ModbusValidationError as e:
                self._logger.error("Refused to write: %s", e)
                return False
        else:
            self._logger.error("Unknown command: %s", command)
            return False

        if not self.mqtt_client:
            self._logger.error("MQTT client is None")
            return False

        try:
            self._logger.debug("Sending command: %s", command)
            if not self.mqtt_client.publish_command(device_id, command_bytes):
                return False
            await asyncio.sleep(1)  # Allow device to process
            return True
        except Exception as e:
            self._logger.error("Error publishing command: %s", e)
            return False

    async def reconnect(self):
        if self._closing:
            return False
        if self.is_connected():
            return True
        # All callers share one recovery task; cancellation of a poll must
        # not cancel another caller's broker recovery.
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())
        return await asyncio.shield(self._reconnect_task)

    async def _reconnect_loop(self):
        for attempt in range(5):
            if self._closing:
                return False
            if await self.connect():
                return True
            if attempt < 4:
                await asyncio.sleep(min(2**attempt, 15))
        return False

    async def _handle_mqtt_disconnect(self, rc):
        if not self._closing:
            self._logger.warning("MQTT transport disconnected: %s", rc)
            await self.reconnect()

    async def _cleanup_transport(self):
        # Polls and writes own the same lock, so cleanup cannot replace their
        # client halfway through a response or create NoneType races.
        async with self._io_lock:
            client, self.mqtt_client = self.mqtt_client, None
            if client:
                await client.disconnect()

    async def disconnect(self):
        self._closing = True
        tasks = list(self._background_tasks)
        if self._reconnect_task and not self._reconnect_task.done():
            tasks.append(self._reconnect_task)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self._connection_lock:
            await self._cleanup_transport()
            if self.api_client:
                await self.api_client.close()
                self.api_client = None

    def is_connected(self):
        return bool(self.mqtt_client and self.mqtt_client.connected.is_set())

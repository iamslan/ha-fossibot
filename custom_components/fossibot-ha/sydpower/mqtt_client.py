# mqtt_client.py
"""MQTT client for Fossibot devices via local MQTT broker."""

import asyncio
import time
import random
import threading
from typing import Any, Callable, Coroutine, Dict, List, Optional

import paho.mqtt.client as mqtt

from .const import DEFAULT_MQTT_PORT
from .logger import SmartLogger
from .modbus import (
    MIN_DATA_REGISTERS,
    REGRequestSettings,
    high_low_to_int,
    parse_registers,
)
from .registers_v1 import detect_protocol

CONNECTION_CODES = {
    0: "Connection successful",
    1: "Incorrect protocol version",
    2: "Invalid client identifier",
    3: "Server unavailable",
    4: "Bad username or password",
    5: "Not authorized",
}


class MQTTClient:
    """MQTT client for Fossibot device communication via local broker."""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.mqtt_client: Optional[mqtt.Client] = None
        self.connected = asyncio.Event()
        self.data_updated = asyncio.Event()
        self.response_events = {}
        self.responses = {}
        self.loop = loop
        self._logger = SmartLogger(__name__)

        # Device data
        self.devices: Dict[str, Any] = {}
        # Register profile per device (0 = V0, 1 = V1), learned from the
        # holding frame, which the poll requests before the input frame.
        self._protocol: Dict[str, int] = {}
        self._device_data_lock = asyncio.Lock()

        # Message deduplication
        self._message_cache: Dict[str, float] = {}
        self._message_cache_ttl = 2
        self._last_cache_cleanup = 0
        self._message_cache_lock = threading.RLock()

        # State tracking
        self._last_successful_communication = time.time()
        self._is_disconnecting = False
        self._subscribed_topics: List[str] = []

        # Device online/offline state
        self._device_online: Dict[str, bool] = {}

        # Custom message handlers
        self._message_handlers: Dict[str, Callable[[str, List[int]], Coroutine]] = {}

        # Callbacks
        self.on_disconnect_callback: Optional[Callable] = None
        self.on_device_state_callback: Optional[Callable] = None

    async def connect(
        self,
        device_ids: List[str],
        mqtt_host: str,
        mqtt_port: int = DEFAULT_MQTT_PORT,
        mqtt_username: str = "",
    ) -> None:
        """Connect to local MQTT broker and subscribe to device topics."""
        try:
            self._logger.debug(
                "Starting MQTT connection to %s:%s", mqtt_host, mqtt_port
            )
            self._is_disconnecting = False
            self.connected.clear()

            hex_string = "".join(random.choice("0123456789abcdef") for _ in range(24))
            timestamp_ms = int(time.time() * 1000)
            client_id = f"fossibot_ha_{hex_string}_{timestamp_ms}"

            self.mqtt_client = mqtt.Client(
                client_id=client_id,
                clean_session=True,
                transport="tcp",
                protocol=mqtt.MQTTv311,
            )

            # Username auth only — password not required per SYDPOWER docs
            if mqtt_username:
                self.mqtt_client.username_pw_set(username=mqtt_username)

            self.mqtt_client.on_connect = self._on_connect
            self.mqtt_client.on_message = self._on_message
            self.mqtt_client.on_disconnect = self._on_disconnect

            self._device_ids = device_ids

            await asyncio.to_thread(
                self.mqtt_client.connect, mqtt_host, mqtt_port, keepalive=30
            )
            self.mqtt_client.loop_start()

            try:
                await asyncio.wait_for(self.connected.wait(), timeout=30.0)
                self._logger.debug("MQTT connection established successfully")
            except asyncio.TimeoutError:
                self._logger.error("MQTT connection timeout after 30 seconds")
                await self.disconnect()
                raise

        except asyncio.CancelledError:
            await self.disconnect()
            raise
        except Exception as e:
            self._logger.error("MQTT connection failed: %s", e)
            await self.disconnect()
            raise

    def seed_protocols(self, protocols: Dict[str, int]) -> None:
        """Register profiles known from an earlier session.

        Input frames are only decoded once a station's profile is known, so
        seeding lets the first poll after a restart decode even if its
        settings reply is lost. A settings frame still overrides the seed.
        """
        for mac, protocol in protocols.items():
            self._protocol.setdefault(mac, protocol)

    def _on_connect(self, client, userdata, flags, rc):
        """Callback when MQTT connects."""
        self._logger.debug(
            "MQTT connect result: %s (%s)",
            rc,
            CONNECTION_CODES.get(rc, "Unknown error"),
        )

        if rc != 0:
            self._logger.error(
                "MQTT connection refused: %s",
                CONNECTION_CODES.get(rc, "Unknown error"),
            )
            return

        # Unsubscribe from any prior topics
        for topic in self._subscribed_topics:
            client.unsubscribe(topic)
        self._subscribed_topics = []

        subscribe_topics = []
        for device_mac in self._device_ids:
            topics = [
                (f"{device_mac}/device/response/state", 1),
                (f"{device_mac}/device/response/client/+", 1),
            ]
            for topic, qos in topics:
                subscribe_topics.append((topic, qos))
                self._subscribed_topics.append(topic)

        if not subscribe_topics:
            self._logger.error("No devices found to subscribe to")
            return

        client.subscribe(subscribe_topics)
        self._logger.debug("Subscribed to %d topics", len(subscribe_topics))

        # Connector reads after subscription, using each device's address.
        self.loop.call_soon_threadsafe(self.connected.set)

    def _on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages with deduplication."""
        try:
            topic = msg.topic
            payload = msg.payload

            # Handle device connection state messages (1 = online, 0 = offline)
            if topic.endswith("/device/response/state"):
                self._handle_state_message(topic, payload)
                return

            # A retained measurement predates this connection/read and must
            # never restore availability of stale battery or power values.
            if msg.retain:
                return

            payload_list = list(payload)

            # Deduplication
            message_id = f"{topic}:{hash(bytes(payload_list))}"
            current_time = time.time()

            with self._message_cache_lock:
                if current_time - self._last_cache_cleanup > 30:
                    expired = [
                        k
                        for k, v in self._message_cache.items()
                        if current_time - v > self._message_cache_ttl
                    ]
                    for key in expired:
                        del self._message_cache[key]
                    self._last_cache_cleanup = current_time

                if (
                    message_id in self._message_cache
                    and current_time - self._message_cache[message_id]
                    < self._message_cache_ttl
                ):
                    age = current_time - self._message_cache[message_id]
                    self._logger.debug(
                        "Dedup: dropping duplicate on %s (%.1fs old)",
                        topic.split("/", 1)[1] if "/" in topic else topic,
                        age,
                    )
                    return
                self._message_cache[message_id] = current_time

            # Filter short/invalid messages
            if len(payload_list) < 8:
                return

            data_bytes = payload_list[6:]

            if len(data_bytes) % 2 != 0:
                self._logger.warning("Odd byte count in payload from %s", topic)
                return

            registers = [
                high_low_to_int(data_bytes[i], data_bytes[i + 1])
                for i in range(0, len(data_bytes), 2)
            ]

            if len(registers) < MIN_DATA_REGISTERS:
                # Short responses (e.g. 1 register) are normal write ACKs
                self._logger.debug(
                    "Short response (%d registers) from %s — likely write ACK",
                    len(registers),
                    topic,
                )
                return

            device_mac = topic.split("/")[0]

            if device_mac in self._message_handlers:
                asyncio.run_coroutine_threadsafe(
                    self._message_handlers[device_mac](topic, registers),
                    self.loop,
                )
                return

            if "client/data" in topic:
                protocol = detect_protocol(registers)
                if self._protocol.get(device_mac) != protocol:
                    self._logger.info(
                        "Device %s uses register profile V%d", device_mac, protocol,
                    )
                self._protocol[device_mac] = protocol
            elif device_mac not in self._protocol:
                # Input words mean different things per profile; wait for
                # the holding frame rather than decode with the wrong table.
                self._logger.debug(
                    "Profile of %s unknown yet, skipping input frame", device_mac,
                )
                return

            device_update = parse_registers(
                registers, topic, self._protocol.get(device_mac, 0)
            )
            if device_update and "client/data" in topic:
                device_update.setdefault(
                    "protocolProfile", self._protocol[device_mac]
                )

            # Determine topic type for logging
            if "client/04" in topic:
                topic_tag = "sensors"
            elif "client/data" in topic:
                topic_tag = "settings"
            else:
                topic_tag = "other"

            if device_update:
                self._logger.debug(
                    "Device %s [%s]: %d fields — %s",
                    device_mac,
                    topic_tag,
                    len(device_update),
                    sorted(device_update.keys()),
                )
                asyncio.run_coroutine_threadsafe(
                    self._update_device_data(
                        device_mac,
                        device_update,
                        4 if topic.endswith("/04") else 3,
                    ),
                    self.loop,
                )
            else:
                self._logger.warning("No data extracted from message on %s", topic)

        except Exception as e:
            self._logger.error("Error processing MQTT message: %s", e)

    def _handle_state_message(self, topic: str, payload: bytes):
        """Handle device online/offline state messages.

        The device publishes '1' (online) or '0' (offline) to
        {MAC}/device/response/state.
        """
        device_mac = topic.split("/")[0]

        try:
            state_str = payload.decode("utf-8").strip()
        except (UnicodeDecodeError, AttributeError):
            # Fallback: interpret raw bytes
            state_str = str(payload[0]) if payload else ""

        if state_str not in ("0", "1"):
            return
        online = state_str == "1"
        prev_state = self._device_online.get(device_mac)
        self._device_online[device_mac] = online

        self._logger.info(
            "Device %s state: %s (was %s)",
            device_mac,
            "online" if online else "offline",
            "online"
            if prev_state
            else ("offline" if prev_state is not None else "unknown"),
        )

        # Notify connector to sync state with platform API
        if self.on_device_state_callback and online != prev_state:
            asyncio.run_coroutine_threadsafe(
                self.on_device_state_callback(device_mac, online),
                self.loop,
            )

    def is_device_online(self, device_mac: str) -> bool:
        """Check if a device is reported as online via the state topic."""
        return self._device_online.get(device_mac, False)

    async def _update_device_data(self, device_mac, device_update, func):
        """Update device data safely."""
        async with self._device_data_lock:
            if device_mac not in self.devices:
                self.devices[device_mac] = {}
            self.devices[device_mac].update(device_update)
            key = (device_mac, func)
            self.responses[key] = device_update.copy()
            self.response_events.setdefault(key, asyncio.Event()).set()
            self._last_successful_communication = time.time()
            self.data_updated.set()
            self._logger.debug(
                "Device %s total: %d fields accumulated",
                device_mac,
                len(self.devices[device_mac]),
            )

    def _on_disconnect(self, client, userdata, rc):
        """Handle MQTT disconnection."""
        self._logger.debug("MQTT disconnected with code: %s", rc)

        if self._is_disconnecting:
            return

        self.loop.call_soon_threadsafe(self.connected.clear)

        if rc != 0:
            self._logger.warning("Unexpected MQTT disconnection (code %s)", rc)
            self.loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self._handle_disconnect_callback(rc))
            )

    async def _handle_disconnect_callback(self, rc):
        """Handle disconnect callback in async context."""
        if self.on_disconnect_callback:
            try:
                await self.on_disconnect_callback(rc)
            except Exception as e:
                self._logger.error("Error in disconnect callback: %s", e)

    def publish_command(self, device_id: str, command: List[int]) -> bool:
        """Publish a command to a device."""
        if not self.mqtt_client or not self.mqtt_client.is_connected():
            self._logger.error("Cannot send command: MQTT not connected")
            return False

        try:
            topic = f"{device_id}/client/request/data"
            result = self.mqtt_client.publish(topic, bytes(command), qos=1)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                self._logger.warning("MQTT publish failed: %s", result.rc)
                return False
            return True
        except Exception as e:
            self._logger.error("Error publishing command: %s", e)
            return False

    def register_message_handler(self, device_id: str, handler: Callable) -> None:
        """Register a custom message handler for a device."""
        self._message_handlers[device_id] = handler

    def clear_message_cache(self) -> None:
        """Clear the deduplication cache so the next response is not swallowed."""
        with self._message_cache_lock:
            self._message_cache.clear()

    def request_data_update(self, device_id: str) -> None:
        """Request a data update from a device."""
        self.publish_command(device_id, REGRequestSettings)

    async def disconnect(self) -> None:
        """Disconnect from the MQTT broker."""
        if self.mqtt_client:
            try:
                self._is_disconnecting = True
                self.connected.clear()
                self.data_updated.clear()
                await asyncio.to_thread(self.mqtt_client.disconnect)
                await asyncio.to_thread(self.mqtt_client.loop_stop)
                self._logger.debug("MQTT client disconnected")
            except Exception as e:
                self._logger.error("Error during MQTT disconnect: %s", e)
            finally:
                self.mqtt_client = None
                self._is_disconnecting = False

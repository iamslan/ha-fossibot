"""Offline recovery regressions using the real integration modules.

Only broker/cloud/framework hosting is stubbed; no device or network is used.
"""

import asyncio
import importlib
import importlib.util
import logging
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.update_coordinator import UpdateFailed

from fossibot_ha.sydpower import modbus
from fossibot_ha.sydpower import connector as connector_module
from fossibot_ha.sydpower import mqtt_client as mqtt_client_module

MAC = "AABBCCDDEEFF"
OTHER = "000000000001"
logger = logging.getLogger("fossibot_recovery_test")
logger.addHandler(logging.NullHandler())
Connector = connector_module.SydpowerConnector


class FakeCloud:
    calls = 0
    updates = []
    fail_discovery = False
    extra_devices = {}

    def __init__(self, token):
        self.closed = False

    async def get_devices(self):
        FakeCloud.calls += 1
        if FakeCloud.fail_discovery:
            raise OSError("cloud unreachable")
        return {
            **FakeCloud.extra_devices,
            MAC: {
                "_modbus_address": 17,
                "_modbus_count": 80,
                "device_name": "F2400-B",
                "soc": 100,
                "api_token": "must-not-be-persisted",
            }
        }

    async def close(self):
        self.closed = True

    async def update_mqtt_state(self, *args):
        FakeCloud.updates.append(args)
        return True


class FakeBroker:
    instances = []
    station_online = True
    fail_connect = False
    settings_only = False
    wrong_response = False
    offline_macs = set()

    def __init__(self, loop):
        FakeBroker.instances.append(self)
        self.connected = asyncio.Event()
        self.response_events = {}
        self.responses = {}
        self.disconnect_count = 0
        self.published = []
        self.on_disconnect_callback = None
        self.on_device_state_callback = None

    async def connect(self, *args):
        await asyncio.sleep(0)
        if FakeBroker.fail_connect:
            raise OSError("broker offline")
        self.connected.set()

    async def disconnect(self):
        self.disconnect_count += 1
        self.connected.clear()

    def clear_message_cache(self):
        pass

    def seed_protocols(self, protocols):
        self.seeded_protocols = dict(protocols)

    def publish_command(self, mac, frame):
        self.published.append((mac, frame))
        func = frame[1]
        if (
            not FakeBroker.station_online
            or mac in FakeBroker.offline_macs
            or (FakeBroker.settings_only and func == 4)
        ):
            return True
        if func in (3, 4):
            key = (OTHER, 3) if FakeBroker.wrong_response else (mac, func)
            self.responses[key] = (
                {"acOutput": True, "gridAcAutoOutput": False}
                if func == 3
                else {"soc": 85.2, "totalOutput": 300}
            )
            self.response_events.setdefault(key, asyncio.Event()).set()
        return True


class FakeHass:
    def __init__(self):
        self.data = {}
        self.tasks = []
        self.config_entries = self

    def async_create_background_task(self, coro, name):
        task = asyncio.create_task(coro, name=name)
        self.tasks.append(task)
        return task

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwarded = platforms

    async def async_unload_platforms(self, *args):
        return True


class FakeStore:
    value = None

    def __init__(self, *args):
        pass

    async def async_load(self):
        return FakeStore.value

    async def async_save(self, data):
        FakeStore.value = data

    async def async_remove(self):
        FakeStore.value = None


# Execute the real setup module using the framework stubs from conftest.
sys.modules["homeassistant.helpers.storage"].Store = FakeStore
Coordinator = importlib.import_module(
    "fossibot_ha.coordinator"
).FossibotDataUpdateCoordinator

integration_module = sys.modules["fossibot_ha"]
spec = importlib.util.spec_from_file_location(
    "fossibot_ha",
    Path(integration_module.__path__[0]) / "__init__.py",
)
integration_module.__spec__ = spec
integration_module.__package__ = "fossibot_ha"
spec.loader.exec_module(integration_module)


def new_connector():
    result = Connector("test-token", "test-broker")
    result.devices = Connector.device_descriptors({MAC: {}})
    return result


class ReconnectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for name, replacement in (
            ("APIClient", FakeCloud),
            ("MQTTClient", FakeBroker),
            ("SmartLogger", lambda name: logger),
        ):
            patcher = patch.object(connector_module, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        FakeCloud.calls = 0
        FakeCloud.updates = []
        FakeCloud.fail_discovery = False
        FakeCloud.extra_devices = {}
        FakeBroker.instances.clear()
        FakeBroker.station_online = True
        FakeBroker.fail_connect = False
        FakeBroker.settings_only = False
        FakeBroker.wrong_response = False
        FakeBroker.offline_macs = set()
        FakeStore.value = None
        self.connectors = []
        self.original_wait_for = asyncio.wait_for

        async def fast_wait(awaitable, timeout):
            return await self.original_wait_for(awaitable, min(timeout, 0.03))

        self.fast_wait_patch = patch.object(asyncio, "wait_for", fast_wait)
        self.fast_wait_patch.start()

    async def asyncTearDown(self):
        for connector in self.connectors:
            await connector.disconnect()
        self.fast_wait_patch.stop()

    def connector(self):
        result = new_connector()
        self.connectors.append(result)
        return result

    async def test_cached_identity_connects_without_cloud(self):
        FakeCloud.fail_discovery = True
        c = self.connector()
        self.assertTrue(await c.connect())
        data = await c.get_data()
        self.assertEqual(data[MAC]["soc"], 85.2)

    async def test_cached_start_refreshes_discovery_in_background(self):
        c = self.connector()
        saved = []

        async def save(value):
            saved.append(value)

        c.on_device_list = save
        FakeCloud.extra_devices = {OTHER: {"device_name": "Second"}}
        self.assertTrue(await c.connect())
        await asyncio.sleep(0.01)
        self.assertEqual(FakeCloud.calls, 1)
        # Known station renamed in place; the new one is saved for the next
        # reload but not polled by a client that never subscribed to it.
        self.assertEqual(c.devices[MAC]["device_name"], "F2400-B")
        self.assertNotIn(OTHER, c.devices)
        self.assertEqual(saved[-1][OTHER]["device_name"], "Second")
        await c.connect()
        await asyncio.sleep(0.01)
        self.assertEqual(FakeCloud.calls, 1)

    async def test_learned_profile_is_persisted_and_seeded(self):
        c = self.connector()
        saved = []

        async def save(value):
            saved.append(value)

        c.on_device_list = save
        c.devices[MAC]["protocolProfile"] = 1
        await c.get_data()
        await asyncio.sleep(0.01)
        self.assertEqual(saved[-1][MAC]["protocolProfile"], 1)
        restarted = self.connector()
        restarted.load_cached_devices(saved[-1])
        await restarted.connect()
        self.assertEqual(restarted.mqtt_client.seeded_protocols, {MAC: 1})

    async def test_v0_commands_are_refused_on_v1_station(self):
        c = self.connector()
        await c.connect()
        c.devices[MAC]["protocolProfile"] = 1
        client = c.mqtt_client
        self.assertFalse(await c.run_command(MAC, "REGEnableACOutput"))
        self.assertFalse(await c.run_command(MAC, "write_register", (57, 1)))
        self.assertEqual(client.published, [])

    async def test_fresh_read_syncs_cloud_after_cached_start_without_online_marker(
        self,
    ):
        c = self.connector()
        await c.get_data()
        await asyncio.sleep(0.01)
        self.assertEqual(FakeCloud.calls, 1)  # background discovery refresh
        self.assertEqual(FakeCloud.updates, [("AA:BB:CC:DD:EE:FF", True)])
        await c.get_data()
        await asyncio.sleep(0.01)
        self.assertEqual(len(FakeCloud.updates), 1)

    async def test_initial_discovery_persists_no_telemetry_or_credentials(self):
        c = self.connector()
        c.devices = {}
        saved = []

        async def save(value):
            saved.append(value)

        c.on_device_list = save
        self.assertTrue(await c.connect())
        self.assertEqual(FakeCloud.calls, 1)
        self.assertEqual(saved[0][MAC]["device_name"], "F2400-B")
        self.assertNotIn("soc", saved[0][MAC])
        self.assertNotIn("api_token", saved[0][MAC])

    async def test_concurrent_connect_has_one_client(self):
        c = self.connector()
        self.assertEqual(await asyncio.gather(c.connect(), c.connect()), [True, True])
        self.assertEqual(len(FakeBroker.instances), 1)

    async def test_reconnect_reaches_broker_without_self_wait(self):
        c = self.connector()
        await c.connect()
        old = c.mqtt_client
        old.connected.clear()
        self.assertTrue(await self.original_wait_for(c.reconnect(), 0.2))
        self.assertIsNot(c.mqtt_client, old)
        self.assertEqual(old.disconnect_count, 1)
        # Only the one background discovery refresh of the first start;
        # broker recovery never goes back to the cloud.
        self.assertEqual(FakeCloud.calls, 1)

    async def test_concurrent_reconnect_has_one_replacement(self):
        c = self.connector()
        await c.connect()
        c.mqtt_client.connected.clear()
        self.assertEqual(
            await asyncio.gather(c.reconnect(), c.reconnect()), [True, True]
        )
        self.assertEqual(len(FakeBroker.instances), 2)

    async def test_station_off_keeps_subscription_and_returns_no_cached_soc(self):
        c = self.connector()
        self.assertIn(MAC, await c.get_data())
        old = c.mqtt_client
        FakeBroker.station_online = False
        self.assertEqual(await c.get_data(), {})
        self.assertTrue(await c.reconnect())
        self.assertIs(c.mqtt_client, old)
        self.assertEqual(old.disconnect_count, 0)

    async def test_station_return_recovers_on_next_read_without_reconnect(self):
        c = self.connector()
        FakeBroker.station_online = False
        self.assertEqual(await c.get_data(), {})
        old = c.mqtt_client
        FakeBroker.station_online = True
        self.assertEqual((await c.get_data())[MAC]["soc"], 85.2)
        self.assertIs(c.mqtt_client, old)

    async def test_settings_reply_does_not_restore_cached_live_data(self):
        c = self.connector()
        await c.get_data()
        FakeBroker.settings_only = True
        self.assertEqual(await c.get_data(), {})

    async def test_other_device_or_function_cannot_complete_requested_read(self):
        c = self.connector()
        FakeBroker.wrong_response = True
        self.assertEqual(await c.get_data(), {})

    async def test_offline_station_does_not_hide_another_online_station(self):
        c = self.connector()
        c.devices = Connector.device_descriptors({MAC: {}, OTHER: {}})
        FakeBroker.offline_macs = {MAC}
        data = await self.original_wait_for(c.get_data(), 0.2)
        self.assertNotIn(MAC, data)
        self.assertEqual(data[OTHER]["soc"], 85.2)

    async def test_descriptor_validation_preserves_address_count_and_raw_id(self):
        data = Connector.device_descriptors(
            {
                MAC: {
                    "_modbus_address": 23,
                    "_modbus_count": 120,
                    "_raw_device_id": "aa:bb:cc:dd:ee:ff",
                }
            }
        )
        self.assertEqual(data[MAC]["_modbus_address"], 23)
        self.assertEqual(data[MAC]["_modbus_count"], 100)
        self.assertEqual(data[MAC]["_raw_device_id"], "aa:bb:cc:dd:ee:ff")
        self.assertEqual(
            Connector.device_descriptors({MAC: {"_modbus_address": 0}}), {}
        )

    async def test_cloud_state_sync_does_not_block_local_online_notification(self):
        c = self.connector()
        calls = []
        c.on_device_available = lambda: calls.append("local_refresh")
        gate = asyncio.Event()

        async def cloud_update(*args):
            await gate.wait()

        c.api_client = FakeCloud("test")
        c.api_client.update_mqtt_state = cloud_update
        await self.original_wait_for(c._handle_device_state(MAC, True), 0.1)
        self.assertEqual(calls, ["local_refresh"])
        self.assertEqual(len(c._background_tasks), 1)

    async def test_offline_poll_does_not_start_coordinator_reconnection(self):
        h = FakeHass()
        co = Coordinator(h, {"api_token": "test", "mqtt_host": "test"}, None)
        self.connectors.append(co.connector)
        co.connector.devices = Connector.device_descriptors({MAC: {}})
        FakeBroker.station_online = False
        for _ in range(3):
            with self.assertRaises(UpdateFailed):
                await co._async_update_data()
        self.assertFalse(co._reconnection_in_progress)
        self.assertEqual(len(FakeBroker.instances), 1)

    async def test_reconnect_refresh_runs_after_guard_is_released(self):
        h = FakeHass()
        co = Coordinator(h, {"api_token": "test", "mqtt_host": "test"}, None)
        self.connectors.append(co.connector)
        co.connector.devices = Connector.device_descriptors({MAC: {}})
        co._reconnection_in_progress = True
        await co._handle_reconnection()
        self.assertTrue(co.last_update_success)
        self.assertFalse(co._reconnection_in_progress)

    async def test_setup_offline_with_saved_identity_keeps_unavailable_entities(self):
        FakeStore.value = Connector.device_descriptors({MAC: {}})
        FakeBroker.station_online = False
        FakeCloud.fail_discovery = True
        h = FakeHass()
        entry = types.SimpleNamespace(
            entry_id="test-entry", data={"api_token": "test", "mqtt_host": "test"}
        )
        self.assertTrue(await integration_module.async_setup_entry(h, entry))
        co = h.data["fossibot"]["test-entry"]
        self.connectors.append(co.connector)
        self.assertFalse(co.last_update_success)
        self.assertEqual(co.data, {MAC: {}})
        self.assertTrue(co.connector.is_connected())
        FakeBroker.station_online = True
        await co.async_request_refresh()
        self.assertTrue(co.last_update_success)
        await integration_module.async_unload_entry(h, entry)
        self.assertTrue(co.base_shutdown_called)

    async def test_shutdown_cancels_shared_recovery(self):
        c = self.connector()
        FakeBroker.fail_connect = True
        task = asyncio.create_task(c.reconnect())
        await asyncio.sleep(0.01)
        await c.disconnect()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(c._reconnect_task.done())
        self.assertFalse(await c.connect())

    async def test_failed_setup_closes_transport_and_recovery_tasks(self):
        FakeBroker.fail_connect = True
        h = FakeHass()
        entry = types.SimpleNamespace(
            entry_id="test-entry", data={"api_token": "test", "mqtt_host": "test"}
        )
        with self.assertRaises(ConfigEntryNotReady):
            await integration_module.async_setup_entry(h, entry)
        self.assertNotIn("test-entry", h.data["fossibot"])
        self.assertTrue(all(not c.connected.is_set() for c in FakeBroker.instances))
        self.assertTrue(all(task.done() for task in h.tasks))

    async def test_platform_setup_failure_cleans_up_coordinator(self):
        h = FakeHass()

        async def fail_platform(*args):
            raise RuntimeError("platform failed")

        h.async_forward_entry_setups = fail_platform
        entry = types.SimpleNamespace(
            entry_id="test-entry", data={"api_token": "test", "mqtt_host": "test"}
        )
        with self.assertRaisesRegex(RuntimeError, "platform failed"):
            await integration_module.async_setup_entry(h, entry)
        self.assertNotIn("test-entry", h.data["fossibot"])
        self.assertTrue(all(not c.connected.is_set() for c in FakeBroker.instances))

    async def test_removing_entry_removes_saved_identities(self):
        FakeStore.value = Connector.device_descriptors({MAC: {}})
        await integration_module.async_remove_entry(
            FakeHass(), types.SimpleNamespace(entry_id="test-entry")
        )
        self.assertIsNone(FakeStore.value)

    async def test_register_allowlist_is_preserved(self):
        c = self.connector()
        await c.connect()
        client = c.mqtt_client
        self.assertFalse(await c.run_command(MAC, "write_register", (0, 1)))
        self.assertFalse(await c.run_command(MAC, "write_register", (67, 500)))
        self.assertEqual(client.published, [])

    async def test_cleanup_waits_for_inflight_poll(self):
        c = self.connector()
        await c.connect()
        FakeBroker.station_online = False
        poll = asyncio.create_task(c.get_data())
        await asyncio.sleep(0.005)
        close = asyncio.create_task(c.disconnect())
        self.assertEqual(await poll, {})
        await close
        self.assertIsNone(c.mqtt_client)


class MQTTTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.module = mqtt_client_module
        for name, replacement in (
            ("mqtt", types.SimpleNamespace(Client=object, MQTT_ERR_SUCCESS=0)),
            ("SmartLogger", lambda name: logger),
        ):
            patcher = patch.object(self.module, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = self.module.MQTTClient(asyncio.get_running_loop())
        self.client.seed_protocols({MAC: 0})

    async def test_retained_measurement_is_not_accepted(self):
        msg = types.SimpleNamespace(
            topic=MAC + "/device/response/client/04", payload=bytes(168), retain=True
        )
        self.client._on_message(None, None, msg)
        await asyncio.sleep(0)
        self.assertEqual(self.client.responses, {})

    async def test_real_input_frame_decodes_and_signals_only_input_response(self):
        registers = [0] * 80
        registers[56] = 852
        registers[39] = 123
        data = [byte for value in registers for byte in (value >> 8, value & 255)]
        msg = types.SimpleNamespace(
            topic=MAC + "/device/response/client/04",
            payload=bytes(modbus.sa(17, 4, [0, 0, 0, 80] + data, False)),
            retain=False,
        )
        self.client._on_message(None, None, msg)
        await asyncio.sleep(0.01)
        self.assertEqual(self.client.responses[(MAC, 4)]["soc"], 85.2)
        self.assertEqual(self.client.responses[(MAC, 4)]["totalOutput"], 123)
        self.assertNotIn((MAC, 3), self.client.responses)

    async def test_only_matching_function_event_is_set(self):
        await self.client._update_device_data(MAC, {"soc": 80}, 4)
        self.assertTrue(self.client.response_events[(MAC, 4)].is_set())
        self.assertNotIn((MAC, 3), self.client.response_events)
        self.assertNotIn((OTHER, 4), self.client.response_events)

    async def test_state_deduplicates_online_but_allows_return_after_offline(self):
        calls = []

        async def available(mac, online):
            calls.append(online)

        self.client.on_device_state_callback = available
        topic = MAC + "/device/response/state"
        for payload in (b"1", b"1", b"invalid", b"0", b"1"):
            self.client._handle_state_message(topic, payload)
        await asyncio.sleep(0.01)
        self.assertEqual(calls, [True, False, True])

    async def test_publish_failure_is_reported(self):
        self.client.mqtt_client = types.SimpleNamespace(
            is_connected=lambda: True,
            publish=lambda *args, **kwargs: types.SimpleNamespace(rc=4),
        )
        self.assertFalse(self.client.publish_command(MAC, [17, 3]))

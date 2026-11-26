"""Regression tests for reported issues (#39, #40, #41)."""

import asyncio

from fossibot_ha.entity import FossibotEntity, device_profile
from fossibot_ha.switch import FossibotSwitch
from fossibot_ha.sydpower.const import IREG_BATTERY_USABLE_CAPACITY
from fossibot_ha.sydpower.modbus import parse_registers

MAC = "AABBCCDDEEFF"


class _Connector:
    def __init__(self, devices=None):
        self.devices = devices or {}
        self.commands = []

    async def run_command(self, device_id, command, value=None):
        self.commands.append((device_id, command))
        return True


class _Coordinator:
    def __init__(self, data, success=True, devices=None):
        self.data = data
        self.last_update_success = success
        self.connector = _Connector(devices)
        self.refreshes = 0

    async def async_request_refresh(self):
        self.refreshes += 1


def _ac_switch(coordinator):
    switch = object.__new__(FossibotSwitch)
    switch.coordinator = coordinator
    switch._device_id = MAC
    switch._key = "acOutput"
    switch._on_command = "REGEnableACOutput"
    switch._off_command = "REGDisableACOutput"
    return switch


class TestOutputSwitchesDoNotToggleBlindly:
    """#40: the F2400 firmware toggles the output on any write."""

    def test_turn_on_when_already_on_sends_nothing(self):
        co = _Coordinator({MAC: {"acOutput": True}})
        asyncio.run(_ac_switch(co).async_turn_on())
        assert co.connector.commands == []

    def test_turn_off_when_already_off_sends_nothing(self):
        co = _Coordinator({MAC: {"acOutput": False}})
        asyncio.run(_ac_switch(co).async_turn_off())
        assert co.connector.commands == []

    def test_turn_on_when_off_sends_the_command(self):
        co = _Coordinator({MAC: {"acOutput": False}})
        asyncio.run(_ac_switch(co).async_turn_on())
        assert co.connector.commands == [(MAC, "REGEnableACOutput")]
        assert co.refreshes == 1

    def test_unknown_state_still_sends(self):
        co = _Coordinator({MAC: {}})
        asyncio.run(_ac_switch(co).async_turn_on())
        assert co.connector.commands == [(MAC, "REGEnableACOutput")]

    def test_stale_state_after_failed_poll_still_sends(self):
        co = _Coordinator({MAC: {"acOutput": True}}, success=False)
        asyncio.run(_ac_switch(co).async_turn_on())
        assert co.connector.commands == [(MAC, "REGEnableACOutput")]


class TestBatteryUsableCapacityScale:
    """#41: input 54 counts 0.1 Ah (390 on a 40 Ah F2400-B pack)."""

    def test_raw_390_is_39_ah(self):
        regs = [0] * 81
        regs[IREG_BATTERY_USABLE_CAPACITY] = 390
        data = parse_registers(regs, "device/response/client/04")
        assert data["batteryUsableCapacity"] == 39.0


class TestEntityNamesFollowTheDevice:
    """#39: names are relative to the device so renaming it renames them."""

    def test_has_entity_name(self):
        assert FossibotEntity._attr_has_entity_name is True

    def test_device_name_survives_station_off(self):
        entity = object.__new__(FossibotEntity)
        entity._device_id = MAC
        entity.coordinator = _Coordinator(
            {MAC: {}}, devices={MAC: {"device_name": "Garage F2400"}}
        )
        assert entity.device_info["name"] == "Garage F2400"


class TestProfileFallback:
    def test_saved_profile_is_used_while_station_is_off(self):
        co = _Coordinator({MAC: {}}, devices={MAC: {"protocolProfile": 1}})
        assert device_profile(co, MAC) == 1

    def test_fresh_profile_wins(self):
        co = _Coordinator(
            {MAC: {"protocolProfile": 0}}, devices={MAC: {"protocolProfile": 1}}
        )
        assert device_profile(co, MAC) == 0

    def test_unknown_defaults_to_v0(self):
        assert device_profile(_Coordinator({MAC: {}}), MAC) == 0

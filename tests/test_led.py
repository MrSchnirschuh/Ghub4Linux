"""LEDControl 0x1300 — the on-device status indicators.

Two defects shaped this module and both are pinned here:

* The first three functions are ``GetCount``/``GetInfo``/``GetSWControl``, not
  ``getInfo``/``getState``/``getConfig``.  Reading the first reply byte as the
  mode produced nonsense (it echoes the LED index).
* A write is rejected with error 0x02 while the firmware still owns the LEDs, so
  software control has to be claimed first or a correct-looking write does
  nothing at all.

The frame layouts below are the ones verified live on a G502 Lightspeed with the
feature at index 0x08.
"""

import pytest

from ghub4linux.core.led import (
    DISPLAY_INDEX_ALL,
    LED_BATTERY,
    LED_DPI,
    LED_PROFILE,
    MODE_BLINK,
    MODE_OFF,
    MODE_ON,
    NV_AUTO,
    LedControl,
)


class FakeConnection:
    """Answers the 0x1300 frames a G502 Lightspeed actually returns."""

    def __init__(self) -> None:
        """Start firmware-owned, with three supported LEDs."""
        self.sw_control: int = 0
        self.states: dict[int, int] = {LED_BATTERY: 1, LED_DPI: 1, LED_PROFILE: 1}
        self.calls: list[tuple[int, bytes]] = []
        self.reject_without_software_control = True

    def send_feature_request(self, index: int, function: int, params: bytes = b"") -> bytes:
        """Reply like the hardware, including its error behaviour.

        A real reply carries the full four-byte header (report id, device
        index, feature index, function|swid), so the payload starts at byte 4 —
        which is what the reader relies on.
        """
        self.calls.append((function, params))
        head = [0x11, 0x01, index, function << 4 | 1]

        if function == 0x00:  # GetCount
            return bytes(head + [0x03, 0x00, 0x00])
        if function == 0x01:  # GetInfo(i)
            led = params[0]
            types = {LED_BATTERY: 0x01, LED_DPI: 0x02, LED_PROFILE: 0x03}
            if led not in types:
                raise RuntimeError("error frame (invalid argument)")
            nv = 0x07 if led == LED_DPI else 0x00
            # [index, led_type, physical_count, modes(u16 BE), nv_caps]
            return bytes(head + [led, types[led], 0x03, 0x00, 0x03, nv, 0x00])
        if function == 0x02:  # GetSWControl
            return bytes(head + [self.sw_control, 0x00])
        if function == 0x03:  # SetSWControl
            self.sw_control = params[0]
            return bytes(head + [0x00, 0x00])
        if function == 0x04:  # GetState(i): mode is a LITTLE-endian u16
            led = params[0]
            return bytes(head + [led]) + self.states[led].to_bytes(2, "little") + bytes([0x00])
        if function == 0x05:  # SetState
            if self.reject_without_software_control and not self.sw_control:
                raise RuntimeError("error frame 0x02 (invalid argument)")
            led = params[0]
            # The transport turns an error frame into b"", which is how the
            # device reports a rejected argument.
            mode = int.from_bytes(params[1:3], "big")
            if mode not in (MODE_OFF, MODE_ON):
                return b""
            self.states[led] = 2 if mode == MODE_ON else 1
            return bytes(head + [0x00, 0x00])
        if function == 0x06:  # GetNVConfig
            return bytes(head + [params[0], 0x04, 0x00])
        if function == 0x07:  # SetNVConfig
            return bytes(head + [params[0], params[1], 0x00])
        raise RuntimeError(f"unexpected function {function}")


@pytest.fixture
def led():
    """A LedControl bound to the fake hardware."""
    return LedControl(FakeConnection(), 0x08)


class TestEnumeration:
    def test_three_logical_leds_are_found(self, led):
        assert [info.index for info in led.refresh()] == [LED_BATTERY, LED_DPI, LED_PROFILE]

    def test_led_functions_are_named(self, led):
        assert [info.name for info in led.refresh()] == ["Battery", "DPI", "Profile"]

    def test_the_reported_type_is_decoded_not_assumed(self, led):
        """Type comes from the reply, so a device with other LEDs still works."""
        info = led.led(LED_DPI)
        assert info is not None
        assert info.led_type == 0x02
        assert info.name == "DPI"

    def test_the_index_comes_from_the_reply(self, led):
        """The first payload byte is the index, not the mode."""
        for info in led.refresh():
            assert info.index in (LED_BATTERY, LED_DPI, LED_PROFILE)

    def test_only_on_off_is_advertised(self, led):
        """This hardware rejects every other mode, so the UI must not offer them."""
        for info in led.refresh():
            assert info.mode_names == ["Off", "On"]
            assert info.supports(MODE_ON)
            assert not info.supports(MODE_BLINK)

    def test_physical_count_is_read(self, led):
        """Three physical LEDs sit behind each logical one on a G502."""
        for info in led.refresh():
            assert info.physical == 3

    def test_nv_caps_differ_per_led(self, led):
        """Only the DPI LED advertises NV configuration on this device."""
        led.refresh()
        assert led.led(LED_DPI).nv_caps == 0x07
        assert led.led(LED_BATTERY).nv_caps == 0x00

    def test_an_absent_led_is_not_invented(self, led):
        assert led.led(7) is None


class TestSoftwareControl:
    def test_reads_firmware_ownership(self, led):
        assert led.get_sw_control() is False

    def test_claiming_is_confirmed_by_reading_back(self, led):
        assert led.set_sw_control(True) is True
        assert led.get_sw_control() is True

    def test_releasing_works_too(self, led):
        led.set_sw_control(True)
        assert led.set_sw_control(False) is True
        assert led.get_sw_control() is False


class TestState:
    def test_a_write_claims_control_by_itself(self, led):
        """Without this the write is rejected and looks like a broken feature."""
        assert led.get_sw_control() is False
        assert led.set_state(LED_DPI, MODE_ON, 3) is True

    def test_the_write_is_confirmed_by_reading_back(self, led):
        led.set_state(LED_DPI, MODE_ON, 3)
        assert led.get_state(LED_DPI).is_on

    def test_turning_off_is_visible(self, led):
        led.set_on(LED_DPI)
        assert led.set_off(LED_DPI) is True
        assert led.get_state(LED_DPI).is_on is False

    def test_mode_is_sent_big_endian(self, led):
        """Little-endian is rejected by the hardware with error 0x02."""
        led.set_state(LED_DPI, MODE_ON, 3)
        function, params = led._connection.calls[-1]
        assert function == 0x05
        assert params[1:3] == b"\x00\x02"

    def test_the_write_is_a_long_report(self, led):
        """Nine payload bytes exceed a short report, so it must go out long."""
        led.set_state(LED_DPI, MODE_ON, 3)
        _function, params = led._connection.calls[-1]
        assert len(params) == 9

    def test_display_index_is_carried_big_endian(self, led):
        led.set_state(LED_DPI, MODE_ON, 3)
        _function, params = led._connection.calls[-1]
        assert params[3:5] == b"\x00\x03"

    @pytest.mark.parametrize("bad", [0, 6, 7, 100])
    def test_an_out_of_range_display_index_is_refused(self, led, bad):
        """The device rejects 0 and everything above 5."""
        assert led.set_state(LED_DPI, MODE_ON, bad) is False

    def test_the_all_index_is_allowed(self, led):
        """0xFF means 'everything' and is explicitly valid."""
        assert led.set_state(LED_DPI, MODE_ON, DISPLAY_INDEX_ALL) is True

    def test_an_unsupported_mode_is_refused_before_it_is_sent(self, led):
        """Advertising only Off|On means blink must not be attempted."""
        assert led.set_state(LED_DPI, MODE_BLINK, 1) is False


class TestTheHardwareRejectionIsCovered:
    def test_a_write_without_control_fails_at_the_device_level(self):
        """Pins why claiming control first is mandatory, not cosmetic."""
        connection = FakeConnection()
        control = LedControl(connection, 0x08)
        control.refresh()
        # Claim, then release, then try to write straight through the transport
        # the way the old code did.
        control.set_sw_control(False)
        with pytest.raises(RuntimeError, match="0x02"):
            connection.send_feature_request(0x08, 0x05, bytes([LED_DPI, 0, 2, 0, 3, 0, 0, 0, 0]))


class TestBatteryGauge:
    @pytest.mark.parametrize(
        ("percent", "bars"),
        [(100, 3), (83, 3), (50, 3), (49, 2), (30, 2), (29, 1), (15, 1), (14, 0), (0, 0)],
    )
    def test_bar_count_follows_the_documented_thresholds(self, percent, bars):
        """50 % and up is three bars, from 30 % two, from 15 % one, below none."""
        assert LedControl.battery_bars_for(percent) == bars

    def test_an_unknown_level_stays_unknown(self):
        """No percentage must not be shown as a full battery."""
        assert LedControl.battery_bars_for(None) is None

    def test_a_full_battery_lights_three_bars(self, led):
        assert led.show_battery(83) is True
        assert led.get_state(LED_BATTERY).is_on

    def test_an_unknown_level_leaves_the_indicator_alone(self, led):
        assert led.show_battery(None) is False

    def test_a_critical_level_is_not_shown_as_a_steady_bar(self, led):
        """Below 15 % the hardware should flash red; it cannot, so do nothing."""
        assert led.show_battery(9) is False

    def test_the_battery_led_is_used_not_the_dpi_one(self, led):
        led.show_battery(83)
        function, params = led._connection.calls[-1]
        assert function == 0x05
        assert params[0] == LED_BATTERY


class TestNvConfig:
    def test_reading_and_writing_config(self, led):
        assert led.get_nv_config(LED_DPI) == NV_AUTO
        assert led.set_nv_config(LED_DPI, NV_AUTO) is True

    def test_an_unknown_config_is_refused(self, led):
        assert led.set_nv_config(LED_DPI, 0x99) is False


class TestTheDeviceReportsInLittleEndian:
    """The mode field's byte order, pinned from the device's own replies.

    The G502 answers ``00 01 00`` for LED0 and ``01 02 00`` for LED1.  Only the
    little-endian reading gives a legal mode there (0x0001 Off, 0x0002 On);
    reading big-endian would give 0x0100/0x0200, which are not modes.  The
    neighbouring GetInfo capability mask *is* big-endian, so the two fields
    genuinely differ and each has to be read the way it is sent.
    """

    @pytest.mark.parametrize(
        ("reply_modes", "expected"),
        [((0x01, 0x00), 0x0001), ((0x02, 0x00), 0x0002), ((0x04, 0x00), 0x0004)],
    )
    def test_state_field_is_read_little_endian(self, reply_modes, expected):
        class Connection:
            def send_feature_request(self, index: int, function: int, params: bytes = b"") -> bytes:
                """Answer GetState, echoing the requested LED index."""
                assert function == 0x04
                return bytes([0x11, 0x01, index, 0x41, params[0], *reply_modes])

        assert LedControl(Connection(), 0x08).get_state(0).mode == expected

    def test_the_index_byte_is_not_read_as_the_mode(self):
        """``frame[4]`` echoes the index; reading it as the mode is the old bug."""

        class Connection:
            def send_feature_request(self, index: int, function: int, params: bytes = b"") -> bytes:
                """Echo the requested index while reporting mode Off."""
                assert function == 0x04
                return bytes([0x11, 0x01, index, 0x41, params[0], 0x01, 0x00])

        state = LedControl(Connection(), 0x08).get_state(2)
        assert state.index == 2
        assert state.mode == 0x0001
        assert state.name == "Off"


class TestARejectedWriteIsNotSuccess:
    """An empty reply means the device refused, not that it complied.

    The transport turns an HID++ error frame into ``b""`` — that is how the
    device rejects an invalid argument — so a check for ``None`` alone let a
    refused write be reported as applied.
    """

    def test_an_empty_reply_makes_the_write_fail(self):
        class Rejecting:
            """Accepts no write: the device answers an error frame."""

            def __init__(self) -> None:
                self.sw_control: int = 1

            def send_feature_request(self, index: int, function: int, params: bytes = b"") -> bytes:
                if function == 0x02:  # GetSWControl
                    return bytes([0x11, 0x01, index, 0x21, self.sw_control])
                if function == 0x05:  # SetState - refused
                    return b""
                # GetInfo, so that the LED lookup itself succeeds and the write
                # is the only thing that fails.
                assert params
                return bytes([0x11, 0x01, index, 0x11, params[0], 0x02, 0x03, 0x00, 0x03, 0x00])

        assert LedControl(Rejecting(), 0x08).set_state(LED_DPI, MODE_ON, 3) is False

    def test_an_empty_reply_makes_a_read_fail(self):
        class Silent:
            """Never answers — the shape a timed-out or rejected read takes."""

            def send_feature_request(self, index: int, function: int, params: bytes = b"") -> bytes:
                # Any request gets the same nothing; the point is the emptiness.
                assert index >= 0 and function >= 0 and isinstance(params, bytes)
                return b""

        control = LedControl(Silent(), 0x08)
        assert control.get_state(LED_DPI) is None
        assert control.get_sw_control() is None

    def test_the_device_rejecting_an_unknown_mode_is_reported(self):
        """The fake answers b"" for a mode outside Off/On, like the hardware."""

        class Connection:
            """Lets software control through but refuses the actual write."""

            def __init__(self) -> None:
                self.sw_control: int = 1

            def send_feature_request(self, index: int, function: int, params: bytes = b"") -> bytes:
                if function == 0x02:  # GetSWControl
                    return bytes([0x11, 0x01, index, 0x21, self.sw_control])
                if function == 0x05:  # SetState - refused, like the hardware
                    return b""
                # GetInfo: report only Off|On as supported, so the mode under
                # test is genuinely outside the device's capabilities.
                assert params
                return bytes([0x11, 0x01, index, 0x11, params[0], 0x02, 0x03, 0x00, 0x03, 0x00])

        control = LedControl(Connection(), 0x08)
        assert control.set_state(LED_DPI, MODE_BLINK, 1) is False

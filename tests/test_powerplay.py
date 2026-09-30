"""Tests for the POWERPLAY mouse pad driver.

The pad is the awkward one in this codebase: it has no DPI and no battery, its
HID++ device name ("Candy companion chip") looks like an internal chip, and its
RGB engine is ``0x8070`` colorLedEffects rather than the newer ``0x8071``.  Each
of those is a way for the pad to disappear from the device list again, so each
one is pinned down here.
"""

from ghub4linux.core.config import RGBColor
from ghub4linux.core.device import DeviceCapability, DeviceType
from ghub4linux.core.hid import HIDDevice
from ghub4linux.core.hidpp import FEATURE_COLOR_LED_EFFECTS, FEATURE_RGB_EFFECTS
from ghub4linux.core.rgb import EFFECT_NAMES
from ghub4linux.devices.powerplay import (
    POWERPLAY_DEVICES,
    POWERPLAY_PID,
    Powerplay,
)


def _pad_hid_device() -> HIDDevice:
    """A HIDDevice shaped like the POWERPLAY base."""
    return HIDDevice(
        vendor_id=0x046D,
        product_id=POWERPLAY_PID,
        serial_number="candycompanionch",
        manufacturer="Logitech",
        product="Candy companion chip",
        path=b"/dev/hidraw16",
        interface_number=0,
        usage_page=0xFF00,
        usage=0x0001,
        node="/dev/hidraw16",
        device_index=0x01,
        identified=True,
    )


class FakeConnection:
    """Serves the HID++ replies a POWERPLAY pad gives for the features used."""

    # Feature index map as the real pad reports it.
    INDEXES = {
        0x0003: 0x02,  # DEVICE_INFO
        0x0005: 0x03,  # DEVICE_NAME
        FEATURE_COLOR_LED_EFFECTS: 0x0B,
    }

    def __init__(self):
        self.writes: list[tuple[int, int, bytes]] = []
        self.color = (0, 255, 128)

    def feature_index(self, feature_id: int) -> int:
        return self.INDEXES.get(feature_id, 0)

    def send_feature_request(self, index: int, function: int, params: bytes = b"") -> bytes:
        """Frame layout: 4 header bytes then the payload at offset 4."""
        self.writes.append((index, function, params))
        payload = b""

        if index == 0x02:  # DeviceInfo
            if function == 0x00:
                payload = bytes([0x02])  # two entities
            elif function == 0x01:
                entity = params[0]
                if entity == 0:
                    # cc 07 00 00 10 01 ... -> firmware 07.00 build 10
                    payload = bytes(
                        [0x00, 0x43, 0x43, 0x20, 0x07, 0x00, 0x00, 0x10, 0x01, 0x40, 0x5F]
                    )
                else:
                    payload = bytes(
                        [0x01, 0x42, 0x4F, 0x54, 0x32, 0x00, 0x00, 0x10, 0x00, 0x40, 0x5F]
                    )
        elif index == 0x03:  # DeviceName
            if function == 0x00:
                payload = bytes([20])
            elif function == 0x01:
                name = b"Candy companion chip"
                offset = params[0]
                payload = name[offset : offset + 16]
        elif index == 0x0B:  # COLOR_LED_EFFECTS
            if function == 0x00:  # get_info
                payload = bytes([0x01, 0x00, 0x03, 0x00, 0x04])
            elif function == 0x01:  # get_zone_info
                # Real pad frame: `00 | 00 02 | 04 | 00` — zone 0, location a
                # BE u16 (0x0002 = Logo), effectsNumber 4, persistency 0.
                # Serving the location's low byte where the count belongs is
                # what once made this pad look like it had only two effects.
                payload = bytes([0x00, 0x00, 0x02, 0x04, 0x00])
            elif function == 0x02:  # get_zone_effect_info
                effect_index = params[1]
                # The pad's four effects, with real capabilities and periods.
                table = {
                    0: (0x0000, 0x0000, 0),
                    1: (0x0001, 0x0000, 0),
                    2: (0x0003, 0xC005, 1000),
                    3: (0x000A, 0xC105, 60),
                }
                effect_id, caps, period = table.get(effect_index, (0xFFFF, 0, 0))
                payload = bytes(
                    [
                        0x00,
                        effect_index,
                        effect_id >> 8,
                        effect_id & 0xFF,
                        caps >> 8,
                        caps & 0xFF,
                        period >> 8,
                        period & 0xFF,
                    ]
                )
            elif function == 0x03:  # set_zone_effect
                self.color = (params[2], params[3], params[4])
                payload = bytes([0x00, params[1]])
            elif function == 0x08:  # set_sw_control
                payload = bytes([0x01, params[0]])
            elif function == 0x0C:  # get_current_color
                payload = bytes([0x00, *self.color])

        return bytes([0x11, 0x07, index, function << 4]) + payload


def _connected_pad() -> tuple[Powerplay, FakeConnection]:
    """Build a pad with a fake connection, bypassing HID."""
    pad = Powerplay(_pad_hid_device())
    connection = FakeConnection()
    pad._connection = connection  # type: ignore[assignment]
    pad._init_device()
    return pad, connection


class TestIdentity:
    def test_registered_by_its_own_pid(self):
        """The pad's own PID maps to the driver.

        Registering it against the receiver PID 0xC53A would hand the mouse's
        features to the pad driver, because that PID describes the mouse on the
        pad.
        """
        assert POWERPLAY_DEVICES[POWERPLAY_PID] is Powerplay

    def test_device_type_is_mousepad(self):
        pad, _ = _connected_pad()
        assert pad.info is not None
        assert pad.info.device_type is DeviceType.MOUSEPAD

    def test_no_dpi_and_no_battery(self):
        """The pad has neither a sensor nor a battery of its own."""
        pad, _ = _connected_pad()
        assert not pad.has_capability(DeviceCapability.DPI_ADJUSTMENT)
        assert not pad.has_capability(DeviceCapability.BATTERY_STATUS)
        assert pad.info is not None
        assert pad.info.has_battery is False
        assert pad.info.max_dpi == 0

    def test_advertises_rgb(self):
        pad, _ = _connected_pad()
        assert pad.has_capability(DeviceCapability.RGB_LIGHTING)

    def test_no_rgb_when_the_led_feature_is_absent(self):
        """A pad without 0x8070 must not offer a lighting tab."""

        class NoLed(FakeConnection):
            INDEXES = {0x0003: 0x02, 0x0005: 0x03}

        pad = Powerplay(_pad_hid_device())
        pad._connection = NoLed()  # type: ignore[assignment]
        pad._init_device()
        assert not pad.has_capability(DeviceCapability.RGB_LIGHTING)

    def test_product_name_replaces_the_chip_codename(self):
        """The user sees "POWERPLAY…", not "Candy companion chip"."""
        pad, _ = _connected_pad()
        assert pad.name == "POWERPLAY Wireless Charging System"
        # The raw hardware string stays reachable.
        assert pad.hidpp_device_name() == "Candy companion chip"

    def test_firmware_version_is_decoded(self):
        """Packed-BCD bytes decode to the version Solaar documents (07.00/B0010)."""
        pad, _ = _connected_pad()
        assert pad.info is not None
        assert pad.info.firmware_version == "7.00 (build 10)"


class TestLighting:
    def test_colour_read_from_the_device(self):
        pad, connection = _connected_pad()
        connection.color = (10, 20, 30)
        assert pad.get_lighting_settings().effect.color == RGBColor(10, 20, 30)

    def test_set_colour_is_applied_and_verified(self):
        pad, _ = _connected_pad()
        settings = pad.get_lighting_settings()
        settings.effect.color = RGBColor(0, 120, 255)

        assert pad.set_lighting_settings(settings) is True
        read_back = pad.get_lighting_settings().effect.color
        assert read_back == RGBColor(0, 120, 255)

    def test_set_colour_claims_software_control_first(self):
        """Without software control the firmware owns the LED and drops the write."""
        pad, connection = _connected_pad()
        settings = pad.get_lighting_settings()
        pad.set_lighting_settings(settings)

        led_calls = [(fn, p) for idx, fn, p in connection.writes if idx == 0x0B]
        functions = [fn for fn, _ in led_calls]
        assert 0x08 in functions, "set_sw_control was never sent"
        assert functions.index(0x08) < functions.index(0x03)

    def test_set_zone_effect_uses_the_effect_index_not_the_id(self):
        """The request carries the zone-local index, and Disabled has none.

        Effect indexes are looked up per zone; sending the effect *ID* where an
        index is expected is a silent no-op on the device.
        """
        pad, connection = _connected_pad()
        settings = pad.get_lighting_settings()
        settings.enabled = False

        assert pad.set_lighting_settings(settings) is True
        write = next(p for idx, fn, p in connection.writes if idx == 0x0B and fn == 0x03)
        assert write[0] == 0x00  # zone
        # Disabled sits at index 0 on this pad; its ID (0x0000) is not the index.
        assert write[1] == 0

    def test_fixed_colour_index_is_resolved_from_the_device(self):
        pad, connection = _connected_pad()
        settings = pad.get_lighting_settings()
        settings.enabled = True
        settings.effect.effect_type = "static"
        pad.set_lighting_settings(settings)

        write = next(p for idx, fn, p in connection.writes if idx == 0x0B and fn == 0x03)
        assert write[1] == 1, "FixedColor lives at index 1, not at its ID 0x0001"

    def test_effect_id_is_compared_as_big_endian(self):
        """A u16 effect ID must not be matched by its high byte alone."""
        pad, connection = _connected_pad()
        settings = pad.get_lighting_settings()
        settings.enabled = True
        settings.effect.effect_type = "static"

        # Must find FixedColor (id 0x0001); comparing frame[6] alone would see
        # 0x00 for every effect and match index 0.
        assert pad.set_lighting_settings(settings) is True
        write = next(p for idx, fn, p in connection.writes if idx == 0x0B and fn == 0x03)
        assert write[1] == 1

    def test_write_reports_failure_when_the_device_ignores_it(self):
        """A refused write must not be reported as success."""

        class IgnoresWrites(FakeConnection):
            def send_feature_request(self, index, function, params=b""):
                if index == 0x0B and function == 0x03:
                    self.writes.append((index, function, params))
                    return bytes([0x11, 0x07, index, function << 4])  # no colour change
                return super().send_feature_request(index, function, params)

        pad = Powerplay(_pad_hid_device())
        pad._connection = IgnoresWrites()  # type: ignore[assignment]
        pad._init_device()

        settings = pad.get_lighting_settings()
        settings.effect.color = RGBColor(1, 2, 3)
        assert pad.set_lighting_settings(settings) is False

    def test_unknown_zone_is_rejected(self):
        pad, _ = _connected_pad()
        assert pad.set_zone_lighting("side", pad.get_lighting_settings().effect) is False


class TestFeatureHandling:
    def test_uses_color_led_effects_not_rgb_effects(self):
        """0x8070 and 0x8071 are different engines and must not be conflated."""
        pad, _ = _connected_pad()
        assert FEATURE_COLOR_LED_EFFECTS == 0x8070
        assert FEATURE_RGB_EFFECTS == 0x8071
        assert pad._rgb is not None
        assert pad._rgb.index == 0x0B

    def test_effect_ids_are_the_documented_values(self):
        """The engine's effect IDs, not invented ones.

        FixedColor is 0x0001; an earlier build mapped its own codes
        (off=0x00, static=0x01, breathing=0x02…) through the wrong functions,
        which is a large part of why no effect other than static did anything.
        """
        assert EFFECT_NAMES[0x0000] == "Disabled"
        assert EFFECT_NAMES[0x0001] == "Fixed"
        assert EFFECT_NAMES[0x0004] == "Color Wave"
        assert EFFECT_NAMES[0x000B] == "Ripple"

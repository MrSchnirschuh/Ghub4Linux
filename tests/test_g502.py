"""Tests for the G502 device driver (pure logic paths, no HID hardware)."""

import pytest

from ghub4linux.core.config import (
    DeviceConfig,
    LightingEffect,
    LightingSettings,
    RGBColor,
)
from ghub4linux.core.device import (
    ConnectionType,
    DeviceCapability,
    DeviceType,
)
from ghub4linux.core.hid import HIDDevice
from ghub4linux.core.rgb import (
    EFFECT_IDS_BY_NAME,
    EFFECT_NAME_BY_ID,
    EFFECT_NAMES,
)
from ghub4linux.devices.g502 import (
    G502_DEVICES,
    G502_HERO_PID,
    G502_LIGHTSPEED_PID,
    G502_LIGHTSPEED_WIRED_PID,
    G502_RECEIVER_HINTS,
    G502X_PLUS_PID,
    G502X_PLUS_WIRED_PID,
    G502Device,
    G502Hero,
    G502Lightspeed,
    G502XPlus,
)


@pytest.fixture
def hid_device():
    """A G502 Lightspeed HID device (no connection opened)."""
    return HIDDevice(
        vendor_id=0x046D,
        product_id=G502_LIGHTSPEED_PID,
        serial_number="mockg502",
        manufacturer="Logitech",
        product="G502 Lightspeed",
        path=b"/dev/mock",
        interface_number=0,
        usage_page=0xFF00,
        usage=0x0001,
    )


def make_device(cls, hid, **config_kwargs):
    """Build a device instance without opening a HID connection."""
    return cls(hid, DeviceConfig(device_id=hid.device_id, device_name="G502", **config_kwargs))


class TestEffectCodes:
    """Config effect names map onto the engine's documented 0x8070 effect IDs.

    The old implementation carried its own invented code table and pushed it
    through functions that do not take an effect at all.  These are the real IDs,
    and a name may legitimately have more than one implementation: breathing
    exists both as the waveform variant (10) and the legacy one (2), so the
    device is asked which it has rather than one being assumed.
    """

    @pytest.mark.parametrize(
        ("effect_type", "effect_id"),
        [
            ("off", 0),
            ("static", 1),
            ("cycle", 3),
            ("wave", 4),
            ("starlight", 5),
            ("press", 6),
            ("ripple", 11),
        ],
    )
    def test_known_effects(self, effect_type, effect_id):
        assert EFFECT_IDS_BY_NAME[effect_type] == (effect_id,)

    def test_breathing_prefers_the_waveform_variant(self):
        """The waveform effect can set period/waveform; legacy only has speed."""
        assert EFFECT_IDS_BY_NAME["breathing"][0] == 10
        assert 2 in EFFECT_IDS_BY_NAME["breathing"]

    def test_unknown_effect_is_not_mapped(self):
        """An unknown name must not silently become some effect ID."""
        assert "rainbow" not in EFFECT_IDS_BY_NAME

    def test_every_id_has_a_name(self):
        """Otherwise the UI would show a raw number for a real effect."""
        for ids in EFFECT_IDS_BY_NAME.values():
            for effect_id in ids:
                assert effect_id in EFFECT_NAMES
                assert effect_id in EFFECT_NAME_BY_ID

    def test_g502_has_no_lighting_without_a_connection(self, hid_device):
        """Without 0x8070 resolved there is nothing to write to."""
        dev = make_device(G502Hero, hid_device)
        assert dev._rgb is None
        assert dev.supported_lighting_effects() == []
        assert dev.lighting_zones() == []
        assert dev.set_lighting_settings(LightingSettings()) is False


class TestConnectionType:
    """Connection type is derived from the product ID."""

    def test_wireless_lightspeed(self, hid_device):
        assert (
            make_device(G502Lightspeed, hid_device)._get_connection_type()
            == ConnectionType.LIGHTSPEED
        )

    def test_wired_pid_returns_wired(self):
        wired = HIDDevice(
            vendor_id=0x046D,
            product_id=G502_LIGHTSPEED_WIRED_PID,
            serial_number="wired",
            manufacturer="Logitech",
            product="G502 Lightspeed",
            path=b"/dev/wired",
            interface_number=0,
            usage_page=0xFF00,
            usage=0x0001,
        )
        assert make_device(G502Lightspeed, wired)._get_connection_type() == ConnectionType.WIRED

    def test_xplus_wired_pid_returns_wired(self):
        wired = HIDDevice(
            vendor_id=0x046D,
            product_id=G502X_PLUS_WIRED_PID,
            serial_number="xplusw",
            manufacturer="Logitech",
            product="G502X Plus",
            path=b"/dev/wired",
            interface_number=0,
            usage_page=0xFF00,
            usage=0x0001,
        )
        assert make_device(G502XPlus, wired)._get_connection_type() == ConnectionType.WIRED


class TestDeviceInfo:
    """_make_device_info fills common fields from the HID device."""

    def test_hero_info(self, hid_device):
        info = make_device(G502Hero, hid_device).get_device_info()
        assert info.name == "G502 Hero"
        assert info.model == "G502 Hero"
        assert info.vendor_id == 0x046D
        assert info.device_type == DeviceType.MOUSE
        assert info.has_rgb is True
        assert info.has_battery is True
        assert info.max_dpi == 25600
        assert info.dpi_step == 50

    def test_xplus_button_count(self, hid_device):
        info = make_device(G502XPlus, hid_device).get_device_info()
        assert info.button_count == 13

    def test_default_button_count(self, hid_device):
        info = make_device(G502Lightspeed, hid_device).get_device_info()
        assert info.button_count == 11


class TestReportRate:
    """Report rate: a millisecond interval on the wire, hertz in the API.

    The protocol expresses the rate as a *millisecond interval* (``0x8060``
    fn 0 returns a bitfield of them, fn 1 the active one, fn 2 writes one), so
    the previous implementation — invented hertz codes written through fn 0 of a
    hardcoded feature index — never touched the real feature.

    The API is in **hertz** even though the wire is in milliseconds, because a
    millisecond representation cannot tell the fast rates apart: 1000, 2000,
    4000 and 8000 Hz would all read as "1 ms".
    """

    def test_milliseconds_are_normalised_to_hertz(self):
        assert G502Device._to_hertz(1) == 1000
        assert G502Device._to_hertz(8) == 125

    @pytest.mark.parametrize(("hz", "ms"), [(1000, 1), (500, 2), (250, 4), (125, 8)])
    def test_hertz_survives_and_converts_to_the_wire_value(self, hz, ms):
        assert G502Device._to_hertz(hz) == hz
        assert G502Device._to_milliseconds(hz) == ms

    @pytest.mark.parametrize("rate", [0, 100, 2000, -1, 7])
    def test_unrepresentable_rates_are_rejected(self, rate):
        # 7 is neither a valid interval (1-8 is legal, but 7 ms = 143 Hz is not
        # a rate this device family offers) nor a known hertz value.
        assert G502Device._to_hertz(rate) is None

    def test_the_fast_rates_stay_distinguishable(self):
        """The reason the API is not in milliseconds: this must not collapse."""
        assert {G502Device._to_hertz(rate) for rate in (125, 250, 500, 1000)} == {
            125,
            250,
            500,
            1000,
        }

    def test_set_without_a_connection_reports_failure(self, hid_device):
        """No connection means no write happened — must not claim success."""
        assert make_device(G502Hero, hid_device).set_report_rate(1000) is False

    def test_get_without_a_connection_returns_none(self, hid_device):
        assert make_device(G502Hero, hid_device).get_report_rate() is None

    def test_list_without_a_connection_is_empty(self, hid_device):
        assert make_device(G502Hero, hid_device).get_report_rate_list() == []


class TestZoneLighting:
    """Per-zone lighting.

    Zones are read from the device's 0x8070 engine, not from a fixed name list:
    without a connection there are no zones, and claiming a write succeeded
    would be the same lie the old "mock success" path told.
    """

    def test_no_zones_without_a_connection(self, hid_device):
        dev = make_device(G502XPlus, hid_device)
        assert dev.set_zone_lighting("logo", LightingEffect(effect_type="breathing")) is False

    def test_unknown_zone_is_rejected(self, hid_device):
        dev = make_device(G502XPlus, hid_device)
        assert dev.set_zone_lighting("nonexistent_zone", LightingEffect()) is False

    def test_setting_lighting_without_the_engine_reports_failure(self, hid_device):
        dev = make_device(G502XPlus, hid_device)
        settings = LightingSettings(enabled=True)
        assert dev.set_lighting_settings(settings) is False


class TestRegistry:
    """Device registry maps PIDs to the correct classes."""

    def test_all_pids_registered(self):
        assert G502_DEVICES[G502_HERO_PID] is G502Hero
        assert G502_DEVICES[G502_LIGHTSPEED_PID] is G502Lightspeed
        assert G502_DEVICES[G502_LIGHTSPEED_WIRED_PID] is G502Lightspeed
        assert G502_DEVICES[G502X_PLUS_PID] is G502XPlus
        assert G502_DEVICES[G502X_PLUS_WIRED_PID] is G502XPlus

    def test_receiver_hints_target_g502(self):
        assert all(cls is G502Lightspeed for _, _, cls in G502_RECEIVER_HINTS)


class TestCapabilities:
    """G502 exposes the documented feature set."""

    def test_capability_set(self, hid_device):
        caps = make_device(G502Hero, hid_device).capabilities
        assert DeviceCapability.DPI_ADJUSTMENT in caps
        assert DeviceCapability.RGB_LIGHTING in caps
        assert DeviceCapability.MACROS in caps
        assert DeviceCapability.ONBOARD_PROFILES in caps
        assert DeviceCapability.BATTERY_STATUS in caps
        assert DeviceCapability.REPORT_RATE in caps


class TestDpiLevelSync:
    """The profile's DPI levels must mirror the sensor without growing."""

    def _device(self):
        from ghub4linux.core.config import DeviceConfig
        from ghub4linux.core.device import DeviceCapability
        from ghub4linux.core.hid import HIDDevice
        from ghub4linux.devices.g502 import G502Lightspeed

        hid = HIDDevice(
            vendor_id=0x046D,
            product_id=0x407F,
            serial_number="x",
            manufacturer="Logitech",
            product="G502",
            path=b"/dev/hidraw15",
            interface_number=0xFF,
            usage_page=0xFF00,
            usage=1,
            node="/dev/hidraw15",
            device_index=0xFF,
            identified=True,
        )
        device = G502Lightspeed(hid, DeviceConfig(device_id="x", device_name="G502"))
        device._capabilities = set(device._capabilities) | {DeviceCapability.DPI_ADJUSTMENT}
        return device

    def test_a_preset_value_selects_that_level(self):
        device = self._device()
        device.get_sensor_dpi = lambda _sensor=0: 3200
        device._sync_dpi_levels()
        settings = device.active_profile.dpi_settings
        assert settings.levels[settings.active_level].dpi == 3200

    def test_an_off_preset_value_reuses_one_extra_slot(self):
        device = self._device()
        baseline = len(device.active_profile.dpi_settings.levels)
        for value in (1450, 1234, 2000, 1450):
            device.get_sensor_dpi = lambda _sensor=0, v=value: v
            device._sync_dpi_levels()
            settings = device.active_profile.dpi_settings
            # The list must not grow past one extra slot, however often the
            # hardware button is used.
            assert len(settings.levels) == baseline + 1
            assert settings.levels[settings.active_level].dpi == value

    def test_no_sensor_reading_leaves_the_levels_untouched(self):
        device = self._device()
        device.get_sensor_dpi = lambda _sensor=0: None
        before = [level.dpi for level in device.active_profile.dpi_settings.levels]
        device._sync_dpi_levels()
        assert [level.dpi for level in device.active_profile.dpi_settings.levels] == before


class TestSeparateZoneColours:
    """The bars and the logo can carry different colours.

    This is what the battery gauge needs: the bars' *count* comes from the
    status-LED feature, which carries no colour at all, so the colour has to
    come from the RGB engine — and for the bars and the logo to differ at all,
    the two zones must be addressable separately.

    Measured on a G502 Lightspeed: setting Primary to (0,255,0) and Logo to
    (0,0,255) and reading both back returns exactly those, and swapping them
    returns the swapped values — so they are genuinely independent rather than
    one colour written twice.
    """

    class FakeRgb:
        """Records what each zone was told, keyed by zone index."""

        def __init__(self) -> None:
            self.zones = [_Zone(0, "Primary"), _Zone(1, "Logo")]
            self.applied: dict[int, tuple[str, tuple[int, int, int]]] = {}

        def zone(self, index: int):
            """The zone object for *index*, like the real engine."""
            return next((z for z in self.zones if z.index == index), None)

        def set_effect_by_name(self, index, name, colour, speed=None):
            """Remember the name and colour for one zone."""
            del speed
            self.applied[index] = (name, tuple(colour))
            return True

        def set_off(self, index):
            """Remember that a zone was switched off."""
            self.applied[index] = ("off", (0, 0, 0))
            return True

    def _device(self, hid_device):
        dev = make_device(G502Lightspeed, hid_device)
        dev._rgb = self.FakeRgb()
        return dev

    def test_a_zone_takes_its_own_colour(self, hid_device):
        dev = self._device(hid_device)
        settings = LightingSettings(
            enabled=True,
            effect=LightingEffect(color=RGBColor(255, 255, 255)),
            zones={
                "Primary": LightingEffect(color=RGBColor(0, 255, 0)),
                "Logo": LightingEffect(color=RGBColor(0, 0, 255)),
            },
        )
        assert dev.set_lighting_settings(settings) is True
        assert dev._rgb.applied[0][1] == (0, 255, 0)
        assert dev._rgb.applied[1][1] == (0, 0, 255)

    def test_a_zone_without_an_entry_follows_the_shared_effect(self, hid_device):
        """Only the bars were given a colour, so the logo keeps the default."""
        dev = self._device(hid_device)
        settings = LightingSettings(
            enabled=True,
            effect=LightingEffect(color=RGBColor(255, 255, 255)),
            zones={"Primary": LightingEffect(color=RGBColor(255, 0, 0))},
        )
        assert dev.set_lighting_settings(settings) is True
        assert dev._rgb.applied[0][1] == (255, 0, 0)
        assert dev._rgb.applied[1][1] == (255, 255, 255)

    def test_a_zone_can_carry_a_different_effect_than_another(self, hid_device):
        dev = self._device(hid_device)
        settings = LightingSettings(
            enabled=True,
            effect=LightingEffect(effect_type="static", color=RGBColor(255, 255, 255)),
            zones={
                "Logo": LightingEffect(effect_type="breathing", color=RGBColor(0, 0, 255), speed=40)
            },
        )
        assert dev.set_lighting_settings(settings) is True
        assert dev._rgb.applied[0][0] == "static"
        assert dev._rgb.applied[1][0] == "breathing"

    def test_each_zone_still_gets_its_own_write(self, hid_device):
        """Two zones means two writes — one colour written twice is the old bug."""
        dev = self._device(hid_device)
        settings = LightingSettings(enabled=True, effect=LightingEffect())
        assert dev.set_lighting_settings(settings) is True
        assert set(dev._rgb.applied) == {0, 1}


class _Zone:
    """Minimal stand-in for a ColorLedZone: an index and a name."""

    def __init__(self, index: int, location_name: str) -> None:
        self.index = index
        self.location_name = location_name


class TestReadingZoneColoursBack:
    """Each zone's colour is read separately.

    Reading only zone 0 and showing it for both would make the panel state
    something false about the second zone — and the two zones really can hold
    different colours, so the false statement would be visible.
    """

    class FakeRgb:
        """Answers a different colour per zone, plus a stored effect."""

        def __init__(self, colours, stored=0x0001) -> None:
            self.zones = [_Zone(0, "Primary"), _Zone(1, "Logo")]
            self._colours = colours
            self._stored = stored

        def get_current_color(self, index: int):
            """The colour this zone was primed with."""
            return self._colours.get(index)

        def get_stored_effect(self, index: int):
            """The effect this zone is showing."""
            del index
            return self._stored

        def zone(self, index: int):
            return next((z for z in self.zones if z.index == index), None)

    def _device(self, hid_device, colours, stored=0x0001):
        dev = make_device(G502Lightspeed, hid_device)
        dev._rgb = self.FakeRgb(colours, stored)
        return dev

    def test_both_zones_are_read(self, hid_device):
        dev = self._device(hid_device, {0: (0, 255, 0), 1: (0, 0, 255)})
        settings = dev.get_lighting_settings()
        assert settings.zones["Primary"].color.green == 255
        assert settings.zones["Logo"].color.blue == 255
        assert settings.zones["Primary"].color.blue == 0
        assert settings.zones["Logo"].color.green == 0

    def test_a_single_zone_device_reports_only_that_zone(self, hid_device):
        dev = self._device(hid_device, {0: (255, 0, 0), 1: None})
        settings = dev.get_lighting_settings()
        assert settings.effect.color.red == 255
        assert "Logo" not in settings.zones or settings.zones["Logo"].color.red == 255

    def test_black_alone_does_not_mean_switched_off(self, hid_device):
        """A black readback is ambiguous, so the stored effect decides."""
        dev = self._device(hid_device, {0: (0, 0, 0), 1: (0, 0, 0)}, stored=0x0001)
        assert dev.get_lighting_settings().enabled is True

    def test_a_disabled_zone_does_read_as_switched_off(self, hid_device):
        dev = self._device(hid_device, {0: (0, 0, 0), 1: (0, 0, 0)}, stored=0x0000)
        assert dev.get_lighting_settings().enabled is False

    def test_an_unreadable_zone_is_not_invented(self, hid_device):
        """An unanswered read must not produce a colour the device never sent."""
        dev = self._device(hid_device, {0: None, 1: None})
        settings = dev.get_lighting_settings()
        assert settings.zones == {}

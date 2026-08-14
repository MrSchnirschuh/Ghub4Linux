"""Tests for the G502 device driver (pure logic paths, no HID hardware)."""

import pytest

from ghub4linux.core.config import (
    DeviceConfig,
    LightingEffect,
    LightingSettings,
)
from ghub4linux.core.device import (
    ConnectionType,
    DeviceCapability,
    DeviceType,
)
from ghub4linux.core.hid import HIDDevice
from ghub4linux.devices.g502 import (
    G502_DEVICES,
    G502_HERO_PID,
    G502_LIGHTSPEED_PID,
    G502_LIGHTSPEED_WIRED_PID,
    G502_RECEIVER_HINTS,
    G502X_PLUS_PID,
    G502X_PLUS_WIRED_PID,
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


class TestEffectCode:
    """_get_effect_code maps effect types to HID++ codes."""

    @pytest.mark.parametrize(
        ("effect_type", "code"),
        [
            ("off", 0x00),
            ("static", 0x01),
            ("breathing", 0x02),
            ("cycle", 0x03),
            ("wave", 0x04),
        ],
    )
    def test_known_effects(self, hid_device, effect_type, code):
        assert make_device(G502Hero, hid_device)._get_effect_code(effect_type) == code

    def test_unknown_effect_defaults_to_static(self, hid_device):
        assert make_device(G502Hero, hid_device)._get_effect_code("rainbow") == 0x01


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
    """Report rate validation and encoding."""

    @pytest.mark.parametrize("rate", [125, 250, 500, 1000])
    def test_valid_rates(self, hid_device, rate):
        # No HID connection opened -> method returns True (mock success).
        assert make_device(G502Hero, hid_device).set_report_rate(rate) is True

    @pytest.mark.parametrize("rate", [0, 100, 2000, -1])
    def test_invalid_rates_rejected(self, hid_device, rate):
        assert make_device(G502Hero, hid_device).set_report_rate(rate) is False


class TestZoneLighting:
    """G502X Plus zone lighting."""

    def test_valid_zone_updates_local_config(self, hid_device):
        dev = make_device(G502XPlus, hid_device)
        effect = LightingEffect(effect_type="breathing")
        # No HID connection -> _set_lighting_settings updates local config and
        # returns True; the effect is recorded on the active profile.
        assert dev.set_zone_lighting("logo", effect) is True
        assert dev.active_profile.lighting_settings.zones["logo"] is effect

    def test_zone_set_after_enable(self, hid_device):
        dev = make_device(G502XPlus, hid_device)
        settings = LightingSettings(enabled=True)
        dev.active_profile.lighting_settings = settings
        effect = LightingEffect(effect_type="cycle")
        assert dev.set_zone_lighting("dpi_indicator", effect) is True

    def test_invalid_zone_rejected(self, hid_device):
        dev = make_device(G502XPlus, hid_device)
        effect = LightingEffect()
        assert dev.set_zone_lighting("nonexistent_zone", effect) is False


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

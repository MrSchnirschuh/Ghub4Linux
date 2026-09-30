"""Tests for honest battery reporting.

The previous build reported fabricated battery data: it read feature ``0x1004``
function 0 — which is *get_battery_capabilities*, not a measurement — and
presented those capability bits as a charge, so a PRO X 2 DEX sitting at 82% and
discharging showed "15% charging".  It also asserted "not charging" from a
``0x1001`` flags byte of ``0x00`` while the same mouse was demonstrably charging
on a PowerPlay pad.

These tests pin down the byte layouts and, just as importantly, that a value the
device did not report comes out as unknown instead of a guess.
"""

import pytest

from ghub4linux.core.device import (
    BatteryStatus,
    _charge_state_from_status,
    _percent_from_millivolts,
    _voltage_charge_state,
)


class TestChargeStatusEnum:
    """0x1004 get_battery_info byte 2 and 0x1000 byte 2 use the same enum."""

    @pytest.mark.parametrize("status", [1, 2])
    def test_charging_states(self, status):
        assert _charge_state_from_status(status) is True

    @pytest.mark.parametrize("status", [0, 3])
    def test_not_charging_states(self, status):
        assert _charge_state_from_status(status) is False

    def test_error_is_not_turned_into_a_claim(self):
        """An error code must not be reported as either charging or not."""
        assert _charge_state_from_status(4) is None

    def test_unknown_code_is_not_turned_into_a_claim(self):
        assert _charge_state_from_status(7) is None


class TestVoltageFlags:
    """0x1001 flags byte: bit 7 external power, bits 0-1 status, bits 3/4 rate."""

    def test_bit7_clear_means_discharging(self):
        # The G502 reports exactly this while on the PowerPlay pad.
        assert _voltage_charge_state(0x00) is False

    def test_external_power_with_no_detail_is_unknown(self):
        """Bit 7 set but no rate/complete bit: the byte cannot say."""
        assert _voltage_charge_state(0x80) is None

    def test_fast_charging(self):
        assert _voltage_charge_state(0x88) is True

    def test_slow_charging(self):
        assert _voltage_charge_state(0x90) is True

    def test_full_takes_precedence_over_rate_bits(self):
        assert _voltage_charge_state(0x81) is False
        assert _voltage_charge_state(0x83) is False

    def test_charge_fault_is_not_charging(self):
        assert _voltage_charge_state(0x82) is False

    def test_critical_bit_does_not_change_the_state(self):
        assert _voltage_charge_state(0xA0) is None


class TestVoltageEstimate:
    def test_endpoints(self):
        assert _percent_from_millivolts(4200) == 100
        assert _percent_from_millivolts(3500) == 0

    def test_clamped(self):
        assert _percent_from_millivolts(5000) == 100
        assert _percent_from_millivolts(1000) == 0

    def test_measured_g502_value(self):
        """The G502 reported 4044 mV — roughly 78%, and an estimate."""
        assert _percent_from_millivolts(4044) == 78


class TestDescribe:
    """describe() is the single wording the CLI, sidebar and panel all use."""

    def test_reported_percentage_is_shown_plainly(self):
        text = BatteryStatus(level=82, charging=False).describe()
        assert "82%" in text
        assert "~" not in text, "a reported value must not look like an estimate"

    def test_estimate_is_marked(self):
        text = BatteryStatus(level=78, charging=None, voltage=4.044, estimated=True).describe()
        assert "~78%" in text
        assert "4.044 V" in text

    def test_unknown_level_says_so(self):
        text = BatteryStatus(level=None, charging=None).describe()
        assert "unknown" in text
        assert "%" not in text

    def test_unknown_charge_state_is_not_silently_a_no(self):
        """None must not render as "not charging"."""
        assert "not charging" not in BatteryStatus(level=50, charging=None).describe()

    def test_device_status_text_is_included(self):
        assert (
            "discharging"
            in BatteryStatus(level=50, charging=False, status_text="discharging").describe()
        )

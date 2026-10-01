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
    """0x1001 flags byte per the kernel and the LKML Table 1.

    bit 7 external power (gates everything), bits 0-2 charge status, bit 3 fast
    charge, bit 4 slow charge, bit 5 critical.
    """

    def test_all_zero_means_not_charging(self):
        """0x00 is the plain "no external power" case — a definite answer.

        Measured alongside the voltage: at 0x00 the battery read 3999 mV, and
        when the byte flipped to 0x90 the voltage jumped to 4044 mV in the same
        second.  The bit tracks the hardware, so it is answered rather than
        softened into "unknown" — see TestTheChargeFlagTracksTheHardware.
        """
        assert _voltage_charge_state(0x00) is False

    def test_status_bits_without_external_power_are_not_decoded(self):
        """Bit 7 gates the status bits, so they cannot be read without it."""
        assert _voltage_charge_state(0x07) is None

    def test_external_power_with_status_zero_is_charging(self):
        assert _voltage_charge_state(0x80) is True

    def test_fast_charging(self):
        assert _voltage_charge_state(0x88) is True

    def test_slow_charging(self):
        assert _voltage_charge_state(0x90) is True

    def test_end_of_charge_is_not_charging(self):
        """Status 1 = charge complete, which is not the same as charging."""
        assert _voltage_charge_state(0x81) is False

    def test_charge_stopped_is_not_charging(self):
        """Status 2 = charging stopped."""
        assert _voltage_charge_state(0x82) is False

    def test_charge_restarting_is_charging(self):
        assert _voltage_charge_state(0x83) is True

    def test_hardware_error_is_not_a_claim(self):
        """Status 7 means the battery reported a fault, not a state."""
        assert _voltage_charge_state(0x87) is None

    def test_critical_bit_does_not_change_the_state(self):
        """Bit 5 flags a low charge level, not the charging state."""
        assert _voltage_charge_state(0xA0) is True


class TestVoltageEstimate:
    """The curve must match the public reference, not a straight ramp.

    A linear 4200..3500 ramp is materially wrong across the whole useful range:
    at 4044 mV it says 78% where the kernel's table and Solaar's both say 87%.
    """

    @pytest.mark.parametrize(
        ("millivolts", "percent"),
        [
            (4186, 100),
            (4067, 90),
            (3989, 80),
            (3922, 70),
            (3859, 60),
            (3811, 50),
            (3778, 40),
            (3751, 30),
            (3717, 20),
            (3671, 10),
            (3646, 5),
            (3579, 2),
            (3500, 0),
        ],
    )
    def test_reference_points(self, millivolts, percent):
        """Every published point must be reproduced exactly."""
        assert _percent_from_millivolts(millivolts) == percent

    def test_interpolates_between_points(self):
        """3945 mV is a real Solaar G502 readout, and lands at 73%."""
        assert _percent_from_millivolts(3945) == 73

    def test_measured_g502_value(self):
        """The G502's 4044 mV is ~87%, not the 78% a linear ramp would claim.

        That is consistent with PowerPlay holding the battery between 85% and
        95% by design.
        """
        assert _percent_from_millivolts(4044) == 87

    def test_clamped_outside_the_curve(self):
        assert _percent_from_millivolts(5000) == 100
        assert _percent_from_millivolts(1000) == 0

    def test_never_goes_negative(self):
        assert _percent_from_millivolts(2000) == 0


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


class TestTheChargeFlagTracksTheHardware:
    """0x00 is a definite "not charging", not an "unknown".

    Measured on a G502 Lightspeed on a PowerPlay pad, sampled once a second: the
    byte sat at ``0x00`` with the battery at 3999 mV, then flipped to ``0x90`` —
    and in the same second the voltage **jumped to 4044 mV**, the charging
    voltage.  The flag change therefore tracked a real change at the hardware
    rather than being noise, so the honest output is the state of the current
    read.  Earlier builds softened it to "unknown", which hid an answer the
    device gave and made the indicator look broken while the pad was working.

    The pad holds the battery between 85% and 95% by design, so it really does
    stop and resume charging on its own — both values are legitimately correct
    at different times.
    """

    def test_no_external_power_is_a_definite_not_charging(self):
        assert _voltage_charge_state(0x00) is False

    def test_external_power_with_slow_charge_is_charging(self):
        """0x90: external power + slow charge, exactly what a pad does."""
        assert _voltage_charge_state(0x90) is True

    def test_both_values_the_hardware_produced_are_answered(self):
        """Neither of the two real readings may come out as unknown."""
        assert _voltage_charge_state(0x00) is not None
        assert _voltage_charge_state(0x90) is not None

    def test_a_byte_without_bit7_and_other_claims_stays_unknown(self):
        """Bit 7 gates the status bits, so 0x08 alone justifies no answer."""
        assert _voltage_charge_state(0x08) is None

    def test_the_rendered_text_names_the_state(self):
        """The UI must say which of the two it is, not hedge."""
        charging = BatteryStatus(level=81, charging=False, voltage=3.999, estimated=True)
        assert "not charging" in charging.describe()
        assert "unknown" not in charging.describe()

"""PRO X 2 DEX report rate — the extendedAdjustableReportRate feature (0x8061).

The DEX does **not** have the classic ReportRate (0x8060) the G502 uses, so the
driver kept finding no such feature and the app told the user the mouse does not
support a polling rate at all.  It supports one through 0x8061, which has a
different layout and — the part that is easy to miss — an **enum rate code**
rather than hertz or a millisecond interval:

    0=125, 1=250, 2=500, 3=1000, 4=2000, 5=4000, 6=8000 Hz

Two defects follow from that and are pinned here:

* Reading the capability bitmask and converting each code to "1000 // hertz"
  collapses the four fast rates onto the same value, so the panel could not
  offer 2000 Hz at all and 1000 Hz was indistinguishable from 8000 Hz.
* Treating the code as hertz (or as milliseconds) writes a rate the device does
  not interpret as intended, while the acknowledgement makes it look applied.
  The setter therefore reads back and compares against the requested rate.
"""

import pytest

from ghub4linux.devices.pro_dex import (
    RATE_CODE_BY_HERTZ,
    RATE_HERTZ_BY_CODE,
    RATE_HERTZ_BY_MS,
    ProDex2,
)


class FakeDex:
    """A minimal stand-in exposing the pieces the rate logic needs."""

    def __init__(self, capabilities=0x7F, current_code=3, connection_type=None):
        """Answer the 0x8061 frames the feature defines."""
        self.capabilities = capabilities
        self.current_code = current_code
        self.connection_type = connection_type
        self.writes: list[int] = []
        self.reads: list[tuple[int, bytes]] = []

    @property
    def name(self) -> str:
        """Device name, as the logger uses it."""
        return "PRO X 2 DEX"

    @property
    def _features(self) -> dict[int, int]:
        """The feature index table, with 0x8061 present."""
        return {0x8061: 0x0D}

    def info(self):
        """No DeviceInfo, which the connection code treats as wireless."""
        return None

    def _read_feature(self, index: int, function: int, params: bytes = b"") -> bytes:
        """Answer the four 0x8061 functions."""
        self.reads.append((function, params))
        head = [0x11, 0x02, index, function << 4 | 1]
        if function == 0x00:  # capabilities: u16 big-endian bitmask
            return bytes(head + list(self.capabilities.to_bytes(2, "big")))
        if function == 0x02:  # current rate code, at payload position 0
            return bytes(head + [self.current_code, 0x00, 0x00])
        if function == 0x03:  # set rate code
            code = params[0]
            self.writes.append(code)
            self.current_code = code
            return bytes(head + [0x00, 0x00])
        return b""


class WiredDex(ProDex2):
    """A ProDex2 whose feature reads come from a fake transport.

    Only the rate methods are real; everything they depend on (the feature
    index, the device name, the connection code) is served by the fake.
    """

    def __init__(self, fake: FakeDex):  # noqa: D107 - test double
        self.fake = fake
        self._features = {0x8061: 0x0D}

    @property
    def name(self) -> str:  # noqa: D102
        return "PRO X 2 DEX"

    def _read_feature(self, index: int, function: int = 0x00, params: bytes = b"") -> bytes:  # noqa: D102
        return self.fake._read_feature(index, function, params)

    def _connection_code(self) -> int:  # noqa: D102
        return 1


def make_dex(**kwargs) -> WiredDex:
    """A DEX with its rate methods wired to a fake transport."""
    return WiredDex(FakeDex(**kwargs))


class TestRateTables:
    def test_codes_are_an_enum_not_a_number(self):
        """The wire carries a code; hertz is what it means."""
        assert RATE_HERTZ_BY_CODE == {0: 125, 1: 250, 2: 500, 3: 1000, 4: 2000, 5: 4000, 6: 8000}

    def test_the_tables_are_inverses(self):
        assert {hertz: code for code, hertz in RATE_HERTZ_BY_CODE.items()} == RATE_CODE_BY_HERTZ

    def test_millisecond_intervals_map_to_their_rate(self):
        assert RATE_HERTZ_BY_MS == {1: 1000, 2: 500, 4: 250, 8: 125}


class TestSupportedRates:
    def test_all_seven_rates_are_reported(self):
        assert make_dex(capabilities=0x7F).get_report_rate_list() == [
            8000,
            4000,
            2000,
            1000,
            500,
            250,
            125,
        ]

    def test_the_fast_rates_do_not_collapse(self):
        """This is the defect: expressing them as intervals yields 1 ms each."""
        rates = make_dex(capabilities=0x7F).get_report_rate_list()
        assert len({2000, 4000, 8000} & set(rates)) == 3

    def test_only_advertised_rates_are_offered(self):
        """Bit N means code N; a device offering 125/500 only reports those."""
        assert make_dex(capabilities=0b0000101).get_report_rate_list() == [500, 125]

    def test_no_capability_answer_means_no_rates(self):
        assert make_dex(capabilities=0x0000).get_report_rate_list() == []

    def test_the_mask_is_read_as_two_bytes(self):
        """A single-byte read would lose the three fastest rates."""
        only_fast = make_dex(capabilities=0b111 << 4).get_report_rate_list()
        assert only_fast == [8000, 4000, 2000]


class TestCurrentRate:
    def test_the_code_is_translated_to_hertz(self):
        assert make_dex(current_code=3).get_report_rate() == 1000

    def test_every_code_translates(self):
        for code, hertz in RATE_HERTZ_BY_CODE.items():
            assert make_dex(current_code=code).get_report_rate() == hertz

    def test_an_unknown_code_is_not_guessed(self):
        """Better to report nothing than to invent a rate."""
        assert make_dex(current_code=9).get_report_rate() is None


class TestSetRate:
    def test_hertz_is_converted_to_the_rate_code(self):
        device = make_dex()
        assert device.set_report_rate(2000) is True
        assert device.fake.writes == [4]

    def test_the_connection_code_is_sent_with_every_rate_call(self):
        """Wired and wireless offer different rates, so the code is sent."""
        device = make_dex()
        device.set_report_rate(1000)
        rate_calls = [(f, p) for f, p in device.fake.reads if f in (0x00, 0x02)]
        assert rate_calls
        assert all(params[0] == 1 for _function, params in rate_calls)

    @pytest.mark.parametrize("hertz", [125, 250, 500, 1000, 2000, 4000, 8000])
    def test_every_offered_rate_can_be_set(self, hertz):
        device = make_dex(capabilities=0x7F)
        assert device.set_report_rate(hertz) is True
        assert device.get_report_rate() == hertz

    def test_a_millisecond_interval_is_also_accepted(self):
        """The G502's API style is accepted for convenience."""
        device = make_dex()
        assert device.set_report_rate(2) is True
        assert device.get_report_rate() == 500

    def test_an_unofferable_rate_is_refused_before_writing(self):
        device = make_dex(capabilities=0b0000101)  # only 125 and 500
        assert device.set_report_rate(8000) is False
        assert device.fake.writes == []

    def test_a_rate_the_device_ignores_is_not_reported_as_success(self):
        """Acknowledged but unchanged must come back False, not True."""

        class Stubborn(FakeDex):
            def _read_feature(self, index, function, params=b""):
                if function == 0x03:
                    self.writes.append(params[0])
                    return bytes([0x11, 0x02, index, 0x31, 0x00, 0x00])
                return FakeDex._read_feature(self, index, function, params)

        fake = Stubborn(current_code=3)
        device = make_dex()
        # Rewire the read to the stubborn fake's, leaving the rest in place.
        device._read_feature = lambda index, function, params=b"": fake._read_feature(
            index, function, params
        )
        assert device.set_report_rate(8000) is False
        assert fake.writes == [6]

    def test_a_rate_the_device_does_not_have_at_all_is_refused(self):
        device = make_dex()
        assert device.set_report_rate(12345) is False

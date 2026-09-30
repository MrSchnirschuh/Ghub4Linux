"""Tests for the hidraw-based HID++ 2.0 transport.

The transport talks to ``/dev/hidraw*`` through ``os.write``/``os.read`` plus
``select``; the tests substitute a fake file descriptor so framing, error
handling and feature discovery are covered without real Logitech hardware.

The regressions locked in here:

* short (7-byte) vs long (20-byte) reports are chosen by payload length,
* ``0x00`` is never used as a software id (it belongs to the host),
* a reply addressed to another device index is not handed to this caller,
* feature *indexes* come from IRoot discovery, never from a hardcoded table.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ghub4linux.core import hidpp
from ghub4linux.core.hidpp import (
    DEVICE_INDEX_DIRECT,
    DEVICE_INDEX_RECEIVER_1,
    FEATURE_ERROR,
    HIDPP,
    HIDPPError,
    HIDPPUnsupportedError,
    HidrawDevice,
    _sysfs_props,
    enumerate_hidraw,
)

# Response frames are built here rather than imported so a change in the
# production constants cannot silently redefine the expected wire format.
SHORT_LEN = 7
LONG_LEN = 20


def long_response(device_index: int, feature_index: int, function_id: int, payload: bytes) -> bytes:
    header = bytes([0x11, device_index, feature_index, function_id << 4])
    return (header + payload).ljust(LONG_LEN, b"\x00")[:LONG_LEN]


def short_response(
    device_index: int, feature_index: int, function_id: int, payload: bytes
) -> bytes:
    header = bytes([0x10, device_index, feature_index, function_id << 4])
    return (header + payload).ljust(SHORT_LEN, b"\x00")[:SHORT_LEN]


class FakeHidraw:
    """Stand-in for an open hidraw fd.

    ``responses`` maps ``(device_index, feature_index, function_id)`` to the
    frame the device answers with.  A request that is not listed stays
    unanswered, which makes ``select`` report the fd as unreadable exactly like
    a real device refusing a feature.

    The methods mirror the signatures of the ``os`` functions they replace, so
    they can be used directly as ``side_effect`` for patched ``os.write`` /
    ``os.read``.
    """

    def __init__(self) -> None:
        self.responses: dict[tuple[int, int, int], bytes] = {}
        self.written: list[bytes] = []
        self._pending: list[bytes] = []
        self._responder = None

    def write(self, _fd: int, data: bytes) -> int:
        """Record a request and queue a matching response when one is staged."""
        self.written.append(data)
        if len(data) >= 4:
            key = (data[1], data[2], data[3] >> 4)
            if self._responder is not None:
                reply = self._responder(data)
                if reply:
                    self._pending.append(reply)
            elif key in self.responses:
                self._pending.append(self.responses[key])
        return len(data)

    def read(self, _fd: int, _size: int) -> bytes:
        """Pop the next staged response frame."""
        if not self._pending:
            raise BlockingIOError("no data")
        frame = self._pending.pop(0)
        return frame.ljust(64, b"\x00")[:64]

    @property
    def has_data(self) -> bool:
        return bool(self._pending)


@pytest.fixture
def link():
    """An open HIDPP link backed by a fake fd."""
    instance = HIDPP("/dev/hidraw-test", DEVICE_INDEX_DIRECT, timeout=0.2)
    fake = FakeHidraw()
    instance._fd = 7  # any int: the fd is never touched directly in tests
    instance._fake = fake

    def fake_select(*_args: object, **_kwargs: object) -> tuple[list, list, list]:
        """Report the fd readable exactly when a staged reply is waiting."""
        return ([7], [], []) if fake.has_data else ([], [], [])

    with (
        patch.object(hidpp.os, "write", fake.write),
        patch.object(hidpp.os, "read", fake.read),
        patch.object(hidpp.select, "select", fake_select),
    ):
        yield instance
    instance._fd = None


class TestFraming:
    """Short vs long reports must be chosen by payload length."""

    def test_short_request_is_seven_bytes(self, link):
        with pytest.raises(HIDPPError):  # unanswered, but the write happened
            link.request(0x05, 0x01, b"\x00\x01")
        frame = link._fake.written[-1]
        assert frame[0] == 0x10
        assert len(frame) == SHORT_LEN

    def test_long_request_is_twenty_bytes(self, link):
        with pytest.raises(HIDPPError):
            link.request(0x05, 0x01, bytes(10))
        frame = link._fake.written[-1]
        assert frame[0] == 0x11
        assert len(frame) == LONG_LEN

    def test_three_parameter_bytes_still_fit_a_short_report(self, link):
        with pytest.raises(HIDPPError):
            link.request(0x05, 0x01, bytes(3))
        assert len(link._fake.written[-1]) == SHORT_LEN

    def test_device_index_is_carried_in_the_header(self, link):
        link.device_index = DEVICE_INDEX_RECEIVER_1
        with pytest.raises(HIDPPError):
            link.request(0x05, 0x01, b"\x00")
        assert link._fake.written[-1][1] == DEVICE_INDEX_RECEIVER_1

    def test_function_is_in_the_high_nibble(self, link):
        with pytest.raises(HIDPPError):
            link.request(0x05, 0x03, b"\x00")
        assert link._fake.written[-1][3] >> 4 == 0x03

    def test_software_id_is_never_zero(self, link):
        # 0x00 is reserved for the host and must never be used for a request.
        for _ in range(4):
            with pytest.raises(HIDPPError):
                link.request(0x05, 0x01, b"\x00")
        for frame in link._fake.written:
            assert frame[3] & 0x0F != 0

    def test_software_ids_stay_within_the_nibble(self, link):
        seen = set()
        for _ in range(20):
            with pytest.raises(HIDPPError):
                link.request(0x05, 0x01, b"\x00")
            seen.add(link._fake.written[-1][3] & 0x0F)
        assert len(seen) <= 0x0F

    def test_oversized_parameters_are_rejected(self, link):
        with pytest.raises(HIDPPError):
            link.request(0x05, 0x01, bytes(LONG_LEN))


class TestResponses:
    def test_matching_response_is_returned(self, link):
        link._fake.responses[(DEVICE_INDEX_DIRECT, 0x05, 0x01)] = short_response(
            DEVICE_INDEX_DIRECT, 0x05, 0x01, bytes([0xAA, 0xBB, 0xCC])
        )
        response = link.request(0x05, 0x01, b"\x00")
        assert response[4:7] == bytes([0xAA, 0xBB, 0xCC])

    def test_response_for_another_device_index_times_out(self, link):
        # A receiver multiplexes endpoints: a reply addressed to another index
        # must not be handed to this caller.
        link._fake.responses[(DEVICE_INDEX_RECEIVER_1, 0x05, 0x01)] = short_response(
            DEVICE_INDEX_RECEIVER_1, 0x05, 0x01, b"\x01\x02\x03"
        )
        with pytest.raises(HIDPPError):
            link.request(0x05, 0x01, b"\x00")

    def test_response_for_another_function_times_out(self, link):
        link._fake.responses[(DEVICE_INDEX_DIRECT, 0x05, 0x02)] = short_response(
            DEVICE_INDEX_DIRECT, 0x05, 0x02, b"\x01\x02\x03"
        )
        with pytest.raises(HIDPPError):
            link.request(0x05, 0x01, b"\x00")

    def test_unanswered_request_raises(self, link):
        with pytest.raises(HIDPPError):
            link.request(0x05, 0x01, b"\x00")

    def test_error_frame_raises_unsupported(self, link):
        # An error reply carries feature index 0x8F plus the culprit feature
        # and the error code.  It arrives instead of the requested reply, so
        # the responder answers every request with the error frame.
        error = short_response(DEVICE_INDEX_DIRECT, FEATURE_ERROR, 0x01, bytes([0x03, 0x05, 0x01]))
        link._fake._responder = lambda _frame: error
        with pytest.raises(HIDPPUnsupportedError):
            link.request(0x05, 0x01, b"\x00")

    def test_closed_link_refuses_requests(self):
        instance = HIDPP("/dev/hidraw-test", DEVICE_INDEX_DIRECT, timeout=0.2)
        with pytest.raises(HIDPPError):
            instance.request(0x05, 0x01, b"\x00")


class TestFeatureDiscovery:
    def test_feature_index_is_read_from_iroot(self, link):
        # Measured on a G502: IRoot fn 0 answers long, with the device-local
        # index in frame[4] followed by the feature type.
        #   request  10 01 00 00 22 01 00
        #   response 11 01 00 01 0c 00 01   -> index 0x0c, type 0x01
        link._fake.responses[(DEVICE_INDEX_DIRECT, 0x00, 0x00)] = long_response(
            DEVICE_INDEX_DIRECT, 0x00, 0x00, bytes([0x0C, 0x00, 0x01])
        )
        assert link.feature_index(0x2201) == 0x0C

    def test_index_zero_means_the_feature_is_absent(self, link):
        link._fake.responses[(DEVICE_INDEX_DIRECT, 0x00, 0x00)] = long_response(
            DEVICE_INDEX_DIRECT, 0x00, 0x00, bytes([0x00, 0x00, 0x00])
        )
        assert link.feature_index(0x2201) == 0

    def test_unanswered_iroot_reports_absent(self, link):
        assert link.feature_index(0x9999) == 0

    def test_lookup_is_cached(self, link):
        link._fake.responses[(DEVICE_INDEX_DIRECT, 0x00, 0x00)] = long_response(
            DEVICE_INDEX_DIRECT, 0x00, 0x00, bytes([0x0C, 0x00, 0x01])
        )
        link.feature_index(0x2201)
        writes = len(link._fake.written)
        assert link.feature_index(0x2201) == 0x0C
        assert len(link._fake.written) == writes

    def test_supports_reflects_discovery(self, link):
        link._fake.responses[(DEVICE_INDEX_DIRECT, 0x00, 0x00)] = long_response(
            DEVICE_INDEX_DIRECT, 0x00, 0x00, bytes([0x0C, 0x00, 0x01])
        )
        assert link.supports(0x2201) is True

    def test_absent_feature_is_not_supported(self, link):
        assert link.supports(0x9999) is False

    def test_discover_features_returns_only_present_ones(self, link):
        # Answer every IRoot probe: two candidates get an index, the rest zero.
        present = {0x2201: 0x0C, 0x1001: 0x06}

        def responder(frame: bytes) -> bytes:
            if frame[2] != 0x00:  # not an IRoot probe
                return b""
            feature_id = (frame[4] << 8) | frame[5]
            index = present.get(feature_id, 0)
            return long_response(DEVICE_INDEX_DIRECT, 0x00, 0x00, bytes([index, 0x00, 0x01]))

        link._fake._responder = responder
        assert link.discover_features() == present


class TestDeviceName:
    def test_name_is_decoded_from_the_chunks(self, link):
        text = b"G502 LIGHTSPEED"
        link._fake.responses[(DEVICE_INDEX_DIRECT, 0x01, 0x00)] = short_response(
            DEVICE_INDEX_DIRECT, 0x01, 0x00, bytes([len(text)])
        )
        link._fake.responses[(DEVICE_INDEX_DIRECT, 0x01, 0x01)] = long_response(
            DEVICE_INDEX_DIRECT, 0x01, 0x01, text
        )
        # IRoot answers with index 0x01 in frame[4] for feature 0x0005.
        link._fake.responses[(DEVICE_INDEX_DIRECT, 0x00, 0x00)] = long_response(
            DEVICE_INDEX_DIRECT, 0x00, 0x00, bytes([0x01, 0x00, 0x01])
        )
        assert link.device_name(0x0005) == "G502 LIGHTSPEED"

    def test_missing_feature_returns_none(self, link):
        assert link.device_name(0x0005) is None

    def test_zero_length_name_returns_none(self, link):
        # Feature present (index 0x01) but the device reports a 0-length string.
        link._fake.responses[(DEVICE_INDEX_DIRECT, 0x00, 0x00)] = long_response(
            DEVICE_INDEX_DIRECT, 0x00, 0x00, bytes([0x01, 0x00, 0x01])
        )
        link._fake.responses[(DEVICE_INDEX_DIRECT, 0x01, 0x00)] = short_response(
            DEVICE_INDEX_DIRECT, 0x01, 0x00, bytes([0x00])
        )
        assert link.device_name(0x0005) is None


class TestPing:
    def test_hidpp_10_ping_reports_the_protocol_version(self, link):
        # The 1.0 ping is not a feature request: it uses the literal 0x1B and
        # answers with the major/minor protocol version.
        link._fake.responses[(DEVICE_INDEX_DIRECT, 0x00, 0x01)] = bytes(
            [0x10, DEVICE_INDEX_DIRECT, 0x00, 0x1B, 0x04, 0x02, 0x00]
        )
        result = link.ping()
        assert result == (0x04, 0x02)

    def test_unanswered_ping_returns_none(self, link):
        assert link.ping() is None

    def test_ping_writes_the_raw_1b_frame(self, link):
        link.ping()
        frame = link._fake.written[-1]
        assert frame[3] == 0x1B
        assert frame[2] == 0x00


class TestHidrawDevice:
    def test_device_id_combines_vendor_product_serial(self):
        device = HidrawDevice(
            node="/dev/hidraw15",
            name="Logitech G502",
            vendor_id=0x046D,
            product_id=0x407F,
            hid_id="0003:0000046D:0000407F",
            usb_path="1-10.2.3",
            interface="2",
            serial="g502lightspeedwi",
        )
        assert device.device_id == "046d:407f:g502lightspeedwi"

    def test_a_mouse_is_not_a_receiver(self):
        device = HidrawDevice(
            node="/dev/hidraw15",
            name="Logitech G502",
            vendor_id=0x046D,
            product_id=0x407F,
            hid_id="",
            usb_path="",
            interface="",
        )
        assert device.is_receiver is False

    def test_a_lightspeed_dongle_is_a_receiver(self):
        device = HidrawDevice(
            node="/dev/hidraw19",
            name="Logitech USB Receiver",
            vendor_id=0x046D,
            product_id=0xC54D,
            hid_id="",
            usb_path="",
            interface="",
        )
        assert device.is_receiver is True


class TestSysfs:
    def test_uevent_is_parsed_into_a_mapping(self, tmp_path):
        # The real path is <node>/device/uevent, not <node>/uevent.
        device = tmp_path / "hidraw0" / "device"
        device.mkdir(parents=True)
        (device / "uevent").write_text(
            "DRIVER=hid-generic\nHID_ID=0003:0000046D:0000C54D\nHID_NAME=Logitech USB Receiver\n"
        )
        props = _sysfs_props(str(tmp_path / "hidraw0"))
        assert props["HID_NAME"] == "Logitech USB Receiver"
        assert props["HID_ID"] == "0003:0000046D:0000C54D"

    def test_missing_uevent_yields_an_empty_mapping(self, tmp_path):
        assert _sysfs_props(str(tmp_path / "nope")) == {}

    def test_enumerate_without_nodes_returns_empty(self):
        with patch.object(hidpp.glob, "glob", return_value=[]):
            assert enumerate_hidraw(0x046D) == []


class TestClose:
    def test_close_survives_a_bad_fd(self):
        instance = HIDPP("/dev/hidraw-test", DEVICE_INDEX_DIRECT, timeout=0.2)
        instance._fd = 12345  # not open: os.close raises EBADF
        instance.close()  # must not propagate
        assert instance._fd is None

    def test_close_is_idempotent(self):
        instance = HIDPP("/dev/hidraw-test", DEVICE_INDEX_DIRECT, timeout=0.2)
        instance.close()
        instance.close()
        assert instance._fd is None

    def test_context_manager_returns_the_link(self):
        instance = HIDPP("/dev/hidraw-test", DEVICE_INDEX_DIRECT, timeout=0.2)
        with patch.object(HIDPP, "open", lambda _self: None), instance as entered:
            assert entered is instance
        assert instance._fd is None

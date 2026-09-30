"""HID++ 2.0 transport over ``/dev/hidraw*``.

This module talks to Logitech devices through the kernel's hidraw interface
instead of ``hidapi``.  Two reasons:

* ``hidapi`` built against libusb needs write access to ``/dev/bus/usb`` — a
  plain desktop user does not have that, so every ``open()`` fails with
  ``OSError: open failed`` even when the device works perfectly.
* ``hidapi`` in 0.15.0 exposes ``hid.device``/``hid.Device``, not
  ``hid.Device``; the wrapper also reports empty ``product_string`` for
  Logitech receivers, which makes device identification impossible.

The kernel already knows the real product name (``HID_NAME`` in the hidraw
uevent), so enumeration reads sysfs and the actual HID++ conversation runs
over a file descriptor.  No third-party dependency is required.
"""

from __future__ import annotations

import contextlib
import glob
import logging
import os
import select
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

LOGITECH_VENDOR_ID = 0x046D

# HID++ report ids
HIDPP_SHORT = 0x10
HIDPP_LONG = 0x11
SHORT_LEN = 7
LONG_LEN = 20

# Root (IRoot) feature and the reserved error feature index
FEATURE_ROOT = 0x0000
FEATURE_ERROR = 0x8F

# Device index used for a device that is attached directly over USB, and for
# the first paired device behind a Unifying/LightSpeed receiver.
DEVICE_INDEX_DIRECT = 0xFF
DEVICE_INDEX_RECEIVER_1 = 0x01
DEVICE_INDEX_BLUETOOTH = 0x01

# Well-known HID++ 2.0 feature IDs
FEATURE_DEVICE_INFO = 0x0003
FEATURE_DEVICE_NAME = 0x0005
FEATURE_BATTERY_STATUS = 0x1000
FEATURE_BATTERY_VOLTAGE = 0x1001
FEATURE_UNIFIED_BATTERY = 0x1004
FEATURE_LED_CONTROL = 0x1300
FEATURE_ADJUSTABLE_DPI = 0x2201
FEATURE_EXTENDED_ADJUSTABLE_DPI = 0x2202
FEATURE_REPORT_RATE = 0x8060
FEATURE_EXT_REPORT_RATE = 0x8061
FEATURE_RGB_EFFECTS = 0x8071
FEATURE_COLOR_LED_EFFECTS = 0x8070
FEATURE_ONBOARD_PROFILES = 0x8100

# Features worth discovering; ordered by relevance for this application.
DISCOVERABLE_FEATURES: tuple[int, ...] = (
    FEATURE_DEVICE_INFO,
    FEATURE_DEVICE_NAME,
    FEATURE_ADJUSTABLE_DPI,
    FEATURE_EXTENDED_ADJUSTABLE_DPI,
    FEATURE_UNIFIED_BATTERY,
    FEATURE_BATTERY_STATUS,
    FEATURE_BATTERY_VOLTAGE,
    FEATURE_LED_CONTROL,
    FEATURE_RGB_EFFECTS,
    FEATURE_COLOR_LED_EFFECTS,
    FEATURE_REPORT_RATE,
    FEATURE_EXT_REPORT_RATE,
    FEATURE_ONBOARD_PROFILES,
)


class HIDPPError(Exception):
    """A HID++ request could not be completed."""


class HIDPPUnsupportedError(HIDPPError):
    """The device answered with an HID++ 'unsupported' error frame."""


@dataclass
class HidrawDevice:
    """A ``/dev/hidrawN`` node as described by sysfs."""

    node: str
    name: str
    vendor_id: int
    product_id: int
    hid_id: str
    usb_path: str
    interface: str
    serial: str = ""

    @property
    def device_id(self) -> str:
        """Stable identifier: ``vendor:product:serial`` (serial may be empty)."""
        return f"{self.vendor_id:04x}:{self.product_id:04x}:{self.serial}"

    @property
    def is_receiver(self) -> bool:
        """True for receiver dongles rather than the endpoint device itself."""
        upper = self.product_id & 0xF000
        return self.product_id in RECEIVER_PIDS or upper == 0xC000


# Receiver / PowerPlay dongle product IDs.
RECEIVER_PIDS: frozenset[int] = frozenset(
    {
        0xC539,  # Lightspeed Receiver (Unifying era)
        0xC53A,  # PowerPlay Wireless Charging System (1st gen)
        0xC547,  # Lightspeed Receiver
        0xC54D,  # Lightspeed Receiver (PRO X Superlight 2 / DEX)
    }
)


def _sysfs_props(node: str) -> dict[str, str]:
    """Read the uevent properties of a hidraw node."""
    props: dict[str, str] = {}
    try:
        with open(f"{node}/device/uevent") as handle:
            for line in handle:
                if "=" in line:
                    key, value = line.rstrip("\n").split("=", 1)
                    props[key] = value
    except OSError:
        return {}
    return props


def _usb_serial(node: str) -> str:
    """Return the USB iSerial of the interface's parent device, if readable."""
    try:
        base = os.path.realpath(f"{node}/device")
        # walk up to the usb_device directory that owns the 'serial' attribute
        cur = base
        for _ in range(4):
            candidate = os.path.join(cur, "serial")
            if os.path.exists(candidate):
                with open(candidate) as handle:
                    return handle.read().strip()
            cur = os.path.dirname(cur)
    except OSError:
        pass
    return ""


def enumerate_hidraw(vendor_id: int | None = LOGITECH_VENDOR_ID) -> list[HidrawDevice]:
    """List available hidraw nodes, optionally filtered by USB vendor id."""
    found: list[HidrawDevice] = []
    for sysfs in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        props = _sysfs_props(sysfs)
        hid_id = props.get("HID_ID", "")  # e.g. 0003:0000046D:0000407F
        parts = hid_id.split(":")
        if len(parts) != 3:
            continue
        try:
            bus, vid, pid = (int(p, 16) for p in parts)
        except ValueError:
            continue
        if vendor_id is not None and vid != vendor_id:
            continue
        dev = HidrawDevice(
            node=f"/dev/{os.path.basename(sysfs)}",
            name=props.get("HID_NAME", ""),
            vendor_id=vid,
            product_id=pid,
            hid_id=hid_id,
            usb_path=os.path.basename(os.path.dirname(os.path.realpath(f"{sysfs}/device"))),
            interface=os.path.basename(os.path.realpath(f"{sysfs}/device")),
            serial=_usb_serial(sysfs),
        )
        found.append(dev)
    return found


class HIDPP:
    """A HID++ 2.0 conversation with one device index on one hidraw node."""

    def __init__(self, node: str, device_index: int = DEVICE_INDEX_DIRECT, timeout: float = 0.6):
        self.node = node
        self.device_index = device_index
        self.timeout = timeout
        self._fd: int | None = None
        self._feature_cache: dict[int, int] = {}
        self._sw_id = 0

    # ── lifecycle ────────────────────────────────────────────────────────────
    def open(self) -> None:
        """Open the hidraw node for reading and writing."""
        try:
            self._fd = os.open(self.node, os.O_RDWR | os.O_NONBLOCK)
        except OSError as exc:
            raise HIDPPError(f"cannot open {self.node}: {exc}") from exc
        self._drain()

    def close(self) -> None:
        """Close the node."""
        if self._fd is not None:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "HIDPP":
        self.open()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ── low level ────────────────────────────────────────────────────────────
    def _drain(self, idle: float = 0.02) -> int:
        """Discard notifications left in the buffer, return their count."""
        if self._fd is None:
            return 0
        count = 0
        while select.select([self._fd], [], [], idle)[0]:
            try:
                os.read(self._fd, 64)
                count += 1
            except OSError:
                break
        return count

    def write_raw(self, data: bytes) -> int:
        """Write a raw report (report id included) to the node."""
        if self._fd is None:
            raise HIDPPError("connection not open")
        try:
            return os.write(self._fd, data)
        except OSError as exc:
            raise HIDPPError(f"write to {self.node} failed: {exc}") from exc

    def read_raw(self, size: int = 64, timeout: float | None = None) -> bytes:
        """Read one raw report from the node, or ``b""`` on timeout."""
        if self._fd is None:
            raise HIDPPError("connection not open")
        wait = timeout if timeout is not None else self.timeout
        if not select.select([self._fd], [], [], wait)[0]:
            return b""
        try:
            return os.read(self._fd, size)
        except OSError:
            return b""

    def _next_sw_id(self) -> int:
        self._sw_id = (self._sw_id + 1) % 16 or 1
        return self._sw_id

    def ping(self, timeout: float | None = None) -> tuple[int, int] | None:
        """Perform a HID++ 1.0 ping and return ``(major, minor)``.

        The 1.0 ping is not a HID++ 2.0 feature request: its fourth byte is the
        literal ``0x1B`` (function ``0x1`` and software id ``0xB``), so it is
        written raw instead of going through :meth:`request`.
        """
        if self._fd is None:
            raise HIDPPError("connection not open")
        self._drain()
        packet = bytes([HIDPP_SHORT, self.device_index, 0x00, 0x1B, 0x00, 0x00, 0x00])
        try:
            os.write(self._fd, packet)
        except OSError as exc:
            raise HIDPPError(f"write to {self.node} failed: {exc}") from exc

        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return None
            if not select.select([self._fd], [], [], left)[0]:
                continue
            try:
                frame = os.read(self._fd, 64)
            except OSError:
                continue
            if len(frame) >= 6 and frame[2] == 0x00 and frame[3] == 0x1B:
                return frame[4], frame[5]

    def request(
        self,
        feature_index: int,
        function: int,
        params: bytes = b"",
        timeout: float | None = None,
    ) -> bytes:
        """Send one HID++ request and return the matching response frame."""
        if self._fd is None:
            raise HIDPPError("connection not open")

        long_msg = len(params) > 3
        size = LONG_LEN if long_msg else SHORT_LEN
        sw_id = self._next_sw_id()
        # Byte 3 packs the function and the software id.  Two shapes exist:
        # most features use a nibble function (0x0-0xF) which has to be shifted
        # into the high nibble, while some — notably OnboardProfiles 0x8100 —
        # use an 8-bit command space (0x00, 0x10, 0x20 … 0xD0) that is already
        # aligned and must not be shifted at all.  Shifting those raised
        # ValueError, so 0x8100 could never be spoken to; masking a nibble
        # instead would collapse every ordinary function to zero.  Pick by
        # whether the value fits in a nibble.
        command = (function << 4) if function <= 0x0F else (function & 0xF0)
        header = bytes(
            [
                HIDPP_LONG if long_msg else HIDPP_SHORT,
                self.device_index,
                feature_index,
                command | sw_id,
            ]
        )
        packet = header + params
        if len(packet) > size:
            raise HIDPPError("parameters too long for a HID++ report")
        packet += bytes(size - len(packet))

        self._drain()
        try:
            os.write(self._fd, packet)
        except OSError as exc:
            raise HIDPPError(f"write to {self.node} failed: {exc}") from exc

        deadline = time.monotonic() + (timeout if timeout is not None else self.timeout)
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise HIDPPError(f"timeout waiting for response from {self.node}")
            if not select.select([self._fd], [], [], left)[0]:
                continue
            try:
                frame = os.read(self._fd, 64)
            except OSError:
                continue
            if len(frame) < 4:
                continue
            # Error frames carry feature_index 0x8F and report the culprit.
            if frame[2] == FEATURE_ERROR:
                code = frame[4] if len(frame) > 4 else 0
                raise HIDPPUnsupportedError(
                    f"feature {frame[5] if len(frame) > 5 else feature_index:#04x} "
                    f"rejected with error {code:#04x}"
                )
            if frame[2] == feature_index and (frame[3] >> 4) == function:
                return frame
            # anything else is a notification or a stale reply — keep waiting

    # ── feature discovery ────────────────────────────────────────────────────
    def feature_index(self, feature_id: int) -> int:
        """Resolve a HID++ feature ID to its device-local index (0 = absent)."""
        if feature_id in self._feature_cache:
            return self._feature_cache[feature_id]
        params = bytes([(feature_id >> 8) & 0xFF, feature_id & 0xFF])
        index = 0
        try:
            frame = self.request(FEATURE_ROOT, 0x00, params)
            if len(frame) >= 5:
                index = frame[4]
        except HIDPPError:
            index = 0
        self._feature_cache[feature_id] = index
        return index

    def supports(self, feature_id: int) -> bool:
        """True when the device exposes *feature_id*."""
        return self.feature_index(feature_id) != 0

    def discover_features(self) -> dict[int, int]:
        """Map every known feature ID to its index for the supported ones."""
        return {fid: index for fid in DISCOVERABLE_FEATURES if (index := self.feature_index(fid))}

    # ── convenience readers ──────────────────────────────────────────────────
    def device_name(self, feature_id: int = FEATURE_DEVICE_NAME) -> str | None:
        """Read the device's own name string, if the feature is available."""
        index = self.feature_index(feature_id)
        if not index:
            return None
        try:
            length = self.request(index, 0x00)[4]
        except HIDPPError:
            return None
        if length == 0 or length > 64:
            return None
        raw = bytearray()
        offset = 0
        while offset < length:
            try:
                chunk = self.request(index, 0x01, bytes([offset]))
            except HIDPPError:
                break
            if len(chunk) <= 4:
                break
            raw += bytes(chunk[4 : 4 + min(16, length - offset)])
            offset += 16
        return raw.decode("utf-8", "replace").rstrip("\x00") or None

    def protocol_version(self) -> tuple[int, int] | None:
        """Return the HID++ protocol version via a 1.0 ping."""
        return self.ping()

    def device_product_id(self) -> int | None:
        """Read the device's own USB product ID from DeviceInfo (0x0003).

        On a receiver endpoint the HID++ header carries the *dongle's* product
        ID (0xc54d / 0xc53a), so the peripheral looks like its own dongle.  The
        DeviceInfo entity for the peripheral carries the real ID, which is what
        a driver lookup needs.

        Measured on a G502 behind a PowerPlay pad and on a PRO X 2 DEX behind a
        Lightspeed receiver: the entity fields are ``type, unitId, transport,
        modelId[4] (LE), version[3], pid_hi, pid_lo`` — the entity with
        ``type == 0`` is the peripheral, and its PID appears as
        ``.. 01 <hi> <lo>`` (``40 7f`` / ``40 b8`` for these two mice).
        """
        index = self.feature_index(FEATURE_DEVICE_INFO)
        if not index:
            return None
        try:
            count = self.request(index, 0x00)[4]
        except HIDPPError:
            return None

        for entity in range(min(count, 8)):
            try:
                payload = bytes(self.request(index, 0x01, bytes([entity]))[4:])
            except HIDPPError:
                continue
            if len(payload) < 11 or payload[0] != 0:
                continue
            # The PID is the last big-endian u16 of the entity descriptor and
            # must look like a Logitech product ID; anything else is a
            # different firmware revision field.
            candidate = (payload[9] << 8) | payload[10]
            if 0x2000 <= candidate <= 0xFFFF:
                return candidate
        return None


def probe(
    node: str, indexes: tuple[int, ...] = (DEVICE_INDEX_DIRECT, DEVICE_INDEX_RECEIVER_1)
) -> tuple[int, str] | None:
    """Find a device index on *node* that answers HID++ and return (index, name)."""
    for index in indexes:
        try:
            with HIDPP(node, index, timeout=0.5) as link:
                name = link.device_name()
                if name:
                    return index, name
                if link.feature_index(FEATURE_ROOT) or link.discover_features():
                    return index, ""
        except HIDPPError:
            continue
    return None

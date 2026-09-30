"""Device discovery and connection layer.

This module enumerates Logitech peripherals through the kernel's ``hidraw``
interface and keeps the public API (``HIDDevice``, ``HIDManager``,
``HIDConnection``) that the rest of the code base and the test-suite expect.

Why hidraw and not ``hidapi``
-----------------------------
``hidapi`` as shipped by distributions is usually linked against **libusb**,
which opens ``/dev/bus/usb/...``; a normal desktop user has no write access
there, so every ``open()`` fails with ``OSError: open failed`` even though the
device works fine.  Additionally the 0.15.0 Python binding exposes
``hid.device``/``hid.Device`` and reports an *empty* ``product_string`` for
Logitech receivers, which makes it impossible to tell a dongle from the mouse
behind it.

The kernel already knows the truth: ``HID_NAME`` in the hidraw uevent names the
paired device (``Logitech G502``, ``Logitech PRO X 2 DEX``).  Enumeration reads
sysfs; the HID++ conversation runs over a file descriptor (see
:mod:`ghub4linux.core.hidpp`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from .hidpp import (
    DEVICE_INDEX_DIRECT,
    DEVICE_INDEX_RECEIVER_1,
    FEATURE_ADJUSTABLE_DPI,
    FEATURE_BATTERY_STATUS,
    FEATURE_BATTERY_VOLTAGE,
    FEATURE_DEVICE_INFO,
    FEATURE_DEVICE_NAME,
    FEATURE_ERROR,
    FEATURE_EXTENDED_ADJUSTABLE_DPI,
    FEATURE_LED_CONTROL,
    FEATURE_ONBOARD_PROFILES,
    FEATURE_REPORT_RATE,
    FEATURE_RGB_EFFECTS,
    FEATURE_ROOT,
    FEATURE_UNIFIED_BATTERY,
    HIDPP,
    LOGITECH_VENDOR_ID,
    RECEIVER_PIDS,
    HIDPPError,
    HIDPPUnsupportedError,
    HidrawDevice,
    enumerate_hidraw,
)

logger = logging.getLogger(__name__)

# Feature *indexes* are never hardcoded: they are resolved per device via HID++
# feature discovery, because the same feature sits at a different index on every
# model (the G502 reports AdjustableDPI at 0x0c, not at the 0x06 the code used
# to assume, and it carries BatteryVoltage rather than BatteryStatus).
DISCOVERABLE_FEATURES: tuple[int, ...] = (
    FEATURE_DEVICE_INFO,
    FEATURE_ADJUSTABLE_DPI,
    FEATURE_EXTENDED_ADJUSTABLE_DPI,
    FEATURE_UNIFIED_BATTERY,
    FEATURE_BATTERY_STATUS,
    FEATURE_BATTERY_VOLTAGE,
    FEATURE_LED_CONTROL,
    FEATURE_RGB_EFFECTS,
    FEATURE_REPORT_RATE,
    FEATURE_ONBOARD_PROFILES,
)

# Features that only a real peripheral has — not a dongle, not a companion chip.
PERIPHERAL_MARKER_FEATURES: tuple[int, ...] = (
    FEATURE_ADJUSTABLE_DPI,
    FEATURE_EXTENDED_ADJUSTABLE_DPI,
    FEATURE_UNIFIED_BATTERY,
    FEATURE_ONBOARD_PROFILES,
    FEATURE_RGB_EFFECTS,
    FEATURE_LED_CONTROL,
)

# Receiver PIDs, re-exported under the names the device drivers use.
LIGHTSPEED_RECEIVER_PID_1 = 0xC539
LIGHTSPEED_RECEIVER_PID_2 = 0xC53A
LIGHTSPEED_RECEIVER_PID_3 = 0xC547
LIGHTSPEED_RECEIVER_PID_4 = 0xC54D


class HIDError(Exception):
    """HID communication error."""


@dataclass
class HIDDevice:
    """A Logitech peripheral reachable over a hidraw node.

    ``node`` plus ``device_index`` identify the endpoint: a mouse paired to a
    receiver lives at index ``0x01`` on that receiver's node, and a device
    plugged in directly answers at ``0xFF``.
    """

    vendor_id: int
    product_id: int
    serial_number: str
    manufacturer: str
    product: str
    path: bytes
    interface_number: int
    usage_page: int
    usage: int
    node: str = ""
    device_index: int = DEVICE_INDEX_DIRECT
    receiver_name: str = ""
    identified: bool = False

    @property
    def device_id(self) -> str:
        """Get unique device identifier."""
        return f"{self.vendor_id:04x}:{self.product_id:04x}:{self.serial_number}"

    @property
    def is_receiver_endpoint(self) -> bool:
        """True when the endpoint is a device paired behind a receiver."""
        return self.device_index != DEVICE_INDEX_DIRECT


class HIDConnection:
    """Manages HID++ connection to a device."""

    def __init__(self, device: HIDDevice):
        """Initialize HID connection."""
        self.device = device
        self._link: HIDPP | None = None

    def open(self) -> None:
        """Open connection to the device."""
        if not self.device.node:
            raise HIDError(f"no hidraw node for {self.device.product!r}")
        link = HIDPP(self.device.node, self.device.device_index)
        try:
            link.open()
        except HIDPPError as exc:
            raise HIDError(f"Failed to open device: {exc}") from exc
        self._link = link
        logger.info(f"Opened connection to {self.device.product} on {self.device.node}")

    def close(self) -> None:
        """Close connection to the device."""
        if self._link:
            self._link.close()
            self._link = None
            logger.info(f"Closed connection to {self.device.product}")

    @property
    def link(self) -> HIDPP:
        """The underlying HID++ transport."""
        if self._link is None:
            raise HIDError("Device not open")
        return self._link

    def write(self, data: bytes) -> int:
        """Write raw report data to the device."""
        try:
            return self.link.write_raw(data)
        except HIDPPError as exc:
            raise HIDError(f"Failed to write to device: {exc}") from exc

    def read(self, size: int = 64, timeout: int = 1000) -> bytes:
        """Read raw report data from the device."""
        try:
            return self.link.read_raw(size, timeout / 1000)
        except HIDPPError as exc:
            raise HIDError(f"Failed to read from device: {exc}") from exc

    def send_feature_request(
        self,
        feature_index: int,
        function_id: int,
        params: bytes = b"",
        device_index: int | None = None,
    ) -> bytes:
        """Send a HID++ feature request and get the response."""
        if device_index is not None:
            self.link.device_index = device_index
        try:
            return self.link.request(feature_index, function_id, params)
        except HIDPPUnsupportedError:
            # An unsupported feature is not an error worth propagating: callers
            # treat an empty response as "the device said no".
            return b""
        except HIDPPError as exc:
            raise HIDError(str(exc)) from exc

    def feature_index(self, feature_id: int) -> int:
        """Resolve a feature ID to the device-local index (0 = unsupported)."""
        try:
            return self.link.feature_index(feature_id)
        except HIDPPError:
            return 0

    def __enter__(self) -> "HIDConnection":
        """Context manager entry."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()


class HIDManager:
    """Manages HID device enumeration and connections."""

    def __init__(self, probe_receivers: bool = True):
        """Initialize HID manager.

        With *probe_receivers* enabled, receiver dongles are asked over HID++
        which devices are paired with them — the only way to see a wireless
        mouse that answers on the receiver's node rather than its own.
        """
        self.probe_receivers = probe_receivers

    def enumerate_devices(
        self, vendor_id: int = LOGITECH_VENDOR_ID, product_id: int = 0
    ) -> list[HIDDevice]:
        """Enumerate connected Logitech HID devices."""
        nodes = enumerate_hidraw(vendor_id)
        if product_id:
            nodes = [n for n in nodes if n.product_id == product_id]

        devices: list[HIDDevice] = []
        seen: set[str] = set()
        for node in nodes:
            for endpoint in self._endpoints(node):
                key = f"{endpoint.device_id}:{endpoint.node}:{endpoint.device_index}"
                if key in seen:
                    continue
                seen.add(key)
                devices.append(endpoint)

        devices = _resolve_product_ids(devices)
        return _deduplicate(devices)

    def _endpoints(self, node: HidrawDevice) -> list[HIDDevice]:
        """Resolve the peripherals reachable through one hidraw node."""
        # A dongle has no endpoint of its own; a device paired to it answers at
        # index 0x01.  Only one of a dongle's interfaces speaks HID++ — writing
        # to the others fails with EPIPE — so probing is done per node instead
        # of assuming an interface number.
        if node.is_receiver:
            if not self.probe_receivers:
                return []
            indexes: tuple[int, ...] = (DEVICE_INDEX_RECEIVER_1,)
        else:
            indexes = (DEVICE_INDEX_DIRECT,)

        endpoints: list[HIDDevice] = []
        for index in indexes:
            try:
                # The enumeration timeout is generous on purpose: the direct
                # node of a wireless mouse carries the input-report flood
                # (hundreds of frames per second), which delays HID++ replies
                # well beyond the sub-second timeout used for steady state.
                link = HIDPP(node.node, index, timeout=1.5)
                link.open()
            except HIDPPError as exc:
                logger.debug(f"{node.node} idx {index:#04x}: {exc}")
                continue
            try:
                name = link.device_name()
                if not name:
                    # One retry: a single dropped reply must not turn a known
                    # device into an anonymous PID entry.
                    name = link.device_name()
                features = link.discover_features()
            except HIDPPError as exc:
                logger.debug(f"{node.node} idx {index:#04x}: {exc}")
                continue
            finally:
                link.close()

            if not name and not features:
                continue
            if name and _is_internal(name):
                logger.debug(f"{node.node}: skipping internal device {name!r}")
                continue
            if not any(f in features for f in PERIPHERAL_MARKER_FEATURES):
                logger.debug(f"{node.node}: {name!r} exposes no peripheral feature")
                continue

            display = name or node.name
            endpoints.append(
                HIDDevice(
                    vendor_id=node.vendor_id,
                    product_id=node.product_id,
                    serial_number=node.serial or _endpoint_serial(name or ""),
                    manufacturer="Logitech",
                    product=display,
                    path=node.node.encode(),
                    interface_number=index,
                    usage_page=0xFF00,
                    usage=0x0001,
                    node=node.node,
                    device_index=index,
                    receiver_name=node.name if index == DEVICE_INDEX_RECEIVER_1 else "",
                    identified=bool(name),
                )
            )
        return endpoints

    def find_logitech_devices(self) -> list[HIDDevice]:
        """Find all Logitech gaming devices."""
        return self.enumerate_devices(LOGITECH_VENDOR_ID)

    def get_connection(self, device: HIDDevice) -> HIDConnection:
        """Get a connection to a device."""
        return HIDConnection(device)


def _is_internal(name: str) -> bool:
    """True for dongles and companion chips that are not user-facing devices."""
    lowered = name.lower()
    return any(marker in lowered for marker in ("companion chip", "receiver"))


def _resolve_product_ids(devices: list[HIDDevice]) -> list[HIDDevice]:
    """Replace a dongle's product ID with the paired peripheral's own ID.

    A mouse paired to a receiver is reachable at index ``0x01`` on the dongle's
    node and reports the *dongle's* USB product ID there (the receiver's own
    0xc54d / 0xc53a), so driver lookup by PID would miss it.  The same mouse
    also exposes its own USB node while it is awake, and that node carries the
    real product ID (0x40b8 for a PRO X 2 DEX).  Name is the join key because
    the wireless endpoint reports no serial on the receiver path.

    A direct node that never answered HID++ is dropped when the same product is
    already represented by an identified endpoint.  Such a node is the
    peripheral's own USB interface caught in a power-saving state, and keeping
    it would list the same mouse twice — once as an anonymous ``046d:407f:``
    entry and once by name.
    """
    real_ids: dict[str, int] = {}
    named_pids: dict[int, str] = {}
    for device in devices:
        if device.identified:
            key = device.product.strip().lower()
            if not device.is_receiver_endpoint:
                real_ids[key] = device.product_id
            named_pids.setdefault(device.product_id, key)

    resolved: list[HIDDevice] = []
    for device in devices:
        if not device.identified:
            # Drop an anonymous direct node whose PID already has a named
            # endpoint elsewhere; keep it otherwise (a driver may still match
            # it, and silently hiding a device would be worse).
            if not device.is_receiver_endpoint and device.product_id in named_pids:
                continue
            resolved.append(device)
            continue
        if not device.is_receiver_endpoint:
            resolved.append(device)
            continue

        real = real_ids.get(device.product.strip().lower())
        if real is None or real == device.product_id:
            resolved.append(device)
            continue
        # The peripheral answers on the dongle's node with the dongle's PID;
        # hand it its own ID so driver lookup matches, and leave the
        # peripheral's own node in the list.  The two entries carry the same
        # name, so the deduplication step collapses them and keeps the quieter
        # receiver path.
        resolved.append(replace(device, product_id=real))
    return resolved


def _deduplicate(devices: list[HIDDevice]) -> list[HIDDevice]:
    """Collapse the same physical device reachable through several paths.

    A wireless mouse on a PowerPlay pad is reachable twice — once through the
    receiver node and once through its own USB node.  The direct node is the
    less useful of the two: it carries the input-report flood (several hundred
    frames per second), which starves HID++ replies.  So when the same product
    ID shows up on more than one path, the endpoint that actually answered
    HID++ with a device name wins, and the rest are dropped.
    """

    def score(device: HIDDevice) -> tuple[int, int]:
        # Prefer a quiet receiver path over the input-flooded direct node; the
        # receiver answers HID++ immediately, so the GUI and CLI stay snappy.
        return (1 if device.is_receiver_endpoint else 0, 1 if device.identified else 0)

    def identity(device: HIDDevice) -> str:
        # A wireless endpoint reports no serial, but its HID++ device name is
        # the real identity — the same mouse seen on the receiver node and on
        # its own USB node answers with the same name.
        if device.identified:
            return device.product.strip().lower()
        return f"{device.product_id:04x}:{device.node}:{device.device_index}"

    best: dict[str, HIDDevice] = {}
    order: list[str] = []
    for device in devices:
        key = identity(device)
        current = best.get(key)
        if current is None:
            best[key] = device
            order.append(key)
        elif score(device) > score(current):
            best[key] = device
    return [best[key] for key in order]


def _endpoint_serial(name: str) -> str:
    """Fall back to a name-derived serial for wireless endpoints."""
    if not name:
        return ""
    return "".join(ch for ch in name.lower() if ch.isalnum())[:16]


__all__ = [
    "DISCOVERABLE_FEATURES",
    "FEATURE_ADJUSTABLE_DPI",
    "FEATURE_BATTERY_STATUS",
    "FEATURE_BATTERY_VOLTAGE",
    "FEATURE_DEVICE_INFO",
    "FEATURE_DEVICE_NAME",
    "FEATURE_ERROR",
    "FEATURE_LED_CONTROL",
    "FEATURE_ONBOARD_PROFILES",
    "FEATURE_REPORT_RATE",
    "FEATURE_RGB_EFFECTS",
    "FEATURE_ROOT",
    "FEATURE_UNIFIED_BATTERY",
    "HIDConnection",
    "HIDDevice",
    "HIDError",
    "HIDManager",
    "HIDPP",
    "HIDPPError",
    "LIGHTSPEED_RECEIVER_PID_1",
    "LIGHTSPEED_RECEIVER_PID_2",
    "LIGHTSPEED_RECEIVER_PID_3",
    "LIGHTSPEED_RECEIVER_PID_4",
    "LOGITECH_VENDOR_ID",
    "RECEIVER_PIDS",
]

"""HID communication layer for Logitech devices.

Provides low-level USB HID communication functionality for
interacting with Logitech gaming peripherals.
"""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import hid

logger = logging.getLogger(__name__)


# Logitech vendor ID
LOGITECH_VENDOR_ID = 0x046D

# HID++ protocol constants
HIDPP_SHORT_MESSAGE = 0x10
HIDPP_LONG_MESSAGE = 0x11
HIDPP_VERY_LONG_MESSAGE = 0x12

# Common feature indexes
FEATURE_ROOT = 0x0000
FEATURE_FEATURE_SET = 0x0001
FEATURE_DEVICE_INFO = 0x0003
FEATURE_DEVICE_NAME = 0x0005
FEATURE_BATTERY_STATUS = 0x1000
FEATURE_BATTERY_VOLTAGE = 0x1001
FEATURE_UNIFIED_BATTERY = 0x1004
FEATURE_LED_CONTROL = 0x1300
FEATURE_RGB_EFFECTS = 0x8071
FEATURE_ADJUSTABLE_DPI = 0x2201
FEATURE_ONBOARD_PROFILES = 0x8100
FEATURE_REPORT_RATE = 0x8060


@dataclass
class HIDDevice:
    """Represents an HID device."""

    vendor_id: int
    product_id: int
    serial_number: str
    manufacturer: str
    product: str
    path: bytes
    interface_number: int
    usage_page: int
    usage: int

    @property
    def device_id(self) -> str:
        """Get unique device identifier."""
        return f"{self.vendor_id:04x}:{self.product_id:04x}:{self.serial_number}"


class HIDError(Exception):
    """HID communication error."""


class HIDConnection:
    """Manages HID connection to a device."""

    def __init__(self, device: HIDDevice):
        """Initialize HID connection."""
        self.device = device
        self._handle: "hid.Device | None" = None

    def open(self) -> None:
        """Open connection to the device."""
        try:
            import hid

            self._handle = hid.Device(path=self.device.path)
            logger.info(f"Opened connection to {self.device.product}")
        except Exception as e:
            raise HIDError(f"Failed to open device: {e}") from e

    def close(self) -> None:
        """Close connection to the device."""
        if self._handle:
            self._handle.close()
            self._handle = None
            logger.info(f"Closed connection to {self.device.product}")

    def write(self, data: bytes) -> int:
        """Write data to the device."""
        if not self._handle:
            raise HIDError("Device not open")
        try:
            return self._handle.write(data)
        except Exception as e:
            raise HIDError(f"Failed to write to device: {e}") from e

    def read(self, size: int = 64, timeout: int = 1000) -> bytes:
        """Read data from the device."""
        if not self._handle:
            raise HIDError("Device not open")
        try:
            data = self._handle.read(size, timeout)
            return bytes(data) if data else b""
        except Exception as e:
            raise HIDError(f"Failed to read from device: {e}") from e

    def send_feature_request(
        self,
        feature_index: int,
        function_id: int,
        params: bytes = b"",
        device_index: int = 0xFF,
    ) -> bytes:
        """Send a HID++ feature request and get response."""
        # Build HID++ 2.0 message
        msg_type = HIDPP_LONG_MESSAGE if len(params) > 3 else HIDPP_SHORT_MESSAGE
        msg_len = 20 if msg_type == HIDPP_LONG_MESSAGE else 7

        message = bytearray(msg_len)
        message[0] = msg_type
        message[1] = device_index
        message[2] = feature_index
        message[3] = (function_id << 4) & 0xF0

        for i, b in enumerate(params):
            if i + 4 < msg_len:
                message[4 + i] = b

        self.write(bytes(message))
        response = self.read(msg_len)

        if not response:
            raise HIDError("No response from device")

        return response

    def __enter__(self) -> "HIDConnection":
        """Context manager entry."""
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()


class HIDManager:
    """Manages HID device enumeration and connections."""

    def __init__(self):
        """Initialize HID manager."""
        self._devices: list[HIDDevice] = []

    def enumerate_devices(
        self, vendor_id: int = LOGITECH_VENDOR_ID, product_id: int = 0
    ) -> list[HIDDevice]:
        """Enumerate connected HID devices."""
        try:
            import hid

            devices = []
            for dev_info in hid.enumerate(vendor_id, product_id):
                device = HIDDevice(
                    vendor_id=dev_info["vendor_id"],
                    product_id=dev_info["product_id"],
                    serial_number=dev_info.get("serial_number", ""),
                    manufacturer=dev_info.get("manufacturer_string", ""),
                    product=dev_info.get("product_string", ""),
                    path=dev_info["path"],
                    interface_number=dev_info.get("interface_number", -1),
                    usage_page=dev_info.get("usage_page", 0),
                    usage=dev_info.get("usage", 0),
                )
                devices.append(device)
            self._devices = devices
            return devices
        except ImportError:
            logger.warning("hidapi not available, using mock devices")
            return []
        except Exception as e:
            logger.error(f"Failed to enumerate devices: {e}")
            return []

    def find_logitech_devices(self) -> list[HIDDevice]:
        """Find all Logitech gaming devices."""
        return self.enumerate_devices(LOGITECH_VENDOR_ID)

    def get_connection(self, device: HIDDevice) -> HIDConnection:
        """Get a connection to a device."""
        return HIDConnection(device)

"""Logitech Pro DEX 2 device implementation.

Supports:
- Pro DEX 2 (PRO X Superlight 2 DEX)
"""

import logging

from ..core.config import DeviceConfig, DPISettings, LightingSettings
from ..core.device import (
    ConnectionType,
    DeviceCapability,
    DeviceInfo,
    DeviceType,
)
from ..core.hid import HIDDevice
from .g502 import G502Device

logger = logging.getLogger(__name__)


# Pro DEX 2 Product IDs
PRO_DEX_2_PID = 0x40A3  # Pro DEX 2 wireless
PRO_DEX_2_WIRED_PID = 0x40A4  # Pro DEX 2 wired mode
PRO_DEX_2_RECEIVER_PID = 0x40A5  # Pro DEX 2 receiver

# Lightspeed receiver PIDs (shared across multiple Logitech mice)
LIGHTSPEED_RECEIVER_PID_1 = 0xC539
LIGHTSPEED_RECEIVER_PID_2 = 0xC53A
LIGHTSPEED_RECEIVER_PID_3 = 0xC547


class ProDex2(G502Device):
    """Pro DEX 2 (PRO X Superlight 2 DEX) device implementation."""

    MAX_DPI = 44000
    DPI_STEP = 50
    BUTTON_COUNT = 5
    DEFAULT_DPI_LEVELS = [400, 800, 1600, 3200]

    def __init__(self, hid_device: HIDDevice, config: DeviceConfig | None = None):
        """Initialize Pro DEX 2 device."""
        super().__init__(hid_device, config)
        self._capabilities = {
            DeviceCapability.DPI_ADJUSTMENT,
            DeviceCapability.MACROS,
            DeviceCapability.ONBOARD_PROFILES,
            DeviceCapability.BATTERY_STATUS,
            DeviceCapability.REPORT_RATE,
        }
        self._dpi_feature_index: int | None = None
        self._battery_feature_index: int | None = None
        # ponytail: no RGB feature index — Pro DEX 2 has no RGB

    def _query_features(self) -> None:
        """Query HID++ feature indexes via IRoot (0x0000) feature discovery."""
        from ..core.hid import FEATURE_ADJUSTABLE_DPI, FEATURE_BATTERY_STATUS

        feature_map = self.discover_features()
        self._dpi_feature_index = feature_map.get(FEATURE_ADJUSTABLE_DPI, 0x06)
        self._battery_feature_index = feature_map.get(FEATURE_BATTERY_STATUS, 0x07)

    def get_device_info(self) -> DeviceInfo:
        """Get device information."""
        info = super().get_device_info()
        return DeviceInfo(
            name="PRO X SUPERLIGHT 2 DEX",
            model="PRO X SUPERLIGHT 2 DEX",
            vendor_id=info.vendor_id,
            product_id=info.product_id,
            serial_number=info.serial_number,
            firmware_version=info.firmware_version,
            device_type=DeviceType.MOUSE,
            connection_type=self._get_connection_type(),
            has_battery=True,
            has_rgb=False,
            max_dpi=self.MAX_DPI,
            dpi_step=self.DPI_STEP,
            button_count=self.BUTTON_COUNT,
            has_onboard_profiles=True,
        )

    def _get_connection_type(self) -> ConnectionType:
        """Determine connection type."""
        if self.hid_device.product_id == PRO_DEX_2_WIRED_PID:
            return ConnectionType.WIRED
        return ConnectionType.LIGHTSPEED

    def _set_lighting_settings(self, settings: LightingSettings) -> bool:
        """Set lighting settings (minimal on Pro DEX 2)."""
        self.active_profile.lighting_settings = settings
        return True

    def set_report_rate(self, rate: int) -> bool:
        """Set polling/report rate. Pro DEX 2 supports up to 4000Hz."""
        valid_rates = [125, 250, 500, 1000, 2000, 4000]
        if rate not in valid_rates:
            return False
        if not self._connection:
            return True
        try:
            rate_code = {125: 0x05, 250: 0x04, 500: 0x03, 1000: 0x02, 2000: 0x01, 4000: 0x00}[rate]
            self._connection.send_feature_request(0x09, 0x00, bytes([rate_code]))
            return True
        except Exception as e:
            logger.error(f"Failed to set report rate: {e}")
            return False


# Device registry mapping
PRO_DEX_2_DEVICES = {
    PRO_DEX_2_PID: ProDex2,
    PRO_DEX_2_WIRED_PID: ProDex2,
    PRO_DEX_2_RECEIVER_PID: ProDex2,
}

# Hint-based entries for shared Lightspeed receiver PIDs.
# Format: (product_id, product_string_hint, device_class).
# The hint is matched as a case-insensitive substring of the HID product string
# reported by the OS for the receiver device.
PRO_DEX_2_RECEIVER_HINTS: list[tuple[int, str, type]] = [
    (LIGHTSPEED_RECEIVER_PID_1, "pro x superlight", ProDex2),
    (LIGHTSPEED_RECEIVER_PID_2, "pro x superlight", ProDex2),
    (LIGHTSPEED_RECEIVER_PID_3, "pro x superlight", ProDex2),
]

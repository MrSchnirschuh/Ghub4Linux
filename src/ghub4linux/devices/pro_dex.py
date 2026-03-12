"""Logitech Pro DEX 2 device implementation.

Supports:
- Pro DEX 2 (PRO X Superlight 2 DEX)
"""

import logging

from ..core.config import (
    DeviceConfig,
    DPISettings,
    LightingSettings,
)
from ..core.device import (
    BaseDevice,
    BatteryStatus,
    ConnectionType,
    DeviceCapability,
    DeviceInfo,
    DeviceType,
)
from ..core.hid import HIDDevice

logger = logging.getLogger(__name__)


# Pro DEX 2 Product IDs
PRO_DEX_2_PID = 0x40A3  # Pro DEX 2 wireless
PRO_DEX_2_WIRED_PID = 0x40A4  # Pro DEX 2 wired mode
PRO_DEX_2_RECEIVER_PID = 0x40A5  # Pro DEX 2 receiver

# Lightspeed receiver PIDs (shared across multiple Logitech mice)
LIGHTSPEED_RECEIVER_PID_1 = 0xC539
LIGHTSPEED_RECEIVER_PID_2 = 0xC53A
LIGHTSPEED_RECEIVER_PID_3 = 0xC547


class ProDex2(BaseDevice):
    """Pro DEX 2 (PRO X Superlight 2 DEX) device implementation."""

    # Device specifications
    MAX_DPI = 44000  # Pro DEX 2 has very high max DPI
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
        # Pro DEX 2 has minimal RGB (just indicator)
        self._dpi_feature_index: int | None = None
        self._battery_feature_index: int | None = None

    def _init_device(self) -> None:
        """Initialize device after connection."""
        self._query_features()
        self._info = self.get_device_info()
        logger.info(f"Initialized {self._info.name}")

    def _query_features(self) -> None:
        """Query HID++ feature indexes via IRoot (0x0000) feature discovery.

        Falls back to typical hardcoded indexes when the device does not
        respond or is not connected.
        """
        from ..core.hid import FEATURE_ADJUSTABLE_DPI, FEATURE_BATTERY_STATUS

        feature_map = self.discover_features()

        self._dpi_feature_index = feature_map.get(FEATURE_ADJUSTABLE_DPI, 0x06)
        self._battery_feature_index = feature_map.get(FEATURE_BATTERY_STATUS, 0x07)

    def get_device_info(self) -> DeviceInfo:
        """Get device information."""
        return DeviceInfo(
            name="PRO DEX 2",
            model="PRO X Superlight 2 DEX",
            vendor_id=self.hid_device.vendor_id,
            product_id=self.hid_device.product_id,
            serial_number=self.hid_device.serial_number,
            firmware_version=self._get_firmware_version(),
            device_type=DeviceType.MOUSE,
            connection_type=self._get_connection_type(),
            has_battery=True,
            has_rgb=False,  # Pro DEX 2 has minimal lighting
            max_dpi=self.MAX_DPI,
            dpi_step=self.DPI_STEP,
            button_count=self.BUTTON_COUNT,
            has_onboard_profiles=True,
        )

    def _get_firmware_version(self) -> str:
        """Get firmware version from device."""
        if not self._connection:
            return "Unknown"

        try:
            response = self._connection.send_feature_request(0x00, 0x01)
            if response and len(response) >= 6:
                major = response[4]
                minor = response[5]
                return f"{major}.{minor}"
        except Exception as e:
            logger.debug(f"Could not get firmware version: {e}")

        return "Unknown"

    def _get_connection_type(self) -> ConnectionType:
        """Determine connection type."""
        if self.hid_device.product_id == PRO_DEX_2_WIRED_PID:
            return ConnectionType.WIRED
        return ConnectionType.LIGHTSPEED

    def _get_battery_status(self) -> BatteryStatus | None:
        """Get battery status from device."""
        if not self._connection or self._battery_feature_index is None:
            # Return mock data for demonstration
            return BatteryStatus(level=90, charging=False, voltage=3.9)

        try:
            response = self._connection.send_feature_request(
                self._battery_feature_index, 0x00
            )
            if response and len(response) >= 6:
                level = response[4]
                status = response[5]
                charging = (status & 0x80) != 0
                return BatteryStatus(level=level, charging=charging)
        except Exception as e:
            logger.debug(f"Could not get battery status: {e}")

        return BatteryStatus(level=0, charging=False)

    def _set_dpi_settings(self, settings: DPISettings) -> bool:
        """Set DPI settings on device."""
        if not self._connection or self._dpi_feature_index is None:
            self.active_profile.dpi_settings = settings
            return True

        try:
            for i, level in enumerate(settings.levels):
                dpi_value = level.dpi
                dpi_encoded = dpi_value // self.DPI_STEP

                params = bytes([i, (dpi_encoded >> 8) & 0xFF, dpi_encoded & 0xFF])
                self._connection.send_feature_request(
                    self._dpi_feature_index, 0x03, params
                )

            self._connection.send_feature_request(
                self._dpi_feature_index, 0x04, bytes([settings.active_level])
            )

            self.active_profile.dpi_settings = settings
            return True
        except Exception as e:
            logger.error(f"Failed to set DPI: {e}")
            return False

    def _set_lighting_settings(self, settings: LightingSettings) -> bool:
        """Set lighting settings (minimal on Pro DEX 2)."""
        # Pro DEX 2 has very limited lighting
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
            rate_code = {
                125: 0x05,
                250: 0x04,
                500: 0x03,
                1000: 0x02,
                2000: 0x01,
                4000: 0x00,
            }[rate]
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

# TODO: Add Logitech Powerplay mousepad support (PIDs not yet registered).
# The Powerplay mousepad has its own USB product IDs and acts as a Lightspeed
# receiver for the connected mouse while wirelessly charging it.

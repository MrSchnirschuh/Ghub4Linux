"""Logitech G502 device implementations.

Supports:
- G502 Lightspeed (wireless)
- G502X Plus (wireless with RGB)
"""

import logging

from ..core.config import (
    DeviceConfig,
    DPISettings,
    LightingEffect,
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
from ..core.hid import (
    HIDDevice,
)

logger = logging.getLogger(__name__)


# G502 Product IDs
G502_LIGHTSPEED_PID = 0x407F  # G502 Lightspeed wireless
G502_LIGHTSPEED_WIRED_PID = 0x407E  # G502 Lightspeed wired mode
G502X_PLUS_PID = 0x4099  # G502X Plus
G502X_PLUS_RECEIVER_PID = 0x409A  # G502X Plus receiver

# Lightspeed receiver PIDs (shared across multiple Logitech mice)
LIGHTSPEED_RECEIVER_PID_1 = 0xC539
LIGHTSPEED_RECEIVER_PID_2 = 0xC53A
LIGHTSPEED_RECEIVER_PID_3 = 0xC547


class G502Device(BaseDevice):
    """Base class for G502 series devices."""

    # Device specifications
    MAX_DPI = 25600
    DPI_STEP = 50
    BUTTON_COUNT = 11
    DEFAULT_DPI_LEVELS = [400, 800, 1600, 3200, 6400]

    def __init__(self, hid_device: HIDDevice, config: DeviceConfig | None = None):
        """Initialize G502 device."""
        super().__init__(hid_device, config)
        self._capabilities = {
            DeviceCapability.DPI_ADJUSTMENT,
            DeviceCapability.RGB_LIGHTING,
            DeviceCapability.MACROS,
            DeviceCapability.ONBOARD_PROFILES,
            DeviceCapability.BATTERY_STATUS,
            DeviceCapability.REPORT_RATE,
        }
        self._feature_indexes: dict[int, int] = {}
        self._dpi_feature_index: int | None = None
        self._battery_feature_index: int | None = None
        self._rgb_feature_index: int | None = None

    def _init_device(self) -> None:
        """Initialize device after connection."""
        # Query feature indexes
        self._query_features()
        # Get device info
        self._info = self.get_device_info()
        logger.info(f"Initialized {self._info.name}")

    def _query_features(self) -> None:
        """Query HID++ feature indexes via IRoot (0x0000) feature discovery.

        Falls back to typical hardcoded indexes when the device does not
        respond or is not connected.
        """
        from ..core.hid import (
            FEATURE_ADJUSTABLE_DPI,
            FEATURE_BATTERY_STATUS,
            FEATURE_RGB_EFFECTS,
        )

        feature_map = self.discover_features()

        self._dpi_feature_index = feature_map.get(FEATURE_ADJUSTABLE_DPI, 0x06)
        self._battery_feature_index = feature_map.get(FEATURE_BATTERY_STATUS, 0x07)
        self._rgb_feature_index = feature_map.get(FEATURE_RGB_EFFECTS, 0x08)

    def get_device_info(self) -> DeviceInfo:
        """Get device information."""
        return DeviceInfo(
            name=self.hid_device.product or "G502",
            model="G502",
            vendor_id=self.hid_device.vendor_id,
            product_id=self.hid_device.product_id,
            serial_number=self.hid_device.serial_number,
            firmware_version=self._get_firmware_version(),
            device_type=DeviceType.MOUSE,
            connection_type=self._get_connection_type(),
            has_battery=True,
            has_rgb=True,
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
            # Send firmware version request
            # This is a simplified implementation
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
        # G502 Lightspeed can be wired or wireless
        if self.hid_device.product_id in (G502_LIGHTSPEED_WIRED_PID,):
            return ConnectionType.WIRED
        return ConnectionType.LIGHTSPEED

    def _get_battery_status(self) -> BatteryStatus | None:
        """Get battery status from device."""
        if not self._connection or self._battery_feature_index is None:
            # Return mock data for demonstration
            return BatteryStatus(level=85, charging=False, voltage=3.8)

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
            # Update local config only
            self.active_profile.dpi_settings = settings
            return True

        try:
            # Set each DPI level
            for i, level in enumerate(settings.levels):
                dpi_value = level.dpi
                # Convert DPI to device format (usually divided by step)
                dpi_encoded = dpi_value // self.DPI_STEP

                params = bytes([i, (dpi_encoded >> 8) & 0xFF, dpi_encoded & 0xFF])
                self._connection.send_feature_request(
                    self._dpi_feature_index, 0x03, params
                )

            # Set active level
            self._connection.send_feature_request(
                self._dpi_feature_index, 0x04, bytes([settings.active_level])
            )

            self.active_profile.dpi_settings = settings
            return True
        except Exception as e:
            logger.error(f"Failed to set DPI: {e}")
            return False

    def _set_lighting_settings(self, settings: LightingSettings) -> bool:
        """Set lighting settings on device."""
        if not self._connection or self._rgb_feature_index is None:
            # Update local config only
            self.active_profile.lighting_settings = settings
            return True

        try:
            if not settings.enabled:
                # Turn off lighting
                self._connection.send_feature_request(
                    self._rgb_feature_index, 0x00, bytes([0x00])
                )
            else:
                # Set effect
                effect = settings.effect
                effect_code = self._get_effect_code(effect.effect_type)
                color = effect.color

                params = bytes(
                    [
                        effect_code,
                        color.red,
                        color.green,
                        color.blue,
                        effect.speed,
                        effect.brightness,
                    ]
                )
                self._connection.send_feature_request(
                    self._rgb_feature_index, 0x01, params
                )

            self.active_profile.lighting_settings = settings
            return True
        except Exception as e:
            logger.error(f"Failed to set lighting: {e}")
            return False

    def _get_effect_code(self, effect_type: str) -> int:
        """Convert effect type to device code."""
        effects = {
            "off": 0x00,
            "static": 0x01,
            "breathing": 0x02,
            "cycle": 0x03,
            "wave": 0x04,
        }
        return effects.get(effect_type, 0x01)

    def set_report_rate(self, rate: int) -> bool:
        """Set polling/report rate."""
        valid_rates = [125, 250, 500, 1000]
        if rate not in valid_rates:
            return False

        if not self._connection:
            return True  # Mock success

        try:
            rate_code = {125: 0x03, 250: 0x02, 500: 0x01, 1000: 0x00}[rate]
            self._connection.send_feature_request(0x09, 0x00, bytes([rate_code]))
            return True
        except Exception as e:
            logger.error(f"Failed to set report rate: {e}")
            return False


class G502Lightspeed(G502Device):
    """G502 Lightspeed specific implementation."""

    MAX_DPI = 25600

    def get_device_info(self) -> DeviceInfo:
        """Get device information."""
        info = super().get_device_info()
        return DeviceInfo(
            name="G502 Lightspeed",
            model="G502 Lightspeed",
            vendor_id=info.vendor_id,
            product_id=info.product_id,
            serial_number=info.serial_number,
            firmware_version=info.firmware_version,
            device_type=DeviceType.MOUSE,
            connection_type=ConnectionType.LIGHTSPEED,
            has_battery=True,
            has_rgb=True,
            max_dpi=self.MAX_DPI,
            dpi_step=50,
            button_count=11,
            has_onboard_profiles=True,
        )


class G502XPlus(G502Device):
    """G502X Plus specific implementation."""

    MAX_DPI = 25600
    BUTTON_COUNT = 13  # G502X Plus has more buttons

    def __init__(self, hid_device: HIDDevice, config: DeviceConfig | None = None):
        """Initialize G502X Plus."""
        super().__init__(hid_device, config)
        # G502X Plus has enhanced RGB with 8 zones
        self._rgb_zones = [
            "logo",
            "scroll_wheel",
            "front_left",
            "front_right",
            "side_left",
            "side_right",
            "dpi_indicator",
            "base",
        ]

    def get_device_info(self) -> DeviceInfo:
        """Get device information."""
        info = super().get_device_info()
        return DeviceInfo(
            name="G502 X Plus",
            model="G502X Plus",
            vendor_id=info.vendor_id,
            product_id=info.product_id,
            serial_number=info.serial_number,
            firmware_version=info.firmware_version,
            device_type=DeviceType.MOUSE,
            connection_type=ConnectionType.LIGHTSPEED,
            has_battery=True,
            has_rgb=True,
            max_dpi=self.MAX_DPI,
            dpi_step=50,
            button_count=self.BUTTON_COUNT,
            has_onboard_profiles=True,
        )

    def set_zone_lighting(self, zone: str, effect: LightingEffect) -> bool:
        """Set lighting for a specific RGB zone."""
        if zone not in self._rgb_zones:
            return False

        settings = self.active_profile.lighting_settings
        settings.zones[zone] = effect
        return self._set_lighting_settings(settings)


# Device registry mapping
G502_DEVICES = {
    G502_LIGHTSPEED_PID: G502Lightspeed,
    G502_LIGHTSPEED_WIRED_PID: G502Lightspeed,
    G502X_PLUS_PID: G502XPlus,
    G502X_PLUS_RECEIVER_PID: G502XPlus,
}

# Hint-based entries for shared Lightspeed receiver PIDs.
# Format: (product_id, product_string_hint, device_class).
# The hint is matched as a case-insensitive substring of the HID product string
# reported by the OS for the receiver device.
G502_RECEIVER_HINTS: list[tuple[int, str, type]] = [
    (LIGHTSPEED_RECEIVER_PID_1, "g502", G502Lightspeed),
    (LIGHTSPEED_RECEIVER_PID_2, "g502", G502Lightspeed),
    (LIGHTSPEED_RECEIVER_PID_3, "g502", G502Lightspeed),
]

"""Logitech Powerplay Wireless Charging System device implementation.

Supports:
- Powerplay Wireless Charging System (1st generation)
"""

import logging

from ..core.config import DeviceConfig, LightingSettings
from ..core.device import (
    BaseDevice,
    ConnectionType,
    DeviceCapability,
    DeviceInfo,
    DeviceType,
)
from ..core.hid import HIDDevice

logger = logging.getLogger(__name__)


# Powerplay Product IDs
POWERPLAY_PID = 0xC53A  # Powerplay 1st gen (shared Lightspeed receiver PID)


class Powerplay(BaseDevice):
    """Logitech Powerplay Wireless Charging System (1st gen) device implementation."""

    def __init__(self, hid_device: HIDDevice, config: DeviceConfig | None = None):
        """Initialize Powerplay device."""
        super().__init__(hid_device, config)
        self._capabilities = {
            DeviceCapability.RGB_LIGHTING,
        }

    def _init_device(self) -> None:
        """Initialize device after connection."""
        self._info = self.get_device_info()
        logger.info(f"Initialized {self._info.name}")

    def get_device_info(self) -> DeviceInfo:
        """Get device information."""
        return DeviceInfo(
            name="Powerplay Wireless Charging System",
            model="Powerplay Wireless Charging System",
            vendor_id=self.hid_device.vendor_id,
            product_id=self.hid_device.product_id,
            serial_number=self.hid_device.serial_number,
            firmware_version="Unknown",
            device_type=DeviceType.MOUSEPAD,
            connection_type=ConnectionType.LIGHTSPEED,
            has_battery=False,
            has_rgb=True,
            max_dpi=0,
            dpi_step=0,
            button_count=0,
            has_onboard_profiles=False,
        )

    def _set_lighting_settings(self, settings: LightingSettings) -> bool:
        """Set lighting settings on the Powerplay receiver LED."""
        self.active_profile.lighting_settings = settings
        return True


# Hint-based entries for shared Lightspeed receiver PIDs.
# Format: (product_id, product_string_hint, device_class).
POWERPLAY_RECEIVER_HINTS: list[tuple[int, str, type]] = [
    (POWERPLAY_PID, "powerplay", Powerplay),
]

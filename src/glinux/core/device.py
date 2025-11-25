"""Base device class and device manager for GLinux."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

from .config import (
    AppConfig,
    DeviceConfig,
    DeviceProfile,
    DPISettings,
    LightingSettings,
)
from .hid import HIDConnection, HIDDevice, HIDManager

logger = logging.getLogger(__name__)


class DeviceType(Enum):
    """Type of Logitech device."""

    MOUSE = "mouse"
    KEYBOARD = "keyboard"
    HEADSET = "headset"
    UNKNOWN = "unknown"


class ConnectionType(Enum):
    """Device connection type."""

    WIRED = "wired"
    WIRELESS_RECEIVER = "wireless_receiver"
    BLUETOOTH = "bluetooth"
    LIGHTSPEED = "lightspeed"


@dataclass
class DeviceInfo:
    """Device information."""

    name: str
    model: str
    vendor_id: int
    product_id: int
    serial_number: str
    firmware_version: str
    device_type: DeviceType
    connection_type: ConnectionType
    has_battery: bool
    has_rgb: bool
    max_dpi: int
    dpi_step: int
    button_count: int
    has_onboard_profiles: bool


@dataclass
class BatteryStatus:
    """Battery status information."""

    level: int  # 0-100 percentage
    charging: bool
    voltage: float | None = None  # Optional voltage reading


class DeviceCapability(Enum):
    """Device capabilities."""

    DPI_ADJUSTMENT = "dpi_adjustment"
    RGB_LIGHTING = "rgb_lighting"
    MACROS = "macros"
    ONBOARD_PROFILES = "onboard_profiles"
    BATTERY_STATUS = "battery_status"
    FIRMWARE_UPDATE = "firmware_update"
    REPORT_RATE = "report_rate"


class BaseDevice(ABC):
    """Base class for all Logitech devices."""

    def __init__(self, hid_device: HIDDevice, config: DeviceConfig | None = None):
        """Initialize device."""
        self.hid_device = hid_device
        self._connection: HIDConnection | None = None
        self._config = config or DeviceConfig(
            device_id=hid_device.device_id, device_name=hid_device.product
        )
        self._info: DeviceInfo | None = None
        self._capabilities: set[DeviceCapability] = set()

    @property
    def device_id(self) -> str:
        """Get device ID."""
        return self.hid_device.device_id

    @property
    def name(self) -> str:
        """Get device name."""
        return self._config.device_name

    @property
    def config(self) -> DeviceConfig:
        """Get device configuration."""
        return self._config

    @property
    def info(self) -> DeviceInfo | None:
        """Get device information."""
        return self._info

    @property
    def capabilities(self) -> set[DeviceCapability]:
        """Get device capabilities."""
        return self._capabilities

    @property
    def active_profile(self) -> DeviceProfile:
        """Get active profile."""
        return self._config.profiles[self._config.active_profile]

    def has_capability(self, capability: DeviceCapability) -> bool:
        """Check if device has a capability."""
        return capability in self._capabilities

    def connect(self) -> bool:
        """Connect to the device."""
        try:
            self._connection = HIDConnection(self.hid_device)
            self._connection.open()
            self._init_device()
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {self.name}: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from the device."""
        if self._connection:
            self._connection.close()
            self._connection = None

    @abstractmethod
    def _init_device(self) -> None:
        """Initialize device after connection."""

    @abstractmethod
    def get_device_info(self) -> DeviceInfo:
        """Get device information."""

    def get_battery_status(self) -> BatteryStatus | None:
        """Get battery status (if supported)."""
        if not self.has_capability(DeviceCapability.BATTERY_STATUS):
            return None
        return self._get_battery_status()

    def _get_battery_status(self) -> BatteryStatus | None:
        """Implementation of battery status retrieval."""
        return None

    def get_dpi_settings(self) -> DPISettings:
        """Get current DPI settings."""
        return self.active_profile.dpi_settings

    def set_dpi_settings(self, settings: DPISettings) -> bool:
        """Set DPI settings."""
        if not self.has_capability(DeviceCapability.DPI_ADJUSTMENT):
            return False
        return self._set_dpi_settings(settings)

    def _set_dpi_settings(self, settings: DPISettings) -> bool:  # noqa: ARG002
        """Implementation of DPI settings."""
        return False

    def get_lighting_settings(self) -> LightingSettings:
        """Get current lighting settings."""
        return self.active_profile.lighting_settings

    def set_lighting_settings(self, settings: LightingSettings) -> bool:
        """Set lighting settings."""
        if not self.has_capability(DeviceCapability.RGB_LIGHTING):
            return False
        return self._set_lighting_settings(settings)

    def _set_lighting_settings(self, settings: LightingSettings) -> bool:  # noqa: ARG002
        """Implementation of lighting settings."""
        return False

    def get_firmware_version(self) -> str:
        """Get firmware version."""
        if self._info:
            return self._info.firmware_version
        return "Unknown"

    def apply_profile(self, profile_index: int) -> bool:
        """Apply a profile."""
        if 0 <= profile_index < len(self._config.profiles):
            self._config.active_profile = profile_index
            profile = self.active_profile
            self.set_dpi_settings(profile.dpi_settings)
            self.set_lighting_settings(profile.lighting_settings)
            return True
        return False


class DeviceManager:
    """Manages connected Logitech devices."""

    def __init__(self, app_config: AppConfig):
        """Initialize device manager."""
        self.app_config = app_config
        self._hid_manager = HIDManager()
        self._devices: dict[str, BaseDevice] = {}
        self._device_registry: dict[int, type[BaseDevice]] = {}

    def register_device_class(
        self, product_id: int, device_class: type[BaseDevice]
    ) -> None:
        """Register a device class for a product ID."""
        self._device_registry[product_id] = device_class

    def scan_devices(self) -> list[BaseDevice]:
        """Scan for connected devices."""
        hid_devices = self._hid_manager.find_logitech_devices()
        new_devices = []

        for hid_device in hid_devices:
            device_id = hid_device.device_id
            if device_id in self._devices:
                continue

            # Get or create device config
            device_config = self.app_config.get_device_config(device_id)

            # Find appropriate device class
            device_class = self._device_registry.get(hid_device.product_id)
            if device_class:
                device = device_class(hid_device, device_config)
            else:
                # Skip unknown devices
                continue

            self._devices[device_id] = device
            new_devices.append(device)

        return new_devices

    def get_device(self, device_id: str) -> BaseDevice | None:
        """Get a device by ID."""
        return self._devices.get(device_id)

    def get_all_devices(self) -> list[BaseDevice]:
        """Get all connected devices."""
        return list(self._devices.values())

    def remove_device(self, device_id: str) -> None:
        """Remove a device."""
        if device_id in self._devices:
            device = self._devices[device_id]
            device.disconnect()
            del self._devices[device_id]

    def save_device_configs(self) -> None:
        """Save all device configurations."""
        for device_id, device in self._devices.items():
            self.app_config.set_device_config(device_id, device.config)
        self.app_config.save()

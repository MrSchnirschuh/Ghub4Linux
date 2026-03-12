"""Base device class and device manager for ghub4linux."""

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
from .hid import HIDConnection, HIDDevice, HIDManager, HIDError

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

    @property
    def is_connected(self) -> bool:
        """Return True if the device has an open HID connection."""
        return self._connection is not None

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

    def discover_features(self) -> dict[int, int]:
        """Discover HID++ 2.0 feature indexes by querying the device via IRoot (0x0000).

        Sends a ``getFeature`` request (function 0, index 0x00) for each known
        feature ID and records the returned feature index.  Returns a mapping
        of ``feature_id -> feature_index`` for every feature that the device
        reports as supported (non-zero index).
        """
        from .hid import (
            FEATURE_ADJUSTABLE_DPI,
            FEATURE_BATTERY_STATUS,
            FEATURE_BATTERY_VOLTAGE,
            FEATURE_LED_CONTROL,
            FEATURE_ONBOARD_PROFILES,
            FEATURE_REPORT_RATE,
            FEATURE_RGB_EFFECTS,
            FEATURE_UNIFIED_BATTERY,
        )

        feature_map: dict[int, int] = {}
        if not self._connection:
            return feature_map

        features_to_discover = [
            FEATURE_ADJUSTABLE_DPI,
            FEATURE_BATTERY_STATUS,
            FEATURE_BATTERY_VOLTAGE,
            FEATURE_UNIFIED_BATTERY,
            FEATURE_LED_CONTROL,
            FEATURE_RGB_EFFECTS,
            FEATURE_ONBOARD_PROFILES,
            FEATURE_REPORT_RATE,
        ]

        for feature_id in features_to_discover:
            try:
                params = bytes([(feature_id >> 8) & 0xFF, feature_id & 0xFF])
                response = self._connection.send_feature_request(0x00, 0x00, params)
                # Byte 4 of the response contains the feature index (0 = not supported)
                if response and len(response) >= 5 and response[4] != 0:
                    feature_map[feature_id] = response[4]
            except HIDError as e:
                logger.debug(f"Feature discovery failed for {feature_id:#06x}: {e}")

        return feature_map

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
        # Hint-based registry for PIDs shared across multiple devices (e.g.
        # Lightspeed receivers).  Maps product_id -> [(product_hint, class), …].
        # During scan, the device's product_string is matched against each hint
        # (case-insensitive substring) to pick the correct class.
        self._device_registry_hints: dict[int, list[tuple[str, type[BaseDevice]]]] = {}

    def register_device_class(
        self,
        product_id: int,
        device_class: type[BaseDevice],
        product_hint: str = "",
    ) -> None:
        """Register a device class for a product ID.

        When *product_hint* is provided the class is stored in the
        hint-based registry: during :py:meth:`scan_devices` the hint is
        matched as a case-insensitive substring of the HID product string.
        Multiple classes may share the same *product_id* with different hints
        (useful for shared Lightspeed receiver PIDs).
        """
        if product_hint:
            self._device_registry_hints.setdefault(product_id, []).append(
                (product_hint.lower(), device_class)
            )
        else:
            self._device_registry[product_id] = device_class

    def scan_devices(self) -> list[BaseDevice]:
        """Scan for connected devices and attempt to connect to new ones."""
        hid_devices = self._hid_manager.find_logitech_devices()
        new_devices = []

        for hid_device in hid_devices:
            device_id = hid_device.device_id
            if device_id in self._devices:
                continue

            # Get or create device config
            device_config = self.app_config.get_device_config(device_id)

            # Find appropriate device class – first try exact PID match, then
            # fall back to product_string hints for shared receiver PIDs.
            device_class = self._device_registry.get(hid_device.product_id)

            if device_class is None and hid_device.product_id in self._device_registry_hints:
                product_lower = (hid_device.product or "").lower()
                for hint, cls in self._device_registry_hints[hid_device.product_id]:
                    if hint in product_lower:
                        device_class = cls
                        break

            if device_class is None:
                continue

            device = device_class(hid_device, device_config)
            try:
                device.connect()
            except Exception as e:
                logger.warning(f"Could not connect to {device.name}: {e}")

            self._devices[device_id] = device
            new_devices.append(device)
            logger.info(
                f"Found device: {device.name} (PID: {hid_device.product_id:#06x},"
                f" connected: {device.is_connected})"
            )

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

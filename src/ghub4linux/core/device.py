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
from .hid import HIDConnection, HIDDevice, HIDError, HIDManager

logger = logging.getLogger(__name__)

# Coarse unifiedBattery level enum (1=critical, 2=low, 4=good, 8=full) mapped
# to a representative percentage.
_LEVEL_ENUM_TO_PERCENT: dict[int, int] = {1: 5, 2: 20, 4: 60, 8: 100}

# Lithium-polymer discharge curve: 4200 mV is full, 3500 mV is empty.
_MV_FULL = 4200
_MV_EMPTY = 3500


def _percent_from_millivolts(millivolts: int) -> int:
    """Estimate a charge percentage from a single-cell Li-Po voltage.

    ``0x1001 batteryVoltage`` reports only a voltage, but the GUI wants a
    percentage, so the usual linear approximation between empty and full is
    used and clamped to 0..100.
    """
    span = _MV_FULL - _MV_EMPTY
    percent = round((millivolts - _MV_EMPTY) / span * 100)
    return max(0, min(100, percent))


class DeviceType(Enum):
    """Type of Logitech device."""

    MOUSE = "mouse"
    MOUSEPAD = "mousepad"


class ConnectionType(Enum):
    """Device connection type."""

    WIRED = "wired"
    WIRELESS_RECEIVER = "wireless_receiver"
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
    BATTERY_STATUS = "battery_status"
    FIRMWARE_UPDATE = "firmware_update"
    ONBOARD_PROFILES = "onboard_profiles"
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
        """Discover HID++ 2.0 feature indexes for this device.

        Resolves every entry of
        :data:`~ghub4linux.core.hid.DISCOVERABLE_FEATURES` through IRoot
        (feature 0x0000, function 0) and returns ``feature_id -> feature_index``
        for the features the device actually reports.

        Indexes must never be assumed: on a G502 Lightspeed, AdjustableDPI sits
        at ``0x0c`` and battery data comes from BatteryVoltage at ``0x06``,
        whereas the code used to look for BatteryStatus at ``0x07``.
        """
        from .hid import DISCOVERABLE_FEATURES

        feature_map: dict[int, int] = {}
        if not self._connection:
            return feature_map

        for feature_id in DISCOVERABLE_FEATURES:
            index = self._connection.feature_index(feature_id)
            if index:
                feature_map[feature_id] = index

        logger.debug(f"{self.name}: discovered features {feature_map}")
        return feature_map

    # ── feature helpers ──────────────────────────────────────────────────────
    def _read_feature(self, index: int, function: int = 0x00, params: bytes = b"") -> bytes:
        """Read a feature, returning ``b""`` when the device refuses.

        One retry is attempted: a wireless mouse shares the air and the
        receiver's HID++ queue with its input traffic, so a single lost frame is
        normal and must not be reported as "unsupported" to the user.
        """
        if not self._connection or not index:
            return b""
        for attempt in range(2):
            try:
                response = self._connection.send_feature_request(index, function, params)
            except HIDError as exc:
                logger.debug(
                    f"{self.name}: feature 0x{index:02x} fn 0x{function:02x} failed: {exc}"
                )
                response = b""
            if response:
                return response
            if attempt == 0:
                logger.debug(
                    f"{self.name}: feature 0x{index:02x} fn 0x{function:02x} empty, retrying"
                )
        return b""

    def _battery_from_features(self, features: dict[int, int]) -> BatteryStatus | None:
        """Read the battery using whichever HID++ battery feature exists.

        Logitech ships three variants and a device carries exactly one:

        * ``0x1004`` UnifiedBattery — fn 0 returns the charge percentage,
          fn 1 a coarse level/charging enum.
        * ``0x1000`` BatteryStatus — fn 0 returns ``[discharge_level,
          next_level, status]`` where *status* is an enum (0 = discharging,
          1..4 = charging), **not** a bitmask.
        * ``0x1001`` BatteryVoltage — fn 0 returns ``[voltage_hi, voltage_lo,
          flags]`` as a big-endian millivolt reading plus charging flags.  This
          is the only battery source on G-series wireless mice such as the
          G502 Lightspeed; it reports no percentage, so one is estimated from
          the voltage.
        """
        from .hidpp import (
            FEATURE_BATTERY_STATUS,
            FEATURE_BATTERY_VOLTAGE,
            FEATURE_UNIFIED_BATTERY,
        )

        unified = features.get(FEATURE_UNIFIED_BATTERY)
        if unified:
            frame = self._read_feature(unified)
            if len(frame) >= 6 and frame[4] <= 100:
                return BatteryStatus(level=frame[4], charging=bool(frame[5] & 0x0F))
            level = self._read_feature(unified, 0x01)
            if len(level) >= 6:
                return BatteryStatus(
                    level=_LEVEL_ENUM_TO_PERCENT.get(level[5], 0),
                    charging=bool(level[6] & 0x0F) if len(level) > 6 else False,
                )

        legacy = features.get(FEATURE_BATTERY_STATUS)
        if legacy:
            frame = self._read_feature(legacy)
            if len(frame) >= 7 and frame[4] <= 100:
                # enum: 0 discharging, 1 recharging, 2 almost full, 3 full,
                # 4 slow recharge, 5/6 invalid/thermal error, 7 other
                return BatteryStatus(level=frame[4], charging=1 <= frame[6] <= 4)

        voltage_feature = features.get(FEATURE_BATTERY_VOLTAGE)
        if voltage_feature:
            frame = self._read_feature(voltage_feature)
            if len(frame) >= 7:
                millivolts = (frame[4] << 8) | frame[5]
                flags = frame[6]
                if 2000 <= millivolts <= 5000:
                    external_power = bool(flags & 0x80)
                    charging = external_power and (flags & 0x03) != 0x02
                    return BatteryStatus(
                        level=_percent_from_millivolts(millivolts),
                        charging=charging,
                        voltage=millivolts / 1000.0,
                    )

        logger.debug(f"{self.name}: no usable battery feature in {features}")
        return None

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
        """Scan for connected devices and return every device found.

        A device already known from an earlier scan is returned as well, not
        just the newly added ones: callers repopulate their device list from
        this result, so returning only the delta would empty the list on a
        refresh. Re-scanning is also how removal is noticed — a device that is
        gone from the HID enumeration is dropped from the registry.
        """
        hid_devices = self._hid_manager.find_logitech_devices()
        present_ids = {hid_device.device_id for hid_device in hid_devices}

        # Forget devices that are no longer enumerated, so a reconnect or a
        # different device on the same receiver path is not shadowed by a stale
        # entry.
        for stale_id in [d for d in self._devices if d not in present_ids]:
            logger.info(f"Device gone: {self._devices[stale_id].name} ({stale_id})")
            self._devices.pop(stale_id, None)

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
            device.connect()

            self._devices[device_id] = device
            logger.info(
                f"Found device: {device.name} (PID: {hid_device.product_id:#06x},"
                f" connected: {device.is_connected})"
            )

        # Report in enumeration order so the sidebar is stable between scans.
        return [
            self._devices[hid_device.device_id]
            for hid_device in hid_devices
            if hid_device.device_id in self._devices
        ]

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

    def add_device(self, device: BaseDevice) -> None:
        """Add a device directly (used for demo/testing)."""
        self._devices[device.device_id] = device

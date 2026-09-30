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

# Lithium-polymer discharge curve used to *estimate* a percentage from the
# voltage-only 0x1001 feature.  The kernel's 100-point table
# (hidpp20_map_battery_capacity) is used because a straight 4200..3500 ramp is
# materially wrong: for the 4044 mV a G502 Lightspeed reports, the linear
# approximation says 78% while the real curve (and Solaar's 13-point table,
# which agrees with it) says 87%.  Logitech's own per-device table is not
# public, so this is the best available public approximation and is always
# labelled as an estimate.
_VOLTAGE_CURVE: tuple[tuple[int, int], ...] = (
    (4186, 100),
    (4067, 90),
    (3989, 80),
    (3922, 70),
    (3859, 60),
    (3811, 50),
    (3778, 40),
    (3751, 30),
    (3717, 20),
    (3671, 10),
    (3646, 5),
    (3579, 2),
    (3500, 0),
)


# Coarse battery level enum reported by the 0x1004 unifiedBattery feature
# (get_battery_info, byte 1).  These are *level* codes, not a percentage.
_UNIFIED_LEVEL_NAMES: dict[int, str] = {1: "critical", 2: "low", 4: "good", 8: "full"}

# Charging status enum reported by 0x1004 get_battery_info (byte 2) and by the
# 0x1000 batteryStatus feature (byte 2).  Verified against Solaar's
# BatteryStatus flag definitions and OpenLogi's spec for x1004.
_CHARGE_STATUS_NAMES: dict[int, str] = {
    0: "discharging",
    1: "charging",
    2: "charging slowly",
    3: "full",
    4: "error",
}

# The G-series voltage-only devices expose no charge percentage at all, and the
# voltage alone cannot distinguish "on the PowerPlay pad" from "in a drawer".
# The honest label is therefore unknown rather than a guessed number.
CHARGING_UNKNOWN = None


def _charge_state_from_status(status: int) -> bool | None:
    """Map a 0x1004/0x1000 status byte to charging / not charging / unknown."""
    if status in (1, 2):  # charging, charging slowly
        return True
    if status in (0, 3):  # discharging, full
        return False
    # 4 = the battery subsystem reported an error; anything else is a code this
    # build does not know.  Neither justifies an invented yes/no.
    return CHARGING_UNKNOWN


def _percent_from_millivolts(millivolts: int) -> int:
    """Estimate a charge percentage from a single-cell Li-Po voltage.

    ``0x1001 batteryVoltage`` reports only a voltage, so any percentage derived
    from it is an estimate and must be presented as one.  The curve is
    interpolated between the public reference points rather than assumed linear.

    Outside the curve's range the result is clamped, and a value far below the
    range is reported as 0 rather than extrapolated into a negative charge.
    """
    points = _VOLTAGE_CURVE
    if millivolts >= points[0][0]:
        return 100
    if millivolts <= points[-1][0]:
        return 0
    for (high_mv, high_pct), (low_mv, low_pct) in zip(points, points[1:], strict=True):
        if low_mv <= millivolts <= high_mv:
            span = high_mv - low_mv
            ratio = (millivolts - low_mv) / span
            return round(low_pct + ratio * (high_pct - low_pct))
    return 0


def _voltage_charge_state(flags: int) -> bool | None:
    """Decode the 0x1001 charging-flags byte, per the kernel and LKML spec.

    ``Table 1`` of the LKML patch "HID: logitech-hidpp: only read chargeStatus
    if extPower is active":

    * bit 7 — external power active.  **Bit 7 gates every other bit**: the
      charge status is only valid while it is set.
    * bits 0-2 — charge status, read only when bit 7 is set: 0 charging,
      1 end of charge, 2 charge stopped, 7 hardware error.
    * bit 3 — fast charge, bit 4 — slow charge.
    * bit 5 — charge level critical.

    The G502 Lightspeed reports ``0x00`` here, which the wire format reads as
    "no external power, therefore discharging" — while the mouse sits on a
    PowerPlay pad with its charging LED lit.  Logitech's documented PowerPlay
    behaviour explains the contradiction rather than resolving it: on the pad
    the battery is deliberately held between 85% and 95%, so the pad
    legitimately stops and resumes charging and the firmware does not always
    surface the pad as external power.

    Since this value cannot be reconciled with the observable hardware, it is
    reported as unknown rather than as a discharge claim the device contradicts.
    """
    if not flags & 0x80:
        # No external power reported.  Treat as discharging only when the byte
        # carries no other claim; all-zero is the ambiguous case above.
        return False if flags else CHARGING_UNKNOWN

    status_bits = flags & 0x07
    if status_bits == 0x00 or flags & 0x08 or flags & 0x10:
        return True  # charging, or a fast/slow charge rate reported
    if status_bits in (0x01, 0x02):
        return False  # end of charge, or charging stopped
    if status_bits == 0x03:
        return True  # charge restarting
    # 7 = hardware error and 4..6 are reserved: neither justifies a yes/no.
    return CHARGING_UNKNOWN


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
    has_led_control: bool


@dataclass
class BatteryStatus:
    """Battery status information.

    ``level`` is ``None`` when the device does not report a percentage — the
    G-series voltage-only devices never do.  Consumers must render an unknown
    level as unknown; inventing one is what made the previous build claim a
    percentage the hardware never sent.

    ``charging`` is ``None`` when the device's own status byte cannot say.  The
    G502 reports a flags byte of ``0x00`` even while charging on a PowerPlay
    pad, so "not charging" there would be a claim the hardware contradicts.

    ``estimated`` marks a level that was derived (for example from a voltage
    curve) rather than reported, so a UI can label it honestly.
    """

    level: int | None  # 0-100 percentage, or None when unreported
    charging: bool | None
    voltage: float | None = None  # Optional voltage reading
    status_text: str | None = None  # device-reported state, e.g. "discharging"
    estimated: bool = False  # True when level was derived, not reported

    def describe(self) -> str:
        """Human-readable one-liner that never states more than was measured.

        Used by the CLI, the sidebar and the settings panel so all three agree.
        """
        parts: list[str] = []
        if self.level is None:
            parts.append("level unknown")
        else:
            estimate = "~" if self.estimated else ""
            parts.append(f"{estimate}{self.level}%")

        if self.charging is True:
            parts.append("charging")
        elif self.charging is False:
            # "not charging" is only worth saying when the device really said
            # so; when it is unknown the level line already carries that.
            parts.append("not charging")
        if self.status_text and self.status_text not in ("voltage only",):
            parts.append(self.status_text)
        if self.voltage is not None:
            parts.append(f"{self.voltage:.3f} V")
        return ", ".join(parts)


class DeviceCapability(Enum):
    """Device capabilities."""

    DPI_ADJUSTMENT = "dpi_adjustment"
    RGB_LIGHTING = "rgb_lighting"
    MACROS = "macros"
    BATTERY_STATUS = "battery_status"
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

        * ``0x1004`` UnifiedBattery — **fn 0 returns capabilities, fn 1 the
          actual charge**.  Reading fn 0 and treating its capability bits as a
          charge is what made a PRO X 2 DEX report "15%, charging" while the
          device was at 82% and discharging: ``0f 0f 02`` is a level bitmask of
          0x0f plus "percentage supported", not a measurement.
        * ``0x1000`` BatteryStatus — fn 0 returns ``[discharge_level,
          next_level, status]`` where *status* is an enum (0 = discharging,
          1..4 = charging), **not** a bitmask.
        * ``0x1001`` BatteryVoltage — fn 0 returns ``[voltage_hi, voltage_lo,
          flags]`` as a big-endian millivolt reading plus charging flags.  This
          is the only battery source on G-series wireless mice such as the
          G502 Lightspeed; it reports no percentage, so one is estimated from
          the voltage and flagged as an estimate.
        """
        from .hidpp import (
            FEATURE_BATTERY_STATUS,
            FEATURE_BATTERY_VOLTAGE,
            FEATURE_UNIFIED_BATTERY,
        )

        unified = features.get(FEATURE_UNIFIED_BATTERY)
        if unified:
            # fn 1 is get_battery_info: [percentage, level, status, ...].
            # fn 0 is get_battery_capabilities and carries no measurement.
            frame = self._read_feature(unified, 0x01)
            if len(frame) >= 7:
                percentage, status = frame[4], frame[6]
                return BatteryStatus(
                    level=percentage if percentage <= 100 else None,
                    charging=_charge_state_from_status(status),
                    status_text=_CHARGE_STATUS_NAMES.get(status),
                )
            # Some firmware answers fn 1 with a coarse level only.
            if len(frame) >= 6 and frame[4] in _UNIFIED_LEVEL_NAMES:
                return BatteryStatus(
                    level=None,
                    charging=None,
                    status_text=_UNIFIED_LEVEL_NAMES[frame[4]],
                )

        legacy = features.get(FEATURE_BATTERY_STATUS)
        if legacy:
            frame = self._read_feature(legacy)
            if len(frame) >= 7 and frame[4] <= 100:
                # enum: 0 discharging, 1 recharging, 2 almost full, 3 full,
                # 4 slow recharge, 5/6 invalid/thermal error, 7 other
                status = frame[6]
                return BatteryStatus(
                    level=frame[4],
                    charging=_charge_state_from_status(status),
                    status_text=_CHARGE_STATUS_NAMES.get(status),
                )

        voltage_feature = features.get(FEATURE_BATTERY_VOLTAGE)
        if voltage_feature:
            frame = self._read_feature(voltage_feature)
            if len(frame) >= 7:
                millivolts = (frame[4] << 8) | frame[5]
                flags = frame[6]
                if 2000 <= millivolts <= 5000:
                    return BatteryStatus(
                        level=_percent_from_millivolts(millivolts),
                        charging=_voltage_charge_state(flags),
                        voltage=millivolts / 1000.0,
                        status_text="voltage only",
                        estimated=True,
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

    def lighting_effect_ids(self) -> dict[str, int]:
        """Effect name -> ID, empty for devices that cannot enumerate them."""
        return {}

    def _set_lighting_settings(self, settings: LightingSettings) -> bool:  # noqa: ARG002
        """Implementation of lighting settings."""
        return False

    def get_firmware_version(self) -> str:
        """Get firmware version."""
        if self._info:
            return self._info.firmware_version
        return "Unknown"

    # ── report rate ──────────────────────────────────────────────────────────
    def get_report_rate_list(self) -> list[int]:
        """Return the supported report intervals in milliseconds.

        The wire protocol expresses report rate as a *millisecond interval*, not
        as hertz: 1 ms is 1000 Hz, 8 ms is 125 Hz.  Devices with no report-rate
        feature offer none.
        """
        return []

    def get_report_rate(self) -> int | None:
        """Return the active report interval in milliseconds."""
        return None

    def set_report_rate(self, rate: int) -> bool:  # noqa: ARG002
        """Set the report interval; returns False when the device has none.

        Implementations accept either milliseconds or a hertz value.
        """
        return False

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

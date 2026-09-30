"""Logitech G502 device implementations.

Supports:
- G502 Lightspeed (wireless)
- G502X Plus (wireless with RGB)
"""

import logging

from ..core.config import (
    DeviceConfig,
    DPILevel,
    DPISettings,
    LightingEffect,
    LightingSettings,
    RGBColor,
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
    LIGHTSPEED_RECEIVER_PID_1,
    LIGHTSPEED_RECEIVER_PID_2,
    LIGHTSPEED_RECEIVER_PID_3,
    HIDDevice,
)
from ..core.hidpp import FEATURE_REPORT_RATE
from ..core.rgb import ColorLedEffects

logger = logging.getLogger(__name__)


def _bcd(value: int) -> int:
    """Decode a packed-BCD byte (0x12 -> 12), used by DeviceInfo versions."""
    return (value >> 4) * 10 + (value & 0x0F)


# G502 Product IDs
G502_HERO_PID = 0xC092  # G502 Hero wired
G502_LIGHTSPEED_PID = 0x407F  # G502 Lightspeed wireless
G502_LIGHTSPEED_WIRED_PID = 0x407E  # G502 Lightspeed wired mode
G502X_PLUS_PID = 0x4099  # G502X Plus
G502X_PLUS_RECEIVER_PID = 0x409A  # G502X Plus receiver
G502X_PLUS_WIRED_PID = 0x409B  # G502X Plus wired mode


class G502Device(BaseDevice):
    """Base class for G502 series devices."""

    # Device specifications
    MAX_DPI = 25600
    DPI_MIN = 100
    DPI_STEP = 50
    BUTTON_COUNT = 11
    DEFAULT_DPI_LEVELS = [400, 800, 1600, 3200, 6400]

    # Per-model metadata; subclasses override only what differs.
    _DEVICE_NAME = "G502"
    _MODEL_NAME = "G502"

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
        self._dpi_feature_index: int | None = None
        self._battery_feature_index: int | None = None
        # colorLedEffects (0x8070) reader, set up in _query_features.
        self._rgb: ColorLedEffects | None = None
        self._features: dict[int, int] = {}

    def _init_device(self) -> None:
        """Initialize device after connection."""
        self._query_features()
        self._apply_capabilities()
        self._info = self.get_device_info()
        self._sync_dpi_levels()
        logger.info(
            f"Initialized {self._info.name} "
            f"(features: {', '.join(f'0x{k:04x}' for k in sorted(self._features)) or 'none'})"
        )

    def _sync_dpi_levels(self) -> None:
        """Seed the profile's DPI levels from what the sensor actually runs.

        The profile starts with the class defaults (400…6400), which have
        nothing to do with the real device: a mouse left at 1450 DPI (set with
        the hardware button) would be shown as "800 DPI active".  The current
        sensor resolution is read back and the active level is set to the
        matching entry, so the GUI and the CLI agree with the hardware.

        A value that matches no preset is reported by occupying a single extra
        slot, which is reused on the next change instead of appending a new
        entry every time — otherwise the list would grow on every scan.
        """
        if not self.has_capability(DeviceCapability.DPI_ADJUSTMENT):
            return
        current = self.get_sensor_dpi(0)
        if not current:
            return

        settings = self.active_profile.dpi_settings
        levels = list(settings.levels)
        for index, level in enumerate(levels):
            if level.dpi == current:
                settings.active_level = index
                return

        presets = self.DEFAULT_DPI_LEVELS
        extra = [i for i, level in enumerate(levels) if level.dpi not in presets]
        if len(levels) > len(presets) and extra:
            slot = extra[-1]
            levels[slot] = DPILevel(dpi=current, color=levels[slot].color)
        else:
            slot = len(levels)
            levels.append(DPILevel(dpi=current, color=RGBColor(255, 0, 255)))
        settings.levels = levels
        settings.active_level = slot

    def _apply_capabilities(self) -> None:
        """Declare only the capabilities the device actually reported.

        Claiming a capability the hardware lacks makes the GUI render controls
        that write to unrelated features, so every entry is conditional.
        """
        from ..core.hidpp import (
            FEATURE_ADJUSTABLE_DPI,
            FEATURE_BATTERY_STATUS,
            FEATURE_BATTERY_VOLTAGE,
            FEATURE_ONBOARD_PROFILES,
            FEATURE_REPORT_RATE,
            FEATURE_RGB_EFFECTS,
            FEATURE_UNIFIED_BATTERY,
        )

        caps: set[DeviceCapability] = {DeviceCapability.MACROS}
        if FEATURE_ADJUSTABLE_DPI in self._features:
            caps.add(DeviceCapability.DPI_ADJUSTMENT)
        if any(
            f in self._features
            for f in (FEATURE_UNIFIED_BATTERY, FEATURE_BATTERY_STATUS, FEATURE_BATTERY_VOLTAGE)
        ):
            caps.add(DeviceCapability.BATTERY_STATUS)
        if FEATURE_ONBOARD_PROFILES in self._features:
            caps.add(DeviceCapability.ONBOARD_PROFILES)
        if FEATURE_REPORT_RATE in self._features:
            caps.add(DeviceCapability.REPORT_RATE)
        if 0x8070 in self._features or FEATURE_RGB_EFFECTS in self._features:
            caps.add(DeviceCapability.RGB_LIGHTING)
        self._capabilities = caps

    def _query_features(self) -> None:
        """Query HID++ feature indexes via IRoot (0x0000) feature discovery.

        Indexes are only taken from the device's own answer.  Hardcoded
        fallbacks are deliberately absent: the previous defaults (DPI 0x06,
        battery 0x07, RGB 0x08) address unrelated features on a real G502 and
        made writes silently corrupt unrelated settings.
        """
        from ..core.hidpp import (
            FEATURE_ADJUSTABLE_DPI,
        )
        from ..core.rgb import ColorLedEffects

        self._features = self.discover_features()
        self._dpi_feature_index = self._features.get(FEATURE_ADJUSTABLE_DPI)
        # Battery comes from whichever variant the device carries; the actual
        # read happens in BaseDevice._battery_from_features.
        self._battery_feature_index = (
            self._features.get(0x1004) or self._features.get(0x1000) or self._features.get(0x1001)
        )
        # The G502 Lightspeed drives its lighting through colorLedEffects
        # (0x8070) — *not* the newer rgbEffects (0x8071), which it does not have.
        # Keying on 0x8071 is why the app previously showed no lighting settings
        # for this mouse at all, despite the hardware reporting two zones and
        # three effects for it.
        index = self._features.get(0x8070) or self._features.get(0x8071)
        if index and self._connection:
            self._rgb = ColorLedEffects(self._connection, index)
            self._rgb.refresh()
        else:
            self._rgb = None

    def get_device_info(self) -> DeviceInfo:
        """Get device information."""
        return self._make_device_info(
            name=self._DEVICE_NAME,
            model=self._MODEL_NAME,
            has_rgb=True,
        )

    def _make_device_info(
        self,
        name: str,
        model: str,
        has_rgb: bool = True,
        has_battery: bool = True,
        max_dpi: int | None = None,
        dpi_step: int | None = None,
        button_count: int | None = None,
        has_onboard_profiles: bool = True,
    ) -> DeviceInfo:
        """Build a DeviceInfo with common fields filled from the device."""
        return DeviceInfo(
            name=name,
            model=model,
            vendor_id=self.hid_device.vendor_id,
            product_id=self.hid_device.product_id,
            serial_number=self.hid_device.serial_number,
            firmware_version=self._get_firmware_version(),
            device_type=DeviceType.MOUSE,
            connection_type=self._get_connection_type(),
            has_battery=has_battery,
            has_rgb=has_rgb,
            max_dpi=max_dpi or self.MAX_DPI,
            dpi_step=dpi_step or self.DPI_STEP,
            button_count=button_count or self.BUTTON_COUNT,
            has_onboard_profiles=has_onboard_profiles,
        )

    def _get_firmware_version(self) -> str:
        """Get the main firmware version from DeviceInfo (0x0003).

        ``getFwInfo`` (fn 1) returns, in the 4 response bytes after the 3
        payload bytes: entity type, a 3-char firmware prefix, a packed-BCD
        firmware number, a packed-BCD revision and a packed-BCD build.
        """
        if not self._connection or not self._features:
            return "Unknown"

        info_index = self._features.get(0x0003)
        if not info_index:
            return "Unknown"

        frame = self._read_feature(info_index, 0x00)
        if len(frame) < 5:
            return "Unknown"
        entity_count = min(frame[4], 8)

        for entity in range(entity_count):
            detail = self._read_feature(info_index, 0x01, bytes([entity]))
            if len(detail) < 11:
                continue
            entity_type = detail[4]
            # Only the main application firmware is meaningful to a user;
            # bootloader and hardware entities report a different numbering.
            if entity_type != 0:
                continue
            number = _bcd(detail[8])
            revision = _bcd(detail[9])
            build = _bcd(detail[10]) * 100 + _bcd(detail[11]) if len(detail) > 11 else 0
            version = f"{number}.{revision:02d}"
            if build:
                version += f" (build {build})"
            return version
        return "Unknown"

    def _get_connection_type(self) -> ConnectionType:
        """Determine connection type."""
        # G502 Lightspeed can be wired or wireless
        if self.hid_device.product_id in (G502_LIGHTSPEED_WIRED_PID, G502X_PLUS_WIRED_PID):
            return ConnectionType.WIRED
        return ConnectionType.LIGHTSPEED

    def _get_battery_status(self) -> BatteryStatus | None:
        """Get battery status from device."""
        return self._battery_from_features(self._features)

    def _set_dpi_settings(self, settings: DPISettings) -> bool:
        """Set DPI settings on the device.

        Per HID++ 2.0 ``adjustableDpi`` (0x2201) the per-sensor call is

        * function 2 ``getSensorDpi(sensor)``
        * function 3 ``setSensorDpi(sensor, dpi)`` with the value as a
          **big-endian** ``u16``.

        Logitech stores *one* active sensor resolution, not a table of DPI
        levels, so the active level of the profile is what gets written.
        """
        if not self._connection or self._dpi_feature_index is None:
            # Nothing to talk to — keep the change in the local profile only.
            self.active_profile.dpi_settings = settings
            return False

        if not settings.levels:
            return False
        index = max(0, min(settings.active_level, len(settings.levels) - 1))
        dpi = max(self.DPI_MIN, min(settings.levels[index].dpi, self.MAX_DPI))

        frame = self._read_feature(
            self._dpi_feature_index, 0x03, bytes([0x00, (dpi >> 8) & 0xFF, dpi & 0xFF])
        )
        if not frame:
            logger.error(f"{self.name}: device rejected DPI {dpi}")
            return False

        self.active_profile.dpi_settings = settings
        logger.info(f"{self.name}: DPI set to {dpi} (level {index + 1})")
        return True

    def get_sensor_dpi(self, sensor: int = 0) -> int | None:
        """Read the sensor's current resolution in DPI."""
        if not self._dpi_feature_index:
            return None
        frame = self._read_feature(self._dpi_feature_index, 0x02, bytes([sensor, 0x00, 0x00]))
        if len(frame) < 7:
            return None
        return (frame[5] << 8) | frame[6]

    def get_supported_dpi(self, sensor: int = 0) -> list[int]:
        """Return the DPI values the sensor accepts.

        The device describes them as explicit values plus range markers; a
        marker's low 13 bits are the step size and it follows the range start,
        with the next explicit value acting as the range end.
        """
        if not self._dpi_feature_index:
            return []
        frame = self._read_feature(self._dpi_feature_index, 0x01, bytes([sensor, 0x00, 0x00]))
        if len(frame) < 5:
            return []

        # 0x2201 payload[0] echoes the sensor index, then u16 BE entries; a
        # range marker (value >> 13 == 0b111) carries the step in its low bits
        # and is followed by the range end value.
        values: list[int] = []
        pending_step: int | None = None
        payload = bytes(frame[4:])
        for offset in range(1, len(payload) - 1, 2):
            raw = (payload[offset] << 8) | payload[offset + 1]
            if raw == 0:
                break
            if raw >> 13 == 0b111:
                pending_step = raw & 0x1FFF
                continue
            if pending_step and values:
                start = values[-1]
                if pending_step > 0 and raw > start:
                    values.extend(range(start + pending_step, raw + 1, pending_step))
                else:
                    values.append(raw)
                pending_step = None
            else:
                values.append(raw)
        return sorted(set(values))

    # ── lighting (colorLedEffects 0x8070) ────────────────────────────────────
    #
    # The G502 Lightspeed exposes 0x8070 with **two** zones (the logo and a
    # second one) and three effects each. The previous implementation sent
    # invented effect codes through function 0 and 1 of a feature it never
    # actually resolved on this model — the write was acknowledged and changed
    # nothing.

    def supported_lighting_effects(self) -> list[str]:
        """Effect names this mouse actually offers, read from its own engine."""
        if not self._rgb:
            return []
        return [name for name in self._rgb.supported_effect_names() if name != "off"]

    def lighting_zones(self) -> list[str]:
        """Human-readable names of this mouse's LED zones."""
        if not self._rgb:
            return []
        return [zone.location_name for zone in self._rgb.zones]

    def get_lighting_settings(self) -> LightingSettings:
        """Read the current colour back from the device."""
        settings = super().get_lighting_settings()
        if self._rgb:
            color = self._rgb.get_current_color(0)
            if color is not None:
                settings.effect.color.red = color[0]
                settings.effect.color.green = color[1]
                settings.effect.color.blue = color[2]
                settings.enabled = any(color)
        return settings

    def _set_lighting_settings(self, settings: LightingSettings) -> bool:
        """Apply lighting settings to the mouse."""
        if not self._rgb:
            return False

        effect = settings.effect
        color = (effect.color.red, effect.color.green, effect.color.blue)

        # Apply to every zone the device reported: writing only to zone 0 would
        # change one LED and leave the others as they were.
        zone_indexes = [zone.index for zone in self._rgb.zones] or [0]
        results = []
        for zone_index in zone_indexes:
            if not settings.enabled:
                results.append(self._rgb.set_off(zone_index))
            else:
                results.append(
                    self._rgb.set_effect_by_name(
                        zone_index, effect.effect_type, color, duration_ms=effect.speed
                    )
                )

        if not any(results):
            logger.warning(f"{self.name}: lighting change not applied by the device")
            return False
        self.active_profile.lighting_settings = settings
        return True

    # ── report rate (adjustableReportRate 0x8060) ────────────────────────────
    #
    # Wire format, verified against the hardware and the specification:
    #   fn 0 get_report_rate_list ()            -> bitfield, bit N = (N+1) ms
    #   fn 1 get_report_rate     ()             -> [interval_ms]
    #   fn 2 set_report_rate     (interval_ms)  -> ()
    #
    # The unit is milliseconds, not hertz: the G502 reports 0x8b for its list and
    # 0x01 as the active interval, i.e. 1 ms = 1000 Hz.  The previous code mapped
    # invented hertz codes through the wrong function on a hardcoded feature
    # index, which silently wrote to whatever feature happened to live there.

    def get_report_rate_list(self) -> list[int]:
        """Return the supported report intervals in milliseconds."""
        index = self._features.get(FEATURE_REPORT_RATE)
        if not index:
            return []
        frame = self._read_feature(index, 0x00)
        if len(frame) < 5:
            return []
        bitfield = frame[4]
        return [
            milliseconds for milliseconds in range(1, 9) if bitfield & (1 << (milliseconds - 1))
        ]

    def get_report_rate(self) -> int | None:
        """Return the active report interval in milliseconds."""
        index = self._features.get(FEATURE_REPORT_RATE)
        if not index:
            return None
        frame = self._read_feature(index, 0x01)
        if len(frame) < 5 or not frame[4]:
            return None
        return frame[4]

    def set_report_rate(self, rate: int) -> bool:
        """Set the report interval in milliseconds.

        Accepts milliseconds (1-8) as the protocol defines them.  Hertz values
        such as 1000 are accepted too, because that is how users and mice are
        usually described, and converted.
        """
        index = self._features.get(FEATURE_REPORT_RATE)
        if not index or not self._connection:
            return False

        milliseconds = self._to_milliseconds(rate)
        if milliseconds is None:
            return False
        supported = self.get_report_rate_list()
        if supported and milliseconds not in supported:
            logger.warning(
                f"{self.name}: {milliseconds} ms is not supported (device offers {supported})"
            )
            return False

        frame = self._read_feature(index, 0x02, bytes([milliseconds]))
        if not frame:
            return False
        # Read back rather than assume the device accepted the value.
        applied = self.get_report_rate() == milliseconds
        if not applied:
            logger.warning(f"{self.name}: report rate {milliseconds} ms not applied")
        return applied

    @staticmethod
    def _to_milliseconds(rate: int) -> int | None:
        """Normalise a rate given either in milliseconds or in hertz."""
        if rate in (1, 2, 3, 4, 5, 6, 7, 8):
            return rate
        if rate in (125, 250, 500, 1000):
            # 1000 Hz = 1 ms, 500 Hz = 2 ms, 250 Hz = 4 ms, 125 Hz = 8 ms.
            return 1000 // rate
        return None


class G502Lightspeed(G502Device):
    """G502 Lightspeed specific implementation."""

    _DEVICE_NAME = "G502 Lightspeed"
    _MODEL_NAME = "G502 Lightspeed"


class G502Hero(G502Device):
    """G502 Hero specific implementation (wired)."""

    _DEVICE_NAME = "G502 Hero"
    _MODEL_NAME = "G502 Hero"


class G502XPlus(G502Device):
    """G502X Plus specific implementation."""

    _DEVICE_NAME = "G502 X Plus"
    _MODEL_NAME = "G502X Plus"
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

    def set_zone_lighting(self, zone: str, effect: LightingEffect) -> bool:
        """Set lighting for a specific RGB zone."""
        if zone not in self._rgb_zones:
            return False

        settings = self.active_profile.lighting_settings
        settings.zones[zone] = effect
        return self._set_lighting_settings(settings)


# Device registry mapping
G502_DEVICES: dict[int, type[BaseDevice]] = {
    G502_HERO_PID: G502Hero,
    G502_LIGHTSPEED_PID: G502Lightspeed,
    G502_LIGHTSPEED_WIRED_PID: G502Lightspeed,
    G502X_PLUS_PID: G502XPlus,
    G502X_PLUS_RECEIVER_PID: G502XPlus,
    G502X_PLUS_WIRED_PID: G502XPlus,
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

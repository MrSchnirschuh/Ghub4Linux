"""Logitech POWERPLAY wireless charging system implementation.

The POWERPLAY base does not enumerate under a name of its own. Its USB-level
device (``046d:c53a``) calls itself "USB Receiver" — the same string every
Lightspeed dongle uses — and its HID++ interface reports product ``0x405F``
with the device name *"Candy companion chip"*, which is why the pad stayed
invisible in the device list. Solaar hits the same wall and mislabels it as a
touchpad (pwr-Solaar/Solaar#2222); Logitech's own documentation for that PID
notes it is "Part of the G PowerPlay Wireless Mouse Pad".

The pad is identified by its own PID on its own HID++ interface, **not** through
the receiver PID ``0xC53A``: that receiver enumerates the mouse sitting on the
pad, and registering the pad against it would hand the mouse's features to the
pad's driver.
"""

import logging

from ..core.config import (
    DeviceConfig,
    LightingEffect,
    LightingSettings,
)
from ..core.device import (
    BaseDevice,
    ConnectionType,
    DeviceCapability,
    DeviceInfo,
    DeviceType,
)
from ..core.hid import HIDDevice

logger = logging.getLogger(__name__)

# The POWERPLAY base ("Candy companion chip", model ID 405F00000000).
POWERPLAY_PID = 0x405F
# POWERPLAY 2 (2025) is expected to carry a new PID; it is listed so the driver
# is picked up if the pad reports it.
POWERPLAY_2_PID = 0x40C6

# colorLedEffects (0x8070) — the pad's RGB engine. The newer rgbEffects
# (0x8071) is absent here, so the two must not be conflated.
FEATURE_COLOR_LED_EFFECTS = 0x8070

# EffectId values of the colorLedEffects engine.
EFFECT_DISABLED = 0x00
EFFECT_FIXED_COLOR = 0x01
EFFECT_PULSING_BREATHING = 0x02
EFFECT_CYCLING = 0x03
EFFECT_COLOR_WAVE = 0x04

_EFFECT_BY_NAME = {
    "off": EFFECT_DISABLED,
    "static": EFFECT_FIXED_COLOR,
    "breathing": EFFECT_PULSING_BREATHING,
    "cycle": EFFECT_CYCLING,
    "wave": EFFECT_COLOR_WAVE,
}


class Powerplay(BaseDevice):
    """Logitech POWERPLAY wireless charging system (mouse pad)."""

    def __init__(self, hid_device: HIDDevice, config: DeviceConfig | None = None):
        """Initialize the POWERPLAY device."""
        super().__init__(hid_device, config)
        self._features: dict[int, int] = {}
        self._effects_index = 0
        self._zone_count = 0

    def _init_device(self) -> None:
        """Initialize the device after connecting."""
        self._features = self.discover_features()
        # 0x8070 is not part of DISCOVERABLE_FEATURES, so resolve it directly.
        self._effects_index = (
            self._connection.feature_index(FEATURE_COLOR_LED_EFFECTS) if self._connection else 0
        )
        self._capabilities = {DeviceCapability.RGB_LIGHTING} if self._effects_index else set()
        if self._effects_index:
            self._zone_count = self._read_zone_count()
        self._info = self.get_device_info()
        # The hardware calls this controller "Candy companion chip", which tells
        # a user nothing. Show the product name instead; the raw string stays
        # available through hidpp_device_name().
        self._config.device_name = self._info.name
        logger.info(
            f"Initialized {self._info.name} (zones: {self._zone_count}, "
            f"features: {', '.join(f'0x{k:04x}' for k in sorted(self._features)) or 'none'})"
        )

    def get_device_info(self) -> DeviceInfo:
        """Get device information.

        The pad has no battery of its own — it charges the mouse, not itself —
        and no DPI sensor, so those capabilities stay empty.
        """
        return DeviceInfo(
            name="POWERPLAY Wireless Charging System",
            model="POWERPLAY",
            vendor_id=self.hid_device.vendor_id,
            product_id=self.hid_device.product_id,
            serial_number=self.hid_device.serial_number,
            firmware_version=self._get_firmware_version(),
            device_type=DeviceType.MOUSEPAD,
            connection_type=ConnectionType.WIRED,
            has_battery=False,
            has_rgb=bool(self._effects_index),
            max_dpi=0,
            dpi_step=0,
            button_count=0,
            has_onboard_profiles=False,
        )

    # ── lighting (colorLedEffects 0x8070) ────────────────────────────────────
    #
    # Wire format, verified against the hardware:
    #   fn  0 get_info             ()                              -> [zones, nv[2], ext[2]]
    #   fn  1 get_zone_info        (zone)                          -> [zone, location, effects, persistency]
    #   fn  2 get_zone_effect_info (zone, effect)                  -> [zone, effect, id[2], caps[2], period[2]]
    #   fn  3 set_zone_effect      (zone, effect, params[10], persistency)
    #   fn  8 set_sw_control       (control, events)               -> ()
    #   fn 12 get_current_color    (zone)                          -> [zone, r, g, b]
    #
    # `set_zone_effect` takes the zone and the zone-local effect index followed
    # by the colour, so the request is ``zone, effect_index, r, g, b, …``.
    # Software control must be claimed first, otherwise the firmware owns the
    # LED and silently discards the request. The colour is read back afterwards
    # and the write only reported as successful if it actually landed.

    def _read_zone_count(self) -> int:
        """Return the number of LED zones (0 when unreadable)."""
        frame = self._read_feature(self._effects_index, 0x00)
        return frame[4] if len(frame) > 4 else 0

    def _zone_effect_index(self, zone: int, effect_id: int) -> int | None:
        """Resolve *effect_id* to its zone-local index.

        Effect indexes are per zone and not fixed across devices: the index of
        a given effect has to be looked up, never assumed.  ``get_zone_effect_info``
        answers with ``[zone, effect_index, effect_id_hi, effect_id_lo, …]``, so
        the ID is a big-endian u16 — comparing the high byte alone would never
        match (FixedColor is ``0x0001``, whose high byte is 0).
        """
        limit = 16
        for effect_index in range(limit):
            frame = self._read_feature(self._effects_index, 0x02, bytes([zone, effect_index]))
            if len(frame) < 8:
                break
            if (frame[6] << 8) | frame[7] == effect_id:
                return effect_index
        return None

    def get_lighting_settings(self) -> LightingSettings:
        """Read the pad's current colour from the device itself."""
        settings = super().get_lighting_settings()
        if not self._effects_index or not self._zone_count:
            return settings

        frame = self._read_feature(self._effects_index, 0x0C, bytes([0x00]))
        if len(frame) >= 8:
            settings.effect.color.red = frame[5]
            settings.effect.color.green = frame[6]
            settings.effect.color.blue = frame[7]
            settings.effect.effect_type = "static"
            settings.enabled = any(frame[5:8])
        return settings

    def _set_lighting_settings(self, settings: LightingSettings) -> bool:
        """Apply an effect to the pad's LED."""
        if not self._effects_index or not self._zone_count:
            return False

        effect = settings.effect
        if not settings.enabled:
            effect_id = EFFECT_DISABLED
        else:
            effect_id = _EFFECT_BY_NAME.get(effect.effect_type, EFFECT_FIXED_COLOR)

        effect_index = self._zone_effect_index(0x00, effect_id)
        if effect_index is None:
            logger.error(f"{self.name}: zone 0 reports no effect for {effect_id:#04x}")
            return False

        params = bytes(
            [
                0x00,  # zone index
                effect_index,
                effect.color.red,
                effect.color.green,
                effect.color.blue,
                max(0, min(100, effect.brightness)),
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
                0x00,
            ]
        )
        # Claim software control, then write the effect as volatile (RAM only)
        # so the pad's stored configuration is left untouched.
        self._read_feature(self._effects_index, 0x08, bytes([0x01, 0x00]))
        frame = self._read_feature(self._effects_index, 0x03, params + bytes([0x00]))
        if not frame:
            return False

        # Do not claim success on a write the device did not take.
        read_back = self._read_feature(self._effects_index, 0x0C, bytes([0x00]))
        applied = len(read_back) >= 8 and (
            read_back[5],
            read_back[6],
            read_back[7],
        ) == (effect.color.red, effect.color.green, effect.color.blue)
        if not applied:
            logger.warning(
                f"{self.name}: colour not applied "
                f"({effect.color.red},{effect.color.green},{effect.color.blue})"
            )
            return False

        self.active_profile.lighting_settings = settings
        return True

    def set_zone_lighting(self, zone: str, effect: LightingEffect) -> bool:
        """Set the LED effect for a named zone."""
        if zone not in ("primary", "logo", "0"):
            return False
        settings = LightingSettings(enabled=effect.effect_type != "off", effect=effect)
        return self.set_lighting_settings(settings)

    # ── info helpers ─────────────────────────────────────────────────────────
    def _get_firmware_version(self) -> str:
        """Read the firmware version from DeviceInfo (0x0003).

        ``getFwInfo`` (fn 1) returns, in the 4 bytes after the entity type, unit
        ID and transport: a 3-char firmware prefix, then packed-BCD number,
        revision and build.  Verified against this pad: the bytes ``07 00 00
        10`` decode to ``07.00`` build ``10``, matching the ``CC 07.00.B0010``
        Solaar documents for the same hardware.
        """
        info_index = self._features.get(0x0003)
        if not info_index:
            return "Unknown"

        frame = self._read_feature(info_index, 0x00)
        if len(frame) < 5:
            return "Unknown"

        for entity in range(min(frame[4], 8)):
            detail = self._read_feature(info_index, 0x01, bytes([entity]))
            if len(detail) < 12:
                continue
            # Only the main application firmware is user-facing; the bootloader
            # entity reports its own numbering.
            if detail[4] != 0:
                continue
            number = _bcd(detail[8])
            revision = _bcd(detail[9])
            build = (_bcd(detail[10]) * 100 + _bcd(detail[11])) if len(detail) > 11 else 0
            version = f"{number}.{revision:02d}"
            return f"{version} (build {build})" if build else version
        return "Unknown"

    def hidpp_device_name(self) -> str | None:
        """Read the pad's own HID++ DeviceName — "Candy companion chip".

        Exposed for the info panel: the name is what the hardware reports, while
        :attr:`info.name` is the product name a user recognises.
        """
        index = self._features.get(0x0005)
        if not index:
            return None
        header = self._read_feature(index, 0x00)
        if len(header) < 5 or not header[4]:
            return None
        raw = bytearray()
        offset = 0
        while offset < header[4]:
            chunk = self._read_feature(index, 0x01, bytes([offset]))
            if len(chunk) <= 4:
                break
            take = min(16, header[4] - offset)
            raw += bytes(chunk[4 : 4 + take])
            offset += take
        name = raw.decode("utf-8", "replace").rstrip("\x00").strip()
        return name or None


def _bcd(value: int) -> int:
    """Decode one packed-BCD byte (0x17 -> 17)."""
    return (value >> 4) * 10 + (value & 0x0F)


# The pad is registered by its own PID. Its HID++ controller answers on the
# interface that reports 0x405F; the receiver interface (0xC53A) belongs to the
# mouse on the pad and is deliberately not claimed here.
POWERPLAY_DEVICES: dict[int, type[BaseDevice]] = {
    POWERPLAY_PID: Powerplay,
    POWERPLAY_2_PID: Powerplay,
}

# Kept for backwards compatibility with the previous registry shape.
POWERPLAY_RECEIVER_HINTS: list[tuple[int, str, type]] = []

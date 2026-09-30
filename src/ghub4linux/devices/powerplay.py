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

Its LED is driven through colorLedEffects (``0x8070``), and the pad's engine is
deliberately small: **one** zone offering only ``Disabled`` and ``FixedColor``.
An earlier version of the UI offered Static, Breathing, Colour Cycle, Wave and
Off regardless of what the device reported, which is why effects other than
static and off appeared to do nothing — the fabric of that list was invented,
not read.
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
from ..core.rgb import (
    EFFECT_NAMES,
    ColorLedEffects,
)

logger = logging.getLogger(__name__)

# The POWERPLAY base ("Candy companion chip", model ID 405F00000000).
POWERPLAY_PID = 0x405F
# POWERPLAY 2 (2025) is expected to carry a new PID; it is listed so the driver
# is picked up if the pad reports it.
POWERPLAY_2_PID = 0x40C6

_EFFECT_BY_NAME = {
    "off": 0x0000,
    "static": 0x0001,
    "breathing": 0x0002,
    "cycle": 0x0003,
    "wave": 0x0004,
    "starlight": 0x0005,
    "press": 0x0006,
    "ripple": 0x000B,
}


class Powerplay(BaseDevice):
    """Logitech POWERPLAY wireless charging system (mouse pad)."""

    def __init__(self, hid_device: HIDDevice, config: DeviceConfig | None = None):
        """Initialize the POWERPLAY device."""
        super().__init__(hid_device, config)
        self._features: dict[int, int] = {}
        self._rgb: ColorLedEffects | None = None

    def _init_device(self) -> None:
        """Initialize the device after connecting."""
        self._features = self.discover_features()
        index = (
            self._connection.feature_index(0x8070)  # colorLedEffects
            if self._connection
            else 0
        )
        if index and self._connection:
            self._rgb = ColorLedEffects(self._connection, index)
            self._rgb.refresh()
        self._capabilities = {DeviceCapability.RGB_LIGHTING} if self._rgb else set()
        self._info = self.get_device_info()
        # The hardware calls this controller "Candy companion chip", which tells
        # a user nothing. Show the product name instead; the raw string stays
        # available through hidpp_device_name().
        self._config.device_name = self._info.name
        zones = len(self._rgb.zones) if self._rgb else 0
        effects = (
            ", ".join(EFFECT_NAMES.get(e, hex(e)) for e in self._rgb.supported_effect_ids())
            if self._rgb
            else "none"
        )
        logger.info(f"Initialized {self._info.name} (zones: {zones}, effects: {effects})")

    def supported_lighting_effects(self) -> list[str]:
        """Effect names this pad actually offers.

        The UI builds its list from this instead of a hardcoded catalogue, so it
        cannot offer an effect the hardware will silently refuse.
        """
        if not self._rgb:
            return []
        by_id = {value: name for name, value in _EFFECT_BY_NAME.items()}
        names: list[str] = []
        for effect_id in self._rgb.supported_effect_ids():
            name = by_id.get(effect_id)
            if name is None:
                continue
            if name == "off":
                # "Off" is the enable switch, not a choice in the effect list.
                continue
            names.append(name)
        return names

    def lighting_zones(self) -> list[str]:
        """Human-readable names of the pad's LED zones."""
        if not self._rgb:
            return []
        return [zone.location_name for zone in self._rgb.zones]

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
            has_rgb=bool(self._rgb),
            max_dpi=0,
            dpi_step=0,
            button_count=0,
            has_onboard_profiles=False,
        )

    # ── lighting ─────────────────────────────────────────────────────────────
    #
    # The pad's engine lives in core/rgb.py: it reads the zones and the effect
    # list from the device instead of assuming them, and it claims software
    # control before writing (the firmware discards effect writes otherwise).

    def get_lighting_settings(self) -> LightingSettings:
        """Read the pad's current colour from the device itself."""
        settings = super().get_lighting_settings()
        if not self._rgb:
            return settings
        color = self._rgb.get_current_color(0)
        if color is not None:
            settings.effect.color.red, settings.effect.color.green, settings.effect.color.blue = (
                color
            )
            settings.effect.effect_type = "static"
            settings.enabled = any(color)
        return settings

    def _set_lighting_settings(self, settings: LightingSettings) -> bool:
        """Apply an effect to the pad's LED, or turn it off."""
        if not self._rgb:
            return False

        if not settings.enabled:
            applied = self._rgb.set_off(0)
        else:
            effect = settings.effect
            effect_id = _EFFECT_BY_NAME.get(effect.effect_type, 0x0001)
            applied = self._rgb.set_effect(
                0,
                effect_id,
                (effect.color.red, effect.color.green, effect.color.blue),
                effect.brightness,
            )

        if not applied:
            logger.warning(f"{self.name}: lighting change not applied by the device")
            return False
        self.active_profile.lighting_settings = settings
        return True

    def set_zone_lighting(self, zone: str, effect: LightingEffect) -> bool:
        """Set the LED effect for a named zone."""
        if not self._rgb:
            return False
        target = None
        for candidate in self._rgb.zones:
            if zone.lower() in (candidate.location_name.lower(), str(candidate.index)):
                target = candidate
                break
        if target is None:
            return False
        if effect.effect_type == "off":
            return self._rgb.set_off(target.index)
        effect_id = _EFFECT_BY_NAME.get(effect.effect_type, 0x0001)
        return self._rgb.set_effect(
            target.index,
            effect_id,
            (effect.color.red, effect.color.green, effect.color.blue),
            effect.brightness,
        )

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

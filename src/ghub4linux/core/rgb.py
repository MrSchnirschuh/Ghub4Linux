"""HID++ colorLedEffects (0x8070) — the per-zone RGB engine.

Shared by every device that drives RGB through this feature: the POWERPLAY pad
and the G502 Lightspeed both expose ``0x8070`` (neither has the newer ``0x8071``
rgbEffects), but with different zone and effect counts, so nothing here may be
hardcoded per device.

Wire format (verified against the hardware and the reverse-engineered spec):

======  =========================  ==========================================
fn 0    get_info()                 -> [zones, nv_caps(2), ext_caps(2)]
fn 1    get_zone_info(zone)        -> [zone, location, effects, persistency]
fn 2    get_zone_effect_info(z, e)  -> [zone, e, id(2 BE), caps(2), period(2)]
fn 3    set_zone_effect(z, e,       -> ()
        params[10], persistence)
fn 7    get_sw_control()           -> [control, events, ...]
fn 8    set_sw_control(ctrl, evts) -> ()
fn 12   get_current_color(zone)    -> [zone, r, g, b]
======  =========================  ==========================================

Effect indexes are **per zone** and not stable across models: the index of a
given effect must be looked up with fn 2, never assumed. The effect ID itself is
a big-endian u16 there, so comparing one byte never matches ``FixedColor``
(``0x0001``, high byte 0).
"""

from __future__ import annotations

import logging

from .hid import HIDConnection

logger = logging.getLogger(__name__)

FEATURE_COLOR_LED_EFFECTS = 0x8070

# EffectId values (OpenLogi color_led_effects/types.rs, #[repr(u16)]).
EFFECT_NAMES: dict[int, str] = {
    0: "Disabled",
    1: "FixedColor",
    2: "PulsingBreathingLegacy",
    3: "Cycling",
    4: "ColorWave",
    5: "Starlight",
    6: "LightOnPress",
    7: "AudioVisualizer",
    8: "BootUp",
    9: "DemoMode",
    10: "PulsingBreathingWaveform",
    11: "Ripple",
}

# Zone locations (LocationEffect, #[repr(u16)] but sent as one byte here).
LOCATION_NAMES: dict[int, str] = {
    1: "Primary",
    2: "Logo",
    3: "Left side",
    4: "Right side",
    5: "Combined",
    6: "Primary 1",
    7: "Primary 2",
    8: "Primary 3",
    9: "Primary 4",
    10: "Primary 5",
    11: "Primary 6",
}

# What each effect needs in its 10 parameter bytes. Only the effects a device
# here actually exposes are spelled out; anything else gets the colour.
PARAM_COLOR_FIRST = {1, 2, 3, 4, 5, 6, 10, 11}

# Persistence for set_zone_effect.
PERSISTENCE_VOLATILE = 0x00  # RAM only, lost on power cycle
PERSISTENCE_BOTH = 0x01  # RAM + EEPROM
PERSISTENCE_NON_VOLATILE = 0x02  # EEPROM only

# How many effect indexes to probe when looking an effect ID up. The pad reports
# 2, the G502 3 per zone; 16 leaves room for future models without looping.
MAX_EFFECT_INDEX = 16


class ColorLedZone:
    """One LED zone as the device describes it."""

    def __init__(self, index: int, location: int, effects: list[tuple[int, int]]):
        """Store a zone's index, its physical location and its (index, id) effects."""
        self.index = index
        self.location = location
        self.effects = effects  # list of (zone_effect_index, effect_id)

    @property
    def location_name(self) -> str:
        """Human name of the zone's physical location."""
        return LOCATION_NAMES.get(self.location, f"Zone {self.index}")

    def effect_index(self, effect_id: int) -> int | None:
        """Return the zone-local index for *effect_id*, or None if unsupported.

        Looked up rather than assumed: the same effect sits at a different index
        on different devices (and per zone on the same device).
        """
        for index, found_id in self.effects:
            if found_id == effect_id:
                return index
        return None

    def effect_ids(self) -> list[int]:
        """Every effect ID this zone supports, in device order."""
        return [effect_id for _, effect_id in self.effects]

    def capability(self, effect_id: int) -> bool:
        """True when the zone offers *effect_id*."""
        return self.effect_index(effect_id) is not None


class ColorLedEffects:
    """Reader/writer for the 0x8070 feature on one device connection."""

    def __init__(self, connection: HIDConnection, index: int):
        """Bind to an already-resolved feature index."""
        self._connection = connection
        self.index = index
        self._zones: list[ColorLedZone] = []
        self.nv_capabilities = 0
        self.ext_capabilities = 0

    # ── discovery ────────────────────────────────────────────────────────────
    def refresh(self) -> list[ColorLedZone]:
        """Read and cache the device's zones and their effects."""
        self._zones = []
        frame = self._connection.send_feature_request(self.index, 0x00)
        if not frame or len(frame) < 9:
            return self._zones

        zone_count = frame[4]
        self.nv_capabilities = (frame[5] << 8) | frame[6]
        self.ext_capabilities = (frame[7] << 8) | frame[8]

        for zone_index in range(zone_count):
            info = self._connection.send_feature_request(self.index, 0x01, bytes([zone_index]))
            if not info or len(info) < 7:
                continue
            location = info[5]
            effect_count = info[6]
            effects: list[tuple[int, int]] = []
            for effect_index in range(min(effect_count, MAX_EFFECT_INDEX)):
                detail = self._connection.send_feature_request(
                    self.index, 0x02, bytes([zone_index, effect_index])
                )
                if not detail or len(detail) < 8:
                    continue
                effect_id = (detail[6] << 8) | detail[7]
                effects.append((effect_index, effect_id))
            self._zones.append(ColorLedZone(zone_index, location, effects))

        return self._zones

    @property
    def zones(self) -> list[ColorLedZone]:
        """The zones discovered by :meth:`refresh`."""
        return self._zones

    def zone(self, index: int) -> ColorLedZone | None:
        """Return a zone by index, if discovered."""
        return next((z for z in self._zones if z.index == index), None)

    def supported_effect_ids(self) -> list[int]:
        """Every effect ID offered by any zone, in a stable order.

        This is what a UI must offer: presenting an effect the device does not
        list means the user picks it and nothing happens.
        """
        seen: list[int] = []
        for zone in self._zones:
            for effect_id in zone.effect_ids():
                if effect_id not in seen:
                    seen.append(effect_id)
        return seen

    # ── software control ─────────────────────────────────────────────────────
    def get_software_control(self) -> tuple[int, int] | None:
        """Return ``(control, events)`` or None when unreadable."""
        frame = self._connection.send_feature_request(self.index, 0x07)
        if not frame or len(frame) < 6:
            return None
        return frame[4], frame[5]

    def claim_software_control(self, events: int = 0x00) -> bool:
        """Take the LEDs over from the firmware.

        Without this the firmware owns the LED and silently discards effect
        writes, so a write would appear to succeed while nothing changes.
        """
        frame = self._connection.send_feature_request(
            self.index, 0x08, bytes([0x01, events]) + bytes(13)
        )
        return bool(frame)

    # ── reading ──────────────────────────────────────────────────────────────
    def get_current_color(self, zone_index: int = 0) -> tuple[int, int, int] | None:
        """Return the zone's current (r, g, b)."""
        frame = self._connection.send_feature_request(self.index, 0x0C, bytes([zone_index]))
        if not frame or len(frame) < 8:
            return None
        return frame[5], frame[6], frame[7]

    # ── writing ──────────────────────────────────────────────────────────────
    def set_color(
        self,
        zone_index: int,
        color: tuple[int, int, int],
        brightness: int = 100,
        persistence: int = PERSISTENCE_VOLATILE,
    ) -> bool:
        """Apply a fixed colour and verify it landed.

        Returns False when the device did not take the colour: the write is
        acknowledged by some firmware that then keeps the old value.
        """
        return self.set_effect(zone_index, 0x0001, color, brightness, persistence)

    def set_effect(
        self,
        zone_index: int,
        effect_id: int,
        color: tuple[int, int, int] = (255, 255, 255),
        brightness: int = 100,
        persistence: int = PERSISTENCE_VOLATILE,
        extra: bytes = b"",
    ) -> bool:
        """Apply *effect_id* to one zone.

        The parameter block is effect-specific; for the effects these devices
        expose the first three bytes are red, green and blue, followed by
        brightness.  *extra* carries any effect-specific settings beyond that.
        """
        zone = self.zone(zone_index)
        if zone is None:
            logger.warning(f"zone {zone_index} not discovered on this device")
            return False

        effect_index = zone.effect_index(effect_id)
        if effect_index is None:
            logger.warning(
                f"zone {zone_index} does not offer effect 0x{effect_id:04x} "
                f"(has {[hex(e) for e in zone.effect_ids()]})"
            )
            return False

        self.claim_software_control()

        params = bytearray(10)
        params[0], params[1], params[2] = color
        params[3] = max(0, min(100, brightness))
        for offset, value in enumerate(extra[:6]):
            params[4 + offset] = value

        args = bytes([zone_index, effect_index]) + bytes(params) + bytes([persistence])
        frame = self._connection.send_feature_request(self.index, 0x03, args)
        if not frame:
            return False

        # Read back: an acknowledged write that did not change the LED is a
        # failure, and reporting it as success would be a lie.
        read_back = self.get_current_color(zone_index)
        applied = read_back == tuple(color)
        if not applied:
            logger.warning(f"colour {color} not applied (device reports {read_back})")
        return applied

    def set_off(self, zone_index: int = 0) -> bool:
        """Disable the zone's LED."""
        zone = self.zone(zone_index)
        if zone is None:
            return False
        effect_index = zone.effect_index(0x0000)
        if effect_index is None:
            return False
        self.claim_software_control()
        args = bytes([zone_index, effect_index]) + bytes(10) + bytes([PERSISTENCE_VOLATILE])
        frame = self._connection.send_feature_request(self.index, 0x03, args)
        read_back = self.get_current_color(zone_index)
        return bool(frame) and read_back == (0, 0, 0)

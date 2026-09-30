"""HID++ colorLedEffects (0x8070) — the per-zone RGB engine.

Shared by every device that drives RGB through this feature: the POWERPLAY pad
and the G502 Lightspeed both expose ``0x8070`` (neither has the newer ``0x8071``
rgbEffects), but with different zone and effect counts, so nothing here may be
hardcoded per device.

Wire format, verified byte-for-byte against the hardware and Logitech's own
``x8070_colorledeffect_v7`` spec (payload offsets are ``frame[4 + n]``, all
multi-byte values big-endian):

======  ============================  =========================================
fn 0    get_info()                    -> zoneCount, nvCaps(2), extCaps(2)
fn 1    get_zone_info(zone)           -> zone, location(2), effectsNumber,
                                         persistency
fn 2    get_zone_effect_info(z, e)    -> z, e, effectID(2), caps(2), period(2)
fn 3    set_zone_effect(z, e,         -> ()
        params[10], persistence)
fn 7    get_sw_control()              -> control, events
fn 8    set_sw_control(ctrl, evts)    -> ()
fn 9    get_effect_settings(z, pers)  -> z, r, g, b, period(2), brightness, param
fn 12   get_current_color(zone)       -> _, r, g, b  (live LED colour)
fn 14   get_zone_effect(z, pers)      -> z, zoneEffectIndex, params[10]
======  ============================  =========================================

Three traps this module exists to avoid, each of which produced a UI that
offered effects the device does not have and reported written values that never
landed:

1. ``get_zone_info`` returns location as a **big-endian u16** and
   ``effectsNumber`` one byte further along at ``frame[7]``.  Reading
   ``frame[6]`` as the effect count yields 2 on the POWERPLAY pad, which really
   has four effects — so Cycling and Pulsing/Breathing were hidden and only
   "static" and "off" could ever be selected.
2. The effect ID in ``get_zone_effect_info`` is a **big-endian u16**; comparing
   one byte never matches FixedColor (``0x0001``, high byte 0).
3. Effect parameters are **per effect**, not a shared colour+speed+brightness
   block.  Byte 4 of FixedColor is a ramp mode (0 default / 1 ramp / 2 instant),
   not a brightness — writing a brightness there sends an invalid mode.

Effect indexes are per zone and not stable across models, so the index of a
given effect is looked up with fn 2 and never assumed.
"""

from __future__ import annotations

import logging
import time

from .hid import HIDConnection

logger = logging.getLogger(__name__)

FEATURE_COLOR_LED_EFFECTS = 0x8070

# EffectId values (spec Table 7 / OpenLogi color_led_effects types).
EFFECT_NAMES: dict[int, str] = {
    0: "Disabled",
    1: "Fixed",
    2: "Pulsing/Breathing (legacy)",
    3: "Cycling",
    4: "Color Wave",
    5: "Starlight",
    6: "Light on Press",
    7: "Audio Visualizer",
    8: "Boot Up",
    9: "Demo Mode",
    10: "Pulsing/Breathing (Waveform)",
    11: "Ripple",
}

# Config-model effect name -> the effect IDs that can implement it, most
# preferred first.  Two IDs can mean the same thing (breathing ships both as the
# legacy and the waveform variant), so the device is asked which one it has
# rather than one being assumed.
EFFECT_IDS_BY_NAME: dict[str, tuple[int, ...]] = {
    "off": (0,),
    "static": (1,),
    "breathing": (10, 2),
    "cycle": (3,),
    "wave": (4,),
    "starlight": (5,),
    "press": (6,),
    "ripple": (11,),
}

# Reverse map for building a UI: which config effect a device effect ID means.
EFFECT_NAME_BY_ID: dict[int, str] = {
    0: "off",
    1: "static",
    2: "breathing",
    3: "cycle",
    4: "wave",
    5: "starlight",
    6: "press",
    10: "breathing",
    11: "ripple",
}

# Effects that animate by themselves: their colour changes over time, so reading
# the LED once cannot confirm a write and an exact colour match is the wrong
# test.  Animation is confirmed by sampling instead.
ANIMATED_EFFECTS = {2, 3, 4, 5, 7, 10, 11}

# Waveform parameter for effect 10.
WAVEFORM_DEFAULT = 0
WAVEFORM_SINE = 1
WAVEFORM_SQUARE = 2
WAVEFORM_TRIANGLE = 3
WAVEFORM_SAWTOOTH = 4
WAVEFORM_SHARK_FIN = 5
WAVEFORM_EXPONENTIAL = 6

# Persistence for set_zone_effect.
PERSISTENCE_VOLATILE = 0x00  # RAM only, lost on power cycle
PERSISTENCE_BOTH = 0x01  # RAM + EEPROM
PERSISTENCE_NON_VOLATILE = 0x02  # EEPROM only

# Zone locations (locationEffect, a big-endian u16 in get_zone_info).
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

# get_zone_info reports the effect list length in this byte (see trap 1).
_ZONE_INFO_EFFECTS_BYTE = 7

# How many effect indexes to probe at most, so a bogus count cannot loop.
MAX_EFFECT_INDEX = 16


def _u16(high: int, low: int) -> int:
    """Combine two big-endian bytes."""
    return (high << 8) | low


class ColorLedEffect:
    """One entry in a zone's effect table."""

    def __init__(self, index: int, effect_id: int, capabilities: int, period: int):
        """Store an effect's zone-local index, its ID, capabilities and period."""
        self.index = index
        self.effect_id = effect_id
        self.capabilities = capabilities
        self.period = period

    @property
    def name(self) -> str:
        """Human name of the effect."""
        return EFFECT_NAMES.get(self.effect_id, f"Effect 0x{self.effect_id:04x}")

    @property
    def config_name(self) -> str | None:
        """The configuration-model name for this effect, if it has one."""
        return EFFECT_NAME_BY_ID.get(self.effect_id)

    @property
    def animated(self) -> bool:
        """True when the effect changes colour on its own."""
        return self.effect_id in ANIMATED_EFFECTS

    def supports(self, capability_bit: int) -> bool:
        """True when the device advertised *capability_bit* for this effect.

        A capabilities value of 0 means the effect predates capability
        reporting: callers must assume the documented defaults rather than
        treat every bit as absent.
        """
        if self.capabilities == 0:
            return True
        return bool(self.capabilities & capability_bit)

    def __repr__(self) -> str:
        """Debug representation."""
        return (
            f"<ColorLedEffect index={self.index} id=0x{self.effect_id:04x} "
            f"{self.name} caps=0x{self.capabilities:04x} period={self.period}>"
        )


class ColorLedZone:
    """One LED zone as the device describes it."""

    def __init__(self, index: int, location: int, effects: list[ColorLedEffect]):
        """Store a zone's index, its physical location and its effects."""
        self.index = index
        self.location = location
        self.effects = effects

    @property
    def location_name(self) -> str:
        """Human name of the zone's physical location."""
        return LOCATION_NAMES.get(self.location, f"Zone {self.index}")

    def effect(self, effect_id: int) -> ColorLedEffect | None:
        """Return the entry for *effect_id*, or None when unsupported."""
        for entry in self.effects:
            if entry.effect_id == effect_id:
                return entry
        return None

    def effect_for_name(self, name: str) -> ColorLedEffect | None:
        """Return the best entry implementing config effect *name*.

        Asks the device which variants it has: a pad may offer the waveform
        breathing, the legacy one, both or neither.
        """
        for candidate in EFFECT_IDS_BY_NAME.get(name, ()):
            found = self.effect(candidate)
            if found is not None:
                return found
        return None

    def effect_ids(self) -> list[int]:
        """Every effect ID this zone supports, in device order."""
        return [entry.effect_id for entry in self.effects]

    def effect_names(self) -> list[str]:
        """Config effect names this zone can actually perform, deduplicated.

        This is what a UI must offer.  Listing a fixed catalogue instead means
        the user picks an effect the firmware does not implement and nothing
        happens.
        """
        names: list[str] = []
        for entry in self.effects:
            name = entry.config_name
            if name and name not in names:
                names.append(name)
        return names


class ColorLedEffects:
    """Reader/writer for the 0x8070 feature on one device connection."""

    def __init__(self, connection: HIDConnection, index: int):
        """Bind to an already-resolved feature index."""
        self._connection = connection
        self.index = index
        self._zones: list[ColorLedZone] = []
        self.nv_capabilities = 0
        self.ext_capabilities = 0
        self._software_control = False

    # ── plumbing ─────────────────────────────────────────────────────────────
    def _call(self, function: int, args: bytes = b"") -> bytes | None:
        """Send one feature request, treating a timeout as "no answer".

        Probing beyond a device's effect count is normal, and a device that
        simply does not reply must not abort discovery.
        """
        try:
            return self._connection.send_feature_request(self.index, function, args)
        except Exception as exc:  # noqa: BLE001 - transport-specific
            logger.debug(f"0x8070 fn{function} got no answer: {exc}")
            return None

    # ── discovery ────────────────────────────────────────────────────────────
    def refresh(self) -> list[ColorLedZone]:
        """Read and cache the device's zones and their effects."""
        self._zones = []
        frame = self._call(0x00, bytes(3))
        if not frame or len(frame) < 9:
            return self._zones

        zone_count = frame[4]
        self.nv_capabilities = _u16(frame[5], frame[6])
        self.ext_capabilities = _u16(frame[7], frame[8])

        for zone_index in range(zone_count):
            info = self._call(0x01, bytes([zone_index, 0, 0]))
            if not info or len(info) < 9:
                continue
            # Location is a BE u16, and the effect count sits one byte further
            # along than the location's low byte.
            location = _u16(info[5], info[6])
            effect_count = info[_ZONE_INFO_EFFECTS_BYTE]
            effects: list[ColorLedEffect] = []
            for effect_index in range(min(effect_count, MAX_EFFECT_INDEX)):
                detail = self._call(0x02, bytes([zone_index, effect_index, 0]))
                if not detail or len(detail) < 12:
                    continue
                effects.append(
                    ColorLedEffect(
                        index=detail[5],
                        effect_id=_u16(detail[6], detail[7]),
                        capabilities=_u16(detail[8], detail[9]),
                        period=_u16(detail[10], detail[11]),
                    )
                )
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
        """Every effect ID offered by any zone, in a stable order."""
        seen: list[int] = []
        for zone in self._zones:
            for effect_id in zone.effect_ids():
                if effect_id not in seen:
                    seen.append(effect_id)
        return seen

    def supported_effect_names(self) -> list[str]:
        """Config effect names any zone on this device can perform."""
        seen: list[str] = []
        for zone in self._zones:
            for name in zone.effect_names():
                if name not in seen:
                    seen.append(name)
        return seen

    # ── software control ─────────────────────────────────────────────────────
    def get_software_control(self) -> tuple[int, int] | None:
        """Return ``(control, events)`` or None when unreadable."""
        frame = self._call(0x07)
        if not frame or len(frame) < 6:
            return None
        return frame[4], frame[5]

    def claim_software_control(self, events: int = 0x00) -> bool:
        """Take the LEDs over from the firmware.

        Without this the firmware owns the LED and discards effect writes, so a
        write appears to succeed while nothing changes.
        """
        frame = self._call(0x08, bytes([0x01, events]) + bytes(13))
        if frame:
            self._software_control = True
        return bool(frame)

    # ── reading ──────────────────────────────────────────────────────────────
    def get_current_color(self, zone_index: int = 0) -> tuple[int, int, int] | None:
        """Return the zone's live (r, g, b), or None when unreadable."""
        frame = self._call(0x0C, bytes([zone_index, 0, 0]))
        if not frame or len(frame) < 8:
            return None
        return frame[5], frame[6], frame[7]

    def get_stored_effect(self, zone_index: int = 0, persistence: int = 0) -> int | None:
        """Return the zone's stored effect index, or None.

        Note this reflects what was committed to the device, which can lag or
        differ from the effect currently playing; use :meth:`get_current_color`
        to observe what is on the LED right now.
        """
        frame = self._call(0x0E, bytes([zone_index, persistence, 0]))
        if not frame or len(frame) < 6:
            return None
        return frame[5]

    def get_effect_settings(self, zone_index: int = 0, persistence: int = 0) -> dict | None:
        """Return the zone's stored colour, period, brightness and parameter."""
        frame = self._call(0x09, bytes([zone_index, persistence, 0]))
        if not frame or len(frame) < 12:
            return None
        return {
            "color": (frame[5], frame[6], frame[7]),
            "period": _u16(frame[8], frame[9]),
            "brightness": frame[10],
            "param": frame[11],
        }

    # ── writing ──────────────────────────────────────────────────────────────
    def _build_params(
        self,
        effect: ColorLedEffect,
        color: tuple[int, int, int],
        duration_ms: int | None,
        waveform: int,
        intensity: int,
        ramp: int,
        extra: bytes,
    ) -> bytes:
        """Build the 10 effect-specific parameter bytes.

        The layouts differ per effect; a shared "colour + speed + brightness"
        block is wrong.  Offsets follow spec Table 7.
        """
        params = bytearray(10)
        effect_id = effect.effect_id
        red, green, blue = color

        if effect_id == 0:  # Disabled: no parameters
            return bytes(params)

        if effect_id in (1, 2):  # Fixed / PulsingBreathing (legacy)
            params[0], params[1], params[2] = red, green, blue
            if effect_id == 1:
                params[3] = ramp  # 0 default, 1 ramp up+down, 2 instant
            elif duration_ms:
                params[3] = min(255, duration_ms)

        elif effect_id == 3:  # Cycling: colour comes from intensity, not RGB
            period = self._clamp_period(effect, duration_ms)
            params[6] = (period >> 8) & 0xFF  # period MSB
            params[7] = period & 0xFF  # period LSB
            params[8] = max(0, min(100, intensity))

        elif effect_id == 4:  # Color Wave: start colour, stop colour, speed…
            params[0], params[1], params[2] = red, green, blue
            params[6] = min(255, duration_ms // 10) if duration_ms else 0
            params[8] = max(0, min(100, intensity))

        elif effect_id in (5, 6):  # Starlight / Light on Press: two colours
            params[0], params[1], params[2] = red, green, blue
            if effect_id == 6 and duration_ms:
                params[6] = (min(duration_ms, 0xFFFF) >> 8) & 0xFF
                params[7] = min(duration_ms, 0xFFFF) & 0xFF

        elif effect_id == 10:  # PulsingBreathing (Waveform)
            params[0], params[1], params[2] = red, green, blue
            period = self._clamp_period(effect, duration_ms or effect.period or 1000)
            params[3] = (period >> 8) & 0xFF  # period MSB
            params[4] = period & 0xFF  # period LSB
            params[5] = waveform
            params[6] = max(0, min(100, intensity))

        elif effect_id == 11:  # Ripple
            params[0], params[1], params[2] = red, green, blue
            period = self._clamp_period(effect, duration_ms)
            params[4] = (period >> 8) & 0xFF
            params[5] = period & 0xFF

        else:  # Unknown effect: pass the colour through the documented prefix
            params[0], params[1], params[2] = red, green, blue

        for offset, value in enumerate(extra[:4]):
            if offset + 6 < len(params):
                params[6 + offset] = value
        return bytes(params)

    def _clamp_period(self, effect: ColorLedEffect, duration_ms: int | None) -> int:
        """Return a period the device accepts.

        The spec requires the period to be a multiple of the effect's advertised
        period, so a value outside that grid is snapped onto it rather than sent
        and ignored.
        """
        if not duration_ms:
            return effect.period or 1000
        if effect.period > 1:
            steps = max(1, round(duration_ms / effect.period))
            return min(0xFFFF, steps * effect.period)
        return min(0xFFFF, duration_ms)

    def set_effect(
        self,
        zone_index: int,
        effect_id: int,
        color: tuple[int, int, int] = (255, 255, 255),
        duration_ms: int | None = None,
        waveform: int = WAVEFORM_SINE,
        intensity: int = 100,
        ramp: int = 0,
        persistence: int = PERSISTENCE_VOLATILE,
        extra: bytes = b"",
    ) -> bool:
        """Apply *effect_id* to one zone and confirm the LED changed.

        Returns False when the device does not offer the effect, does not
        acknowledge the write, or acknowledges it without the LED changing.
        An animated effect is confirmed by sampling the LED, because one reading
        of a moving colour cannot match a fixed target.
        """
        zone = self.zone(zone_index)
        if zone is None:
            logger.warning(f"zone {zone_index} not discovered on this device")
            return False

        effect = zone.effect(effect_id)
        if effect is None:
            logger.warning(
                f"zone {zone_index} does not offer effect 0x{effect_id:04x} "
                f"(has {[hex(e) for e in zone.effect_ids()]})"
            )
            return False

        self.claim_software_control()

        before = self.get_current_color(zone_index)
        params = self._build_params(effect, color, duration_ms, waveform, intensity, ramp, extra)
        args = bytes([zone_index, effect.index]) + params + bytes([persistence])
        if not self._call(0x03, args):
            logger.warning(f"zone {zone_index} effect {effect.name}: no acknowledgement")
            return False

        return self._confirm(zone_index, effect, color, before)

    def _confirm(
        self,
        zone_index: int,
        effect: ColorLedEffect,
        color: tuple[int, int, int],
        before: tuple[int, int, int] | None,
    ) -> bool:
        """Decide whether a write actually took effect.

        Reads the live LED a few times: an exact match confirms a fixed colour,
        and any change from the previous reading confirms an animation.  A write
        that left the LED exactly as it was is a failure even though the device
        acknowledged it — reporting success there would be a lie.
        """
        target = tuple(color)
        samples: list[tuple[int, int, int]] = []
        for _ in range(4):
            time.sleep(0.12)
            reading = self.get_current_color(zone_index)
            if reading is not None:
                samples.append(reading)
            # A fixed colour must match exactly.
            if reading == target and not effect.animated:
                return True
            # An animated effect is confirmed when the LED moves, either onto the
            # start colour or away from where it was.
            if (
                effect.animated
                and reading is not None
                and (reading == target or (before is not None and reading != before))
            ):
                return True

        if effect.effect_id == 0:
            # "Off" means dark; anything lit means the write did not take.
            # (Test the colour, not the tuple: (0, 0, 0) is a truthy tuple.)
            return all(reading == (0, 0, 0) for reading in samples)
        if not samples:
            # Cannot see the LED: do not claim either way about the colour.
            logger.debug(f"zone {zone_index}: no colour readback available")
            return True
        logger.warning(f"zone {zone_index} effect {effect.name}: LED unchanged at {samples[-1]}")
        return False

    def set_effect_by_name(
        self,
        zone_index: int,
        name: str,
        color: tuple[int, int, int] = (255, 255, 255),
        duration_ms: int | None = None,
        waveform: int = WAVEFORM_SINE,
        intensity: int = 100,
    ) -> bool:
        """Apply the config effect called *name* to one zone."""
        zone = self.zone(zone_index)
        if zone is None:
            return False
        effect = zone.effect_for_name(name)
        if effect is None:
            logger.warning(f"zone {zone_index} has no effect for '{name}'")
            return False
        return self.set_effect(
            zone_index,
            effect.effect_id,
            color=color,
            duration_ms=duration_ms,
            waveform=waveform,
            intensity=intensity,
        )

    def set_color(
        self,
        zone_index: int,
        color: tuple[int, int, int],
        brightness: int = 100,
        persistence: int = PERSISTENCE_VOLATILE,
    ) -> bool:
        """Apply a fixed colour, using the device's own fixed-colour effect."""
        zone = self.zone(zone_index)
        if zone is None:
            return False
        effect = zone.effect_for_name("static")
        if effect is None:
            logger.warning(f"zone {zone_index} offers no fixed-colour effect")
            return False
        return self.set_effect(
            zone_index,
            effect.effect_id,
            color=color,
            intensity=brightness,
            persistence=persistence,
        )

    def set_off(self, zone_index: int = 0) -> bool:
        """Disable the zone's LED."""
        return self.set_effect(
            zone_index, 0x0000, color=(0, 0, 0), persistence=PERSISTENCE_VOLATILE
        )

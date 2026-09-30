"""HID++ LEDControl (0x1300) — the on-device status indicators.

This drives the *status* LEDs of a G-series mouse: the DPI indicator bars, the
profile indicator and the battery indicator.  It carries **no colour** — it is
strictly on/off.  Colour for the same indicators comes from
:mod:`ghub4linux.core.rgb` (0x8070), and the two are combined: 0x1300 decides
how many bars are lit, 0x8070 decides what colour they are.  That is exactly how
Logitech's own software renders the battery gauge (bar count × colour).

The function map is not the obvious one — the first three functions are
``GetCount``/``GetInfo``/``GetSWControl``, *not* ``getInfo``/``getState``/
``getConfig``.  Writing the state is function 5, and it must be a **long**
report.  Verified against the G502 Lightspeed (046d:407f, feature index 0x08):

* ``fn0 GetCount`` answers ``03`` — three logical LEDs, numbered 0..2.
* ``fn1 GetInfo(i)`` returns ``[index, led_type, physical_count, modes(u16 BE),
  cfg_caps]``.  Types are 1 Battery, 2 Dpi, 3 Profile; each drives three physical
  LEDs.  The G502 advertises mode capability ``0x0003`` — **only Off and On**.
  Blink, travel, ramp, heartbeat and breathing are advertised by the feature but
  *not* by this device, and setting one is rejected with error 0x02.  So there
  is no hardware blink rate here; a flashing low-battery warning has to be
  driven from the host.
* ``fn2 GetSWControl`` / ``fn3 SetSWControl`` — the LEDs are firmware-owned
  until software claims them.  **A valid SetState is rejected with error 0x02
  while software control is not claimed**, which is the trap that makes a
  correct-looking write silently do nothing.
* ``fn4 GetState(i)`` returns ``[index, mode]`` with mode 1 = off, 2 = on.
* ``fn5 SetState`` — 9-byte payload ``[led, mode(u16 BE), display_index(u16 BE),
  4 payload bytes]``.  The mode is **big-endian**; little-endian is rejected.
  ``display_index`` must be 1..5 or 0xFF (0 and >=6 are rejected) and selects
  *which* step is displayed — for the DPI LED the five DPI slots, for the
  battery LED the number of bars.
"""

from __future__ import annotations

import logging

from .hid import HIDConnection

logger = logging.getLogger(__name__)

FEATURE_LED_CONTROL = 0x1300

# Logical LED indices as the device numbers them (GetInfo order).
LED_BATTERY = 0
LED_DPI = 1
LED_PROFILE = 2

LED_TYPE_NAMES: dict[int, str] = {
    0x01: "Battery",
    0x02: "DPI",
    0x03: "Profile",
    0x04: "Logo",
    0x05: "Cosmetic",
}

# Mode bitmask as advertised in GetInfo.  Only Off and On are supported by the
# G502 Lightspeed; the rest exist in the feature for other devices.
MODE_OFF = 0x0001
MODE_ON = 0x0002
MODE_BLINK = 0x0004
MODE_TRAVEL = 0x0008
MODE_RAMP_UP = 0x0010
MODE_RAMP_DOWN = 0x0020
MODE_HEARTBEAT = 0x0040
MODE_BREATHING = 0x0080

MODE_NAMES: dict[int, str] = {
    MODE_OFF: "Off",
    MODE_ON: "On",
    MODE_BLINK: "Blink",
    MODE_TRAVEL: "Travel",
    MODE_RAMP_UP: "Ramp up",
    MODE_RAMP_DOWN: "Ramp down",
    MODE_HEARTBEAT: "Heartbeat",
    MODE_BREATHING: "Breathing",
}

# Non-volatile configuration.
NV_ALWAYS_OFF = 0x01
NV_ALWAYS_ON = 0x02
NV_AUTO = 0x04

NV_NAMES: dict[int, str] = {
    NV_ALWAYS_OFF: "Always off",
    NV_ALWAYS_ON: "Always on",
    NV_AUTO: "Auto (firmware decides)",
}

# The display index the device accepts (1..5, or 0xFF for "everything").
DISPLAY_INDEX_MIN = 1
DISPLAY_INDEX_MAX = 5
DISPLAY_INDEX_ALL = 0xFF


class LedInfo:
    """One logical LED as reported by ``GetInfo``."""

    def __init__(self, index: int, led_type: int, physical: int, modes: int, nv_caps: int):
        """Store the decoded fields of one GetInfo reply."""
        self.index = index
        self.led_type = led_type
        self.physical = physical
        self.modes = modes
        self.nv_caps = nv_caps

    @property
    def name(self) -> str:
        """The LED's function, by name."""
        return LED_TYPE_NAMES.get(self.led_type, f"Unknown ({self.led_type})")

    @property
    def mode_names(self) -> list[str]:
        """Every mode this LED supports, by name."""
        return [name for bit, name in MODE_NAMES.items() if self.modes & bit]

    def supports(self, mode: int) -> bool:
        """True when this LED advertises *mode*."""
        return bool(self.modes & mode)

    def __repr__(self) -> str:
        """Debug representation."""
        return (
            f"<LedInfo {self.index} {self.name} physical={self.physical} "
            f"modes={'|'.join(self.mode_names) or 'none'} nv_caps=0x{self.nv_caps:02x}>"
        )


class LedState:
    """A logical LED's current state, from ``GetState``."""

    def __init__(self, index: int, mode: int):
        """Store the LED index and its reported mode."""
        self.index = index
        self.mode = mode

    @property
    def is_on(self) -> bool:
        """True when the device reports the LED as on."""
        return self.mode == 2

    @property
    def name(self) -> str:
        """The state, by name."""
        return {1: "Off", 2: "On"}.get(self.mode, f"Unknown ({self.mode})")

    def __repr__(self) -> str:
        """Debug representation."""
        return f"<LedState led={self.index} {self.name}>"


class LedControl:
    """Reader/writer for feature 0x1300 on one device connection."""

    def __init__(self, connection: HIDConnection, index: int):
        """Bind to an already-resolved feature index."""
        self._connection = connection
        self.index = index
        self._leds: list[LedInfo] = []

    # ── plumbing ─────────────────────────────────────────────────────────────
    def _call(self, function: int, args: bytes = b"") -> bytes | None:
        """Send one request; ``None`` means the device did not answer usefully.

        The report length follows from the payload: ``SetState`` sends nine
        bytes and therefore goes out as a long report on its own, while the
        one-byte getters stay short.

        An **empty** reply is treated as no reply, not as success.  The
        transport converts an error frame — which is how the device rejects an
        invalid argument — into ``b""``, and the earlier version only checked for
        ``None``, so a rejected write was reported as applied.
        """
        try:
            frame = self._connection.send_feature_request(self.index, function, args)
        except Exception as exc:  # noqa: BLE001 - transport-specific
            logger.debug(f"0x1300 fn{function} got no answer: {exc}")
            return None
        if not frame:
            logger.debug(f"0x1300 fn{function} was rejected or not answered")
            return None
        return frame

    # ── discovery ────────────────────────────────────────────────────────────
    def refresh(self) -> list[LedInfo]:
        """Enumerate the logical LEDs the device implements.

        ``GetInfo`` is the authority — the feature defines five LED types but a
        device answers only for the ones it has, and offering the others would
        put controls on screen that cannot work.
        """
        self._leds = []
        count_frame = self._call(0x00)
        if not count_frame or len(count_frame) < 5:
            return self._leds
        count = count_frame[4]

        for index in range(min(count, 8)):
            frame = self._call(0x01, bytes([index]))
            # Reply: [index, led_type, physical_count, modes(u16 BE), nv_caps]
            if not frame or len(frame) < 8:
                continue
            self._leds.append(
                LedInfo(
                    index=frame[4],
                    led_type=frame[5],
                    physical=frame[6],
                    modes=int.from_bytes(bytes(frame[7:9]), "big"),
                    nv_caps=frame[9] if len(frame) > 9 else 0,
                )
            )
        return self._leds

    @property
    def leds(self) -> list[LedInfo]:
        """The enumerated LEDs, refreshing first if nothing was read yet."""
        if not self._leds:
            self.refresh()
        return self._leds

    def led(self, index: int) -> LedInfo | None:
        """The LED with the given logical index, if present."""
        return next((led for led in self.leds if led.index == index), None)

    def supports(self, mode: int, index: int = LED_DPI) -> bool:
        """True when the given LED advertises *mode*."""
        led = self.led(index)
        return bool(led and led.supports(mode))

    # ── software control ─────────────────────────────────────────────────────
    def get_sw_control(self) -> bool | None:
        """Read who owns the LEDs: True software, False firmware, None no reply."""
        frame = self._call(0x02)
        if not frame or len(frame) < 5:
            return None
        return bool(frame[4])

    def set_sw_control(self, enabled: bool = True) -> bool:
        """Claim (or release) software control of the LEDs.

        Required before any SetState: with the firmware still owning them the
        device rejects an otherwise valid write with error 0x02.
        """
        frame = self._call(0x03, bytes([1 if enabled else 0]))
        if frame is None:
            return False
        return self.get_sw_control() is enabled

    # ── reading ──────────────────────────────────────────────────────────────
    def get_state(self, index: int) -> LedState | None:
        """Read one logical LED's current state.

        The mode is a **little-endian u16** at ``frame[5:7]``.  Verified from the
        device's own replies: LED0 answers ``00 01 00`` and LED1 ``01 02 00``,
        where only the little-endian reading yields a legal mode (0x0001 Off,
        0x0002 On) — reading big-endian gives 0x0100/0x0200, which are not modes
        at all.  ``frame[4]`` echoes the LED index and must not be read as the
        mode.  Note the asymmetry, which is in the hardware: the GetInfo
        capability mask *is* big-endian while this field is not.
        """
        frame = self._call(0x04, bytes([index]))
        if not frame or len(frame) < 7:
            return None
        return LedState(index=frame[4], mode=int.from_bytes(bytes(frame[5:7]), "little"))

    def get_nv_config(self, index: int) -> int | None:
        """Read one LED's non-volatile configuration byte."""
        frame = self._call(0x06, bytes([index]))
        if not frame or len(frame) < 6:
            return None
        return frame[5]

    # ── writing ──────────────────────────────────────────────────────────────
    def set_state(
        self, index: int, mode: int = MODE_ON, display_index: int = DISPLAY_INDEX_ALL
    ) -> bool:
        """Set one logical LED's state.

        *display_index* selects which step is shown — the number of bars for the
        battery LED, the DPI slot for the DPI LED — and must be 1..5 or 0xFF.

        On the mode field's byte order the sources disagree — one writes it
        little-endian (matching what the device reports back) and another
        big-endian — and this implementation sends **big-endian**, which is the
        variant that was measured to work: with the firmware owning the LEDs
        first, writing 0x0002 as ``00 02`` turned the DPI indicator from Off to
        On, confirmed by reading the state back.  The little-endian form has not
        been observed on this hardware either way, so this is an empirical
        choice and not a documented certainty.  If a write is ever rejected with
        error 0x02, swapping the two mode bytes is the first thing to try.
        """
        if not (DISPLAY_INDEX_MIN <= display_index <= DISPLAY_INDEX_MAX) and (
            display_index != DISPLAY_INDEX_ALL
        ):
            logger.warning(f"0x1300: display index {display_index} is out of range (1..5 or 0xff)")
            return False

        led = self.led(index)
        if led is not None and not led.supports(mode):
            logger.warning(
                f"0x1300: LED {index} ({led.name}) does not support mode 0x{mode:04x} "
                f"(supports {'|'.join(led.mode_names)})"
            )
            return False

        if self.get_sw_control() is not True and not self.set_sw_control(True):
            logger.warning("0x1300: could not claim software control")
            return False

        payload = (
            bytes([index]) + mode.to_bytes(2, "big") + display_index.to_bytes(2, "big") + bytes(4)
        )
        frame = self._call(0x05, payload)
        if frame is None:
            logger.warning(f"0x1300: LED {index} write got no acknowledgement")
            return False
        return True

    def set_on(self, index: int, display_index: int = DISPLAY_INDEX_ALL) -> bool:
        """Turn one indicator on."""
        return self.set_state(index, MODE_ON, display_index)

    def set_off(self, index: int) -> bool:
        """Turn one indicator off."""
        return self.set_state(index, MODE_OFF, DISPLAY_INDEX_ALL)

    def set_nv_config(self, index: int, config: int) -> bool:
        """Write one LED's non-volatile configuration."""
        if config not in NV_NAMES:
            logger.warning(f"0x1300: unknown NV config 0x{config:02x}")
            return False
        return self._call(0x07, bytes([index, config])) is not None

    # ── the battery gauge ────────────────────────────────────────────────────
    @staticmethod
    def battery_bars_for(percent: int | None) -> int | None:
        """How many bars the hardware shows for a charge level.

        Taken from Logitech's documented thresholds for this mouse: three bars
        from 50 %, two from 30 %, one from 15 %.  Below that the indicator is
        meant to flash red, which this hardware cannot do — the caller has to
        handle that case, so this returns 0 for it rather than pretending a
        steady single bar is the documented behaviour.
        """
        if percent is None:
            return None
        if percent >= 50:
            return 3
        if percent >= 30:
            return 2
        if percent >= 15:
            return 1
        return 0

    def show_battery(self, percent: int | None) -> bool:
        """Display a charge level on the battery indicator.

        Returns False when nothing was shown, including the under-15% case that
        needs a flashing warning this hardware cannot produce.
        """
        bars = self.battery_bars_for(percent)
        if bars is None:
            logger.info("0x1300: battery level unknown, leaving the indicator alone")
            return False
        if bars == 0:
            logger.info(
                f"0x1300: {percent}% needs a flashing red warning; this device only "
                f"supports on/off, so the indicator was left alone"
            )
            return False
        return self.set_state(LED_BATTERY, MODE_ON, bars)

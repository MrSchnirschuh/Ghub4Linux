"""Animation speed: the one place where a speed is converted into a period.

A UI naturally offers "speed" (higher is faster) while the wire wants a period
in milliseconds (higher is slower).  Passing the slider value through
unconverted inverted the control and crushed its range: a slider value of 100
became a 100 ms period and a value of 1 became 1 ms, so the *slowest* setting
produced a period so short it looked like a still image, and the fastest was
only just visible.

Everything that turns a speed into a period goes through here.
"""

from __future__ import annotations

import math

# Period range an animated effect may use, in milliseconds.  Kept inside the
# range the hardware accepts; the devices snap the value onto their own grid
# (the POWERPLAY pad advertises effectPeriod 1000 for Cycling and 60 for
# breathing), because the specification requires a multiple of that grid.
MIN_PERIOD_MS = 100
MAX_PERIOD_MS = 8000

# Speed (0-100) a fresh effect starts at: clearly visible without being frantic.
DEFAULT_SPEED = 50

# The largest period the hardware accepts in a 16-bit field.
_MAX_REPRESENTABLE_MS = 0xFFFF

# Accepted period range PER EFFECT, in milliseconds.  These are not the same for
# every effect, which is why a single global range was wrong.  Measured on the
# POWERPLAY pad (and the G502 Lightspeed behaves alike for Cycling):
#
#   Cycling (3):  below ~4000 ms the firmware ignores the period entirely and the
#                 LED sits on the last colour — which is why a slider value of
#                 100, passed through as a 100 ms period, produced a "cycling does
#                 not work" solid red.  At and above 4000 ms it animates, and a
#                 larger period yields a finer colour wheel (2 colours at 4000,
#                 23 at 48000).
#   Breathing (10): animates across the whole measured range (200-6000 ms), with
#                 the ramp rate following the period.
#   Legacy breathing (2), wave (4), ripple (11): not measurable on this hardware;
#                 kept to the documented 16-bit millisecond range.
#
# Anything not listed uses DEFAULT_PERIOD_RANGE.
DEFAULT_PERIOD_RANGE = (MIN_PERIOD_MS, MAX_PERIOD_MS)

EFFECT_PERIOD_RANGE: dict[int, tuple[int, int]] = {
    2: (100, 2000),  # Pulsing/Breathing (legacy): single speed byte
    3: (4000, 48000),  # Cycling
    4: (4000, 48000),  # Color Wave (same engine, same floor)
    10: (200, 6000),  # Pulsing/Breathing (Waveform)
    11: (4000, 48000),  # Ripple
}


def period_range_for(effect_id: int) -> tuple[int, int]:
    """Return the period range a given effect accepts."""
    return EFFECT_PERIOD_RANGE.get(effect_id, DEFAULT_PERIOD_RANGE)


def speed_for_effect(effect_id: int, speed: int) -> int:
    """Convert a UI speed into a period inside the given effect's own range."""
    lowest, highest = period_range_for(effect_id)
    return speed_to_period_ms(speed, lowest, highest)


def speed_to_period_ms(
    speed: int, lowest: int = MIN_PERIOD_MS, highest: int = MAX_PERIOD_MS
) -> int:
    """Convert a UI speed (0-100, higher is faster) into a period in milliseconds.

    The mapping is geometric rather than linear: perceived animation speed is
    multiplicative, so a linear ramp would squeeze the whole visible range into
    the top of the slider and spend the rest on periods too short to see.
    ``speed=100`` yields *lowest* (fastest), ``speed=0`` yields *highest*
    (slowest).
    """
    lowest = max(1, lowest)
    highest = max(lowest, min(highest, _MAX_REPRESENTABLE_MS))
    speed = max(0, min(100, speed))
    if speed >= 100:
        return lowest
    if speed <= 0:
        return highest
    ratio = highest / lowest
    period = highest / (ratio ** (speed / 100))
    return max(lowest, min(highest, int(round(period))))


def period_ms_to_speed(
    period_ms: int, lowest: int = MIN_PERIOD_MS, highest: int = MAX_PERIOD_MS
) -> int:
    """Inverse of :func:`speed_to_period_ms`, for displaying a stored value."""
    lowest = max(1, lowest)
    highest = max(lowest, min(highest, _MAX_REPRESENTABLE_MS))
    period = max(lowest, min(highest, period_ms))
    speed = 100 * math.log(highest / period) / math.log(highest / lowest)
    return max(0, min(100, int(round(speed))))

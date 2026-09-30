"""Speed is a UI value; the wire wants a period. The conversion lives here.

Two bugs came from skipping that conversion and from assuming one period range
for every effect:

* The slider value was passed through as a period, which inverted the control
  (higher "speed" meant a shorter period only because the numbers happened to
  line up) and crushed the range — the slowest setting produced a 1 ms period,
  i.e. a still image.
* Cycling on the POWERPLAY pad ignores any period below roughly 4000 ms and
  leaves the LED on the last colour. With a slider at 100, the app sent 100 ms,
  so "cycling" was a solid red LED. The effect's own accepted range has to be
  used, not a global one.
"""

import pytest

from ghub4linux.core.speed import (
    DEFAULT_PERIOD_RANGE,
    EFFECT_PERIOD_RANGE,
    MAX_PERIOD_MS,
    MIN_PERIOD_MS,
    period_ms_to_speed,
    period_range_for,
    speed_for_effect,
    speed_to_period_ms,
)


class TestDirection:
    def test_higher_speed_gives_a_shorter_period(self):
        """The whole point: more speed must mean faster, not slower."""
        assert speed_to_period_ms(100) < speed_to_period_ms(50) < speed_to_period_ms(0)

    def test_ends_of_the_slider(self):
        assert speed_to_period_ms(100) == MIN_PERIOD_MS
        assert speed_to_period_ms(0) == MAX_PERIOD_MS

    def test_monotonic_across_the_whole_range(self):
        """No flat or reversed stretch anywhere on the slider."""
        periods = [speed_to_period_ms(s) for s in range(0, 101)]
        assert all(later <= earlier for earlier, later in zip(periods, periods[1:], strict=False))

    def test_the_slowest_setting_is_not_a_still_image(self):
        """A 1 ms period looked static; the old slider produced exactly that."""
        assert speed_to_period_ms(0) >= 1000

    def test_out_of_range_speeds_are_clamped(self):
        assert speed_to_period_ms(-50) == MAX_PERIOD_MS
        assert speed_to_period_ms(500) == MIN_PERIOD_MS


class TestInverse:
    @pytest.mark.parametrize("speed", [0, 10, 25, 50, 75, 90, 100])
    def test_round_trips(self, speed):
        """Showing a stored value must not drift the slider."""
        assert period_ms_to_speed(speed_to_period_ms(speed)) == speed


class TestPerEffectRanges:
    def test_cycling_stays_above_the_floor_where_it_runs(self):
        """Below ~4000 ms the firmware ignores the period and the LED freezes."""
        lowest, _ = EFFECT_PERIOD_RANGE[3]
        assert lowest >= 4000
        for speed in range(0, 101):
            assert speed_for_effect(3, speed) >= 4000

    def test_breathing_keeps_its_own_wider_range(self):
        """Breathing animates from ~200 ms, so it must not be pushed to 4000."""
        assert speed_for_effect(10, 100) < 4000
        assert speed_for_effect(10, 100) >= 200

    def test_unknown_effect_falls_back_to_the_default(self):
        assert period_range_for(0x7FFF) == DEFAULT_PERIOD_RANGE

    def test_every_known_effect_has_a_sane_range(self):
        for effect_id, (lowest, highest) in EFFECT_PERIOD_RANGE.items():
            assert 0 < lowest < highest, f"effect {effect_id} has an unusable range"
            assert highest <= 0xFFFF, f"effect {effect_id} exceeds the 16-bit field"

    def test_speed_still_increases_within_an_effect_range(self):
        """The direction must hold inside each effect's own range too."""
        for effect_id in EFFECT_PERIOD_RANGE:
            slow = speed_for_effect(effect_id, 0)
            fast = speed_for_effect(effect_id, 100)
            assert fast <= slow, f"effect {effect_id} inverted the direction"
            assert fast == EFFECT_PERIOD_RANGE[effect_id][0]
            assert slow == EFFECT_PERIOD_RANGE[effect_id][1]

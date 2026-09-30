"""Wire-format tests for the colorLedEffects (0x8070) engine.

Every test here pins down a byte offset that was once read wrongly, and each of
those misreadings showed up as a feature that looked absent rather than broken:

* ``get_zone_info`` was parsed with the effect count at ``frame[6]``, which is
  the *low byte of the location*, so the POWERPLAY pad reported 2 effects
  instead of 4 and the UI offered only "static" and "off" while its real
  Cycling and Pulsing/Breathing effects were unreachable.
* effect IDs were compared one byte at a time, so FixedColor (``0x0001``) never
  matched.
* a write was confirmed by comparing the live colour, which cannot work for an
  animated effect whose colour is always moving.

The frames used below are the ones the hardware actually returns.
"""

import pytest

from ghub4linux.core.rgb import (
    ANIMATED_EFFECTS,
    COLOUR_FROM_HOST,
    EFFECT_IDS_BY_NAME,
    EFFECT_NAME_BY_ID,
    EFFECT_NAMES,
    ColorLedEffect,
    ColorLedEffects,
    ColorLedZone,
)


class FakeLedConnection:
    """Serves the 0x8070 replies of a POWERPLAY pad (1 zone, 4 effects)."""

    INDEX = 0x0B
    ZONE_INFO = bytes([0x00, 0x00, 0x02, 0x04, 0x00])
    EFFECTS = {
        0: (0x0000, 0x0000, 0),
        1: (0x0001, 0x0000, 0),
        2: (0x0003, 0xC005, 1000),
        3: (0x000A, 0xC105, 60),
    }

    def __init__(self):
        self.writes: list[tuple[int, int, bytes]] = []
        self.color = (0, 0, 0)
        # Frames the fake device refuses to answer, to exercise probing past a
        # device's effect count.
        self.silent_functions: set[tuple[int, int]] = set()

    def feature_index(self, feature_id: int) -> int:  # noqa: ARG002 - fake
        return self.INDEX

    def send_feature_request(self, index: int, function: int, params: bytes = b"") -> bytes:
        if (index, function) in self.silent_functions:
            raise TimeoutError("no answer from the fake device")
        self.writes.append((index, function, params))
        payload = b""
        if function == 0x00:
            payload = bytes([0x01, 0x00, 0x03, 0x00, 0x04])
        elif function == 0x01:
            payload = self.ZONE_INFO
        elif function == 0x02:
            effect_id, caps, period = self.EFFECTS.get(params[1], (0xFFFF, 0, 0))
            payload = bytes(
                [
                    0x00,
                    params[1],
                    effect_id >> 8,
                    effect_id & 0xFF,
                    caps >> 8,
                    caps & 0xFF,
                    period >> 8,
                    period & 0xFF,
                ]
            )
        elif function == 0x03:
            self.color = (params[2], params[3], params[4])
            payload = bytes([0x00, params[1]])
        elif function == 0x07:
            payload = bytes([0x01, 0x00])
        elif function == 0x08:
            payload = bytes([0x01, params[0]])
        elif function == 0x0C:
            payload = bytes([0x00, *self.color])
        return bytes([0x11, 0x07, index, function << 4]) + payload


@pytest.fixture
def engine():
    """An engine bound to the fake pad, already enumerated."""
    connection = FakeLedConnection()
    rgb = ColorLedEffects(connection, FakeLedConnection.INDEX)
    rgb.refresh()
    return rgb, connection


class TestZoneInfoParsing:
    def test_effect_count_comes_from_byte_7(self, engine):
        """The count sits one byte past the location's low byte.

        For the pad both happen to be plausible small numbers (2 vs 4), which is
        exactly why this went unnoticed: nothing looked broken, two effects just
        silently went missing.
        """
        rgb, _ = engine
        assert len(rgb.zones[0].effects) == 4

    def test_all_four_effect_ids_are_found(self, engine):
        rgb, _ = engine
        assert rgb.zones[0].effect_ids() == [0x0000, 0x0001, 0x0003, 0x000A]

    def test_location_is_a_big_endian_u16(self, engine):
        """0x0002 is Logo; read as one byte at the wrong offset it would be 0.

        A zero location falls through to "Zone 0" in the UI, which is how a
        mislabelled zone stays invisible.
        """
        rgb, _ = engine
        assert rgb.zones[0].location == 0x0002
        assert rgb.zones[0].location_name == "Logo"

    def test_effect_index_and_id_are_distinct(self, engine):
        """Cycling is effect ID 3 at zone index 2; the request carries the index."""
        rgb, _ = engine
        cycling = rgb.zones[0].effect(0x0003)
        assert cycling is not None
        assert cycling.index == 2
        assert cycling.effect_id == 0x0003

    def test_period_is_read_big_endian(self, engine):
        rgb, _ = engine
        assert rgb.zones[0].effect(0x0003).period == 1000
        assert rgb.zones[0].effect(0x000A).period == 60

    def test_capabilities_are_read_big_endian(self, engine):
        rgb, _ = engine
        assert rgb.zones[0].effect(0x0003).capabilities == 0xC005
        assert rgb.zones[0].effect(0x000A).capabilities == 0xC105

    def test_silence_past_the_effect_count_does_not_abort_discovery(self):
        """Probing beyond the count is normal; a non-reply must not stop it."""
        connection = FakeLedConnection()
        connection.silent_functions.add((FakeLedConnection.INDEX, 0x02))
        connection.EFFECTS = {}
        rgb = ColorLedEffects(connection, FakeLedConnection.INDEX)

        zones = rgb.refresh()
        # Every effect probe timed out, so no effects are claimed... but the zone
        # itself is still reported.
        assert len(zones) == 1
        assert zones[0].effects == []


class TestEffectNames:
    def test_effects_without_a_config_name_are_not_offered(self):
        """Boot Up and Demo Mode have no config equivalent and stay hidden."""
        zone = ColorLedZone(
            0,
            2,
            [ColorLedEffect(0, 0x0008, 0, 0), ColorLedEffect(1, 0x0009, 0, 0)],
        )
        assert zone.effect_names() == []

    def test_breathing_resolves_to_the_variant_the_device_has(self):
        """A device with only the legacy breathing effect still gets breathing."""
        legacy = ColorLedZone(0, 2, [ColorLedEffect(0, 0x0002, 0, 0)])
        assert legacy.effect_for_name("breathing").effect_id == 0x0002

        waveform = ColorLedZone(0, 2, [ColorLedEffect(0, 0x000A, 0xC105, 60)])
        assert waveform.effect_for_name("breathing").effect_id == 0x000A

    def test_a_name_the_device_lacks_resolves_to_nothing(self):
        zone = ColorLedZone(0, 2, [ColorLedEffect(0, 0x0001, 0, 0)])
        assert zone.effect_for_name("wave") is None

    def test_every_config_name_is_reachable(self):
        """Every offered name must map to an ID that exists in the engine."""
        for name, ids in EFFECT_IDS_BY_NAME.items():
            for effect_id in ids:
                assert effect_id in EFFECT_NAMES, f"{name} points at unknown {effect_id}"
                assert EFFECT_NAME_BY_ID[effect_id] == name


class TestCapabilities:
    def test_zero_capabilities_means_legacy_defaults(self):
        """0 is not "nothing supported" — older effects report no bits at all."""
        effect = ColorLedEffect(0, 0x0001, 0x0000, 0)
        assert effect.supports(0x8000) is True

    def test_reported_bits_are_respected(self):
        effect = ColorLedEffect(0, 0x000A, 0xC105, 60)
        assert effect.supports(0x8000) is True  # 16-bit period
        assert effect.supports(0x0008) is False  # sine not advertised here

    def test_animated_effects_are_flagged(self):
        assert ColorLedEffect(0, 0x0003, 0, 1000).animated is True
        assert ColorLedEffect(0, 0x0001, 0, 0).animated is False
        assert 0x000A in ANIMATED_EFFECTS


class TestWriting:
    def test_request_carries_the_zone_index(self, engine):
        rgb, connection = engine
        rgb.set_effect_by_name(0, "static", (0, 120, 255))

        write = next(p for _, fn, p in connection.writes if fn == 0x03)
        assert write[0] == 0x00  # zone
        assert write[1] == 1, "Fixed sits at zone index 1, not at its ID 0x0001"

    def test_software_control_is_claimed_before_writing(self, engine):
        rgb, connection = engine
        rgb.set_effect_by_name(0, "static", (0, 120, 255))

        functions = [fn for _, fn, _ in connection.writes]
        assert 0x08 in functions, "set_sw_control was never sent"
        assert functions.index(0x08) < functions.index(0x03)

    def test_fixed_colour_params_are_not_a_brightness(self, engine):
        """Byte 4 of Fixed is a ramp mode, so a brightness there is invalid."""
        rgb, connection = engine
        rgb.set_effect_by_name(0, "static", (10, 20, 30))

        write = next(p for _, fn, p in connection.writes if fn == 0x03)
        assert write[2:5] == bytes([10, 20, 30])
        assert write[5] == 0x00, "ramp mode must be a documented value, not a brightness"

    def test_breathing_sends_period_waveform_and_intensity(self, engine):
        """PulsingBreathingWaveform: p1-3 RGB, p4-5 period, p6 waveform, p7 intensity."""
        rgb, connection = engine
        rgb.set_effect_by_name(0, "breathing", (255, 0, 0), duration_ms=1000, intensity=80)

        write = next(p for _, fn, p in connection.writes if fn == 0x03)
        assert write[1] == 3, "waveform breathing is at zone index 3"
        assert write[2:5] == bytes([255, 0, 0])
        # The period is snapped onto the device's 60 ms grid (17 x 60 = 1020),
        # which is what the spec requires; sending 1000 unmodified would be
        # rejected by the firmware.
        assert (write[5] << 8) | write[6] == 1020
        assert write[7] == 1  # sine
        assert write[8] == 80  # intensity

    def test_period_is_snapped_onto_the_devices_grid(self, engine):
        """The spec requires a multiple of the effect's advertised period."""
        rgb, connection = engine
        rgb.set_effect_by_name(0, "breathing", (255, 0, 0), duration_ms=5000)

        write = next(p for _, fn, p in connection.writes if fn == 0x03)
        period = (write[5] << 8) | write[6]
        assert period % 60 == 0, f"{period} is not a multiple of the pad's 60 ms grid"

    def test_effect_the_device_lacks_is_refused_without_a_write(self, engine):
        rgb, connection = engine
        before = len(connection.writes)
        assert rgb.set_effect_by_name(0, "wave", (255, 0, 0)) is False
        assert len(connection.writes) == before, "a refused effect must not be sent"

    def test_write_that_does_not_change_the_led_reports_failure(self, engine):
        """An acknowledged write that changed nothing is a failure, not a success."""
        rgb, connection = engine
        connection.color = (7, 7, 7)

        # Ask for a colour the fake device will not adopt.
        connection.send_feature_request = _stubborn(connection)
        assert rgb.set_effect_by_name(0, "static", (0, 120, 255)) is False

    def test_animated_effect_is_confirmed_by_movement_not_equality(self, engine):
        """A moving colour can never equal a fixed target."""
        rgb, connection = engine
        readings = iter([(0, 1, 0), (0, 2, 0), (0, 3, 0)])

        def colour_moves(index: int, function: int, params: bytes = b"") -> bytes:
            if function == 0x0C:
                return bytes([0x11, 0x07, index, 0xC0, 0x00, *next(readings)])
            return FakeLedConnection.send_feature_request(connection, index, function, params)

        connection.send_feature_request = colour_moves
        assert rgb.set_effect_by_name(0, "breathing", (0, 255, 0)) is True

    def test_off_means_dark(self, engine):
        """Off is confirmed by the LED being dark, not by matching a colour."""
        rgb, connection = engine
        connection.color = (0, 255, 0)
        assert rgb.set_off(0) is True
        assert connection.color == (0, 0, 0)

    def test_off_is_not_confirmed_while_the_led_stays_lit(self, engine):
        """`all(...)` on the samples, not `any(...)`: (0, 0, 0) is a truthy tuple."""
        rgb, connection = engine
        connection.color = (200, 0, 0)
        connection.send_feature_request = _stubborn(connection, keep_lit=(200, 0, 0))
        assert rgb.set_off(0) is False

    def test_zones_are_reported_for_the_ui(self, engine):
        rgb, _ = engine
        assert rgb.supported_effect_names() == ["off", "static", "cycle", "breathing"]


def _stubborn(connection: FakeLedConnection, keep_lit: tuple[int, int, int] | None = None):
    """A connection that acknowledges writes but never changes the LED."""
    fixed = keep_lit or connection.color

    def call(index: int, function: int, params: bytes = b"") -> bytes:
        if function in (0x03, 0x08):
            connection.writes.append((index, function, params))
            return bytes([0x11, 0x07, index, function << 4, 0x00])
        if function == 0x0C:
            return bytes([0x11, 0x07, index, 0xC0, 0x00, *fixed])
        return FakeLedConnection.send_feature_request(connection, index, function, params)

    return call


class TestWhichEffectsTakeAColour:
    """Cycling ignores the colour, so the UI must not offer one for it.

    Measured on a POWERPLAY pad: setting the zone to white and then starting
    Cycling produces a rainbow, and writing a colour into any of Cycling's
    parameter positions changes nothing — parameter 0 alone decides *whether* the
    effect animates.  Breathing and Fixed do take the colour (verified by reading
    the animated greyscale ramp back).  Offering a colour picker for Cycling
    would promise something the hardware cannot do.
    """

    def test_cycling_does_not_take_a_colour(self):
        assert ColorLedEffect(2, 0x0003, 0xC005, 1000).takes_colour is False

    def test_fixed_takes_a_colour(self):
        assert ColorLedEffect(1, 0x0001, 0x0000, 0).takes_colour is True

    def test_breathing_takes_a_colour(self):
        assert ColorLedEffect(3, 0x000A, 0xC105, 60).takes_colour is True

    def test_wave_and_ripple_take_a_colour(self):
        assert ColorLedEffect(0, 0x0004, 0, 0).takes_colour is True
        assert ColorLedEffect(0, 0x000B, 0, 0).takes_colour is True

    def test_disabled_needs_no_colour(self):
        """Nothing is shown, so the picker is meaningless."""
        assert ColorLedEffect(0, 0x0000, 0, 0).takes_colour is False

    def test_the_cycling_variants_with_saturation_also_do_not(self):
        """0x15 is the same firmware sequence with extra parameters."""
        assert 0x0015 not in COLOUR_FROM_HOST

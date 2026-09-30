"""OnboardProfiles 0x8100 — reading and writing a mouse's button assignments.

The layouts here are the ones the mature implementations use and that were
verified against a G502 Lightspeed, and several of them are easy to get wrong in
ways that still look plausible:

* ``getInfo``'s payload is memory_model, profile_format, macro_format,
  profile_count, oob, button_count, sector_count, sector_size(u16 BE),
  mechanical_layout.  Reading button_count from the wrong byte yields 16 on a
  device that has 11, and reading the sector size as one byte yields 267 instead
  of 255 — both of which were observed before the order was pinned down.
* A sector is read 16 bytes at a time, and the **last chunk must be requested at
  ``size - 16``** with its leading bytes discarded; reading straight up to the
  sector end walks past it.
* The CRC is CRC-16/CCITT-FALSE stored big-endian over everything before it.
  Reproducing the device's own stored value is the cheapest proof that the
  layout is right.
* The command space is 8-bit (0x00, 0x10 … 0xC0), so these commands are also a
  regression test for the transport's byte-3 packing.
"""

import pytest

from ghub4linux.core.onboard import (
    BEHAVIOR_FUNCTION,
    BEHAVIOR_SEND,
    BUTTON_ENTRY_SIZE,
    CMD_GET_INFO,
    OFFSET_GSHIFT_BUTTONS,
    OFFSET_PRIMARY_BUTTONS,
    TYPE_BUTTON,
    TYPE_MODIFIER_AND_KEY,
    ButtonEntry,
    OnboardProfiles,
    ProfileSector,
    crc16_ccitt,
)


class TestCrc:
    def test_matches_the_ccitt_false_reference_vector(self):
        """The standard check value for CRC-16/CCITT-FALSE."""
        assert crc16_ccitt(b"123456789") == 0x29B1

    def test_empty_input_gives_the_initial_value(self):
        assert crc16_ccitt(b"") == 0xFFFF

    def test_is_order_sensitive(self):
        assert crc16_ccitt(b"ab") != crc16_ccitt(b"ba")

    def test_is_deterministic(self):
        data = bytes(range(256)) * 3
        assert crc16_ccitt(data) == crc16_ccitt(data)

    def test_fits_in_sixteen_bits(self):
        for length in (1, 7, 64, 253):
            assert 0 <= crc16_ccitt(bytes(range(length % 256))) <= 0xFFFF


class TestButtonEntry:
    def test_a_disabled_entry_reads_as_unassigned(self):
        entry = ButtonEntry(bytes([0xFF, 0xFF, 0xFF, 0xFF]))
        assert entry.behavior == 0xF
        assert entry.is_disabled
        assert entry.description == "Unassigned"

    def test_the_behavior_comes_from_the_high_nibble(self):
        assert ButtonEntry(bytes([0x80, 0x01, 0x00, 0x04])).behavior == BEHAVIOR_SEND
        assert ButtonEntry(bytes([0x90, 0x0B, 0x00, 0x00])).behavior == BEHAVIOR_FUNCTION
        assert ButtonEntry(bytes([0x00, 0x01, 0x00, 0x20])).behavior == 0x0

    def test_a_mouse_button_entry_is_described(self):
        """``8001 0004`` is the middle click the device stores for g3."""
        entry = ButtonEntry(bytes([0x80, 0x01, 0x00, 0x04]))
        assert entry.entry_type == TYPE_BUTTON
        assert "Mouse button 4" in entry.description

    def test_a_keyboard_entry_reports_its_modifiers(self):
        """The modifier byte is a combination value, not independent flags."""
        entry = ButtonEntry(bytes([0x80, 0x02, 0x04, 0x26]))
        assert entry.entry_type == TYPE_MODIFIER_AND_KEY
        assert "Alt" in entry.description

    def test_a_combination_is_named_whole(self):
        """0x06 is Alt+Shift, which reading it as flags would misspell."""
        assert "Alt+Shift" in ButtonEntry.key(0x06, 0x26).description

    def test_no_modifier_leaves_only_the_key(self):
        """The value the device actually stores for the DPI-shift binding."""
        assert ButtonEntry.key(0x00, 0x26).description == "key 0x26"

    def test_helper_constructors_produce_usable_entries(self):
        assert ButtonEntry.mouse_button(4).description == "Mouse button 4"
        assert "0x26" in ButtonEntry.key(0x04, 0x26).description

    def test_a_special_entry_uses_its_name(self):
        assert ButtonEntry.special(0x05).description == "Cycle DPI"

    def test_an_unknown_special_is_not_invented(self):
        assert "0x99" in ButtonEntry.special(0x99).description

    def test_an_entry_must_be_four_bytes(self):
        with pytest.raises(ValueError):
            ButtonEntry(b"\x00\x01")

    def test_factory_helpers_round_trip(self):
        assert ButtonEntry.disabled().is_disabled
        assert ButtonEntry.special(0x03).description == "Next DPI"


class TestProfileLayout:
    def make_sector(self, button_count=11):
        """A sector with recognisable values in the fields that matter."""
        raw = bytearray(255)
        raw[0] = 0x08  # report rate
        raw[1] = 0x02  # default DPI index
        raw[2] = 0x04  # shift DPI index
        for i, dpi in enumerate((800, 1200, 1600, 2400, 3200)):
            raw[3 + i * 2 : 5 + i * 2] = dpi.to_bytes(2, "little")
        raw[13:16] = bytes([0x11, 0x22, 0x33])
        raw[18:20] = (7).to_bytes(2, "little")
        raw[160:164] = "Test".encode("utf-16-le")
        for i in range(button_count):
            start = OFFSET_PRIMARY_BUTTONS + i * BUTTON_ENTRY_SIZE
            raw[start : start + 4] = bytes([0x90, i, 0x00, 0x00])
        sector = ProfileSector(bytes(raw), button_count)
        sector.refresh_crc()
        return sector

    def test_dpi_values_are_little_endian(self):
        assert self.make_sector().dpi_values == [800, 1200, 1600, 2400, 3200]

    def test_the_name_is_utf16(self):
        assert self.make_sector().name == "Test"

    def test_buttons_are_read_from_offset_32(self):
        """The primary table starts at 32, not at the top of the sector."""
        buttons = self.make_sector().buttons()
        assert OFFSET_PRIMARY_BUTTONS == 32
        assert len(buttons) == 11
        assert buttons[0].description == "No action"

    def test_gshift_buttons_are_read_from_offset_96(self):
        sector = self.make_sector()
        for i in range(11):
            start = OFFSET_GSHIFT_BUTTONS + i * BUTTON_ENTRY_SIZE
            sector.raw[start : start + 4] = bytes([0x90, 0x0B, 0x00, 0x00])
        assert all(b.description == "G-Shift" for b in sector.buttons(gshift=True))

    def test_only_the_reported_number_of_buttons_is_used(self):
        assert len(self.make_sector(button_count=5).buttons()) == 5

    def test_a_button_can_be_replaced(self):
        sector = self.make_sector()
        sector.set_button(0, ButtonEntry.special(0x05))
        assert sector.buttons()[0].description == "Cycle DPI"

    def test_writing_outside_the_button_range_is_refused(self):
        with pytest.raises(IndexError):
            self.make_sector(button_count=5).set_button(5, ButtonEntry.disabled())

    def test_the_crc_covers_everything_before_it(self):
        sector = self.make_sector()
        assert sector.crc_is_valid

    def test_a_changed_sector_needs_its_crc_refreshed(self):
        """The device would reject a stale checksum, so this must be caught."""
        sector = self.make_sector()
        sector.raw[0] ^= 0xFF
        assert not sector.crc_is_valid
        sector.refresh_crc()
        assert sector.crc_is_valid

    def test_the_crc_is_the_last_two_bytes_big_endian(self):
        sector = self.make_sector()
        assert int.from_bytes(sector.raw[-2:], "big") == sector.stored_crc


class FakeConnection:
    """Serves a synthetic sector and records every command."""

    def __init__(self, size=255):
        """Build a sector with a known pattern."""
        self.size = size
        self.sector = bytearray(size)
        self.sector[0] = 0x08
        self.calls: list[tuple[int, bytes, float | None]] = []

    def send_feature_request(
        self, index: int, command: int, params: bytes = b"", timeout: float | None = None
    ) -> bytes:
        """Answer info, mode and sector reads."""
        self.calls.append((command, params, timeout))
        head = [0x11, 0x01, index, command & 0xF0 | 1]
        if command == CMD_GET_INFO:
            # memory, profile_format, macro_format, count, oob, buttons,
            # sectors, size(u16 BE), mechanical layout
            payload = [0x01, 0x03, 0x00, 0x01, 0x00, 0x0B, 0x10, 0x00, 0xFF, 0x0A]
            return bytes(head + payload + [0x00])
        if command == 0x20:  # getOnboardMode
            return bytes(head + [0x01])
        if command == 0x40:  # getCurrentProfile
            return bytes(head + [0x00])
        if command == 0x50:  # readSector
            offset = int.from_bytes(params[2:4], "big")
            chunk = self.sector[offset : offset + 16].ljust(16, b"\x00")
            return bytes(head + list(chunk))
        return bytes(head + [0x00])


class TestInfoParsing:
    def test_the_geometry_fields_are_read_from_the_right_bytes(self):
        """The off-by-one that reported 16 buttons and a 267-byte sector."""
        profiles = OnboardProfiles(FakeConnection(), 0x09)
        assert profiles.sector_size == 255
        assert profiles.button_count == 11
        assert profiles.sector_count == 16
        assert profiles.profile_count == 1
        assert profiles.memory_model == 1
        assert profiles.profile_format == 3

    def test_gshift_table_is_only_claimed_when_advertised(self):
        """mechanical_layout 0x0A has bits 1|3 set, so G-Shift exists."""
        assert OnboardProfiles(FakeConnection(), 0x09).gshift_count == 11

    def test_a_device_without_gshift_reports_none(self):
        connection = FakeConnection()
        original = connection.send_feature_request

        def patched(index, command, params=b"", timeout=None):
            """Clear the shift bits in the mechanical layout byte."""
            frame = bytearray(original(index, command, params, timeout))
            if command == CMD_GET_INFO:
                frame[13] = 0x00
            return bytes(frame)

        connection.send_feature_request = patched
        assert OnboardProfiles(connection, 0x09).gshift_count == 0


class TestSectorRead:
    def test_a_whole_sector_is_read_with_the_right_length(self):
        profiles = OnboardProfiles(FakeConnection(), 0x09)
        sector = profiles.read_sector(1)
        assert sector is not None
        assert len(sector) == 255

    def test_the_tail_is_not_read_past_the_end(self):
        """The last chunk is fetched at size-16, not at the sector end."""
        connection = FakeConnection()
        profiles = OnboardProfiles(connection, 0x09)
        profiles.read_sector(1)
        offsets = [int.from_bytes(p[2:4], "big") for c, p, _ in connection.calls if c == 0x50]
        assert max(offsets) == 255 - 16

    def test_reads_use_chunks_of_sixteen(self):
        connection = FakeConnection()
        OnboardProfiles(connection, 0x09).read_sector(1)
        offsets = [int.from_bytes(p[2:4], "big") for c, p, _ in connection.calls if c == 0x50]
        assert offsets[0] == 0
        # Whole chunks come first and are 16-aligned; the tail chunk is
        # deliberately requested at size-16 so it never reads past the sector,
        # which makes the final offset unaligned whenever the size is not a
        # multiple of 16 (255 gives 239).
        assert all(o % 16 == 0 for o in offsets[:-1])
        assert offsets[-1] == 255 - 16

    def test_a_slow_sector_command_gets_a_longer_timeout(self):
        """The info command answers instantly; sector reads take seconds."""
        connection = FakeConnection()
        OnboardProfiles(connection, 0x09).read_sector(1)
        timeouts = {c: t for c, _p, t in connection.calls}
        assert timeouts[CMD_GET_INFO] is None
        assert timeouts[0x50] is not None
        assert timeouts[0x50] > 1.0

    def test_a_profile_is_decoded_from_the_sector(self):
        connection = FakeConnection()
        connection.sector[0:4] = bytes([0x08, 0x02, 0x04, 0x20])
        connection.sector[OFFSET_PRIMARY_BUTTONS : OFFSET_PRIMARY_BUTTONS + 4] = bytes(
            [0x90, 0x05, 0x00, 0x00]
        )
        profiles = OnboardProfiles(connection, 0x09)
        profile = profiles.read_profile(1)
        assert profile is not None
        assert profile.buttons()[0].description == "Cycle DPI"


class TestNoAnswers:
    def test_a_silent_device_yields_no_sector(self):
        class Silent(FakeConnection):
            def send_feature_request(self, *_args, **_kwargs):
                return b""

        assert OnboardProfiles(Silent(), 0x09).read_sector(1) is None

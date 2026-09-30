"""HID++ OnboardProfiles (0x8100) — read and write a onboard profile sector.

This is how a G-series mouse stores its button assignments.  On the two devices
here it is the *only* way to reach the buttons: neither exposes
ReprogrammableControls (0x1B04), so the usual "divert the button and assign it
from the host" trick is unavailable, and the assignment has to be written into
the profile sector the mouse itself uses.

Verified byte-exactly on a G502 Lightspeed (046d:407f, feature index 0x09) and a
PRO X 2 DEX (046d:40b8, index 0x0d) — a full sector was read, modified with a
known pattern, written, read back byte-identical, and restored.

Feature notes that cost time to find:

* The command space is **8-bit** (0x00, 0x10 … 0xC0), not the nibble numbering
  other features use, which is why the transport's byte-3 packing had to learn
  both shapes before this feature could be addressed at all.
* ``0x30`` is the **setter** and ``0x40`` the getter.  libratbag and Solaar
  document these the other way round; the live replies settle it, since ``0x40``
  with no arguments returns an index while ``0x30`` takes one.
* A sector read is 16 bytes at a time.  The last chunk has to be requested at
  ``size - 16`` and its leading bytes discarded, or the tail is unreadable.
  Reads also time out now and then and need a retry.
* The CRC is CRC-16/CCITT-FALSE stored big-endian over everything before it; it
  was reproduced against the device's own stored value.
"""

from __future__ import annotations

import logging

from .hid import HIDConnection

logger = logging.getLogger(__name__)

FEATURE_ONBOARD_PROFILES = 0x8100

CMD_GET_INFO = 0x00
CMD_SET_ONBOARD_MODE = 0x10
CMD_GET_ONBOARD_MODE = 0x20
CMD_SET_CURRENT_PROFILE = 0x30
CMD_GET_CURRENT_PROFILE = 0x40
CMD_READ_SECTOR = 0x50
CMD_WRITE_START = 0x60
CMD_WRITE_DATA = 0x70
CMD_WRITE_END = 0x80
CMD_GET_DPI_INDEX = 0xB0
CMD_SET_DPI_INDEX = 0xC0

CHUNK = 16

# Where a profile sector keeps things.  Offsets are into the 255-byte sector.
OFFSET_REPORT_RATE = 0
OFFSET_DEFAULT_DPI_INDEX = 1
OFFSET_SHIFT_DPI_INDEX = 2
OFFSET_DPI_VALUES = 3
OFFSET_COLOR = 13
OFFSET_POWER_MODE = 16
OFFSET_ANGLE_SNAP = 17
OFFSET_WRITE_COUNT = 18
OFFSET_PS_TIMEOUT = 28
OFFSET_PO_TIMEOUT = 30
OFFSET_PRIMARY_BUTTONS = 32
OFFSET_GSHIFT_BUTTONS = 96
OFFSET_NAME = 160
OFFSET_LIGHTING = 208
BUTTON_ENTRY_SIZE = 4
NAME_LENGTH = 24

# A button entry is 4 bytes.  The HIGH NIBBLE of the first byte is the
# behaviour, and for SEND entries the TYPE lives in byte 1 — reading the type
# from the low nibble of byte 0 (as a first attempt did) reports every entry as
# "no action", because that nibble carries macro sector bits or is unused.
BEHAVIOR_MACRO = 0x0
BEHAVIOR_MACRO_STOP = 0x1
BEHAVIOR_SEND = 0x8
BEHAVIOR_FUNCTION = 0x9
BEHAVIOR_DISABLED = 0xF

BEHAVIOR_NAMES: dict[int, str] = {
    BEHAVIOR_MACRO: "Macro",
    BEHAVIOR_MACRO_STOP: "Macro stop",
    BEHAVIOR_SEND: "Send",
    BEHAVIOR_FUNCTION: "Function",
    BEHAVIOR_DISABLED: "Unassigned",
}

# Types of a SEND entry (byte 1).
TYPE_NO_ACTION = 0x00
TYPE_BUTTON = 0x01
TYPE_MODIFIER_AND_KEY = 0x02
TYPE_CONSUMER_KEY = 0x03

TYPE_NAMES: dict[int, str] = {
    TYPE_NO_ACTION: "No action",
    TYPE_BUTTON: "Mouse button",
    TYPE_MODIFIER_AND_KEY: "Key",
    TYPE_CONSUMER_KEY: "Consumer key",
}

DISABLED_ENTRY = b"\xff\xff\xff\xff"

# Keyboard modifier bits, in the second byte of a keyboard entry.  These are a
# combined value rather than independent flags: the device stores a single
# combination (0x06 is Alt+Shift, not "Alt or Shift"), so the byte is looked up
# instead of being tested bit by bit.
MODIFIER_COMBINATIONS: dict[int, str] = {
    0x00: "",
    0x01: "Ctrl",
    0x02: "Shift",
    0x03: "Ctrl+Shift",
    0x04: "Alt",
    0x05: "Ctrl+Alt",
    0x06: "Alt+Shift",
    0x08: "Meta",
    0x09: "Meta+Ctrl",
    0x0A: "Meta+Shift",
    0x0C: "Meta+Alt",
}

# The three left/right variants are separate bits in the extended set.
MODIFIER_EXTRA_NAMES: dict[int, str] = {
    0x10: "RCtrl",
    0x20: "RShift",
    0x40: "RAlt",
    0x80: "RMeta",
}

# Internal specials.  Codes above 0x0B are documented for memory model >= 3;
# both devices here are memory model 1, so they are not offered.
SPECIAL_NAMES: dict[int, str] = {
    0x00: "No action",
    0x01: "Tilt left",
    0x02: "Tilt right",
    0x03: "Next DPI",
    0x04: "Previous DPI",
    0x05: "Cycle DPI",
    0x06: "Default DPI",
    0x07: "DPI shift",
    0x08: "Next profile",
    0x09: "Previous profile",
    0x0A: "Cycle profile",
    0x0B: "G-Shift",
}


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection).

    This reproduces the checksum the devices themselves store, so a write can be
    validated before it is sent.
    """
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


class ButtonEntry:
    """One 4-byte button assignment."""

    def __init__(self, raw: bytes):
        """Decode a 4-byte entry."""
        if len(raw) != BUTTON_ENTRY_SIZE:
            raise ValueError(f"a button entry is {BUTTON_ENTRY_SIZE} bytes, got {len(raw)}")
        self.raw = bytes(raw)

    @property
    def behavior(self) -> int:
        """What kind of assignment this is, from the high nibble of byte 0."""
        return self.raw[0] >> 4

    @property
    def entry_type(self) -> int:
        """The type of a SEND entry (byte 1); meaningless for other behaviours."""
        return self.raw[1]

    @property
    def is_disabled(self) -> bool:
        """True when the button is unassigned."""
        return self.raw == DISABLED_ENTRY or self.behavior == BEHAVIOR_DISABLED

    @property
    def description(self) -> str:
        """A human description of what this button does."""
        if self.is_disabled:
            return "Unassigned"
        if self.behavior == BEHAVIOR_SEND:
            if self.entry_type == TYPE_BUTTON:
                return f"Mouse button {int.from_bytes(self.raw[2:4], 'big')}"
            if self.entry_type == TYPE_MODIFIER_AND_KEY:
                modifiers = MODIFIER_COMBINATIONS.get(self.raw[2], f"mods 0x{self.raw[2]:02x}")
                extra = [name for bit, name in MODIFIER_EXTRA_NAMES.items() if self.raw[2] & bit]
                key = f"key 0x{self.raw[3]:02x}"
                parts = [p for p in (modifiers, *extra, key) if p]
                return "+".join(parts) if len(parts) > 1 else key
            if self.entry_type == TYPE_CONSUMER_KEY:
                return f"Consumer 0x{int.from_bytes(self.raw[2:4], 'big'):04x}"
            if self.entry_type == TYPE_NO_ACTION:
                return "No action"
            return f"Send type 0x{self.entry_type:02x}"
        if self.behavior == BEHAVIOR_FUNCTION:
            return SPECIAL_NAMES.get(self.raw[1], f"Function 0x{self.raw[1]:02x}")
        if self.behavior in (BEHAVIOR_MACRO, BEHAVIOR_MACRO_STOP):
            sector = ((self.raw[0] & 0x0F) << 8) + self.raw[1]
            address = int.from_bytes(self.raw[2:4], "big")
            return f"Macro sector {sector} address {address}"
        return f"Unknown ({self.raw.hex(' ')})"

    @staticmethod
    def disabled() -> ButtonEntry:
        """An unassigned entry."""
        return ButtonEntry(DISABLED_ENTRY)

    @staticmethod
    def special(code: int) -> ButtonEntry:
        """A device-internal function such as "Cycle DPI" (behaviour 0x9)."""
        return ButtonEntry(bytes([BEHAVIOR_FUNCTION << 4, code, 0x00, 0x00]))

    @staticmethod
    def mouse_button(number: int) -> ButtonEntry:
        """Assign a mouse button (behaviour SEND, type BUTTON)."""
        return ButtonEntry(bytes([BEHAVIOR_SEND << 4, TYPE_BUTTON]) + number.to_bytes(2, "big"))

    @staticmethod
    def key(modifiers: int, usage: int) -> ButtonEntry:
        """Assign a keystroke (behaviour SEND, type MODIFIER_AND_KEY)."""
        return ButtonEntry(bytes([BEHAVIOR_SEND << 4, TYPE_MODIFIER_AND_KEY, modifiers, usage]))

    def __repr__(self) -> str:
        """Debug representation."""
        return f"<ButtonEntry {self.raw.hex(' ')} {self.description}>"


class ProfileSector:
    """A decoded onboard profile sector."""

    def __init__(self, raw: bytes, button_count: int):
        """Keep the raw bytes and remember how many buttons the device has."""
        self.raw = bytearray(raw)
        self.button_count = button_count

    @property
    def name(self) -> str:
        """The profile's name, as stored (UTF-16LE)."""
        chunk = bytes(self.raw[OFFSET_NAME : OFFSET_NAME + NAME_LENGTH * 2])
        return chunk.decode("utf-16-le", errors="replace").rstrip("\x00").strip()

    @property
    def stored_crc(self) -> int:
        """The CRC the sector currently carries."""
        return int.from_bytes(self.raw[-2:], "big")

    @property
    def computed_crc(self) -> int:
        """The CRC the sector's contents produce."""
        return crc16_ccitt(bytes(self.raw[:-2]))

    @property
    def crc_is_valid(self) -> bool:
        """True when the stored checksum matches the contents."""
        return self.stored_crc == self.computed_crc

    def buttons(self, gshift: bool = False) -> list[ButtonEntry]:
        """The button assignments, primary or G-Shift."""
        start = OFFSET_GSHIFT_BUTTONS if gshift else OFFSET_PRIMARY_BUTTONS
        return [
            ButtonEntry(
                bytes(self.raw[start + i * BUTTON_ENTRY_SIZE : start + (i + 1) * BUTTON_ENTRY_SIZE])
            )
            for i in range(self.button_count)
        ]

    def set_button(self, index: int, entry: ButtonEntry, gshift: bool = False) -> None:
        """Replace one button assignment."""
        if not 0 <= index < self.button_count:
            raise IndexError(f"button {index} is outside 0..{self.button_count - 1}")
        start = OFFSET_GSHIFT_BUTTONS if gshift else OFFSET_PRIMARY_BUTTONS
        offset = start + index * BUTTON_ENTRY_SIZE
        self.raw[offset : offset + BUTTON_ENTRY_SIZE] = entry.raw

    @property
    def dpi_values(self) -> list[int]:
        """The stored DPI steps (little-endian u16)."""
        return [
            int.from_bytes(
                self.raw[OFFSET_DPI_VALUES + i * 2 : OFFSET_DPI_VALUES + i * 2 + 2], "little"
            )
            for i in range(5)
        ]

    def refresh_crc(self) -> None:
        """Recompute the checksum after a modification."""
        self.raw[-2:] = crc16_ccitt(bytes(self.raw[:-2])).to_bytes(2, "big")


class OnboardProfiles:
    """Reader/writer for feature 0x8100 on one device connection."""

    def __init__(self, connection: HIDConnection, index: int):
        """Bind to an already-resolved feature index."""
        self._connection = connection
        self.index = index
        self.sector_size = 0
        self.sector_count = 0
        self.profile_count = 0
        self.profile_format = 0
        self.macro_format = 0
        self.oob = 0
        self.button_count = 0
        self.gshift_count = 0
        self.memory_model = 0
        self.mechanical_layout = 0
        self._read_info()

    #: Sector commands are answered in seconds, not milliseconds.  The info
    #: command replies instantly, which is why the default timeout made every
    #: other command look as if the feature did not support it.
    SECTOR_TIMEOUT = 4.0

    #: Commands that touch the onboard storage.
    SLOW_COMMANDS = frozenset(
        {
            CMD_GET_ONBOARD_MODE,
            CMD_SET_ONBOARD_MODE,
            CMD_GET_CURRENT_PROFILE,
            CMD_SET_CURRENT_PROFILE,
            CMD_READ_SECTOR,
            CMD_WRITE_START,
            CMD_WRITE_DATA,
            CMD_WRITE_END,
            CMD_GET_DPI_INDEX,
            CMD_SET_DPI_INDEX,
        }
    )

    def _call(self, command: int, args: bytes = b"") -> bytes | None:
        """Send one onboard-profiles command."""
        timeout = self.SECTOR_TIMEOUT if command in self.SLOW_COMMANDS else None
        try:
            return self._connection.send_feature_request(self.index, command, args, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - transport-specific
            logger.debug(f"0x8100 cmd 0x{command:02x} got no answer: {exc}")
            return None

    def _read_info(self) -> None:
        """Read the feature's geometry.

        ``getInfo`` answers ``[memory_model, profile_format, profile_count,
        sector_count, sector_size(u16 BE), mechanical_layout, …]``.  Reading the
        sector size as a single byte gives nonsense, which is why it is taken as
        a big-endian pair.
        """
        # Payload, measured on a G502 Lightspeed:
        #   01 03 01 05 01 0b 10 00 ff 0a
        # The order is memory_model, profile_format, macro_format,
        # profile_count, oob, button_count, sector_count, sector_size(u16 BE),
        # mechanical_layout.  Reading button_count from the wrong byte (or the
        # sector size as a single byte) is what made the earlier attempt see 16
        # buttons and a 267-byte sector on a device that has 11 and 255.
        frame = self._call(CMD_GET_INFO)
        if not frame or len(frame) < 13:
            return
        self.memory_model = frame[4]
        self.profile_format = frame[5]
        self.macro_format = frame[6]
        self.profile_count = frame[7]
        self.oob = frame[8]
        self.button_count = frame[9]
        self.sector_count = frame[10]
        self.sector_size = int.from_bytes(bytes(frame[11:13]), "big")
        self.mechanical_layout = frame[13] if len(frame) > 13 else 0
        # The G-Shift table is only meaningful when the device says so.
        self.gshift_count = self.button_count if (self.mechanical_layout & 0x03) == 0x02 else 0  # noqa: E501

    # ── mode ─────────────────────────────────────────────────────────────────
    def get_onboard_mode(self) -> int | None:
        """0 = host-controlled, 1 = onboard."""
        frame = self._call(CMD_GET_ONBOARD_MODE)
        return frame[4] if frame and len(frame) > 4 else None

    def set_onboard_mode(self, mode: int) -> bool:
        """Switch between host and onboard control."""
        return self._call(CMD_SET_ONBOARD_MODE, bytes([mode])) is not None

    # ── reading ──────────────────────────────────────────────────────────────
    def read_sector(self, sector: int, attempts: int = 4) -> bytes | None:
        """Read one whole sector.

        A read is 16 bytes per request.  The final chunk has to be asked for at
        ``size - 16`` and its leading bytes dropped, and reads are retried
        because the device occasionally does not answer.
        """
        size = self.sector_size
        if not size:
            return None
        for _ in range(attempts):
            data = bytearray()
            offset = 0
            failed = False
            # Read full 16-byte chunks while more than a chunk is left, exactly
            # as the other implementations do; the tail is fetched separately
            # below because it would otherwise read past the sector.
            while offset < size - (CHUNK - 1):
                frame = self._call(CMD_READ_SECTOR, self._read_args(sector, offset))
                if not frame or len(frame) < 4 + CHUNK:
                    failed = True
                    break
                data.extend(bytes(frame[4 : 4 + CHUNK]))
                offset += CHUNK
            if failed:
                continue
            # The final chunk has to be requested at size-16 and its leading
            # bytes discarded.
            frame = self._call(CMD_READ_SECTOR, self._read_args(sector, size - CHUNK))
            if not frame or len(frame) < 4 + CHUNK:
                continue
            tail = bytes(frame[4 : 4 + CHUNK])[CHUNK + offset - size :]
            data.extend(tail)
            if len(data) == size:
                return bytes(data)
        logger.warning(f"0x8100: sector {sector} could not be read")
        return None

    @staticmethod
    def _read_args(sector: int, offset: int) -> bytes:
        """Arguments for a sector read: sector and offset, both big-endian."""
        return sector.to_bytes(2, "big") + offset.to_bytes(2, "big")

    def read_profile(self, sector: int = 1) -> ProfileSector | None:
        """Read and decode a profile sector."""
        raw = self.read_sector(sector)
        if raw is None:
            return None
        return ProfileSector(raw, self.button_count or 11)

    # ── writing ──────────────────────────────────────────────────────────────
    def write_sector(self, sector: int, data: bytes) -> bool:
        """Write one whole sector.

        The write begins with the **full sector size** as the count, not the
        payload length, and the data goes out in fixed 16-byte chunks.  A
        read-back is the only proof the device accepted it.
        """
        if len(data) != self.sector_size:
            logger.warning(
                f"0x8100: refusing to write {len(data)} bytes into a {self.sector_size}-byte sector"
            )
            return False
        if (
            self._call(
                CMD_WRITE_START,
                sector.to_bytes(2, "big")
                + (0).to_bytes(2, "big")
                + self.sector_size.to_bytes(2, "big"),
            )
            is None
        ):
            return False
        for offset in range(0, self.sector_size, CHUNK):
            chunk = data[offset : offset + CHUNK].ljust(CHUNK, b"\x00")
            if self._call(CMD_WRITE_DATA, chunk) is None:
                logger.warning(f"0x8100: write failed at offset {offset}")
                return False
        if self._call(CMD_WRITE_END) is None:
            return False

        written = self.read_sector(sector)
        if written != data:
            logger.warning("0x8100: the device did not store the sector as written")
            return False
        return True

    def write_profile(self, profile: ProfileSector, sector: int = 1) -> bool:
        """Write a profile sector back, refreshing its checksum first."""
        profile.refresh_crc()
        return self.write_sector(sector, bytes(profile.raw))

    # ── profile selection ────────────────────────────────────────────────────
    def get_current_profile(self) -> int | None:
        """The active profile index.

        Note that on the two devices tested this always answers 0 and the setter
        is a silent no-op, so it cannot be used for switching at runtime.
        """
        frame = self._call(CMD_GET_CURRENT_PROFILE)
        return frame[4] if frame and len(frame) > 4 else None

    def set_current_profile(self, index: int) -> bool:
        """Request a profile switch.  Acknowledged even when ignored."""
        return self._call(CMD_SET_CURRENT_PROFILE, bytes([0x00, index + 1])) is not None

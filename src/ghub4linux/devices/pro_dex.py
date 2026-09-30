"""Logitech PRO X 2 DEX device implementation.

The PRO X 2 DEX (``G PRO X Superlight 2 DEX``) enumerates as USB product
``0x40B8`` — verified against the hardware's ``HID_ID``.  Older sources list
``0x40A3``/``0x40A4``/``0x40A5``; those do not match this mouse, which is why
the device used to be reported as unsupported while it sat on the desk.
"""

import logging

from ..core.config import DeviceConfig, DPISettings, LightingSettings
from ..core.device import (
    BaseDevice,
    ConnectionType,
    DeviceCapability,
    DeviceInfo,
)
from ..core.hid import (
    LIGHTSPEED_RECEIVER_PID_1,
    LIGHTSPEED_RECEIVER_PID_2,
    LIGHTSPEED_RECEIVER_PID_3,
    LIGHTSPEED_RECEIVER_PID_4,
    HIDDevice,
)
from ..core.hidpp import (
    FEATURE_ADJUSTABLE_DPI,
    FEATURE_BATTERY_STATUS,
    FEATURE_BATTERY_VOLTAGE,
    FEATURE_EXT_REPORT_RATE,
    FEATURE_EXTENDED_ADJUSTABLE_DPI,
    FEATURE_ONBOARD_PROFILES,
    FEATURE_REPORT_RATE,
    FEATURE_UNIFIED_BATTERY,
)
from .g502 import G502Device

logger = logging.getLogger(__name__)


# PRO X 2 DEX product IDs.
PRO_DEX_2_PID = 0x40B8  # PRO X 2 DEX (enumerates as its own device)
PRO_DEX_2_WIRED_PID = 0x40B9  # wired mode, when the cable is attached
# The receiver a DEX is paired with.  Its product_string is a generic
# "USB Receiver" for every mouse, so the endpoint is identified over HID++
# DeviceName instead of by PID.
PRO_DEX_2_RECEIVER_PID = 0xC54D


class ProDex2(G502Device):
    """PRO X 2 DEX (PRO X Superlight 2 DEX) implementation."""

    MAX_DPI = 44000
    DPI_MIN = 100
    DPI_STEP = 50
    BUTTON_COUNT = 5
    DEFAULT_DPI_LEVELS = [400, 800, 1600, 3200]

    def __init__(self, hid_device: HIDDevice, config: DeviceConfig | None = None):
        """Initialize PRO X 2 DEX device."""
        super().__init__(hid_device, config)
        self._dpi_feature_index: int | None = None
        self._battery_feature_index: int | None = None
        self._features: dict[int, int] = {}

    def _query_features(self) -> None:
        """Query HID++ feature indexes via IRoot (0x0000) feature discovery."""
        self._features = self.discover_features()
        # The PRO X 2 DEX exposes 0x2202 extendedAdjustableDpi, not the older
        # 0x2201 — its DPI must be read through the extended feature.
        self._extended_dpi_index = self._features.get(FEATURE_EXTENDED_ADJUSTABLE_DPI)
        self._dpi_feature_index = self._features.get(FEATURE_ADJUSTABLE_DPI)
        self._battery_feature_index = (
            self._features.get(FEATURE_UNIFIED_BATTERY)
            or self._features.get(FEATURE_BATTERY_STATUS)
            or self._features.get(FEATURE_BATTERY_VOLTAGE)
        )

    def _init_device(self) -> None:
        """Initialize device after connection."""
        self._query_features()
        self._apply_capabilities()
        self._info = self.get_device_info()
        self._sync_dpi_levels()
        logger.info(
            f"Initialized {self._info.name} "
            f"(features: {', '.join(f'0x{k:04x}' for k in sorted(self._features)) or 'none'})"
        )

    def _apply_capabilities(self) -> None:
        """Declare only the capabilities the device actually reported."""
        caps: set[DeviceCapability] = {DeviceCapability.MACROS}
        if self._extended_dpi_index or self._dpi_feature_index:
            caps.add(DeviceCapability.DPI_ADJUSTMENT)
        if any(
            f in self._features
            for f in (FEATURE_UNIFIED_BATTERY, FEATURE_BATTERY_STATUS, FEATURE_BATTERY_VOLTAGE)
        ):
            caps.add(DeviceCapability.BATTERY_STATUS)
        if FEATURE_ONBOARD_PROFILES in self._features:
            caps.add(DeviceCapability.ONBOARD_PROFILES)
        # The DEX exposes the extended rate feature (0x8061); the classic
        # ReportRate (0x8060) it does not have at all.
        if FEATURE_EXT_REPORT_RATE in self._features or FEATURE_REPORT_RATE in self._features:
            caps.add(DeviceCapability.REPORT_RATE)
        # The PRO X 2 DEX has no RGB, so no RGB_LIGHTING capability is
        # advertised and the GUI never offers a lighting tab for it.
        self._capabilities = caps

    def get_sensor_dpi(self, sensor: int = 0) -> int | None:
        """Read the sensor's current resolution (X axis) in DPI.

        ``0x2202`` fn 5 returns, after the 3 payload bytes: sensor index, then
        the current and default X/Y DPI as big-endian u16 values.
        """
        if not self._extended_dpi_index:
            return super().get_sensor_dpi(sensor)
        frame = self._read_feature(self._extended_dpi_index, 0x05, bytes([sensor, 0x00, 0x00]))
        if len(frame) < 7:
            return None
        return (frame[5] << 8) | frame[6]

    def get_sensor_dpi_parameters(self, sensor: int = 0) -> dict[str, int] | None:
        """Read the full DPI parameters (X/Y current and default, LOD)."""
        if not self._extended_dpi_index:
            return None
        frame = self._read_feature(self._extended_dpi_index, 0x05, bytes([sensor, 0x00, 0x00]))
        if len(frame) < 13:
            return None
        payload = frame[4:]
        return {
            "dpi_x": (payload[1] << 8) | payload[2],
            "default_dpi_x": (payload[3] << 8) | payload[4],
            "dpi_y": (payload[5] << 8) | payload[6],
            "default_dpi_y": (payload[7] << 8) | payload[8],
            "lod": payload[9],
        }

    def get_supported_dpi(self, sensor: int = 0) -> list[int]:
        """Return the DPI values the sensor accepts.

        ``0x2202`` fn 3 answers with ``[sensor, direction, <big-endian u16>…]``
        terminated by ``0x0000``; X and Y report the same list on this device.
        """
        if not self._extended_dpi_index:
            return super().get_supported_dpi(sensor)
        frame = self._read_feature(self._extended_dpi_index, 0x03, bytes([sensor, 0x00, 0x00]))
        if len(frame) < 7:
            return []
        # 0x2202 payload = [sensor, direction, <u16 BE>… , 0x0000]
        values: list[int] = []
        payload = bytes(frame[4:])
        for offset in range(2, len(payload) - 1, 2):
            value = (payload[offset] << 8) | payload[offset + 1]
            if value == 0:
                break
            values.append(value)
        return sorted(set(values))

    def _set_dpi_settings(self, settings: DPISettings) -> bool:
        """Set the active sensor DPI (0x2202 fn 6).

        Note: on the measured unit the device acknowledges this request but
        does not apply it, so the write is reported as unverified rather than
        claimed as applied.
        """
        self.active_profile.dpi_settings = settings
        if not self._extended_dpi_index or not settings.levels:
            return False

        index = max(0, min(settings.active_level, len(settings.levels) - 1))
        dpi = max(self.DPI_MIN, min(settings.levels[index].dpi, self.MAX_DPI))
        payload = bytes(
            [
                0x00,
                (dpi >> 8) & 0xFF,
                dpi & 0xFF,
                (dpi >> 8) & 0xFF,
                dpi & 0xFF,
                0x02,  # lift-off distance: medium (the measured unit's default)
            ]
        )
        frame = self._read_feature(
            self._extended_dpi_index, 0x06, payload + bytes(16 - len(payload))
        )
        if not frame:
            return False
        return self.get_sensor_dpi(0) == dpi

    def get_device_info(self) -> DeviceInfo:
        """Get device information."""
        return self._make_device_info(
            name="PRO X SUPERLIGHT 2 DEX",
            model="PRO X SUPERLIGHT 2 DEX",
            has_rgb=False,
            has_battery=any(
                f in self._features
                for f in (FEATURE_UNIFIED_BATTERY, FEATURE_BATTERY_STATUS, FEATURE_BATTERY_VOLTAGE)
            ),
            max_dpi=self.MAX_DPI,
            dpi_step=self.DPI_STEP,
            button_count=self.BUTTON_COUNT,
        )

    def _get_connection_type(self) -> ConnectionType:
        """Determine connection type."""
        if self.hid_device.product_id in (PRO_DEX_2_WIRED_PID, 0x40A4):
            return ConnectionType.WIRED
        return ConnectionType.LIGHTSPEED

    def _set_lighting_settings(self, settings: LightingSettings) -> bool:
        """The PRO X 2 DEX has no RGB; only the local profile is updated."""
        self.active_profile.lighting_settings = settings
        return False

    # ── report rate: extendedAdjustableReportRate (0x8061) ───────────────────
    #
    # The DEX does **not** have the older ReportRate (0x8060) that the G502
    # uses; it exposes the extended variant, which is a different layout:
    #
    #   fn 0 get_device_capabilities(connection_type) -> bitmask of rates
    #   fn 1 get_actual_report_rate_list(connection_type) -> [count, codes...]
    #   fn 2 get_report_rate(connection_type)          -> [rate_code]
    #   fn 3 set_report_rate(rate_code)                -> ()
    #
    # The rate is an **enum code**, not a number of hertz: 0=125, 1=250, 2=500,
    # 3=1000, 4=2000, 5=4000, 6=8000 Hz. The previous implementation looked for
    # 0x8060 (absent here, hence "report rate not supported") and would have
    # written hertz as a big-endian u16 through fn 1 — a function that reads the
    # list, not one that sets anything.

    def _connection_code(self) -> int:
        """0 = wired USB, 1 = Logitech gaming wireless."""
        return 0 if self.info and self.info.connection_type == ConnectionType.WIRED else 1

    def get_report_rate_list(self) -> list[int]:
        """Report intervals in milliseconds, as the base API expresses them."""
        index = self._features.get(FEATURE_EXT_REPORT_RATE)
        if not index:
            return []
        frame = self._read_feature(index, 0x00, bytes([self._connection_code(), 0, 0]))
        if len(frame) < 5:
            return []
        bitmask = frame[4]
        # Bit N set means rate code N is offered; convert each code to hertz and
        # then to the millisecond interval the caller expects (or the
        # sub-millisecond rates as 0, which callers render as "no interval").
        hertz_by_code = {0: 125, 1: 250, 2: 500, 3: 1000, 4: 2000, 5: 4000, 6: 8000}
        intervals = []
        for code, hertz in hertz_by_code.items():
            if bitmask & (1 << code):
                intervals.append(max(1, 1000 // hertz))
        return sorted(set(intervals))

    def get_report_rate(self) -> int | None:
        """Active report interval in milliseconds (None when unreadable)."""
        index = self._features.get(FEATURE_EXT_REPORT_RATE)
        if not index:
            return None
        frame = self._read_feature(index, 0x02, bytes([self._connection_code(), 0, 0]))
        if len(frame) < 5:
            return None
        hertz_by_code = {0: 125, 1: 250, 2: 500, 3: 1000, 4: 2000, 5: 4000, 6: 8000}
        hertz = hertz_by_code.get(frame[4])
        return max(1, 1000 // hertz) if hertz else None

    def set_report_rate(self, rate: int) -> bool:
        """Set the report interval, given in milliseconds or hertz."""
        index = self._features.get(FEATURE_EXT_REPORT_RATE)
        if not index:
            return False

        hertz = rate if rate > 100 else 1000 // rate
        code_by_hertz = {125: 0, 250: 1, 500: 2, 1000: 3, 2000: 4, 4000: 5, 8000: 6}
        code = code_by_hertz.get(hertz)
        if code is None:
            logger.warning(f"{self.name}: {hertz} Hz is not a rate this device offers")
            return False

        supported = self.get_report_rate_list()
        wanted_interval = max(1, 1000 // hertz)
        if supported and wanted_interval not in supported:
            logger.warning(f"{self.name}: {hertz} Hz is not supported (device offers {supported})")
            return False

        frame = self._read_feature(index, 0x03, bytes([code, 0, 0]))
        if not frame:
            return False
        # Read back rather than trust the acknowledgement.
        applied = self.get_report_rate() == wanted_interval
        if not applied:
            logger.warning(f"{self.name}: report rate {hertz} Hz not applied")
        return applied


# Device registry mapping
PRO_DEX_2_DEVICES: dict[int, type[BaseDevice]] = {
    PRO_DEX_2_PID: ProDex2,
    PRO_DEX_2_WIRED_PID: ProDex2,
}

# Hint-based entries for shared Lightspeed receiver PIDs.  A dongle reports one
# product_string for every mouse behind it, so identification really happens
# over HID++ DeviceName (see HIDManager); these entries cover the receivers a
# PRO X 2 DEX is paired with.
PRO_DEX_2_RECEIVER_HINTS: list[tuple[int, str, type]] = [
    (LIGHTSPEED_RECEIVER_PID_1, "pro x superlight", ProDex2),
    (LIGHTSPEED_RECEIVER_PID_2, "pro x superlight", ProDex2),
    (LIGHTSPEED_RECEIVER_PID_3, "pro x superlight", ProDex2),
    (LIGHTSPEED_RECEIVER_PID_4, "pro x superlight", ProDex2),
]

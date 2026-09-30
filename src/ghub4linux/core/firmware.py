"""Firmware update support.

Two questions a user actually asks, and both are answerable here without
inventing anything:

1. *Is there an update for my device?*  Logitech publishes official firmware
   through the Linux Vendor Firmware Service (LVFS), and their `fw_updates`
   repository documents how each device is identified there: a version-5 UUID
   generated from the DNS namespace and the string ``USB\\VID_046D&PID_xxxx``
   (or ``UFY\\...`` for Unifying devices), where *xxxx* is the USB product ID.
   That UUID is what appears as ``<firmware type="flashed">`` in the LVFS
   ``provides`` element, so the catalog can be searched for a device's firmware
   by PID — no heuristic guessing.

2. *Can this application flash it?*  No.  Firmware updates for the G series go
   through the HID++ DFU protocol, which needs vendor-signed images that are not
   distributed publicly: the LVFS catalog carries Logitech firmware only for
   Unifying receivers, not for G-series mice.  This module therefore *reports*
   and never flashes.  Claiming otherwise — or, worse, half-writing an image to
   a device — is not something a configuration tool should do.

The catalog is read from the local fwupd metadata, which fwupd keeps current,
so the check needs no network access of its own and no root rights: the file is
world-readable and Python's standard library decompresses zstd directly.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

LOGITECH_VENDOR_ID = 0x046D

# fwupd keeps the LVFS catalog here; the file is readable by any user.
LVFS_METADATA_CANDIDATES: tuple[Path, ...] = (
    Path("/var/lib/fwupd/metadata/lvfs/firmware.xml.zst"),
    Path("/var/lib/fwupd/metadata/lvfs-testing/firmware.xml.zst"),
    Path("/var/lib/fwupd/metadata/lvfs-embargo/firmware.xml.zst"),
)

# How this application names the two ID spaces.  Logitech's fw_updates README
# defines exactly these prefixes.
ID_PREFIX_USB = "USB"
ID_PREFIX_UNIFYING = "UFY"


def firmware_uuid(product_id: int, prefix: str = ID_PREFIX_USB) -> str:
    """Return the LVFS firmware UUID for a Logitech product ID.

    Logitech generates this as a version-5 UUID over the DNS namespace and the
    string ``USB\\VID_046D&PID_xxxx``, so it can be computed rather than looked
    up.  Verified against the published formula.
    """
    name = f"{prefix}\\VID_{LOGITECH_VENDOR_ID:04X}&PID_{product_id:04X}"
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, name))


@dataclass
class FirmwareRelease:
    """One firmware release of a catalog entry."""

    version: str
    timestamp: int = 0
    urgency: str = ""

    @property
    def release_date(self) -> str:
        """ISO date of the release, or an empty string when unknown."""
        if not self.timestamp:
            return ""
        import datetime

        return datetime.date.fromtimestamp(self.timestamp).isoformat()


@dataclass
class FirmwareInfo:
    """What the catalog knows about one device."""

    device_name: str = ""
    provider: str = ""
    latest_version: str = ""
    release_date: str = ""
    urgency: str = ""
    releases: list[FirmwareRelease] = field(default_factory=list)
    # Whether the entry is addressed by the UUID computed from the device's PID.
    matched_by: str = ""

    @property
    def found(self) -> bool:
        """True when the catalog has an entry for this device."""
        return bool(self.latest_version)


class FirmwareCatalog:
    """Reads the LVFS catalog that fwupd maintains locally."""

    def __init__(self, metadata_path: Path | None = None) -> None:
        self._path = metadata_path
        self._text: str | None = None
        self._by_guid: dict[str, FirmwareInfo] | None = None

    # ── loading ──────────────────────────────────────────────────────────────
    @property
    def metadata_path(self) -> Path | None:
        """The catalog file in use, or None when none is readable."""
        if self._path is not None:
            return self._path
        for candidate in LVFS_METADATA_CANDIDATES:
            if candidate.is_file():
                self._path = candidate
                return candidate
        return None

    @property
    def available(self) -> bool:
        """True when a catalog could be read."""
        return self._load() is not None

    def _load(self) -> str | None:
        """Read the catalog once, compressed or not.

        fwupd ships ``firmware.xml.zst``, but a plain-XML catalog must work too:
        a half-decompressed or hand-provided file would otherwise read as "no
        catalog", which turns into a silent "unknown" for the user.
        """
        if self._text is not None:
            return self._text
        path = self.metadata_path
        if path is None:
            logger.debug("no fwupd metadata found; firmware check unavailable")
            return None
        try:
            raw = path.read_bytes()
        except OSError as exc:
            logger.debug(f"cannot read {path}: {exc}")
            return None

        # Zstandard frames start with the magic number 0x28B52FFD.
        if not raw.startswith(b"\x28\xb5\x2f\xfd"):
            self._text = raw.decode("utf-8", "replace")
            return self._text

        try:
            from compression import zstd  # Python 3.14 stdlib

            self._text = zstd.decompress(raw).decode("utf-8", "replace")
        except Exception:
            # Fall back to the zstd command line; still no root needed.
            import subprocess

            try:
                result = subprocess.run(
                    ["zstd", "-d", "-c", str(path)],
                    capture_output=True,
                    check=True,
                    timeout=60,
                )
                self._text = result.stdout.decode("utf-8", "replace")
            except (OSError, subprocess.SubprocessError) as exc:
                logger.debug(f"cannot decompress {path}: {exc}")
                return None
        return self._text

    def _index(self) -> dict[str, FirmwareInfo]:
        """Map every firmware GUID in the catalog to its release info."""
        if self._by_guid is not None:
            return self._by_guid

        index: dict[str, FirmwareInfo] = {}
        text = self._load()
        if not text:
            self._by_guid = index
            return index

        # Components are independent; a non-greedy scan keeps memory bounded
        # compared to parsing 20 MB of XML into a tree.
        for component in re.findall(r"<component\b.*?</component>", text, re.S):
            guids = re.findall(r'<firmware type="flashed">([0-9a-fA-F-]{36})</firmware>', component)
            if not guids:
                continue
            name_match = re.search(r"<name>(.*?)</name>", component, re.S)
            provider_match = re.search(r"<developer_name>(.*?)</developer_name>", component, re.S)
            releases = [
                FirmwareRelease(
                    version=version,
                    timestamp=int(timestamp) if timestamp else 0,
                    urgency=urgency,
                )
                for version, timestamp, urgency in re.findall(
                    r'<release id="\d+" version="([^"]*)"(?: timestamp="(\d+)")?(?:[^>]*urgency="([^"]*)")?',
                    component,
                )
            ]
            releases.sort(key=lambda r: r.timestamp, reverse=True)
            latest = releases[0] if releases else FirmwareRelease(version="")

            info = FirmwareInfo(
                device_name=(name_match.group(1).strip() if name_match else ""),
                provider=(provider_match.group(1).strip() if provider_match else ""),
                latest_version=latest.version,
                release_date=latest.release_date,
                urgency=latest.urgency,
                releases=releases,
            )
            for guid in guids:
                index[guid.lower()] = info

        logger.debug(f"firmware catalog: {len(index)} GUID entries")
        self._by_guid = index
        return index

    # ── lookup ───────────────────────────────────────────────────────────────
    def lookup(self, product_id: int) -> FirmwareInfo | None:
        """Return the catalog entry for a Logitech product ID, if any."""
        index = self._index()
        if not index:
            return None
        for prefix in (ID_PREFIX_USB, ID_PREFIX_UNIFYING):
            guid = firmware_uuid(product_id, prefix)
            info = index.get(guid)
            if info is not None:
                # Copy so callers cannot mutate the cached entry.
                return FirmwareInfo(
                    device_name=info.device_name,
                    provider=info.provider,
                    latest_version=info.latest_version,
                    release_date=info.release_date,
                    urgency=info.urgency,
                    releases=list(info.releases),
                    matched_by=prefix,
                )
        return None


def parse_version(version: str) -> tuple[int, ...]:
    """Parse a version string into comparable numbers.

    Firmware versions reach us in more than one shape: the plain ``17.00`` this
    application reads over HID++ and catalog versions such as ``07.00.B0010``.
    Anything non-numeric separates groups, so ``07.00.B0010`` becomes
    ``(7, 0, 0, 10)`` and can be compared against another version of the same
    family.
    """
    return tuple(int(part) for part in re.findall(r"\d+", version or ""))


def compare_versions(current: str, candidate: str) -> int:
    """Compare two firmware versions: -1 older, 0 equal, 1 newer.

    Returns ``0`` when either side is unknown, so an unreadable version never
    turns into a "there is an update" claim that cannot be backed up.
    """
    left = parse_version(current)
    right = parse_version(candidate)
    if not left or not right:
        return 0
    # Compare like-length prefixes so "17.00" and "17.0.0" agree.
    length = max(len(left), len(right))
    padded_left = left + (0,) * (length - len(left))
    padded_right = right + (0,) * (length - len(right))
    if padded_left == padded_right:
        return 0
    return -1 if padded_left < padded_right else 1


@dataclass
class FirmwareCheck:
    """Result of checking one device against the catalog."""

    current_version: str
    info: FirmwareInfo | None = None
    catalog_available: bool = True

    @property
    def status(self) -> str:
        """A short, honest status: 'update-available', 'up-to-date',
        'unknown' or 'not-in-catalog'."""
        if not self.catalog_available:
            return "unknown"
        if self.info is None or not self.info.found:
            return "not-in-catalog"
        if not self.current_version or self.current_version == "Unknown":
            return "unknown"
        return (
            "update-available"
            if compare_versions(self.current_version, self.info.latest_version) < 0
            else "up-to-date"
        )

    @property
    def message(self) -> str:
        """A sentence a user can act on."""
        if self.status == "unknown":
            return "Firmware catalog not available on this system."
        if self.status == "not-in-catalog":
            return (
                "Logitech publishes no firmware for this device through LVFS. "
                "Updates are only available through Logitech G HUB on Windows."
            )
        if self.status == "up-to-date":
            return f"Firmware is up to date ({self.current_version})."
        info = self.info
        assert info is not None
        when = f" from {info.release_date}" if info.release_date else ""
        return (
            f"Version {info.latest_version}{when} is available "
            f"(installed: {self.current_version}). "
            f"This tool cannot flash it: Logitech ships G-series firmware only "
            f"through G HUB, not to Linux."
        )

    def to_dict(self) -> dict[str, object]:
        """JSON-friendly form for the CLI."""
        return {
            "status": self.status,
            "current_version": self.current_version,
            "latest_version": self.info.latest_version if self.info else "",
            "release_date": self.info.release_date if self.info else "",
            "device_name": self.info.device_name if self.info else "",
            "matched_by": self.info.matched_by if self.info else "",
            "message": self.message,
        }


def check_firmware(device: object, catalog: FirmwareCatalog | None = None) -> FirmwareCheck:
    """Check one device against the LVFS catalog.

    *device* is any object exposing ``get_firmware_version()`` and
    ``hid_device`` (i.e. every driver in this package).
    """
    catalog = catalog or FirmwareCatalog()
    getter = getattr(device, "get_firmware_version", None)
    current = str(getter()) if callable(getter) else ""

    hid_device = getattr(device, "hid_device", None)
    product_id = getattr(hid_device, "product_id", None)
    if not isinstance(product_id, int):
        return FirmwareCheck(current_version=current, catalog_available=catalog.available)

    info = catalog.lookup(product_id)
    return FirmwareCheck(
        current_version=current,
        info=info,
        catalog_available=catalog.available,
    )

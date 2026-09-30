"""Tests for the firmware check.

The interesting risk here is a false "update available": a check that guesses
would be worse than no check at all, because a user might go hunting for an
image that does not exist.  These tests therefore pin down the identification
formula, the version comparison, and the honest outcomes.
"""

import uuid

from ghub4linux.core.firmware import (
    LOGITECH_VENDOR_ID,
    FirmwareCatalog,
    FirmwareCheck,
    FirmwareInfo,
    FirmwareRelease,
    compare_versions,
    firmware_uuid,
    parse_version,
)


class TestFirmwareUuid:
    """The identification scheme comes from Logitech's own fw_updates repo."""

    def test_matches_the_documented_formula(self):
        """UUID v5 over the DNS namespace and 'USB\\VID_046D&PID_xxxx'."""
        for pid in (0x407F, 0x40B8, 0x405F, 0xC53A):
            expected = uuid.uuid5(
                uuid.NAMESPACE_DNS, f"USB\\VID_{LOGITECH_VENDOR_ID:04X}&PID_{pid:04X}"
            )
            assert firmware_uuid(pid) == str(expected)

    def test_unifying_prefix_uses_ufy(self):
        expected = uuid.uuid5(uuid.NAMESPACE_DNS, "UFY\\VID_046D&PID_AAAD")
        assert firmware_uuid(0xAAAD, "UFY") == str(expected)

    def test_prefixes_produce_different_ids(self):
        assert firmware_uuid(0x40B8, "USB") != firmware_uuid(0x40B8, "UFY")

    def test_known_vendor_value_is_16_bit_hex(self):
        """The string must use %04X, not a decimal or short form."""
        assert f"{LOGITECH_VENDOR_ID:04X}" == "046D"


class TestVersionComparison:
    def test_parses_plain_and_decorated_versions(self):
        assert parse_version("17.00") == (17, 0)
        # "B0010" is one number token, so it yields 10 — not (0, 10).
        assert parse_version("07.00.B0010") == (7, 0, 10)
        assert parse_version("7.00 (build 10)") == (7, 0, 10)

    def test_equal_versions_that_look_different(self):
        """'17.00', '17.0' and '17.0.0' describe the same firmware."""
        assert compare_versions("17.00", "17.0") == 0
        assert compare_versions("7.00 (build 10)", "07.00.B0010") == 0
        assert compare_versions("17.00", "17.0.0") == 0

    def test_older_and_newer(self):
        assert compare_versions("17.00", "18.00") == -1
        assert compare_versions("18.00", "17.99") == 1

    def test_unknown_version_never_claims_an_update(self):
        """An unreadable version must not turn into 'update available'."""
        assert compare_versions("Unknown", "18.00") == 0
        assert compare_versions("", "18.00") == 0


def _info(version="18.00", date="2025-01-02", name="Some Mouse") -> FirmwareInfo:
    return FirmwareInfo(
        device_name=name,
        latest_version=version,
        release_date=date,
        releases=[FirmwareRelease(version=version, timestamp=0)],
    )


class TestFirmwareCheckStatus:
    def test_reports_update_available(self):
        check = FirmwareCheck(current_version="17.00", info=_info("18.00"))
        assert check.status == "update-available"
        assert "18.00" in check.message
        assert "17.00" in check.message

    def test_reports_up_to_date(self):
        check = FirmwareCheck(current_version="18.00", info=_info("18.00"))
        assert check.status == "up-to-date"

    def test_says_the_tool_cannot_flash(self):
        """The message must not leave the impression that this app updates it."""
        message = FirmwareCheck(current_version="17.00", info=_info("18.00")).message
        assert "cannot flash" in message
        assert "G HUB" in message

    def test_device_absent_from_catalog(self):
        check = FirmwareCheck(current_version="17.00", info=None)
        assert check.status == "not-in-catalog"
        assert "no firmware for this device" in check.message

    def test_missing_catalog_is_unknown_not_up_to_date(self):
        """No catalog must never read as 'you are up to date'."""
        check = FirmwareCheck(current_version="17.00", info=None, catalog_available=False)
        assert check.status == "unknown"
        assert "not available" in check.message

    def test_unknown_current_version_is_not_up_to_date(self):
        check = FirmwareCheck(current_version="Unknown", info=_info("18.00"))
        assert check.status == "unknown"

    def test_to_dict_is_json_ready(self):
        data = FirmwareCheck(current_version="17.00", info=_info("18.00")).to_dict()
        assert data["status"] == "update-available"
        assert data["latest_version"] == "18.00"
        assert data["release_date"] == "2025-01-02"
        import json

        json.dumps(data)  # must not raise


# A minimal catalog fragment with the structure fwupd ships, including a
# Logitech entry addressed by the documented UUID formula.
CATALOG_XML = """<?xml version="1.0"?><components>
<component type="firmware">
 <name>Unifying</name>
 <developer_name>Logitech</developer_name>
 <provides>
  <firmware type="flashed">{guids[0]}</firmware>
  <firmware type="flashed">{guids[1]}</firmware>
 </provides>
 <releases>
  <release id="1" version="RQR12.07_B0029" timestamp="1500000000" urgency="low"/>
  <release id="2" version="RQR12.11_B0032" timestamp="1563408000" urgency="low"/>
 </releases>
</component>
<component type="firmware">
 <name>Other Vendor Thing</name>
 <developer_name>SomeoneElse</developer_name>
 <provides><firmware type="flashed">11111111-2222-3333-4444-555555555555</firmware></provides>
 <releases><release id="3" version="1.0" timestamp="1400000000"/></releases>
</component>
</components>"""


def _write_catalog(tmp_path, pid=0xAAAA):
    """Write a catalog fragment shaped like fwupd's and return a catalog."""
    guids = [firmware_uuid(pid), firmware_uuid(pid, "UFY")]
    path = tmp_path / "firmware.xml"
    path.write_text(CATALOG_XML.format(guids=guids), encoding="utf-8")
    return FirmwareCatalog(path)


class TestFirmwareCatalog:
    def test_finds_a_logitech_entry_by_pid(self, tmp_path):
        catalog = _write_catalog(tmp_path)
        info = catalog.lookup(0xAAAA)
        assert info is not None
        assert info.device_name == "Unifying"
        assert info.provider == "Logitech"
        # Newest release wins, not document order.
        assert info.latest_version == "RQR12.11_B0032"

    def test_unknown_pid_returns_nothing(self, tmp_path):
        catalog = _write_catalog(tmp_path)
        assert catalog.lookup(0x407F) is None

    def test_missing_file_is_reported_as_unavailable(self, tmp_path):
        catalog = FirmwareCatalog(tmp_path / "does-not-exist.xml")
        assert catalog.available is False
        assert catalog.lookup(0x407F) is None

    def test_release_dates_are_decoded(self, tmp_path):
        info = _write_catalog(tmp_path).lookup(0xAAAA)
        assert info is not None
        assert info.release_date.startswith("2019-")


class TestCheckFirmwareAgainstDevice:
    def test_uses_the_devices_pid_and_version(self, tmp_path):
        from ghub4linux.core.firmware import check_firmware

        class FakeHid:
            product_id = 0xAAAA

        class FakeDevice:
            hid_device = FakeHid()

            def get_firmware_version(self):
                return "RQR12.07_B0029"

        check = check_firmware(FakeDevice(), _write_catalog(tmp_path))
        assert check.status == "update-available"
        assert check.info is not None
        assert check.info.latest_version == "RQR12.11_B0032"

    def test_device_without_hid_device_does_not_crash(self, tmp_path):
        from ghub4linux.core.firmware import check_firmware

        class Bare:
            def get_firmware_version(self):
                return "1.0"

        check = check_firmware(Bare(), _write_catalog(tmp_path))
        assert check.current_version == "1.0"
        assert check.info is None


class TestCatalogFileHandling:
    """The catalog arrives compressed from fwupd but plain XML must work too.

    Reading a plain file as if it were zstd made the whole catalog look absent,
    which the UI then reported as a failure to read it.
    """

    def test_reads_uncompressed_xml(self, tmp_path):
        path = tmp_path / "firmware.xml"
        path.write_text(CATALOG_XML.format(guids=["0" * 36] * 2), encoding="utf-8")
        catalog = FirmwareCatalog(path)
        assert catalog.available is True

    def test_reads_zstd_compressed_xml(self, tmp_path):
        payload = CATALOG_XML.format(guids=["0" * 36] * 2).encode()
        path = tmp_path / "firmware.xml.zst"
        try:
            from compression import zstd
        except ImportError:
            import pytest

            pytest.skip("no zstd support available")

        path.write_bytes(zstd.compress(payload))
        catalog = FirmwareCatalog(path)
        assert catalog.available is True

    def test_garbage_file_is_not_silently_treated_as_a_catalog(self, tmp_path):
        path = tmp_path / "firmware.xml"
        path.write_bytes(b"\x28\xb5\x2f\xfd this is not valid zstd")
        assert FirmwareCatalog(path).available is False

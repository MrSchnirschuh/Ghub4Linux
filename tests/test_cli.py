"""Tests for ghub4linux CLI module — exercises actual commands with mock devices."""

import pytest

from ghub4linux.cli import main
from ghub4linux.core.config import AppConfig
from ghub4linux.core.device import DeviceManager
from ghub4linux.core.hid import HIDDevice


class MockHIDManager:
    """Ponytail: minimal mock that returns one device."""

    def __init__(self):
        self._device = HIDDevice(
            vendor_id=0x046D,
            product_id=0x407F,  # G502 Lightspeed wireless PID
            serial_number="mock123",
            manufacturer="Logitech",
            product="G502 Lightspeed",
            path=b"/dev/mock",
            interface_number=0,
            usage_page=0xFF00,
            usage=0x0001,
        )

    def find_logitech_devices(self):
        return [self._device]


@pytest.fixture
def mock_manager(monkeypatch):
    """Replace HIDManager with a mock that returns one G502 X device."""
    from ghub4linux.core import hid as hid_module

    monkeypatch.setattr(hid_module, "HIDManager", MockHIDManager)
    # Also register the device class so scan_devices() creates a real device
    from ghub4linux.devices.g502 import G502_DEVICES

    config = AppConfig()
    manager = DeviceManager(config)
    for pid, cls in G502_DEVICES.items():
        manager.register_device_class(pid, cls)
    manager._hid_manager = MockHIDManager()
    return manager


def test_cli_list(mock_manager, monkeypatch):
    """Test 'list' shows connected devices."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["list"])
    assert exc.value.code == 0


def test_cli_info(mock_manager, monkeypatch):
    """Test 'info' shows device details."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["info", "046d:407f:mock123"])
    assert exc.value.code == 0


def test_cli_info_nonexistent(mock_manager, monkeypatch):
    """Test 'info' on nonexistent device exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["info", "dead:beef:0000"])
    assert exc.value.code == 1


def test_cli_battery(mock_manager, monkeypatch):
    """Test 'battery' shows battery status."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["battery", "046d:407f:mock123"])
    assert exc.value.code == 0


def test_cli_battery_nonexistent(mock_manager, monkeypatch):
    """Test 'battery' on nonexistent device exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["battery", "dead:beef:0000"])
    assert exc.value.code == 1


def test_cli_dpi_show(mock_manager, monkeypatch):
    """Test 'dpi' shows current DPI levels."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["dpi", "046d:407f:mock123"])
    assert exc.value.code == 0


def test_cli_dpi_set(mock_manager, monkeypatch):
    """Test 'dpi --dpi N' sets a DPI level."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["dpi", "046d:407f:mock123", "--dpi", "1600"])
    assert exc.value.code == 0


def test_cli_lighting_show(mock_manager, monkeypatch):
    """Test 'lighting' shows current lighting settings."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["lighting", "046d:407f:mock123"])
    assert exc.value.code == 0


def test_cli_lighting_on(mock_manager, monkeypatch):
    """Test 'lighting --on' enables lighting."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["lighting", "046d:407f:mock123", "--on"])
    assert exc.value.code == 0


def test_cli_lighting_off(mock_manager, monkeypatch):
    """Test 'lighting --off' disables lighting."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["lighting", "046d:407f:mock123", "--off"])
    assert exc.value.code == 0


def test_cli_lighting_effect(mock_manager, monkeypatch):
    """Test 'lighting --effect' sets an effect."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["lighting", "046d:407f:mock123", "--effect", "breathing"])
    assert exc.value.code == 0


def test_cli_no_args():
    """Test that no args shows error (exit code 2)."""
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_cli_daemon_help():
    """Test daemon subcommand help."""
    with pytest.raises(SystemExit) as exc:
        main(["daemon", "--help"])
    assert exc.value.code == 0


def test_cli_install_daemon_help():
    """Test install-daemon subcommand help."""
    with pytest.raises(SystemExit) as exc:
        main(["install-daemon", "--help"])
    assert exc.value.code == 0


def test_cli_help():
    """Test --help works."""
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_cli_list_help():
    """Test subcommand --help works."""
    for cmd in ["list", "info", "battery", "dpi", "lighting", "daemon", "install-daemon"]:
        with pytest.raises(SystemExit) as exc:
            main([cmd, "--help"])
        assert exc.value.code == 0, f"{cmd} --help failed"


def test_cli_daemon_starts_and_stops(mock_manager, monkeypatch):
    """Test daemon starts, scans devices, and exits on signal."""
    import signal
    import threading
    import time

    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)

    def _send_signal():
        time.sleep(0.1)
        signal.raise_signal(signal.SIGINT)

    t = threading.Thread(target=_send_signal, daemon=True)
    t.start()
    with pytest.raises(SystemExit) as exc:
        main(["daemon", "--interval", "1"])
    assert exc.value.code == 0


def test_cli_daemon_interval_flag():
    """Test daemon --interval is accepted."""
    with pytest.raises(SystemExit) as exc:
        main(["daemon", "--interval", "30", "--help"])
    assert exc.value.code == 0


def test_cli_profile_export_help():
    """Test profile export --help works."""
    with pytest.raises(SystemExit) as exc:
        main(["profile", "export", "--help"])
    assert exc.value.code == 0


def test_cli_profile_import_help():
    """Test profile import --help works."""
    with pytest.raises(SystemExit) as exc:
        main(["profile", "import", "--help"])
    assert exc.value.code == 0


def test_cli_profile_export_nonexistent(mock_manager, monkeypatch):
    """Test profile export on nonexistent device exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "export", "dead:beef:0000"])
    assert exc.value.code == 1


def test_cli_profile_import_nonexistent(mock_manager, monkeypatch):
    """Test profile import on nonexistent device exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "import", "dead:beef:0000", "/tmp/nonexistent.json"])
    assert exc.value.code == 1

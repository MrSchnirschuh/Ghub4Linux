"""Tests for ghub4linux CLI monitor subcommand."""

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
            product_id=0x407F,
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
    from ghub4linux.devices.g502 import G502_DEVICES

    config = AppConfig()
    manager = DeviceManager(config)
    for pid, cls in G502_DEVICES.items():
        manager.register_device_class(pid, cls)
    manager._hid_manager = MockHIDManager()
    return manager


def test_cli_monitor_help():
    """Test monitor --help works."""
    with pytest.raises(SystemExit) as exc:
        main(["monitor", "--help"])
    assert exc.value.code == 0


def test_cli_monitor_nonexistent(mock_manager, monkeypatch):
    """Test monitor on nonexistent device exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["monitor", "dead:beef:0000"])
    assert exc.value.code == 1


def test_cli_monitor_single_device(mock_manager, monkeypatch):
    """Test monitor on a single device exits cleanly on interrupt."""
    import signal
    import threading
    import time

    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)

    def _send_signal():
        time.sleep(0.2)
        signal.raise_signal(signal.SIGINT)

    t = threading.Thread(target=_send_signal, daemon=True)
    t.start()
    with pytest.raises(SystemExit) as exc:
        main(["monitor", "046d:407f:mock123", "--interval", "1"])
    assert exc.value.code == 0


def test_cli_monitor_all(mock_manager, monkeypatch):
    """Test monitor without device_id monitors all devices."""
    import signal
    import threading
    import time

    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)

    def _send_signal():
        time.sleep(0.2)
        signal.raise_signal(signal.SIGINT)

    t = threading.Thread(target=_send_signal, daemon=True)
    t.start()
    with pytest.raises(SystemExit) as exc:
        main(["monitor", "--interval", "1"])
    assert exc.value.code == 0


def test_cli_monitor_interval_flag():
    """Test monitor --interval is accepted."""
    with pytest.raises(SystemExit) as exc:
        main(["monitor", "--interval", "30", "--help"])
    assert exc.value.code == 0

"""Tests for ghub4linux CLI profile subcommands."""

import pytest

from ghub4linux.cli import main
from ghub4linux.core.config import AppConfig, DeviceConfig, DeviceProfile
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


def test_profile_duplicate_help():
    """Test profile duplicate --help works."""
    with pytest.raises(SystemExit) as exc:
        main(["profile", "duplicate", "--help"])
    assert exc.value.code == 0


def test_profile_duplicate_nonexistent_device(mock_manager, monkeypatch):
    """Test duplicate on nonexistent device exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "duplicate", "dead:beef:0000", "Default"])
    assert exc.value.code == 1


def test_profile_duplicate_nonexistent_profile(mock_manager, monkeypatch):
    """Test duplicate on nonexistent profile exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "duplicate", "046d:407f:mock123", "NoSuchProfile"])
    assert exc.value.code == 1


def test_profile_duplicate_default_name(mock_manager, monkeypatch):
    """Test duplicate creates a profile named '<original> (Copy)'."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "duplicate", "046d:407f:mock123", "Default"])
    assert exc.value.code == 0

    config = mock_manager.app_config.get_device_config("046d:407f:mock123")
    assert config is not None
    names = [p.name for p in config.profiles]
    assert "Default (Copy)" in names
    assert len(config.profiles) == 2


def test_profile_duplicate_custom_name(mock_manager, monkeypatch):
    """Test duplicate with --name creates a profile with the given name."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "duplicate", "046d:407f:mock123", "Default", "--name", "Gaming"])
    assert exc.value.code == 0

    config = mock_manager.app_config.get_device_config("046d:407f:mock123")
    assert config is not None
    names = [p.name for p in config.profiles]
    assert "Gaming" in names
    assert len(config.profiles) == 2


def test_profile_duplicate_duplicate_name(mock_manager, monkeypatch):
    """Test duplicate with an existing name exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "duplicate", "046d:407f:mock123", "Default", "--name", "Default"])
    assert exc.value.code == 1


def test_profile_list(mock_manager, monkeypatch):
    """Test profile list works."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "list", "046d:407f:mock123"])
    assert exc.value.code == 0


def test_profile_create(mock_manager, monkeypatch):
    """Test profile create works."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "create", "046d:407f:mock123", "Gaming"])
    assert exc.value.code == 0

    config = mock_manager.app_config.get_device_config("046d:407f:mock123")
    assert config is not None
    names = [p.name for p in config.profiles]
    assert "Gaming" in names


def test_profile_rename(mock_manager, monkeypatch):
    """Test profile rename works."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "rename", "046d:407f:mock123", "Default", "Work"])
    assert exc.value.code == 0

    config = mock_manager.app_config.get_device_config("046d:407f:mock123")
    assert config is not None
    names = [p.name for p in config.profiles]
    assert "Work" in names
    assert "Default" not in names


def test_profile_delete(mock_manager, monkeypatch):
    """Test profile delete works."""
    # First create a second profile so we can delete one
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "create", "046d:407f:mock123", "Gaming"])
    assert exc.value.code == 0

    # Now delete it
    with pytest.raises(SystemExit) as exc:
        main(["profile", "delete", "046d:407f:mock123", "Gaming"])
    assert exc.value.code == 0

    config = mock_manager.app_config.get_device_config("046d:407f:mock123")
    assert config is not None
    names = [p.name for p in config.profiles]
    assert "Gaming" not in names
    assert len(config.profiles) == 1


def test_profile_switch(mock_manager, monkeypatch):
    """Test profile switch works."""
    # First create a second profile
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "create", "046d:407f:mock123", "Gaming"])
    assert exc.value.code == 0

    # Switch to it
    with pytest.raises(SystemExit) as exc:
        main(["profile", "switch", "046d:407f:mock123", "Gaming"])
    assert exc.value.code == 0

    config = mock_manager.app_config.get_device_config("046d:407f:mock123")
    assert config is not None
    assert config.profiles[config.active_profile].name == "Gaming"

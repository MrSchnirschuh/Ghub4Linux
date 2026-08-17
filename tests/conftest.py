"""Shared pytest fixtures for ghub4linux tests."""

import pytest

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
    from ghub4linux.core.device import BaseDevice
    from ghub4linux.devices.g502 import G502_DEVICES

    monkeypatch.setattr(hid_module, "HIDManager", MockHIDManager)

    # ponytail: avoid importing the real hid library in unit tests.
    def _fake_connect(self):
        self._connection = object()  # truthy placeholder
        self._info = self.get_device_info()
        return True

    def _fake_disconnect(self):
        self._connection = None

    monkeypatch.setattr(BaseDevice, "connect", _fake_connect)
    monkeypatch.setattr(BaseDevice, "disconnect", _fake_disconnect)

    config = AppConfig()
    manager = DeviceManager(config)
    for pid, cls in G502_DEVICES.items():
        manager.register_device_class(pid, cls)
    manager._hid_manager = MockHIDManager()
    return manager

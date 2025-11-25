"""Tests for ghub4linux device module."""

import pytest

from ghub4linux.core.config import DeviceConfig, DPISettings, LightingSettings
from ghub4linux.core.device import (
    BaseDevice,
    BatteryStatus,
    ConnectionType,
    DeviceCapability,
    DeviceInfo,
    DeviceManager,
    DeviceType,
)
from ghub4linux.core.hid import HIDDevice


class MockDevice(BaseDevice):
    """Mock device for testing."""

    def __init__(self, hid_device: HIDDevice, config=None):
        super().__init__(hid_device, config)
        self._capabilities = {
            DeviceCapability.DPI_ADJUSTMENT,
            DeviceCapability.RGB_LIGHTING,
            DeviceCapability.BATTERY_STATUS,
        }
        self._mock_battery = BatteryStatus(level=85, charging=False)

    def _init_device(self):
        self._info = self.get_device_info()

    def get_device_info(self) -> DeviceInfo:
        return DeviceInfo(
            name="Mock Device",
            model="Mock Model",
            vendor_id=0x046D,
            product_id=0x1234,
            serial_number="mock123",
            firmware_version="1.0.0",
            device_type=DeviceType.MOUSE,
            connection_type=ConnectionType.WIRED,
            has_battery=True,
            has_rgb=True,
            max_dpi=16000,
            dpi_step=50,
            button_count=8,
            has_onboard_profiles=True,
        )

    def _get_battery_status(self) -> BatteryStatus:
        return self._mock_battery

    def _set_dpi_settings(self, settings: DPISettings) -> bool:
        self.active_profile.dpi_settings = settings
        return True

    def _set_lighting_settings(self, settings: LightingSettings) -> bool:
        self.active_profile.lighting_settings = settings
        return True


@pytest.fixture
def mock_hid_device():
    """Create a mock HID device."""
    return HIDDevice(
        vendor_id=0x046D,
        product_id=0x1234,
        serial_number="mock123",
        manufacturer="Logitech",
        product="Mock Device",
        path=b"/dev/mock",
        interface_number=0,
        usage_page=0xFF00,
        usage=0x0001,
    )


class TestHIDDevice:
    """Tests for HIDDevice class."""

    def test_device_id(self, mock_hid_device):
        """Test device ID generation."""
        assert mock_hid_device.device_id == "046d:1234:mock123"

    def test_device_properties(self, mock_hid_device):
        """Test device properties."""
        assert mock_hid_device.vendor_id == 0x046D
        assert mock_hid_device.product_id == 0x1234
        assert mock_hid_device.manufacturer == "Logitech"
        assert mock_hid_device.product == "Mock Device"


class TestBaseDevice:
    """Tests for BaseDevice class."""

    def test_device_initialization(self, mock_hid_device):
        """Test device initialization."""
        device = MockDevice(mock_hid_device)

        assert device.device_id == "046d:1234:mock123"
        assert device.name == "Mock Device"

    def test_device_capabilities(self, mock_hid_device):
        """Test device capabilities."""
        device = MockDevice(mock_hid_device)

        assert device.has_capability(DeviceCapability.DPI_ADJUSTMENT)
        assert device.has_capability(DeviceCapability.RGB_LIGHTING)
        assert device.has_capability(DeviceCapability.BATTERY_STATUS)
        assert not device.has_capability(DeviceCapability.FIRMWARE_UPDATE)

    def test_battery_status(self, mock_hid_device):
        """Test battery status retrieval."""
        device = MockDevice(mock_hid_device)

        battery = device.get_battery_status()
        assert battery is not None
        assert battery.level == 85
        assert battery.charging is False

    def test_dpi_settings(self, mock_hid_device):
        """Test DPI settings."""
        device = MockDevice(mock_hid_device)

        settings = device.get_dpi_settings()
        assert settings is not None
        assert len(settings.levels) > 0

        # Modify settings
        from ghub4linux.core.config import DPILevel

        new_settings = DPISettings(
            levels=[DPILevel(dpi=800), DPILevel(dpi=1600)],
            active_level=0,
        )
        result = device.set_dpi_settings(new_settings)
        assert result is True

        # Verify change
        current = device.get_dpi_settings()
        assert len(current.levels) == 2
        assert current.levels[0].dpi == 800

    def test_lighting_settings(self, mock_hid_device):
        """Test lighting settings."""
        device = MockDevice(mock_hid_device)

        settings = device.get_lighting_settings()
        assert settings is not None
        assert settings.enabled is True

        # Modify settings
        new_settings = LightingSettings(enabled=False)
        result = device.set_lighting_settings(new_settings)
        assert result is True

        # Verify change
        current = device.get_lighting_settings()
        assert current.enabled is False

    def test_active_profile(self, mock_hid_device):
        """Test active profile."""
        device = MockDevice(mock_hid_device)

        profile = device.active_profile
        assert profile is not None
        assert profile.name == "Default"

    def test_apply_profile(self, mock_hid_device):
        """Test applying a profile."""
        from ghub4linux.core.config import DeviceProfile

        config = DeviceConfig(
            device_id="test",
            device_name="Test",
            profiles=[
                DeviceProfile(name="Profile 1"),
                DeviceProfile(name="Profile 2"),
            ],
            active_profile=0,
        )
        device = MockDevice(mock_hid_device, config)

        result = device.apply_profile(1)
        assert result is True
        assert device.active_profile.name == "Profile 2"

    def test_apply_invalid_profile(self, mock_hid_device):
        """Test applying invalid profile index."""
        device = MockDevice(mock_hid_device)

        result = device.apply_profile(999)
        assert result is False


class TestDeviceManager:
    """Tests for DeviceManager class."""

    def test_register_device_class(self):
        """Test registering a device class."""
        from ghub4linux.core.config import AppConfig

        config = AppConfig()
        manager = DeviceManager(config)

        manager.register_device_class(0x1234, MockDevice)

        assert 0x1234 in manager._device_registry
        assert manager._device_registry[0x1234] == MockDevice

    def test_get_device(self, mock_hid_device):
        """Test getting a device by ID."""
        from ghub4linux.core.config import AppConfig

        config = AppConfig()
        manager = DeviceManager(config)

        # Manually add device for testing
        device = MockDevice(mock_hid_device)
        manager._devices[device.device_id] = device

        result = manager.get_device(device.device_id)
        assert result is device

        result = manager.get_device("nonexistent")
        assert result is None

    def test_get_all_devices(self, mock_hid_device):
        """Test getting all devices."""
        from ghub4linux.core.config import AppConfig

        config = AppConfig()
        manager = DeviceManager(config)

        # Add multiple devices
        device = MockDevice(mock_hid_device)
        manager._devices[device.device_id] = device

        devices = manager.get_all_devices()
        assert len(devices) == 1
        assert device in devices

    def test_remove_device(self, mock_hid_device):
        """Test removing a device."""
        from ghub4linux.core.config import AppConfig

        config = AppConfig()
        manager = DeviceManager(config)

        device = MockDevice(mock_hid_device)
        manager._devices[device.device_id] = device

        manager.remove_device(device.device_id)

        assert device.device_id not in manager._devices

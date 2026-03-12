"""Tests for ghub4linux configuration module."""

import tempfile
from pathlib import Path

import pytest

from ghub4linux.core.config import (
    AppConfig,
    DeviceConfig,
    DeviceProfile,
    DPILevel,
    DPISettings,
    LightingEffect,
    LightingSettings,
    Macro,
    MacroAction,
    RGBColor,
)


class TestRGBColor:
    """Tests for RGBColor class."""

    def test_default_values(self):
        """Test default RGB values."""
        color = RGBColor()
        assert color.red == 255
        assert color.green == 255
        assert color.blue == 255

    def test_custom_values(self):
        """Test custom RGB values."""
        color = RGBColor(red=128, green=64, blue=32)
        assert color.red == 128
        assert color.green == 64
        assert color.blue == 32

    def test_to_tuple(self):
        """Test conversion to tuple."""
        color = RGBColor(red=100, green=150, blue=200)
        assert color.to_tuple() == (100, 150, 200)

    def test_to_hex(self):
        """Test conversion to hex string."""
        color = RGBColor(red=255, green=128, blue=0)
        assert color.to_hex() == "#ff8000"

    def test_from_hex(self):
        """Test creation from hex string."""
        color = RGBColor.from_hex("#ff8000")
        assert color.red == 255
        assert color.green == 128
        assert color.blue == 0

    def test_from_hex_without_hash(self):
        """Test creation from hex string without hash."""
        color = RGBColor.from_hex("ff8000")
        assert color.red == 255
        assert color.green == 128
        assert color.blue == 0

    def test_validation_bounds(self):
        """Test RGB value bounds validation."""
        with pytest.raises(ValueError):
            RGBColor(red=256, green=0, blue=0)
        with pytest.raises(ValueError):
            RGBColor(red=0, green=-1, blue=0)


class TestDPISettings:
    """Tests for DPISettings class."""

    def test_default_levels(self):
        """Test default DPI levels."""
        settings = DPISettings()
        assert len(settings.levels) == 5
        assert settings.levels[0].dpi == 400
        assert settings.active_level == 1

    def test_custom_levels(self):
        """Test custom DPI levels."""
        levels = [
            DPILevel(dpi=800),
            DPILevel(dpi=1600),
        ]
        settings = DPISettings(levels=levels, active_level=0)
        assert len(settings.levels) == 2
        assert settings.levels[0].dpi == 800


class TestLightingSettings:
    """Tests for LightingSettings class."""

    def test_default_settings(self):
        """Test default lighting settings."""
        settings = LightingSettings()
        assert settings.enabled is True
        assert settings.effect.effect_type == "static"
        assert settings.effect.brightness == 100

    def test_custom_effect(self):
        """Test custom lighting effect."""
        effect = LightingEffect(
            effect_type="breathing",
            color=RGBColor(red=255, green=0, blue=0),
            speed=75,
            brightness=80,
        )
        settings = LightingSettings(enabled=True, effect=effect)
        assert settings.effect.effect_type == "breathing"
        assert settings.effect.color.red == 255


class TestMacro:
    """Tests for Macro class."""

    def test_empty_macro(self):
        """Test empty macro creation."""
        macro = Macro(name="Test Macro")
        assert macro.name == "Test Macro"
        assert len(macro.actions) == 0
        assert macro.repeat_count == 1

    def test_macro_with_actions(self):
        """Test macro with actions."""
        actions = [
            MacroAction(action_type="keypress", value="a"),
            MacroAction(action_type="delay", value=100),
            MacroAction(action_type="keypress", value="b", modifiers=["ctrl"]),
        ]
        macro = Macro(name="Test", actions=actions, repeat_count=3)
        assert len(macro.actions) == 3
        assert macro.repeat_count == 3
        assert macro.actions[2].modifiers == ["ctrl"]


class TestDeviceConfig:
    """Tests for DeviceConfig class."""

    def test_default_config(self):
        """Test default device configuration."""
        config = DeviceConfig(device_id="test:123", device_name="Test Device")
        assert config.device_id == "test:123"
        assert config.device_name == "Test Device"
        assert len(config.profiles) == 1
        assert config.profiles[0].name == "Default"
        assert config.active_profile == 0

    def test_multiple_profiles(self):
        """Test multiple profiles."""
        profiles = [
            DeviceProfile(name="Gaming"),
            DeviceProfile(name="Work"),
            DeviceProfile(name="Default"),
        ]
        config = DeviceConfig(
            device_id="test:123",
            device_name="Test",
            profiles=profiles,
            active_profile=1,
        )
        assert len(config.profiles) == 3
        assert config.active_profile == 1


class TestAppConfig:
    """Tests for AppConfig class."""

    def test_default_config(self):
        """Test default application configuration."""
        config = AppConfig()
        assert config.global_config.language == "en"
        assert len(config.devices) == 0

    def test_save_and_load(self):
        """Test saving and loading configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.json"

            # Create config with device
            config = AppConfig()
            config.global_config.theme = "dark"
            config.devices["test:123"] = DeviceConfig(
                device_id="test:123", device_name="Test Device"
            )

            # Save
            config.save(config_path)

            # Load
            loaded = AppConfig.load(config_path)

            assert loaded.global_config.theme == "dark"
            assert "test:123" in loaded.devices
            assert loaded.devices["test:123"].device_name == "Test Device"

    def test_get_device_config(self):
        """Test getting device configuration."""
        config = AppConfig()
        config.devices["test:123"] = DeviceConfig(
            device_id="test:123", device_name="Test"
        )

        result = config.get_device_config("test:123")
        assert result is not None
        assert result.device_name == "Test"

        result = config.get_device_config("nonexistent")
        assert result is None

    def test_set_device_config(self):
        """Test setting device configuration."""
        config = AppConfig()
        device_config = DeviceConfig(device_id="test:456", device_name="New Device")

        config.set_device_config("test:456", device_config)

        assert "test:456" in config.devices
        assert config.devices["test:456"].device_name == "New Device"

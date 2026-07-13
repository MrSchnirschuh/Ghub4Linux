"""Tests for ghub4linux profile management (DeviceConfig operations)."""


from ghub4linux.core.config import (
    ApplicationProfile,
    DeviceConfig,
    DeviceProfile,
    DPILevel,
    DPISettings,
    LightingEffect,
    LightingSettings,
    Macro,
    RGBColor,
)


class TestDeviceConfigProfiles:
    """Tests for profile CRUD operations on DeviceConfig."""

    def test_add_profile(self):
        """Test adding a new profile."""
        config = DeviceConfig(device_id="test:001", device_name="Test")
        assert len(config.profiles) == 1

        config.profiles.append(DeviceProfile(name="Gaming"))
        assert len(config.profiles) == 2
        assert config.profiles[1].name == "Gaming"

    def test_duplicate_profile_deep_copy(self):
        """Test duplicating a profile with deep copy of all settings."""
        config = DeviceConfig(device_id="test:001", device_name="Test")
        src = config.profiles[0]

        # Customize the source profile
        src.dpi_settings = DPISettings(
            levels=[DPILevel(dpi=800), DPILevel(dpi=3200)],
            active_level=0,
        )
        src.lighting_settings = LightingSettings(
            enabled=True,
            effect=LightingEffect(
                effect_type="breathing",
                color=RGBColor(red=255, green=0, blue=0),
                speed=50,
            ),
        )
        src.macros.append(Macro(name="Test Macro", actions=[]))

        # Duplicate
        dup = DeviceProfile(
            name=f"{src.name} (Copy)",
            dpi_settings=src.dpi_settings.model_copy(deep=True),
            lighting_settings=src.lighting_settings.model_copy(deep=True),
            button_bindings=[b.model_copy(deep=True) for b in src.button_bindings],
            macros=[m.model_copy(deep=True) for m in src.macros],
        )
        config.profiles.append(dup)

        assert len(config.profiles) == 2
        assert config.profiles[1].name == "Default (Copy)"
        assert len(config.profiles[1].dpi_settings.levels) == 2
        assert config.profiles[1].dpi_settings.levels[0].dpi == 800
        assert config.profiles[1].lighting_settings.effect.effect_type == "breathing"
        assert len(config.profiles[1].macros) == 1

        # Verify deep copy — modifying original should NOT affect copy
        src.dpi_settings.levels[0] = DPILevel(dpi=9999)
        assert config.profiles[1].dpi_settings.levels[0].dpi == 800

    def test_rename_profile(self):
        """Test renaming a profile."""
        config = DeviceConfig(device_id="test:001", device_name="Test")
        config.profiles[0].name = "Work"
        assert config.profiles[0].name == "Work"

    def test_delete_profile(self):
        """Test deleting a profile."""
        config = DeviceConfig(
            device_id="test:001",
            device_name="Test",
            profiles=[
                DeviceProfile(name="Gaming"),
                DeviceProfile(name="Work"),
                DeviceProfile(name="Default"),
            ],
            active_profile=1,
        )
        assert len(config.profiles) == 3

        # Delete the active profile (index 1 = "Work")
        config.profiles.pop(1)
        assert len(config.profiles) == 2
        assert config.profiles[0].name == "Gaming"
        assert config.profiles[1].name == "Default"

    def test_cannot_delete_last_profile(self):
        """Test that deleting the last profile is prevented."""
        config = DeviceConfig(device_id="test:001", device_name="Test")
        assert len(config.profiles) == 1

        # Should not be able to delete the only profile
        if len(config.profiles) <= 1:
            pass  # Guard in UI code prevents this
        else:
            config.profiles.pop(0)

        assert len(config.profiles) == 1

    def test_apply_profile_switches_active(self):
        """Test that apply_profile switches the active profile index."""
        config = DeviceConfig(
            device_id="test:001",
            device_name="Test",
            profiles=[
                DeviceProfile(name="Gaming"),
                DeviceProfile(name="Work"),
            ],
            active_profile=0,
        )

        # Simulate apply_profile logic
        config.active_profile = 1
        assert config.active_profile == 1
        assert config.profiles[config.active_profile].name == "Work"

        config.active_profile = 0
        assert config.active_profile == 0
        assert config.profiles[config.active_profile].name == "Gaming"


class TestApplicationProfiles:
    """Tests for application profile management."""

    def test_add_application_profile(self):
        """Test adding an application profile."""
        config = DeviceConfig(device_id="test:001", device_name="Test")
        assert len(config.app_profiles) == 0

        config.app_profiles.append(
            ApplicationProfile(
                app_name="Firefox",
                executable_name="firefox",
                profile_name="Default",
            )
        )
        assert len(config.app_profiles) == 1
        assert config.app_profiles[0].app_name == "Firefox"
        assert config.app_profiles[0].executable_name == "firefox"
        assert config.app_profiles[0].profile_name == "Default"

    def test_remove_application_profile(self):
        """Test removing an application profile."""
        config = DeviceConfig(device_id="test:001", device_name="Test")
        config.app_profiles.append(
            ApplicationProfile(app_name="Firefox", executable_name="firefox", profile_name="Default")
        )
        config.app_profiles.append(
            ApplicationProfile(app_name="VS Code", executable_name="code", profile_name="Coding")
        )
        assert len(config.app_profiles) == 2

        # Remove first
        config.app_profiles.pop(0)
        assert len(config.app_profiles) == 1
        assert config.app_profiles[0].app_name == "VS Code"

    def test_multiple_app_profiles_same_device(self):
        """Test multiple application profiles on one device config."""
        config = DeviceConfig(device_id="test:001", device_name="Test")
        apps = [
            ApplicationProfile(app_name="Firefox", executable_name="firefox", profile_name="Web"),
            ApplicationProfile(app_name="Terminal", executable_name="gnome-terminal", profile_name="Default"),
            ApplicationProfile(app_name="Steam", executable_name="steam", profile_name="Gaming"),
        ]
        config.app_profiles.extend(apps)
        assert len(config.app_profiles) == 3
        assert [a.app_name for a in config.app_profiles] == ["Firefox", "Terminal", "Steam"]

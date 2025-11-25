"""Configuration management for ghub4linux.

Handles loading, saving, and managing user configurations including
device profiles, DPI settings, macros, and application-specific profiles.
"""

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def get_config_dir() -> Path:
    """Get the configuration directory for ghub4linux."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    config_dir = Path(xdg_config) / "ghub4linux"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_data_dir() -> Path:
    """Get the data directory for ghub4linux."""
    xdg_data = os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    data_dir = Path(xdg_data) / "ghub4linux"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


class RGBColor(BaseModel):
    """RGB color representation."""

    red: int = Field(ge=0, le=255, default=255)
    green: int = Field(ge=0, le=255, default=255)
    blue: int = Field(ge=0, le=255, default=255)

    def to_tuple(self) -> tuple[int, int, int]:
        """Convert to tuple."""
        return (self.red, self.green, self.blue)

    def to_hex(self) -> str:
        """Convert to hex string."""
        return f"#{self.red:02x}{self.green:02x}{self.blue:02x}"

    @classmethod
    def from_hex(cls, hex_color: str) -> "RGBColor":
        """Create from hex string."""
        hex_color = hex_color.lstrip("#")
        return cls(
            red=int(hex_color[0:2], 16),
            green=int(hex_color[2:4], 16),
            blue=int(hex_color[4:6], 16),
        )


class DPILevel(BaseModel):
    """DPI level configuration."""

    dpi: int = Field(ge=100, le=32000, default=800)
    color: RGBColor = Field(default_factory=RGBColor)


class DPISettings(BaseModel):
    """DPI settings for a device."""

    levels: list[DPILevel] = Field(default_factory=lambda: [
        DPILevel(dpi=400, color=RGBColor(red=255, green=0, blue=0)),
        DPILevel(dpi=800, color=RGBColor(red=0, green=255, blue=0)),
        DPILevel(dpi=1600, color=RGBColor(red=0, green=0, blue=255)),
        DPILevel(dpi=3200, color=RGBColor(red=255, green=255, blue=0)),
        DPILevel(dpi=6400, color=RGBColor(red=255, green=0, blue=255)),
    ])
    active_level: int = Field(ge=0, le=4, default=1)
    default_dpi: int = Field(ge=100, le=32000, default=800)


class LightingEffect(BaseModel):
    """Lighting effect configuration."""

    effect_type: str = Field(default="static")  # static, breathing, cycle, wave, off
    color: RGBColor = Field(default_factory=RGBColor)
    speed: int = Field(ge=1, le=100, default=50)
    brightness: int = Field(ge=0, le=100, default=100)


class LightingSettings(BaseModel):
    """Lighting settings for a device."""

    enabled: bool = True
    effect: LightingEffect = Field(default_factory=LightingEffect)
    zones: dict[str, LightingEffect] = Field(default_factory=dict)


class MacroAction(BaseModel):
    """A single action in a macro."""

    action_type: str  # keypress, keydown, keyup, delay, mouse_click, mouse_move
    value: Any  # Key code, delay in ms, mouse button, etc.
    modifiers: list[str] = Field(default_factory=list)  # ctrl, shift, alt, meta


class Macro(BaseModel):
    """Macro definition."""

    name: str
    actions: list[MacroAction] = Field(default_factory=list)
    repeat_count: int = Field(ge=1, default=1)
    repeat_while_held: bool = False


class ButtonBinding(BaseModel):
    """Button binding configuration."""

    button_id: int
    action_type: str = "default"  # default, macro, dpi_up, dpi_down, profile_cycle, disabled
    macro_name: str | None = None
    custom_key: str | None = None


class DeviceProfile(BaseModel):
    """Profile for a specific device."""

    name: str = "Default"
    dpi_settings: DPISettings = Field(default_factory=DPISettings)
    lighting_settings: LightingSettings = Field(default_factory=LightingSettings)
    button_bindings: list[ButtonBinding] = Field(default_factory=list)
    macros: list[Macro] = Field(default_factory=list)


class ApplicationProfile(BaseModel):
    """Application-specific profile assignment."""

    app_name: str
    executable_name: str
    profile_name: str


class DeviceConfig(BaseModel):
    """Configuration for a specific device."""

    device_id: str  # vendor_id:product_id:serial
    device_name: str
    profiles: list[DeviceProfile] = Field(
        default_factory=lambda: [DeviceProfile(name="Default")]
    )
    active_profile: int = 0
    app_profiles: list[ApplicationProfile] = Field(default_factory=list)


class GlobalConfig(BaseModel):
    """Global application configuration."""

    version: str = "1.0"
    start_minimized: bool = False
    minimize_to_tray: bool = True
    auto_start: bool = False
    check_updates: bool = True
    language: str = "en"
    theme: str = "system"  # system, light, dark


class AppConfig(BaseModel):
    """Complete application configuration."""

    global_config: GlobalConfig = Field(default_factory=GlobalConfig)
    devices: dict[str, DeviceConfig] = Field(default_factory=dict)

    def save(self, path: Path | None = None) -> None:
        """Save configuration to file."""
        if path is None:
            path = get_config_dir() / "config.json"
        with open(path, "w") as f:
            json.dump(self.model_dump(), f, indent=2)

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        """Load configuration from file."""
        if path is None:
            path = get_config_dir() / "config.json"
        if not path.exists():
            return cls()
        with open(path) as f:
            data = json.load(f)
        return cls.model_validate(data)

    def get_device_config(self, device_id: str) -> DeviceConfig | None:
        """Get configuration for a specific device."""
        return self.devices.get(device_id)

    def set_device_config(self, device_id: str, config: DeviceConfig) -> None:
        """Set configuration for a specific device."""
        self.devices[device_id] = config

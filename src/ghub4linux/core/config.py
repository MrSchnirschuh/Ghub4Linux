"""Configuration management for ghub4linux.

Handles loading, saving, and managing user configurations including
device profiles, DPI settings, macros, and application-specific profiles.

Ponytail: stdlib dataclasses over pydantic — no external dep for config models.
"""

import json
import os
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def get_config_dir() -> Path:
    """Get the configuration directory for ghub4linux."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    config_dir = Path(xdg_config) / "ghub4linux"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


@dataclass
class RGBColor:
    """RGB color representation."""

    red: int = 255
    green: int = 255
    blue: int = 255

    def __post_init__(self) -> None:
        """Validate RGB values are in 0-255 range."""
        for name, val in [("red", self.red), ("green", self.green), ("blue", self.blue)]:
            if not 0 <= val <= 255:
                raise ValueError(f"{name} must be 0-255, got {val}")

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
        if len(hex_color) != 6:
            raise ValueError(f"hex color must be 6 digits, got {hex_color!r}")
        return cls(
            red=int(hex_color[0:2], 16),
            green=int(hex_color[2:4], 16),
            blue=int(hex_color[4:6], 16),
        )


@dataclass
class DPILevel:
    """DPI level configuration."""

    dpi: int = 800
    color: RGBColor = field(default_factory=RGBColor)


@dataclass
class DPISettings:
    """DPI settings for a device."""

    levels: list[DPILevel] = field(
        default_factory=lambda: [
            DPILevel(dpi=400, color=RGBColor(red=255, green=0, blue=0)),
            DPILevel(dpi=800, color=RGBColor(red=0, green=255, blue=0)),
            DPILevel(dpi=1600, color=RGBColor(red=0, green=0, blue=255)),
            DPILevel(dpi=3200, color=RGBColor(red=255, green=255, blue=0)),
            DPILevel(dpi=6400, color=RGBColor(red=255, green=0, blue=255)),
        ]
    )
    active_level: int = 1
    default_dpi: int = 800


@dataclass
class LightingEffect:
    """Lighting effect configuration."""

    effect_type: str = "static"  # static, breathing, cycle, wave, off
    color: RGBColor = field(default_factory=RGBColor)
    speed: int = 50
    brightness: int = 100


@dataclass
class LightingSettings:
    """Lighting settings for a device."""

    enabled: bool = True
    effect: LightingEffect = field(default_factory=LightingEffect)
    zones: dict[str, LightingEffect] = field(default_factory=dict)


@dataclass
class MacroAction:
    """A single action in a macro."""

    action_type: str  # keypress, keydown, keyup, delay, mouse_click, mouse_move
    value: Any  # Key code, delay in ms, mouse button, etc.
    modifiers: list[str] = field(default_factory=list)  # ctrl, shift, alt, meta


@dataclass
class Macro:
    """Macro definition."""

    name: str
    actions: list[MacroAction] = field(default_factory=list)
    repeat_count: int = 1
    repeat_while_held: bool = False


@dataclass
class ButtonBinding:
    """Button binding configuration."""

    button_id: int
    action_type: str = "default"  # default, macro, dpi_up, dpi_down, profile_cycle, disabled
    macro_name: str | None = None
    custom_key: str | None = None


@dataclass
class DeviceProfile:
    """Profile for a specific device."""

    name: str = "Default"
    dpi_settings: DPISettings = field(default_factory=DPISettings)
    lighting_settings: LightingSettings = field(default_factory=LightingSettings)
    button_bindings: list[ButtonBinding] = field(default_factory=list)
    macros: list[Macro] = field(default_factory=list)

    def copy(self, name: str) -> "DeviceProfile":
        """Deep-copy this profile under a new name (all mutable fields duplicated)."""
        return DeviceProfile(
            name=name,
            dpi_settings=deepcopy(self.dpi_settings),
            lighting_settings=deepcopy(self.lighting_settings),
            button_bindings=deepcopy(self.button_bindings),
            macros=deepcopy(self.macros),
        )


@dataclass
class ApplicationProfile:
    """Application-specific profile assignment."""

    app_name: str
    executable_name: str
    profile_name: str


@dataclass
class DeviceConfig:
    """Configuration for a specific device."""

    device_id: str  # vendor_id:product_id:serial
    device_name: str
    profiles: list[DeviceProfile] = field(default_factory=lambda: [DeviceProfile(name="Default")])
    active_profile: int = 0
    app_profiles: list[ApplicationProfile] = field(default_factory=list)


@dataclass
class GlobalConfig:
    """Global application configuration."""

    version: str = "1.0"
    start_minimized: bool = False
    minimize_to_tray: bool = True
    auto_start: bool = False
    check_updates: bool = True
    language: str = "en"
    theme: str = "system"  # system, light, dark


def _from_dict(cls: type, data: dict) -> Any:
    """Recursively reconstruct a dataclass from a dict.

    Handles nested dataclasses, lists of dataclasses, and dicts of dataclasses
    by inspecting type hints.  This is the stdlib equivalent of pydantic's
    ``model_validate``.
    """
    from typing import get_args, get_origin

    if not hasattr(cls, "__dataclass_fields__"):
        return data

    field_types = {}
    for f_name, f_def in cls.__dataclass_fields__.items():
        field_types[f_name] = f_def.type

    kwargs = {}
    for f_name in field_types:
        if f_name not in data:
            continue
        val = data[f_name]
        ftype = field_types[f_name]
        origin = get_origin(ftype)
        args = get_args(ftype)

        if origin is list and args and hasattr(args[0], "__dataclass_fields__"):
            kwargs[f_name] = [_from_dict(args[0], item) for item in val]
        elif (
            origin is dict and args and len(args) == 2 and hasattr(args[1], "__dataclass_fields__")
        ):
            kwargs[f_name] = {k: _from_dict(args[1], v) for k, v in val.items()}  # type: ignore[assignment]
        elif hasattr(ftype, "__dataclass_fields__"):
            kwargs[f_name] = _from_dict(ftype, val)
        else:
            kwargs[f_name] = val

    return cls(**kwargs)


@dataclass
class AppConfig:
    """Complete application configuration."""

    global_config: GlobalConfig = field(default_factory=GlobalConfig)
    devices: dict[str, DeviceConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Track the path this config was loaded from (not serialized)."""
        self._path: Path | None = None

    def save(self, path: Path | None = None) -> None:
        """Save configuration to file."""
        target = path or self._path or get_config_dir() / "config.json"
        with open(target, "w") as f:
            json.dump(asdict(self), f, indent=2)
        self._path = target

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        """Load configuration from file."""
        target = path or get_config_dir() / "config.json"
        if not target.exists():
            new_cfg = cls()
            new_cfg._path = target
            return new_cfg
        with open(target) as f:
            data = json.load(f)
        cfg: AppConfig = _from_dict(cls, data)  # type: ignore[no-any-return]
        cfg._path = target
        return cfg

    def get_device_config(self, device_id: str) -> DeviceConfig | None:
        """Get configuration for a specific device."""
        return self.devices.get(device_id)

    def set_device_config(self, device_id: str, config: DeviceConfig) -> None:
        """Set configuration for a specific device."""
        self.devices[device_id] = config

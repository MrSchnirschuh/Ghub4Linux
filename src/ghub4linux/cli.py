"""CLI interface for ghub4linux — headless device control.

Usage:
  ghub4linux-cli list
  ghub4linux-cli info <device-id>
  ghub4linux-cli battery <device-id>
  ghub4linux-cli dpi <device-id> [--level N] [--dpi N]
  ghub4linux-cli lighting <device-id> [--on|--off] [--effect TYPE] [--brightness N]

Ponytail: argparse over click/typer, helpers dedup boilerplate.
"""

import argparse
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from copy import deepcopy
from dataclasses import asdict
from typing import NoReturn

from . import __version__
from .core.config import (
    AppConfig,
    DeviceConfig,
    DeviceProfile,
    DPILevel,
    LightingEffect,
    _from_dict,
)
from .core.device import DeviceCapability, DeviceManager
from .devices.g502 import G502_DEVICES, G502_RECEIVER_HINTS
from .devices.powerplay import POWERPLAY_RECEIVER_HINTS
from .devices.pro_dex import PRO_DEX_2_DEVICES, PRO_DEX_2_RECEIVER_HINTS

logger = logging.getLogger(__name__)


def _setup_manager() -> DeviceManager:
    config = AppConfig()
    manager = DeviceManager(config)
    for pid, cls in {**G502_DEVICES, **PRO_DEX_2_DEVICES}.items():
        manager.register_device_class(pid, cls)
    for pid, hint, cls in [
        *G502_RECEIVER_HINTS,
        *PRO_DEX_2_RECEIVER_HINTS,
        *POWERPLAY_RECEIVER_HINTS,
    ]:
        manager.register_device_class(pid, cls, hint)
    return manager


def _find_device(manager: DeviceManager, device_id: str) -> None:
    """Resolve device_id, exits with code 1 if not found."""
    manager.scan_devices()
    if not manager.get_device(device_id):
        print(f"Device not found: {device_id}")
        sys.exit(1)


def _save_config(manager: DeviceManager, device_id: str) -> None:
    """Persist the device config and save to disk."""
    device = manager.get_device(device_id)
    if device:
        manager.app_config.set_device_config(device_id, device.config)
    manager.app_config.save()


_running = True


def _signal_handler(signum, frame):  # noqa: ARG001
    global _running
    _running = False


def cmd_list(args: argparse.Namespace) -> None:  # noqa: ARG001
    manager = _setup_manager()
    devices = manager.scan_devices()
    if not devices:
        print("No devices found.")
        return
    for d in devices:
        conn = "connected" if d.is_connected else "disconnected"
        print(f"{d.device_id:40} {d.name:25} {conn}")


def cmd_info(args: argparse.Namespace) -> None:
    manager = _setup_manager()
    _find_device(manager, args.device_id)
    device = manager.get_device(args.device_id)
    info = device.info
    if not info:
        print("Device info not available.")
        return
    print(f"Name:           {info.name}")
    print(f"Model:          {info.model}")
    print(f"Serial:         {info.serial_number}")
    print(f"Firmware:       {info.firmware_version}")
    print(f"Type:           {info.device_type.value}")
    print(f"Connection:     {info.connection_type.value}")
    print(f"Battery:        {'yes' if info.has_battery else 'no'}")
    print(f"RGB:            {'yes' if info.has_rgb else 'no'}")
    print(f"Max DPI:        {info.max_dpi}")
    print(f"Buttons:        {info.button_count}")
    caps = ", ".join(c.value for c in device.capabilities)
    print(f"Capabilities:   {caps}")


def cmd_battery(args: argparse.Namespace) -> None:
    manager = _setup_manager()
    _find_device(manager, args.device_id)
    device = manager.get_device(args.device_id)
    battery = device.get_battery_status()
    if battery is None:
        print("Battery status not supported for this device.")
        return
    status = "charging" if battery.charging else "discharging"
    print(f"Level: {battery.level}% ({status})")
    if battery.voltage is not None:
        print(f"Voltage: {battery.voltage:.3f}V")


def cmd_dpi(args: argparse.Namespace) -> None:
    manager = _setup_manager()
    _find_device(manager, args.device_id)
    device = manager.get_device(args.device_id)
    if not device.has_capability(DeviceCapability.DPI_ADJUSTMENT):
        print("DPI adjustment not supported for this device.")
        return
    settings = device.get_dpi_settings()
    if args.dpi is not None:
        level_idx = args.level if args.level is not None else settings.active_level
        if 0 <= level_idx < len(settings.levels):
            settings.levels[level_idx] = DPILevel(dpi=args.dpi, color=settings.levels[level_idx].color)
            device.set_dpi_settings(settings)
            _save_config(manager, args.device_id)
            print(f"Set DPI level {level_idx + 1} to {args.dpi}")
        else:
            print(f"Invalid level: {level_idx}")
            sys.exit(1)
    else:
        for i, level in enumerate(settings.levels):
            marker = " <-- active" if i == settings.active_level else ""
            print(f"  Level {i + 1}: {level.dpi} DPI  #{level.color.to_hex()}{marker}")


def cmd_lighting(args: argparse.Namespace) -> None:
    manager = _setup_manager()
    _find_device(manager, args.device_id)
    device = manager.get_device(args.device_id)
    if not device.has_capability(DeviceCapability.RGB_LIGHTING):
        print("RGB lighting not supported for this device.")
        return
    settings = device.get_lighting_settings()
    if args.on is not None:
        settings.enabled = args.on
        device.set_lighting_settings(settings)
        _save_config(manager, args.device_id)
        print(f"Lighting {'enabled' if args.on else 'disabled'}")
    elif args.effect is not None:
        settings.effect = LightingEffect(effect_type=args.effect, brightness=args.brightness or settings.effect.brightness)
        device.set_lighting_settings(settings)
        _save_config(manager, args.device_id)
        print(f"Set effect: {args.effect}")
    else:
        print(f"Enabled:    {settings.enabled}")
        print(f"Effect:     {settings.effect.effect_type}")
        print(f"Brightness: {settings.effect.brightness}%")
        print(f"Speed:      {settings.effect.speed}")
        print(f"Color:      #{settings.effect.color.to_hex()}")


def cmd_profile_export(args: argparse.Namespace) -> None:
    """Export device profiles to a JSON file."""
    manager = _setup_manager()
    _find_device(manager, args.device_id)
    device = manager.get_device(args.device_id)
    data = asdict(device.config)
    output = args.output or f"{device.device_id}_profiles.json"
    with open(output, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Exported {len(data['profiles'])} profile(s) to {output}")


def cmd_profile_import(args: argparse.Namespace) -> None:
    """Import device profiles from a JSON file."""
    manager = _setup_manager()
    _find_device(manager, args.device_id)
    device = manager.get_device(args.device_id)
    with open(args.file) as f:
        data = json.load(f)
    imported = _from_dict(DeviceConfig, data)
    device._config = imported
    manager.app_config.set_device_config(args.device_id, imported)
    _save_config(manager, args.device_id)
    print(f"Imported {len(imported.profiles)} profile(s) for {device.name}")


def cmd_profile_list(args: argparse.Namespace) -> None:
    """List all profiles for a device."""
    manager = _setup_manager()
    _find_device(manager, args.device_id)
    device = manager.get_device(args.device_id)
    config = device.config
    for i, profile in enumerate(config.profiles):
        marker = " <-- active" if i == config.active_profile else ""
        print(f"  {i + 1}. {profile.name}{marker}")


def cmd_profile_switch(args: argparse.Namespace) -> None:
    """Switch to a named profile on a device."""
    manager = _setup_manager()
    _find_device(manager, args.device_id)
    device = manager.get_device(args.device_id)
    config = device.config
    for i, profile in enumerate(config.profiles):
        if profile.name == args.profile_name:
            device.apply_profile(i)
            _save_config(manager, args.device_id)
            print(f"Switched to profile: {profile.name}")
            return
    print(f"Profile not found: {args.profile_name}")
    sys.exit(1)


def _find_profile(config, name):
    """Find a profile by name, print error + exit(1) if not found."""
    for p in config.profiles:
        if p.name == name:
            return p
    print(f"Profile not found: {name}")
    sys.exit(1)


def _warn_duplicate(config, name):
    """Exit with code 1 if a profile with *name* already exists."""
    for p in config.profiles:
        if p.name == name:
            print(f"Profile already exists: {name}")
            sys.exit(1)


def cmd_profile_create(args: argparse.Namespace) -> None:
    """Create a new profile on a device."""
    manager = _setup_manager()
    _find_device(manager, args.device_id)
    device = manager.get_device(args.device_id)
    config = device.config
    _warn_duplicate(config, args.profile_name)
    config.profiles.append(DeviceProfile(name=args.profile_name))
    _save_config(manager, args.device_id)
    print(f"Created profile: {args.profile_name}")


def cmd_profile_rename(args: argparse.Namespace) -> None:
    """Rename a profile on a device."""
    manager = _setup_manager()
    _find_device(manager, args.device_id)
    device = manager.get_device(args.device_id)
    config = device.config
    profile = _find_profile(config, args.old_name)
    _warn_duplicate(config, args.new_name)
    profile.name = args.new_name
    _save_config(manager, args.device_id)
    print(f"Renamed profile: {args.old_name} -> {args.new_name}")


def cmd_profile_duplicate(args: argparse.Namespace) -> None:
    """Duplicate a profile on a device."""
    manager = _setup_manager()
    _find_device(manager, args.device_id)
    device = manager.get_device(args.device_id)
    config = device.config
    profile = _find_profile(config, args.profile_name)
    new_name = args.new_name or f"{profile.name} (Copy)"
    _warn_duplicate(config, new_name)
    dup = DeviceProfile(
        name=new_name,
        dpi_settings=deepcopy(profile.dpi_settings),
        lighting_settings=deepcopy(profile.lighting_settings),
        button_bindings=deepcopy(profile.button_bindings),
        macros=deepcopy(profile.macros),
    )
    config.profiles.append(dup)
    _save_config(manager, args.device_id)
    print(f"Duplicated profile: {profile.name} -> {new_name}")


def cmd_profile_delete(args: argparse.Namespace) -> None:
    """Delete a profile from a device."""
    manager = _setup_manager()
    _find_device(manager, args.device_id)
    device = manager.get_device(args.device_id)
    config = device.config
    if len(config.profiles) <= 1:
        print("Cannot delete the last profile.")
        sys.exit(1)
    for i, profile in enumerate(config.profiles):
        if profile.name == args.profile_name:
            config.profiles.pop(i)
            if config.active_profile >= len(config.profiles):
                config.active_profile = len(config.profiles) - 1
            elif config.active_profile > i:
                config.active_profile -= 1
            _save_config(manager, args.device_id)
            print(f"Deleted profile: {args.profile_name}")
            return
    print(f"Profile not found: {args.profile_name}")
    sys.exit(1)


def cmd_profile_copy_to_device(args: argparse.Namespace) -> None:
    """Copy a profile from one device to another."""
    manager = _setup_manager()
    manager.scan_devices()
    src_device = manager.get_device(args.source_device)
    if not src_device:
        print(f"Source device not found: {args.source_device}")
        sys.exit(1)
    dst_device = manager.get_device(args.dest_device)
    if not dst_device:
        print(f"Destination device not found: {args.dest_device}")
        sys.exit(1)
    src_config = src_device.config
    dst_config = dst_device.config
    src_profile = _find_profile(src_config, args.profile_name)
    dst_name = args.new_name or src_profile.name
    _warn_duplicate(dst_config, dst_name)
    dup = DeviceProfile(
        name=dst_name,
        dpi_settings=deepcopy(src_profile.dpi_settings),
        lighting_settings=deepcopy(src_profile.lighting_settings),
        button_bindings=deepcopy(src_profile.button_bindings),
        macros=deepcopy(src_profile.macros),
    )
    dst_config.profiles.append(dup)
    manager.app_config.set_device_config(args.dest_device, dst_config)
    _save_config(manager, args.dest_device)
    print(f"Copied profile '{src_profile.name}' from {src_device.name} to {dst_device.name} as '{dst_name}'")


def cmd_daemon(args: argparse.Namespace) -> None:  # noqa: ARG001
    """Run in daemon mode — scan devices, keep connections alive."""
    manager = _setup_manager()
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    logger.info("ghub4linux daemon starting")
    while _running:
        try:
            devices = manager.scan_devices()
            if devices:
                logger.info("Found %d new device(s)", len(devices))
            for device in manager.get_all_devices():
                if device.is_connected:
                    battery = device.get_battery_status()
                    if battery and battery.level < 20:
                        logger.warning("Low battery: %s at %d%%", device.name, battery.level)
        except Exception as e:
            logger.error("Daemon error: %s", e)
        time.sleep(args.interval)


def cmd_monitor(args: argparse.Namespace) -> None:
    """Monitor device battery levels in real-time."""
    manager = _setup_manager()
    manager.scan_devices()
    if args.device_id:
        device = manager.get_device(args.device_id)
        if not device:
            print(f"Device not found: {args.device_id}")
            sys.exit(1)
        devices = [device]
    else:
        devices = manager.get_all_devices()
        if not devices:
            print("No devices found.")
            return
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    print(f"{'Device':40} {'Battery':8} {'Status':12} {'Voltage':8}")
    print("-" * 70)
    while _running:
        for device in devices:
            if not device.is_connected:
                continue
            battery = device.get_battery_status()
            if battery is None:
                continue
            status = "charging" if battery.charging else "discharging"
            voltage = f"{battery.voltage:.3f}V" if battery.voltage is not None else "N/A"
            print(f"{device.name:40} {battery.level:3d}%     {status:12} {voltage:8}")
        try:
            signal.pause() if args.interval == 0 else time.sleep(args.interval)
        except InterruptedError:
            break
    sys.exit(0)


def cmd_install_daemon(args: argparse.Namespace) -> None:  # noqa: ARG001
    """Install the ghub4linux systemd user service."""
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_path = os.path.join(pkg_dir, "..", "..", "contrib", "ghub4linux@.service")
    if not os.path.exists(src_path):
        src_path = os.path.join(pkg_dir, "contrib", "ghub4linux@.service")
    if not os.path.exists(src_path):
        print("Error: ghub4linux@.service not found", file=sys.stderr)
        sys.exit(1)
    user = args.user or os.environ.get("USER", "pandi")
    unit_name = f"ghub4linux@{user}.service"
    dst = os.path.expanduser(f"~/.config/systemd/user/{unit_name}")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src_path, dst)
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, check=False)
    print(f"Installed: {dst}")
    print(f"Start with: systemctl --user start {unit_name}")
    print(f"Enable with: systemctl --user enable {unit_name}")


def _add_profile_subcommands(sub):
    """Add profile export/import/list/switch subcommands to a subparser group."""
    for name, help_text, fields in [
        ("export", "Export device profiles to JSON",
         [("device_id", {}, {"help": "Device ID"}),
          ("--output", {"-o"}, {"default": None, "help": "Output file path"})]),
        ("import", "Import device profiles from JSON",
         [("device_id", {}, {"help": "Device ID"}),
          ("file", {}, {"help": "JSON file to import"})]),
        ("list", "List all profiles for a device",
         [("device_id", {}, {"help": "Device ID (from list)"})]),
        ("switch", "Switch to a named profile",
         [("device_id", {}, {"help": "Device ID"}),
          ("profile_name", {}, {"help": "Profile name to switch to"})]),
        ("create", "Create a new profile",
         [("device_id", {}, {"help": "Device ID"}),
          ("profile_name", {}, {"help": "Profile name to create"})]),
        ("rename", "Rename a profile",
         [("device_id", {}, {"help": "Device ID"}),
          ("old_name", {}, {"help": "Current profile name"}),
          ("new_name", {}, {"help": "New profile name"})]),
        ("delete", "Delete a profile",
         [("device_id", {}, {"help": "Device ID"}),
          ("profile_name", {}, {"help": "Profile name to delete"})]),
        ("duplicate", "Duplicate a profile",
         [("device_id", {}, {"help": "Device ID"}),
          ("profile_name", {}, {"help": "Profile name to duplicate"}),
          ("--name", {"-n"}, {"dest": "new_name", "default": None,
                              "help": "Name for the new profile (default: '<original> (Copy)')"})]),
        ("copy-to-device", "Copy a profile to another device",
         [("source_device", {}, {"help": "Source device ID"}),
          ("dest_device", {}, {"help": "Destination device ID"}),
          ("profile_name", {}, {"help": "Profile name to copy"}),
          ("--name", {"-n"}, {"dest": "new_name", "default": None,
                              "help": "Name on destination (default: same as source)"})]),
    ]:
        p = sub.add_parser(name, help=help_text)
        for arg_name, flags, kwargs in fields:
            if isinstance(flags, dict):
                p.add_argument(arg_name, **kwargs)
            else:
                p.add_argument(*flags, arg_name, **kwargs)  # type: ignore[arg-type]
        p.set_defaults(func=globals()[f"cmd_profile_{name.replace('-', '_')}"])


def main(argv: list[str] | None = None) -> NoReturn:
    parser = argparse.ArgumentParser(prog="ghub4linux-cli", description="Headless Logitech device control")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text, fields in [
        ("list", "List connected devices", []),
        ("info", "Show device info", [("device_id", {}, {"help": "Device ID (from list)"})]),
        ("battery", "Show battery status", [("device_id", {}, {"help": "Device ID"})]),
        ("dpi", "Get/set DPI settings",
         [("device_id", {}, {"help": "Device ID"}),
          ("--level", {}, {"type": int, "default": None, "help": "DPI level index (0-based)"}),
          ("--dpi", {}, {"type": int, "default": None, "help": "DPI value to set"})]),
        ("lighting", "Get/set lighting settings",
         [("device_id", {}, {"help": "Device ID"}),
          ("--on", {}, {"action": "store_true", "default": None, "dest": "on"}),
          ("--off", {}, {"action": "store_false", "dest": "on"}),
          ("--effect", {}, {"choices": ["static", "breathing", "cycle", "wave", "off"], "default": None}),
          ("--brightness", {}, {"type": int, "default": None, "help": "Brightness 0-100"})]),
        ("daemon", "Run as headless daemon",
         [("--interval", {}, {"type": int, "default": 60, "help": "Poll interval in seconds (default: 60)"})]),
        ("install-daemon", "Install systemd user service for headless daemon",
         [("--user", {}, {"default": None, "help": "Systemd user (default: current user)"})]),
        ("monitor", "Monitor device battery levels in real-time",
         [("device_id", {}, {"nargs": "?", "default": None, "help": "Device ID (omit for all devices)"}),
          ("--interval", {}, {"type": int, "default": 5, "help": "Poll interval in seconds (default: 5)"})]),
    ]:
        p = sub.add_parser(name, help=help_text)
        for arg_name, _, kwargs in fields:
            p.add_argument(arg_name, **kwargs)
        p.set_defaults(func=globals()[f"cmd_{name.replace('-', '_')}"])  # type: ignore[arg-type]

    p_profile = sub.add_parser("profile", help="Manage device profiles")
    _add_profile_subcommands(p_profile.add_subparsers(dest="profile_command", required=True))

    args = parser.parse_args(argv)
    args.func(args)
    sys.exit(0)


if __name__ == "__main__":
    main()

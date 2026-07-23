"""CLI interface for ghub4linux — headless device control.

Usage:
  ghub4linux-cli list
  ghub4linux-cli info <device-id>
  ghub4linux-cli battery <device-id>
  ghub4linux-cli dpi <device-id> [--level N] [--dpi N]
  ghub4linux-cli lighting <device-id> [--on|--off] [--effect TYPE] [--brightness N]

Ponytail: argparse over click/typer — zero new deps.
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
from typing import NoReturn

from .core.config import AppConfig, DPILevel, LightingEffect
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
    manager.scan_devices()
    device = manager.get_device(args.device_id)
    if not device:
        print(f"Device not found: {args.device_id}")
        sys.exit(1)
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
    manager.scan_devices()
    device = manager.get_device(args.device_id)
    if not device:
        print(f"Device not found: {args.device_id}")
        sys.exit(1)
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
    manager.scan_devices()
    device = manager.get_device(args.device_id)
    if not device:
        print(f"Device not found: {args.device_id}")
        sys.exit(1)
    if not device.has_capability(DeviceCapability.DPI_ADJUSTMENT):
        print("DPI adjustment not supported for this device.")
        return
    settings = device.get_dpi_settings()
    if args.dpi is not None:
        level_idx = args.level if args.level is not None else settings.active_level
        if 0 <= level_idx < len(settings.levels):
            settings.levels[level_idx] = DPILevel(dpi=args.dpi, color=settings.levels[level_idx].color)
            device.set_dpi_settings(settings)
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
    manager.scan_devices()
    device = manager.get_device(args.device_id)
    if not device:
        print(f"Device not found: {args.device_id}")
        sys.exit(1)
    if not device.has_capability(DeviceCapability.RGB_LIGHTING):
        print("RGB lighting not supported for this device.")
        return
    settings = device.get_lighting_settings()
    if args.on is not None:
        settings.enabled = args.on
        device.set_lighting_settings(settings)
        print(f"Lighting {'enabled' if args.on else 'disabled'}")
    elif args.effect is not None:
        settings.effect = LightingEffect(effect_type=args.effect, brightness=args.brightness or settings.effect.brightness)
        device.set_lighting_settings(settings)
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
    manager.scan_devices()
    device = manager.get_device(args.device_id)
    if not device:
        print(f"Device not found: {args.device_id}")
        sys.exit(1)

    data = device.config.model_dump()
    output = args.output or f"{device.device_id}_profiles.json"
    with open(output, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Exported {len(data['profiles'])} profile(s) to {output}")


def cmd_profile_import(args: argparse.Namespace) -> None:
    """Import device profiles from a JSON file."""
    manager = _setup_manager()
    manager.scan_devices()
    device = manager.get_device(args.device_id)
    if not device:
        print(f"Device not found: {args.device_id}")
        sys.exit(1)

    with open(args.file) as f:
        data = json.load(f)

    from .core.config import DeviceConfig
    imported = DeviceConfig.model_validate(data)
    device._config = imported
    manager.app_config.set_device_config(args.device_id, imported)
    manager.app_config.save()
    print(f"Imported {len(imported.profiles)} profile(s) for {device.name}")


def cmd_profile_list(args: argparse.Namespace) -> None:
    """List all profiles for a device."""
    manager = _setup_manager()
    manager.scan_devices()
    device = manager.get_device(args.device_id)
    if not device:
        print(f"Device not found: {args.device_id}")
        sys.exit(1)

    config = device.config
    for i, profile in enumerate(config.profiles):
        marker = " <-- active" if i == config.active_profile else ""
        print(f"  {i + 1}. {profile.name}{marker}")


def cmd_profile_switch(args: argparse.Namespace) -> None:
    """Switch to a named profile on a device."""
    manager = _setup_manager()
    manager.scan_devices()
    device = manager.get_device(args.device_id)
    if not device:
        print(f"Device not found: {args.device_id}")
        sys.exit(1)

    config = device.config
    for i, profile in enumerate(config.profiles):
        if profile.name == args.profile_name:
            device.apply_profile(i)
            manager.app_config.set_device_config(args.device_id, config)
            manager.app_config.save()
            print(f"Switched to profile: {profile.name}")
            return

    print(f"Profile not found: {args.profile_name}")
    sys.exit(1)


def cmd_profile_create(args: argparse.Namespace) -> None:
    """Create a new profile on a device."""
    manager = _setup_manager()
    manager.scan_devices()
    device = manager.get_device(args.device_id)
    if not device:
        print(f"Device not found: {args.device_id}")
        sys.exit(1)

    config = device.config
    # Check for duplicate name
    for p in config.profiles:
        if p.name == args.profile_name:
            print(f"Profile already exists: {args.profile_name}")
            sys.exit(1)

    from .core.config import DeviceProfile

    config.profiles.append(DeviceProfile(name=args.profile_name))
    manager.app_config.set_device_config(args.device_id, config)
    manager.app_config.save()
    print(f"Created profile: {args.profile_name}")


def cmd_profile_rename(args: argparse.Namespace) -> None:
    """Rename a profile on a device."""
    manager = _setup_manager()
    manager.scan_devices()
    device = manager.get_device(args.device_id)
    if not device:
        print(f"Device not found: {args.device_id}")
        sys.exit(1)

    config = device.config
    for profile in config.profiles:
        if profile.name == args.old_name:
            # Check new name doesn't conflict
            for p in config.profiles:
                if p.name == args.new_name:
                    print(f"Profile already exists: {args.new_name}")
                    sys.exit(1)
            profile.name = args.new_name
            manager.app_config.set_device_config(args.device_id, config)
            manager.app_config.save()
            print(f"Renamed profile: {args.old_name} -> {args.new_name}")
            return

    print(f"Profile not found: {args.old_name}")
    sys.exit(1)


def cmd_profile_delete(args: argparse.Namespace) -> None:
    """Delete a profile from a device."""
    manager = _setup_manager()
    manager.scan_devices()
    device = manager.get_device(args.device_id)
    if not device:
        print(f"Device not found: {args.device_id}")
        sys.exit(1)

    config = device.config
    if len(config.profiles) <= 1:
        print("Cannot delete the last profile.")
        sys.exit(1)

    for i, profile in enumerate(config.profiles):
        if profile.name == args.profile_name:
            config.profiles.pop(i)
            # Adjust active_profile if needed
            if config.active_profile >= len(config.profiles):
                config.active_profile = len(config.profiles) - 1
            elif config.active_profile > i:
                config.active_profile -= 1
            manager.app_config.set_device_config(args.device_id, config)
            manager.app_config.save()
            print(f"Deleted profile: {args.profile_name}")
            return

    print(f"Profile not found: {args.profile_name}")
    sys.exit(1)


def cmd_daemon(args: argparse.Namespace) -> None:  # noqa: ARG001
    """Run in daemon mode — scan devices, keep connections alive."""
    manager = _setup_manager()
    running = True

    def _handle_signal(signum, frame):  # noqa: ARG001
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("ghub4linux daemon starting")
    while running:
        try:
            devices = manager.scan_devices()
            if devices:
                logger.info("Found %d new device(s)", len(devices))
            for device in manager.get_all_devices():
                if device.is_connected:
                    battery = device.get_battery_status()
                    if battery and battery.level < 20:
                        logger.warning(
                            "Low battery: %s at %d%%", device.name, battery.level
                        )
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

    running = True

    def _handle_signal(signum, frame):  # noqa: ARG001
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    print(f"{'Device':40} {'Battery':8} {'Status':12} {'Voltage':8}")
    print("-" * 70)
    while running:
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
    # Locate the service file relative to the package
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_path = os.path.join(pkg_dir, "..", "..", "contrib", "ghub4linux@.service")
    if not os.path.exists(src_path):
        # Fallback: look relative to the installed package
        src_path = os.path.join(pkg_dir, "contrib", "ghub4linux@.service")
    if not os.path.exists(src_path):
        print("Error: ghub4linux@.service not found", file=sys.stderr)
        sys.exit(1)

    user = args.user or os.environ.get("USER", "pandi")
    unit_name = f"ghub4linux@{user}.service"
    dst = os.path.expanduser(f"~/.config/systemd/user/{unit_name}")

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src_path, dst)

    subprocess.run(
        ["systemctl", "--user", "daemon-reload"], capture_output=True, check=False
    )
    print(f"Installed: {dst}")
    print(f"Start with: systemctl --user start {unit_name}")
    print(f"Enable with: systemctl --user enable {unit_name}")


def _add_profile_subcommands(sub):
    """Add profile export/import/list/switch subcommands to a subparser group."""
    p_export = sub.add_parser("export", help="Export device profiles to JSON")
    p_export.add_argument("device_id", help="Device ID")
    p_export.add_argument("--output", "-o", default=None, help="Output file path")
    p_export.set_defaults(func=cmd_profile_export)

    p_import = sub.add_parser("import", help="Import device profiles from JSON")
    p_import.add_argument("device_id", help="Device ID")
    p_import.add_argument("file", help="JSON file to import")
    p_import.set_defaults(func=cmd_profile_import)

    p_list = sub.add_parser("list", help="List all profiles for a device")
    p_list.add_argument("device_id", help="Device ID")
    p_list.set_defaults(func=cmd_profile_list)

    p_switch = sub.add_parser("switch", help="Switch to a named profile")
    p_switch.add_argument("device_id", help="Device ID")
    p_switch.add_argument("profile_name", help="Profile name to switch to")
    p_switch.set_defaults(func=cmd_profile_switch)

    p_create = sub.add_parser("create", help="Create a new profile")
    p_create.add_argument("device_id", help="Device ID")
    p_create.add_argument("profile_name", help="Profile name to create")
    p_create.set_defaults(func=cmd_profile_create)

    p_rename = sub.add_parser("rename", help="Rename a profile")
    p_rename.add_argument("device_id", help="Device ID")
    p_rename.add_argument("old_name", help="Current profile name")
    p_rename.add_argument("new_name", help="New profile name")
    p_rename.set_defaults(func=cmd_profile_rename)

    p_delete = sub.add_parser("delete", help="Delete a profile")
    p_delete.add_argument("device_id", help="Device ID")
    p_delete.add_argument("profile_name", help="Profile name to delete")
    p_delete.set_defaults(func=cmd_profile_delete)


def main(argv: list[str] | None = None) -> NoReturn:
    parser = argparse.ArgumentParser(prog="ghub4linux-cli", description="Headless Logitech device control")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List connected devices")
    p_list.set_defaults(func=cmd_list)

    p_info = sub.add_parser("info", help="Show device info")
    p_info.add_argument("device_id", help="Device ID (from list)")
    p_info.set_defaults(func=cmd_info)

    p_bat = sub.add_parser("battery", help="Show battery status")
    p_bat.add_argument("device_id", help="Device ID")
    p_bat.set_defaults(func=cmd_battery)

    p_dpi = sub.add_parser("dpi", help="Get/set DPI settings")
    p_dpi.add_argument("device_id", help="Device ID")
    p_dpi.add_argument("--level", type=int, default=None, help="DPI level index (0-based)")
    p_dpi.add_argument("--dpi", type=int, default=None, help="DPI value to set")
    p_dpi.set_defaults(func=cmd_dpi)

    p_light = sub.add_parser("lighting", help="Get/set lighting settings")
    p_light.add_argument("device_id", help="Device ID")
    p_light.add_argument("--on", action="store_true", default=None, dest="on")
    p_light.add_argument("--off", action="store_false", dest="on")
    p_light.add_argument("--effect", choices=["static", "breathing", "cycle", "wave", "off"], default=None)
    p_light.add_argument("--brightness", type=int, default=None, help="Brightness 0-100")
    p_light.set_defaults(func=cmd_lighting)

    p_daemon = sub.add_parser("daemon", help="Run as headless daemon")
    p_daemon.add_argument("--interval", type=int, default=60, help="Poll interval in seconds (default: 60)")
    p_daemon.set_defaults(func=cmd_daemon)

    p_install = sub.add_parser("install-daemon", help="Install systemd user service for headless daemon")
    p_install.add_argument("--user", default=None, help="Systemd user (default: current user)")
    p_install.set_defaults(func=cmd_install_daemon)

    p_monitor = sub.add_parser("monitor", help="Monitor device battery levels in real-time")
    p_monitor.add_argument("device_id", nargs="?", default=None, help="Device ID (omit for all devices)")
    p_monitor.add_argument("--interval", type=int, default=5, help="Poll interval in seconds (default: 5)")
    p_monitor.set_defaults(func=cmd_monitor)

    p_profile = sub.add_parser("profile", help="Export/import device profiles")
    _add_profile_subcommands(p_profile.add_subparsers(dest="profile_command", required=True))

    args = parser.parse_args(argv)
    args.func(args)
    sys.exit(0)


if __name__ == "__main__":
    main()

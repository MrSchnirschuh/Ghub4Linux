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
import logging
import sys
from typing import NoReturn

from .core.config import AppConfig
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
            from .core.config import DPILevel
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
        from .core.config import LightingEffect
        settings.effect = LightingEffect(effect_type=args.effect, brightness=args.brightness or settings.effect.brightness)
        device.set_lighting_settings(settings)
        print(f"Set effect: {args.effect}")
    else:
        print(f"Enabled:    {settings.enabled}")
        print(f"Effect:     {settings.effect.effect_type}")
        print(f"Brightness: {settings.effect.brightness}%")
        print(f"Speed:      {settings.effect.speed}")
        print(f"Color:      #{settings.effect.color.to_hex()}")


def cmd_daemon(args: argparse.Namespace) -> None:  # noqa: ARG001
    """Run in daemon mode — scan devices, keep connections alive."""
    import signal
    import time

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

    args = parser.parse_args(argv)
    args.func(args)
    sys.exit(0)


if __name__ == "__main__":
    main()

"""Device information panel."""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk  # noqa: E402

from ..core.device import BaseDevice  # noqa: E402

logger = logging.getLogger(__name__)


class InfoPanel(Gtk.Box):
    """Panel for device information and firmware."""

    def __init__(self, device: BaseDevice):
        """Initialize info panel."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.device = device
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)

        # Title
        title = Gtk.Label(label="Device Information")
        title.add_css_class("title-1")
        title.set_halign(Gtk.Align.START)
        self.append(title)

        info = device.info
        if info:
            # Info grid
            grid = Gtk.Grid()
            grid.set_column_spacing(24)
            grid.set_row_spacing(8)

            info_items = [
                ("Name", info.name),
                ("Model", info.model),
                ("Serial Number", info.serial_number or "N/A"),
                ("Firmware", info.firmware_version),
                ("Connection", info.connection_type.value),
                ("Max DPI", str(info.max_dpi)),
                ("Buttons", str(info.button_count)),
            ]

            for i, (label, value) in enumerate(info_items):
                label_widget = Gtk.Label(label=f"{label}:")
                label_widget.set_halign(Gtk.Align.START)
                label_widget.add_css_class("dim-label")
                grid.attach(label_widget, 0, i, 1, 1)

                value_widget = Gtk.Label(label=value)
                value_widget.set_halign(Gtk.Align.START)
                value_widget.set_selectable(True)
                grid.attach(value_widget, 1, i, 1, 1)

            self.append(grid)

        # Battery section
        battery_title = Gtk.Label(label="Battery")
        battery_title.add_css_class("title-2")
        battery_title.set_halign(Gtk.Align.START)
        battery_title.set_margin_top(24)
        self.append(battery_title)

        battery = device.get_battery_status()
        if battery:
            battery_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

            level_bar = Gtk.LevelBar()
            level_bar.set_min_value(0)
            level_bar.set_max_value(100)
            level_bar.set_value(battery.level)
            level_bar.set_hexpand(True)
            battery_box.append(level_bar)

            status_text = f"{battery.level}%"
            if battery.charging:
                status_text += " (Charging)"
            battery_label = Gtk.Label(label=status_text)
            battery_box.append(battery_label)

            self.append(battery_box)
        else:
            no_battery = Gtk.Label(label="No battery (wired connection)")
            no_battery.add_css_class("dim-label")
            no_battery.set_halign(Gtk.Align.START)
            self.append(no_battery)

        # Firmware section
        firmware_title = Gtk.Label(label="Firmware")
        firmware_title.add_css_class("title-2")
        firmware_title.set_halign(Gtk.Align.START)
        firmware_title.set_margin_top(24)
        self.append(firmware_title)

        firmware_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        firmware_label = Gtk.Label(label=f"Current version: {device.get_firmware_version()}")
        firmware_label.set_halign(Gtk.Align.START)
        firmware_box.append(firmware_label)

        update_btn = Gtk.Button(label="Check for Updates")
        update_btn.connect("clicked", self._on_check_updates)
        firmware_box.append(update_btn)

        self.append(firmware_box)

    def _on_check_updates(self, _button: Gtk.Button) -> None:
        """Check for firmware updates."""
        logger.info("Checking for firmware updates")
        # ponytail: stub — real check needs Logitech's firmware API endpoint
        self.get_root().show_toast("Firmware update check: not yet implemented")

"""Device row widget for the sidebar device list."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk  # noqa: E402

from ..core.device import BaseDevice  # noqa: E402


class DeviceRow(Gtk.ListBoxRow):
    """A row representing a connected device."""

    def __init__(self, device: BaseDevice):
        """Initialize device row."""
        super().__init__()
        self.device = device

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)

        # Device icon
        icon = Gtk.Image.new_from_icon_name("input-mouse-symbolic")
        icon.set_pixel_size(32)
        box.append(icon)

        # Device info
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_box.set_hexpand(True)

        name_label = Gtk.Label(label=device.name)
        name_label.set_halign(Gtk.Align.START)
        name_label.add_css_class("heading")
        info_box.append(name_label)

        if device.info:
            status_text = f"Connected • {device.info.connection_type.value}"
            status_label = Gtk.Label(label=status_text)
            status_label.set_halign(Gtk.Align.START)
            status_label.add_css_class("dim-label")
            info_box.append(status_label)

        box.append(info_box)

        # Battery indicator (if available)
        battery = device.get_battery_status()
        if battery:
            battery_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)

            battery_icon = Gtk.Image.new_from_icon_name(
                "battery-level-80-charging-symbolic"
                if battery.charging
                else "battery-level-80-symbolic"
            )
            battery_box.append(battery_icon)

            battery_label = Gtk.Label(label=f"{battery.level}%")
            battery_box.append(battery_label)

            box.append(battery_box)

        self.set_child(box)

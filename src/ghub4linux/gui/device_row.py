"""Device row widget for the sidebar device list."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk  # noqa: E402

from ..core.device import BaseDevice, DeviceType  # noqa: E402


class DeviceRow(Gtk.ListBoxRow):
    """A row representing a connected device.

    Styled as a card rather than a plain list item, which is how G HUB's sidebar
    reads: rounded, with the device name, its connection state and the battery
    level at a glance.
    """

    def __init__(self, device: BaseDevice):
        """Initialize device row."""
        super().__init__()
        self.device = device
        self.add_css_class("ghub-device-row")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)

        device_type = device.info.device_type if device.info else DeviceType.MOUSE
        icon = Gtk.Image.new_from_icon_name(
            "input-touchpad-symbolic"
            if device_type == DeviceType.MOUSEPAD
            else "input-mouse-symbolic"
        )
        icon.set_pixel_size(28)
        box.append(icon)

        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        info_box.set_hexpand(True)

        name_label = Gtk.Label(label=device.name)
        name_label.set_halign(Gtk.Align.START)
        name_label.set_ellipsize(3)  # Pango.EllipsizeMode.END
        name_label.add_css_class("ghub-device-name")
        info_box.append(name_label)

        battery = device.get_battery_status()
        if battery:
            state = "Charging" if battery.charging else "On battery"
            status_text = f"{battery.level}% • {state}"
        elif device.info:
            status_text = device.info.connection_type.value.replace("_", " ").title()
        else:
            status_text = "Connected" if device.is_connected else "Offline"

        status_label = Gtk.Label(label=status_text)
        status_label.set_halign(Gtk.Align.START)
        status_label.add_css_class("ghub-device-meta")
        if battery and battery.level <= 15:
            status_label.add_css_class("ghub-battery-low")
        info_box.append(status_label)

        box.append(info_box)
        self.set_child(box)

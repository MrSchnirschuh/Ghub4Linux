"""Device information panel."""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gio, Gtk  # noqa: E402

from ..core.device import BaseDevice  # noqa: E402
from ..core.firmware import FirmwareCatalog, FirmwareCheck, check_firmware  # noqa: E402

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
        title.add_css_class("ghub-panel-title")
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
        battery_title.add_css_class("ghub-section-title")
        battery_title.set_halign(Gtk.Align.START)
        battery_title.set_margin_top(24)
        self.append(battery_title)

        battery = device.get_battery_status()
        if battery and battery.level is not None:
            battery_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

            level_bar = Gtk.LevelBar()
            level_bar.set_min_value(0)
            level_bar.set_max_value(100)
            level_bar.set_value(battery.level)
            level_bar.set_hexpand(True)
            battery_box.append(level_bar)

            # A level derived from voltage is marked as an estimate; a device
            # that reports no percentage at all must not be shown a fake one.
            prefix = "≈" if battery.estimated else ""
            status_text = f"{prefix}{battery.level}%"
            if battery.charging is True:
                status_text += " (Charging)"
            elif battery.charging is None:
                status_text += " (charge state unknown)"
            battery_label = Gtk.Label(label=status_text)
            battery_box.append(battery_label)

            self.append(battery_box)
        elif battery:
            # The device answers, but reports no percentage: say so rather than
            # inventing a number for it.
            detail = battery.status_text or "no percentage reported"
            no_level = Gtk.Label(label=f"Charge level not reported by this device ({detail})")
            no_level.add_css_class("dim-label")
            no_level.set_halign(Gtk.Align.START)
            no_level.set_wrap(True)
            self.append(no_level)
        else:
            no_battery = Gtk.Label(label="No battery (wired connection)")
            no_battery.add_css_class("dim-label")
            no_battery.set_halign(Gtk.Align.START)
            self.append(no_battery)

        # Firmware section
        firmware_title = Gtk.Label(label="Firmware")
        firmware_title.add_css_class("ghub-section-title")
        firmware_title.set_halign(Gtk.Align.START)
        firmware_title.set_margin_top(24)
        self.append(firmware_title)

        firmware_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        firmware_label = Gtk.Label(label=f"Current version: {device.get_firmware_version()}")
        firmware_label.set_halign(Gtk.Align.START)
        firmware_box.append(firmware_label)

        self.update_btn = Gtk.Button(label="Check for Updates")
        self.update_btn.connect("clicked", self._on_check_updates)
        firmware_box.append(self.update_btn)

        self.append(firmware_box)

        # Result of the last check, so the panel can explain itself.
        self.result_label = Gtk.Label(label="")
        self.result_label.set_halign(Gtk.Align.START)
        self.result_label.set_wrap(True)
        self.result_label.add_css_class("dim-label")
        self.result_label.set_visible(False)
        self.append(self.result_label)

    def _on_check_updates(self, _button: Gtk.Button) -> None:
        """Check the device against the firmware catalog fwupd maintains.

        The check runs off the main loop: reading the LVFS catalog means
        decompressing ~20 MB, which would visibly stall the window.
        """
        logger.info("Checking for firmware updates")
        self.update_btn.set_sensitive(False)
        self.update_btn.set_label("Checking…")
        self._show_result("Reading the firmware catalog…")

        def work(*_args: object) -> None:
            """Runs in the worker thread; the result travels via the Task."""
            task = _args[0]
            assert isinstance(task, Gio.Task)
            task.return_value(check_firmware(self.device, FirmwareCatalog()))

        def done(_source: object, task: Gio.Task) -> None:
            try:
                check = task.propagate_value().value
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Firmware check failed: {exc}")
                self._show_result("Could not read the firmware catalog.")
            else:
                assert isinstance(check, FirmwareCheck)
                self._show_result(check.message)
            finally:
                self.update_btn.set_sensitive(True)
                self.update_btn.set_label("Check for Updates")

        task = Gio.Task.new(None, None, done)
        task.run_in_thread(work)

    def _show_result(self, message: str) -> None:
        """Show the outcome inside the panel (and as a toast when possible)."""
        self.result_label.set_label(message)
        self.result_label.set_visible(True)
        root = self.get_root()
        if root is not None and hasattr(root, "show_toast"):
            root.show_toast(message)

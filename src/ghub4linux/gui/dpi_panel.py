"""DPI settings panel."""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gdk, Gtk  # noqa: E402

from ..core.config import DPILevel, DPISettings, RGBColor  # noqa: E402
from ..core.device import BaseDevice  # noqa: E402

logger = logging.getLogger(__name__)


class DPIPanel(Gtk.Box):
    """Panel for DPI settings."""

    def __init__(self, device: BaseDevice):
        """Initialize DPI panel."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.device = device
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)

        # Title
        title = Gtk.Label(label="DPI Settings")
        title.add_css_class("title-1")
        title.set_halign(Gtk.Align.START)
        self.append(title)

        # DPI levels
        settings = device.get_dpi_settings()
        max_dpi = device.info.max_dpi if device.info else 25600

        self.dpi_scales: list[Gtk.Scale] = []
        self.color_buttons: list[Gtk.ColorButton] = []

        for i, level in enumerate(settings.levels):
            level_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

            label = Gtk.Label(label=f"Level {i + 1}")
            label.set_width_chars(8)
            level_box.append(label)

            scale = Gtk.Scale.new_with_range(
                Gtk.Orientation.HORIZONTAL, 100, max_dpi, 50
            )
            scale.set_value(level.dpi)
            scale.set_hexpand(True)
            scale.set_draw_value(True)
            self.dpi_scales.append(scale)
            level_box.append(scale)

            # Color button
            color = level.color
            rgba = self._rgb_to_rgba(color)
            color_btn = Gtk.ColorButton.new_with_rgba(rgba)
            self.color_buttons.append(color_btn)
            level_box.append(color_btn)

            self.append(level_box)

        # Active level selector
        active_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        active_box.set_margin_top(12)

        active_label = Gtk.Label(label="Active Level:")
        active_box.append(active_label)

        self.active_combo = Gtk.ComboBoxText()
        for i in range(len(settings.levels)):
            self.active_combo.append_text(f"Level {i + 1}")
        self.active_combo.set_active(settings.active_level)
        active_box.append(self.active_combo)

        self.append(active_box)

        # Apply button
        apply_btn = Gtk.Button(label="Apply DPI Settings")
        apply_btn.add_css_class("suggested-action")
        apply_btn.set_margin_top(24)
        apply_btn.connect("clicked", self._on_apply)
        self.append(apply_btn)

    def _rgb_to_rgba(self, color: RGBColor) -> Gdk.RGBA:
        """Convert RGBColor to Gdk.RGBA."""
        rgba = Gdk.RGBA()
        rgba.red = color.red / 255.0
        rgba.green = color.green / 255.0
        rgba.blue = color.blue / 255.0
        rgba.alpha = 1.0
        return rgba

    def _on_apply(self, _button: Gtk.Button) -> None:
        """Apply DPI settings."""
        levels = []
        for scale, color_btn in zip(self.dpi_scales, self.color_buttons, strict=True):
            dpi = int(scale.get_value())
            rgba = color_btn.get_rgba()
            color = RGBColor(
                red=int(rgba.red * 255),
                green=int(rgba.green * 255),
                blue=int(rgba.blue * 255),
            )
            levels.append(DPILevel(dpi=dpi, color=color))

        settings = DPISettings(
            levels=levels,
            active_level=self.active_combo.get_active(),
            default_dpi=levels[0].dpi if levels else 800,
        )

        root = self.get_root()
        if self.device.set_dpi_settings(settings):
            # Persist the updated profile to disk
            if hasattr(root, "config"):
                root.config.set_device_config(self.device.device_id, self.device.config)
                root.config.save()
            if hasattr(root, "show_toast"):
                root.show_toast("DPI settings applied")
            logger.info("DPI settings applied")
        else:
            if hasattr(root, "show_toast"):
                root.show_toast("Failed to apply DPI settings")
            logger.error("Failed to apply DPI settings")

"""Lighting/RGB settings panel."""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gdk, Gtk  # noqa: E402

from ..core.config import LightingEffect, LightingSettings, RGBColor  # noqa: E402
from ..core.device import BaseDevice  # noqa: E402

logger = logging.getLogger(__name__)


class LightingPanel(Gtk.Box):
    """Panel for lighting/RGB settings."""

    def __init__(self, device: BaseDevice):
        """Initialize lighting panel."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.device = device
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)

        # Title
        title = Gtk.Label(label="Lighting Settings")
        title.add_css_class("title-1")
        title.set_halign(Gtk.Align.START)
        self.append(title)

        settings = device.get_lighting_settings()

        # Enable toggle
        enable_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        enable_label = Gtk.Label(label="Enable Lighting")
        enable_box.append(enable_label)

        self.enable_switch = Gtk.Switch()
        self.enable_switch.set_active(settings.enabled)
        self.enable_switch.set_halign(Gtk.Align.END)
        self.enable_switch.set_hexpand(True)
        enable_box.append(self.enable_switch)
        self.append(enable_box)

        # Effect selector
        effect_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        effect_label = Gtk.Label(label="Effect")
        effect_box.append(effect_label)

        self.effect_combo = Gtk.ComboBoxText()
        effects = ["Static", "Breathing", "Color Cycle", "Wave", "Off"]
        for effect in effects:
            self.effect_combo.append_text(effect)
        self.effect_combo.set_active(0)
        effect_box.append(self.effect_combo)
        self.append(effect_box)

        # Color picker
        color_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        color_label = Gtk.Label(label="Color")
        color_box.append(color_label)

        rgba = Gdk.RGBA()
        rgba.red = settings.effect.color.red / 255.0
        rgba.green = settings.effect.color.green / 255.0
        rgba.blue = settings.effect.color.blue / 255.0
        rgba.alpha = 1.0

        self.color_button = Gtk.ColorButton.new_with_rgba(rgba)
        color_box.append(self.color_button)
        self.append(color_box)

        # Brightness slider
        brightness_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        brightness_label = Gtk.Label(label="Brightness")
        brightness_box.append(brightness_label)

        self.brightness_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0, 100, 5
        )
        self.brightness_scale.set_value(settings.effect.brightness)
        self.brightness_scale.set_hexpand(True)
        brightness_box.append(self.brightness_scale)
        self.append(brightness_box)

        # Speed slider
        speed_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        speed_label = Gtk.Label(label="Speed")
        speed_box.append(speed_label)

        self.speed_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 100, 1)
        self.speed_scale.set_value(settings.effect.speed)
        self.speed_scale.set_hexpand(True)
        speed_box.append(self.speed_scale)
        self.append(speed_box)

        # Apply button
        apply_btn = Gtk.Button(label="Apply Lighting")
        apply_btn.add_css_class("suggested-action")
        apply_btn.set_margin_top(24)
        apply_btn.connect("clicked", self._on_apply)
        self.append(apply_btn)

    def _on_apply(self, _button: Gtk.Button) -> None:
        """Apply lighting settings."""

        rgba = self.color_button.get_rgba()
        color = RGBColor(
            red=int(rgba.red * 255),
            green=int(rgba.green * 255),
            blue=int(rgba.blue * 255),
        )

        effect_names = ["static", "breathing", "cycle", "wave", "off"]
        effect_type = effect_names[self.effect_combo.get_active()]

        effect = LightingEffect(
            effect_type=effect_type,
            color=color,
            speed=int(self.speed_scale.get_value()),
            brightness=int(self.brightness_scale.get_value()),
        )

        settings = LightingSettings(enabled=self.enable_switch.get_active(), effect=effect)

        root = self.get_root()
        if self.device.set_lighting_settings(settings):
            # Persist the updated profile to disk
            if hasattr(root, "config"):
                root.config.set_device_config(self.device.device_id, self.device.config)
                root.config.save()
            if hasattr(root, "show_toast"):
                root.show_toast("Lighting settings applied")
            logger.info("Lighting settings applied")
        else:
            if hasattr(root, "show_toast"):
                root.show_toast("Failed to apply lighting settings")
            logger.error("Failed to apply lighting settings")

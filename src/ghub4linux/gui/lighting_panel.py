"""Lighting/RGB settings panel."""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gdk, Gtk  # noqa: E402

from ..core.config import LightingEffect, LightingSettings, RGBColor  # noqa: E402
from ..core.device import BaseDevice  # noqa: E402
from ..core.speed import speed_for_effect  # noqa: E402

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
        title.add_css_class("ghub-panel-title")
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

        # Effect selector.
        #
        # The list comes from the device, not from a catalogue: the POWERPLAY
        # pad's engine offers only Disabled and FixedColor, so offering
        # Breathing/Cycle/Wave here meant picking an effect that the firmware
        # silently refused and nothing happened.
        supported = self._supported_effects()
        effect_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        effect_label = Gtk.Label(label="Effect")
        effect_box.append(effect_label)

        self.effect_combo = Gtk.ComboBoxText()
        self.effect_names = supported
        for effect in supported:
            self.effect_combo.append_text(effect.capitalize())
        self.effect_combo.connect("changed", self._on_speed_changed)
        self.effect_combo.set_active(0)
        self.effect_combo.set_hexpand(True)
        effect_box.append(self.effect_combo)
        self.append(effect_box)

        if len(supported) == 1:
            note = Gtk.Label(label=f"This device offers a single effect ({supported[0]}).")
            note.add_css_class("dim-label")
            note.set_halign(Gtk.Align.START)
            note.set_wrap(True)
            self.append(note)

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

        # Cycling runs a colour sequence of its own in the firmware: a colour
        # sent for it is ignored, so offering a colour picker would promise
        # something the hardware cannot do.  The swatch is replaced by a note
        # and the picker comes back when an effect that does use a colour is
        # chosen.
        self.color_note = Gtk.Label(
            label=(
                "This effect animates through its own colour sequence, so the "
                "colour above does not apply to it."
            )
        )
        self.color_note.add_css_class("dim-label")
        self.color_note.set_halign(Gtk.Align.START)
        self.color_note.set_wrap(True)
        self.append(self.color_note)

        # Brightness slider
        brightness_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        brightness_label = Gtk.Label(label="Brightness")
        brightness_box.append(brightness_label)

        self.brightness_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.brightness_scale.set_value(settings.effect.brightness)
        self.brightness_scale.set_hexpand(True)
        brightness_box.append(self.brightness_scale)
        self.append(brightness_box)

        # Speed slider.
        #
        # The slider offers "speed" (higher is faster) and the conversion into
        # the period the wire wants happens in the driver.  The resulting period
        # is shown next to it, because the effect ranges differ widely (Cycling
        # only animates from 4000 ms upwards) and seeing the value makes that
        # understandable instead of surprising.
        speed_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        speed_label = Gtk.Label(label="Speed")
        speed_box.append(speed_label)

        self.speed_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.speed_scale.set_value(settings.effect.speed)
        self.speed_scale.set_hexpand(True)
        self.speed_scale.connect("value-changed", self._on_speed_changed)
        speed_box.append(self.speed_scale)

        self.period_label = Gtk.Label(label="")
        self.period_label.add_css_class("dim-label")
        self.period_label.set_width_chars(22)
        self.period_label.set_halign(Gtk.Align.END)
        speed_box.append(self.period_label)
        self.append(speed_box)
        self._update_period_label()

        # Apply button
        apply_btn = Gtk.Button(label="Apply Lighting")
        apply_btn.add_css_class("suggested-action")
        apply_btn.set_margin_top(24)
        apply_btn.connect("clicked", self._on_apply)
        self.append(apply_btn)

    def _selected_effect_id(self) -> int | None:
        """Effect ID of the currently selected effect, if it is known."""
        index = self.effect_combo.get_active()
        if not (0 <= index < len(self.effect_names)):
            return None
        name = self.effect_names[index]
        getter = getattr(self.device, "lighting_effect_ids", None)
        if callable(getter):
            mapping = getter()
            if name in mapping:
                found = mapping[name]
                if isinstance(found, int):
                    return found
        from ..core.rgb import EFFECT_IDS_BY_NAME

        ids = EFFECT_IDS_BY_NAME.get(name)
        return ids[0] if ids else None

    def _update_period_label(self) -> None:
        """Show the period the current speed produces for the chosen effect."""
        if not hasattr(self, "period_label"):
            return
        # Keep the colour controls in step here too, since this runs both when
        # the effect changes and when the widget is first built.
        self._update_colour_visibility()
        speed = int(self.speed_scale.get_value())
        effect_id = self._selected_effect_id()
        if effect_id is None:
            self.period_label.set_text(f"speed {speed}")
            return
        period = speed_for_effect(effect_id, speed)
        self.period_label.set_text(f"{period} ms per cycle")

    def _on_speed_changed(self, *_args: object) -> None:
        """Keep the period readout and the colour controls in step."""
        self._update_period_label()
        self._update_colour_visibility()

    def _selected_effect_takes_colour(self) -> bool:
        """Whether the chosen effect uses a colour the host supplies.

        Unknown or unreadable effects default to True, so a device whose
        metadata cannot be read still gets the colour picker rather than
        silently losing the control.
        """
        index = self.effect_combo.get_active()
        if not (0 <= index < len(self.effect_names)):
            return True
        name = self.effect_names[index]
        rgb = getattr(self.device, "_rgb", None)
        if rgb is None:
            return True
        for zone in rgb.zones:
            for entry in zone.effects:
                if entry.config_name == name:
                    return bool(entry.takes_colour)
        return True

    def _update_colour_visibility(self) -> None:
        """Hide the colour picker for effects that ignore the colour."""
        takes = self._selected_effect_takes_colour()
        self.color_button.set_visible(takes)
        self.color_note.set_visible(not takes)

    def _supported_effects(self) -> list[str]:
        """Effects the device itself reports, falling back to a sane minimum.

        A driver that can enumerate its engine answers here; one that cannot
        gets "static" only, because claiming more would offer choices that do
        nothing.
        """
        getter = getattr(self.device, "supported_lighting_effects", None)
        if callable(getter):
            try:
                effects = getter()
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"could not read supported effects: {exc}")
                effects = []
            if effects:
                return list(effects)
        return ["static"]

    def _on_apply(self, _button: Gtk.Button) -> None:
        """Apply lighting settings."""

        rgba = self.color_button.get_rgba()
        color = RGBColor(
            red=int(rgba.red * 255),
            green=int(rgba.green * 255),
            blue=int(rgba.blue * 255),
        )

        index = self.effect_combo.get_active()
        effect_type = self.effect_names[index] if 0 <= index < len(self.effect_names) else "static"

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

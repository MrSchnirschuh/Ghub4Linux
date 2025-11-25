"""Main application window for GLinux."""

import logging
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..core.config import AppConfig, DPILevel, DPISettings, LightingSettings, RGBColor  # noqa: E402
from ..core.device import BaseDevice, DeviceCapability, DeviceManager  # noqa: E402

logger = logging.getLogger(__name__)


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
            scale.connect("value-changed", self._on_dpi_changed, i)
            self.dpi_scales.append(scale)
            level_box.append(scale)

            # Color button
            color = level.color
            rgba = self._rgb_to_rgba(color)
            color_btn = Gtk.ColorButton.new_with_rgba(rgba)
            color_btn.connect("color-set", self._on_color_changed, i)
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
        self.active_combo.connect("changed", self._on_active_changed)
        active_box.append(self.active_combo)

        self.append(active_box)

        # Apply button
        apply_btn = Gtk.Button(label="Apply DPI Settings")
        apply_btn.add_css_class("suggested-action")
        apply_btn.set_margin_top(24)
        apply_btn.connect("clicked", self._on_apply)
        self.append(apply_btn)

    def _rgb_to_rgba(self, color: RGBColor) -> Any:
        """Convert RGBColor to Gdk.RGBA."""
        from gi.repository import Gdk

        rgba = Gdk.RGBA()
        rgba.red = color.red / 255.0
        rgba.green = color.green / 255.0
        rgba.blue = color.blue / 255.0
        rgba.alpha = 1.0
        return rgba

    def _on_dpi_changed(self, scale: Gtk.Scale, level_index: int) -> None:
        """Handle DPI value change."""
        pass  # Will apply on button click

    def _on_color_changed(self, button: Gtk.ColorButton, level_index: int) -> None:
        """Handle color change."""
        pass  # Will apply on button click

    def _on_active_changed(self, combo: Gtk.ComboBoxText) -> None:
        """Handle active level change."""
        pass  # Will apply on button click

    def _on_apply(self, _button: Gtk.Button) -> None:
        """Apply DPI settings."""
        levels = []
        for _i, scale in enumerate(self.dpi_scales):
            dpi = int(scale.get_value())
            # Get current color (simplified)
            color = RGBColor(red=255, green=255, blue=255)
            levels.append(DPILevel(dpi=dpi, color=color))

        settings = DPISettings(
            levels=levels,
            active_level=self.active_combo.get_active(),
            default_dpi=levels[0].dpi if levels else 800,
        )

        if self.device.set_dpi_settings(settings):
            logger.info("DPI settings applied")
        else:
            logger.error("Failed to apply DPI settings")


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

        from gi.repository import Gdk

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

        from ..core.config import LightingEffect

        effect = LightingEffect(
            effect_type=effect_type,
            color=color,
            speed=int(self.speed_scale.get_value()),
            brightness=int(self.brightness_scale.get_value()),
        )

        settings = LightingSettings(enabled=self.enable_switch.get_active(), effect=effect)

        if self.device.set_lighting_settings(settings):
            logger.info("Lighting settings applied")
        else:
            logger.error("Failed to apply lighting settings")


class MacroPanel(Gtk.Box):
    """Panel for macro management."""

    def __init__(self, device: BaseDevice):
        """Initialize macro panel."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.device = device
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)

        # Title
        title = Gtk.Label(label="Macros")
        title.add_css_class("title-1")
        title.set_halign(Gtk.Align.START)
        self.append(title)

        # Macro list
        self.macro_list = Gtk.ListBox()
        self.macro_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.macro_list.add_css_class("boxed-list")

        # Add existing macros
        profile = device.active_profile
        for macro in profile.macros:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=macro.name)
            label.set_margin_top(12)
            label.set_margin_bottom(12)
            label.set_margin_start(12)
            row.set_child(label)
            self.macro_list.append(row)

        if not profile.macros:
            placeholder = Gtk.Label(label="No macros defined")
            placeholder.add_css_class("dim-label")
            placeholder.set_margin_top(24)
            placeholder.set_margin_bottom(24)
            self.macro_list.append(placeholder)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(self.macro_list)
        scrolled.set_min_content_height(200)
        scrolled.set_vexpand(True)
        self.append(scrolled)

        # Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_margin_top(12)

        record_btn = Gtk.Button(label="Record Macro")
        record_btn.connect("clicked", self._on_record)
        btn_box.append(record_btn)

        edit_btn = Gtk.Button(label="Edit")
        edit_btn.connect("clicked", self._on_edit)
        btn_box.append(edit_btn)

        delete_btn = Gtk.Button(label="Delete")
        delete_btn.add_css_class("destructive-action")
        delete_btn.connect("clicked", self._on_delete)
        btn_box.append(delete_btn)

        self.append(btn_box)

    def _on_record(self, _button: Gtk.Button) -> None:
        """Start recording a macro."""
        logger.info("Start macro recording")
        # TODO: Implement macro recording dialog

    def _on_edit(self, _button: Gtk.Button) -> None:
        """Edit selected macro."""
        logger.info("Edit macro")
        # TODO: Implement macro editor

    def _on_delete(self, _button: Gtk.Button) -> None:
        """Delete selected macro."""
        logger.info("Delete macro")
        # TODO: Implement deletion


class ProfilePanel(Gtk.Box):
    """Panel for profile management."""

    def __init__(self, device: BaseDevice):
        """Initialize profile panel."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.device = device
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)

        # Title
        title = Gtk.Label(label="Profiles")
        title.add_css_class("title-1")
        title.set_halign(Gtk.Align.START)
        self.append(title)

        # Profile selector
        profile_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        profile_label = Gtk.Label(label="Active Profile:")
        profile_box.append(profile_label)

        self.profile_combo = Gtk.ComboBoxText()
        config = device.config
        for profile in config.profiles:
            self.profile_combo.append_text(profile.name)
        self.profile_combo.set_active(config.active_profile)
        self.profile_combo.connect("changed", self._on_profile_changed)
        profile_box.append(self.profile_combo)

        self.append(profile_box)

        # Profile buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        btn_box.set_margin_top(12)

        new_btn = Gtk.Button(label="New Profile")
        new_btn.connect("clicked", self._on_new_profile)
        btn_box.append(new_btn)

        duplicate_btn = Gtk.Button(label="Duplicate")
        duplicate_btn.connect("clicked", self._on_duplicate)
        btn_box.append(duplicate_btn)

        rename_btn = Gtk.Button(label="Rename")
        rename_btn.connect("clicked", self._on_rename)
        btn_box.append(rename_btn)

        delete_btn = Gtk.Button(label="Delete")
        delete_btn.add_css_class("destructive-action")
        delete_btn.connect("clicked", self._on_delete)
        btn_box.append(delete_btn)

        self.append(btn_box)

        # Application profiles section
        app_title = Gtk.Label(label="Application Profiles")
        app_title.add_css_class("title-2")
        app_title.set_halign(Gtk.Align.START)
        app_title.set_margin_top(24)
        self.append(app_title)

        app_desc = Gtk.Label(
            label="Automatically switch profiles based on the active application"
        )
        app_desc.add_css_class("dim-label")
        app_desc.set_halign(Gtk.Align.START)
        self.append(app_desc)

        # Application profile list
        self.app_list = Gtk.ListBox()
        self.app_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.app_list.add_css_class("boxed-list")

        for app_profile in config.app_profiles:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(12)

            app_label = Gtk.Label(label=app_profile.app_name)
            app_label.set_hexpand(True)
            app_label.set_halign(Gtk.Align.START)
            box.append(app_label)

            profile_label = Gtk.Label(label=f"→ {app_profile.profile_name}")
            profile_label.add_css_class("dim-label")
            box.append(profile_label)

            row.set_child(box)
            self.app_list.append(row)

        if not config.app_profiles:
            placeholder = Gtk.Label(label="No application profiles defined")
            placeholder.add_css_class("dim-label")
            placeholder.set_margin_top(12)
            placeholder.set_margin_bottom(12)
            self.app_list.append(placeholder)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(self.app_list)
        scrolled.set_min_content_height(150)
        self.append(scrolled)

        # App profile buttons
        app_btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        app_btn_box.set_margin_top(12)

        add_app_btn = Gtk.Button(label="Add Application")
        add_app_btn.connect("clicked", self._on_add_app)
        app_btn_box.append(add_app_btn)

        remove_app_btn = Gtk.Button(label="Remove")
        remove_app_btn.add_css_class("destructive-action")
        remove_app_btn.connect("clicked", self._on_remove_app)
        app_btn_box.append(remove_app_btn)

        self.append(app_btn_box)

    def _on_profile_changed(self, combo: Gtk.ComboBoxText) -> None:
        """Handle profile change."""
        index = combo.get_active()
        self.device.apply_profile(index)
        logger.info(f"Switched to profile {index}")

    def _on_new_profile(self, _button: Gtk.Button) -> None:
        """Create new profile."""
        logger.info("Create new profile")

    def _on_duplicate(self, _button: Gtk.Button) -> None:
        """Duplicate current profile."""
        logger.info("Duplicate profile")

    def _on_rename(self, _button: Gtk.Button) -> None:
        """Rename current profile."""
        logger.info("Rename profile")

    def _on_delete(self, _button: Gtk.Button) -> None:
        """Delete current profile."""
        logger.info("Delete profile")

    def _on_add_app(self, _button: Gtk.Button) -> None:
        """Add application profile."""
        logger.info("Add application profile")

    def _on_remove_app(self, _button: Gtk.Button) -> None:
        """Remove application profile."""
        logger.info("Remove application profile")


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
        # TODO: Implement firmware update check


class MainWindow(Adw.ApplicationWindow):
    """Main application window."""

    def __init__(self, app: Adw.Application, config: AppConfig):
        """Initialize main window."""
        super().__init__(application=app)
        self.config = config
        self.device_manager = DeviceManager(config)

        # Register device classes
        from ..devices.g502 import G502_DEVICES
        from ..devices.pro_dex import PRO_DEX_2_DEVICES

        for pid, cls in {**G502_DEVICES, **PRO_DEX_2_DEVICES}.items():
            self.device_manager.register_device_class(pid, cls)

        self.set_title("GLinux")
        self.set_default_size(1000, 700)

        # Create main layout
        self._create_ui()

        # Scan for devices
        GLib.idle_add(self._scan_devices)

    def _create_ui(self) -> None:
        """Create the user interface."""
        # Main content
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        # Sidebar for device list
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.set_size_request(280, -1)
        sidebar.add_css_class("sidebar")

        # Sidebar header
        sidebar_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        sidebar_header.set_margin_top(12)
        sidebar_header.set_margin_bottom(12)
        sidebar_header.set_margin_start(12)
        sidebar_header.set_margin_end(12)

        devices_label = Gtk.Label(label="Devices")
        devices_label.add_css_class("heading")
        devices_label.set_hexpand(True)
        devices_label.set_halign(Gtk.Align.START)
        sidebar_header.append(devices_label)

        refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        refresh_btn.add_css_class("flat")
        refresh_btn.connect("clicked", lambda _: self._scan_devices())
        sidebar_header.append(refresh_btn)

        sidebar.append(sidebar_header)

        # Device list
        self.device_list = Gtk.ListBox()
        self.device_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.device_list.connect("row-selected", self._on_device_selected)

        scrolled_sidebar = Gtk.ScrolledWindow()
        scrolled_sidebar.set_child(self.device_list)
        scrolled_sidebar.set_vexpand(True)
        sidebar.append(scrolled_sidebar)

        main_box.append(sidebar)

        # Separator
        separator = Gtk.Separator(orientation=Gtk.Orientation.VERTICAL)
        main_box.append(separator)

        # Content area
        self.content_stack = Gtk.Stack()
        self.content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.content_stack.set_hexpand(True)
        self.content_stack.set_vexpand(True)

        # Empty state
        empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        empty_box.set_valign(Gtk.Align.CENTER)
        empty_box.set_halign(Gtk.Align.CENTER)

        empty_icon = Gtk.Image.new_from_icon_name("input-mouse-symbolic")
        empty_icon.set_pixel_size(64)
        empty_icon.add_css_class("dim-label")
        empty_box.append(empty_icon)

        empty_label = Gtk.Label(label="No device selected")
        empty_label.add_css_class("title-2")
        empty_box.append(empty_label)

        empty_desc = Gtk.Label(label="Select a device from the sidebar or connect a Logitech device")
        empty_desc.add_css_class("dim-label")
        empty_box.append(empty_desc)

        self.content_stack.add_named(empty_box, "empty")

        main_box.append(self.content_stack)

        # Header bar
        header = Adw.HeaderBar()

        # Menu button
        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")

        menu = Gio.Menu()
        menu.append("Preferences", "app.preferences")
        menu.append("About GLinux", "app.about")
        menu.append("Quit", "app.quit")
        menu_btn.set_menu_model(menu)

        header.pack_end(menu_btn)

        # Main layout with header
        outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer_box.append(header)
        outer_box.append(main_box)

        self.set_content(outer_box)

    def _scan_devices(self) -> bool:
        """Scan for connected devices."""
        # Clear existing device list
        while True:
            row = self.device_list.get_row_at_index(0)
            if row:
                self.device_list.remove(row)
            else:
                break

        # Scan for devices
        devices = self.device_manager.scan_devices()

        if not devices:
            # Add placeholder for demo/testing
            self._add_demo_devices()
        else:
            for device in devices:
                device.connect()
                row = DeviceRow(device)
                self.device_list.append(row)

        return False

    def _add_demo_devices(self) -> None:
        """Add demo devices for testing without hardware."""
        from ..core.hid import HIDDevice

        # Create mock devices for demonstration
        demo_devices = [
            HIDDevice(
                vendor_id=0x046D,
                product_id=0x407F,
                serial_number="demo001",
                manufacturer="Logitech",
                product="G502 Lightspeed",
                path=b"/dev/demo1",
                interface_number=0,
                usage_page=0xFF00,
                usage=0x0001,
            ),
            HIDDevice(
                vendor_id=0x046D,
                product_id=0x4099,
                serial_number="demo002",
                manufacturer="Logitech",
                product="G502 X Plus",
                path=b"/dev/demo2",
                interface_number=0,
                usage_page=0xFF00,
                usage=0x0001,
            ),
        ]

        from ..devices.g502 import G502Lightspeed, G502XPlus

        device_classes = [G502Lightspeed, G502XPlus]

        for hid_dev, dev_cls in zip(demo_devices, device_classes, strict=True):
            device = dev_cls(hid_dev)
            device._info = device.get_device_info()
            self.device_manager._devices[hid_dev.device_id] = device
            row = DeviceRow(device)
            self.device_list.append(row)

    def _on_device_selected(
        self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None
    ) -> None:
        """Handle device selection."""
        if not row or not isinstance(row, DeviceRow):
            self.content_stack.set_visible_child_name("empty")
            return

        device = row.device
        device_id = device.device_id

        # Create or show device panel
        if not self.content_stack.get_child_by_name(device_id):
            panel = self._create_device_panel(device)
            self.content_stack.add_named(panel, device_id)

        self.content_stack.set_visible_child_name(device_id)

    def _create_device_panel(self, device: BaseDevice) -> Gtk.Widget:
        """Create a panel for a device."""
        # Tab view for device settings
        notebook = Gtk.Notebook()

        # DPI tab
        if device.has_capability(DeviceCapability.DPI_ADJUSTMENT):
            dpi_panel = DPIPanel(device)
            dpi_scroll = Gtk.ScrolledWindow()
            dpi_scroll.set_child(dpi_panel)
            notebook.append_page(dpi_scroll, Gtk.Label(label="DPI"))

        # Lighting tab
        if device.has_capability(DeviceCapability.RGB_LIGHTING):
            lighting_panel = LightingPanel(device)
            lighting_scroll = Gtk.ScrolledWindow()
            lighting_scroll.set_child(lighting_panel)
            notebook.append_page(lighting_scroll, Gtk.Label(label="Lighting"))

        # Macros tab
        if device.has_capability(DeviceCapability.MACROS):
            macro_panel = MacroPanel(device)
            macro_scroll = Gtk.ScrolledWindow()
            macro_scroll.set_child(macro_panel)
            notebook.append_page(macro_scroll, Gtk.Label(label="Macros"))

        # Profiles tab
        profile_panel = ProfilePanel(device)
        profile_scroll = Gtk.ScrolledWindow()
        profile_scroll.set_child(profile_panel)
        notebook.append_page(profile_scroll, Gtk.Label(label="Profiles"))

        # Info tab
        info_panel = InfoPanel(device)
        info_scroll = Gtk.ScrolledWindow()
        info_scroll.set_child(info_panel)
        notebook.append_page(info_scroll, Gtk.Label(label="Info"))

        return notebook

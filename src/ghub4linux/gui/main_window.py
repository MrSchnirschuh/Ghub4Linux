"""Main application window for ghub4linux."""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..core.config import AppConfig  # noqa: E402
from ..core.device import BaseDevice, DeviceCapability, DeviceManager  # noqa: E402
from .device_row import DeviceRow  # noqa: E402
from .dpi_panel import DPIPanel  # noqa: E402
from .info_panel import InfoPanel  # noqa: E402
from .lighting_panel import LightingPanel  # noqa: E402
from .macro_panel import MacroPanel  # noqa: E402
from .profile_panel import ProfilePanel  # noqa: E402

logger = logging.getLogger(__name__)


class MainWindow(Adw.ApplicationWindow):
    """Main application window."""

    def __init__(self, app: Adw.Application, config: AppConfig):
        """Initialize main window."""
        super().__init__(application=app)
        self.config = config
        self.device_manager = DeviceManager(config)

        # Register device classes
        from ..devices.g502 import G502_DEVICES, G502_RECEIVER_HINTS
        from ..devices.powerplay import POWERPLAY_RECEIVER_HINTS
        from ..devices.pro_dex import PRO_DEX_2_DEVICES, PRO_DEX_2_RECEIVER_HINTS

        for pid, cls in {**G502_DEVICES, **PRO_DEX_2_DEVICES}.items():
            self.device_manager.register_device_class(pid, cls)

        # Register hint-based entries for shared Lightspeed receiver PIDs
        for pid, hint, cls in [
            *G502_RECEIVER_HINTS,
            *PRO_DEX_2_RECEIVER_HINTS,
            *POWERPLAY_RECEIVER_HINTS,
        ]:
            self.device_manager.register_device_class(pid, cls, hint)

        self.set_title("ghub4linux")
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
        menu.append("About ghub4linux", "app.about")
        menu.append("Quit", "app.quit")
        menu_btn.set_menu_model(menu)

        header.pack_end(menu_btn)

        # Main layout with header
        outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer_box.append(header)
        outer_box.append(main_box)

        # Wrap everything in a ToastOverlay for notifications
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(outer_box)
        self.set_content(self.toast_overlay)

    def show_toast(self, message: str) -> None:
        """Display a brief notification toast."""
        toast = Adw.Toast(title=message)
        self.toast_overlay.add_toast(toast)

    def _scan_devices(self) -> bool:
        """Scan for connected devices and refresh the sidebar."""
        # Clear existing device list
        while True:
            row = self.device_list.get_row_at_index(0)
            if row:
                self.device_list.remove(row)
            else:
                break

        # scan_devices() creates device objects and calls device.connect()
        devices = self.device_manager.scan_devices()
        logger.info(f"Device scan complete: {len(devices)} new device(s) found")

        if not devices:
            # Add placeholder for demo/testing
            self._add_demo_devices()
        else:
            for device in devices:
                logger.info(f"  {device.name}: {'connected' if device.is_connected else 'not connected'}")
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
            HIDDevice(
                vendor_id=0x046D,
                product_id=0xC53A,
                serial_number="demo003",
                manufacturer="Logitech",
                product="Powerplay Wireless Charging System",
                path=b"/dev/demo3",
                interface_number=0,
                usage_page=0xFF00,
                usage=0x0001,
            ),
        ]

        from ..devices.g502 import G502Lightspeed, G502XPlus
        from ..devices.powerplay import Powerplay

        device_classes = [G502Lightspeed, G502XPlus, Powerplay]

        for hid_dev, dev_cls in zip(demo_devices, device_classes, strict=True):
            device = dev_cls(hid_dev)
            device._info = device.get_device_info()
            self.device_manager.add_device(device)
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

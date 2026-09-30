"""Main application window for ghub4linux."""

import logging
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from ..core.config import AppConfig  # noqa: E402
from ..core.device import BaseDevice, DeviceCapability, DeviceManager  # noqa: E402
from .device_row import DeviceRow  # noqa: E402
from .dpi_panel import DPIPanel  # noqa: E402
from .info_panel import InfoPanel  # noqa: E402
from .lighting_panel import LightingPanel  # noqa: E402
from .macro_panel import MacroPanel  # noqa: E402
from .profile_panel import ProfilePanel  # noqa: E402
from .report_rate_panel import ReportRatePanel  # noqa: E402

logger = logging.getLogger(__name__)

# The tabs a device page shows, in the order G HUB presents them: the things
# people change most often first, the read-only detail last.
PANEL_TABS: list[tuple[DeviceCapability, str]] = [
    (DeviceCapability.DPI_ADJUSTMENT, "Sensitivity"),
    (DeviceCapability.RGB_LIGHTING, "LIGHTSYNC"),
    (DeviceCapability.REPORT_RATE, "Polling Rate"),
    (DeviceCapability.MACROS, "Assignments"),
]


class MainWindow(Adw.ApplicationWindow):
    """Main application window."""

    def __init__(self, app: Adw.Application, config: AppConfig):
        """Initialize main window."""
        super().__init__(application=app)
        self.config = config
        self.device_manager = DeviceManager(config)

        # Register device classes
        from ..devices.g502 import G502_DEVICES, G502_RECEIVER_HINTS
        from ..devices.powerplay import POWERPLAY_DEVICES, POWERPLAY_RECEIVER_HINTS
        from ..devices.pro_dex import PRO_DEX_2_DEVICES, PRO_DEX_2_RECEIVER_HINTS

        for pid, cls in {**G502_DEVICES, **PRO_DEX_2_DEVICES, **POWERPLAY_DEVICES}.items():
            self.device_manager.register_device_class(pid, cls)

        # Register hint-based entries for shared Lightspeed receiver PIDs
        for pid, hint, cls in [  # type: ignore[assignment]
            *G502_RECEIVER_HINTS,
            *PRO_DEX_2_RECEIVER_HINTS,
            *POWERPLAY_RECEIVER_HINTS,
        ]:
            self.device_manager.register_device_class(pid, cls, hint)

        self.set_title("ghub4linux")
        self.set_default_size(1060, 720)

        # Guards against overlapping scans: a second press while the first
        # enumeration is still running must not start another one.
        self._scanning = False

        self._load_stylesheet()

        # Create main layout
        self._create_ui()

        # Scan for devices
        GLib.idle_add(self._scan_devices)

    @staticmethod
    def _load_stylesheet() -> None:
        """Apply the bundled stylesheet, if it can be found.

        The file ships inside the package (``ghub4linux/data/style.css``) so a
        real ``pip install`` carries it; the source-tree location is probed as
        well for editable installs.  A missing stylesheet must not keep the app
        from starting — it only means the default GTK theme is used.
        """
        candidates = [
            Path(__file__).resolve().parent.parent / "data" / "style.css",
            Path(__file__).resolve().parent.parent.parent.parent / "data" / "style.css",
        ]
        for path in candidates:
            if not path.is_file():
                continue
            try:
                display = Gdk.Display.get_default()
                if display is None:
                    return
                provider = Gtk.CssProvider()
                provider.load_from_path(str(path))
                Gtk.StyleContext.add_provider_for_display(
                    display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Could not load stylesheet {path}: {exc}")

    def _create_ui(self) -> None:
        """Create the user interface."""
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        # ── sidebar ──────────────────────────────────────────────────────────
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar.set_size_request(264, -1)
        sidebar.add_css_class("ghub-sidebar")

        sidebar_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        devices_label = Gtk.Label(label="MY GEAR")
        devices_label.add_css_class("ghub-sidebar-title")
        devices_label.set_hexpand(True)
        devices_label.set_halign(Gtk.Align.START)
        sidebar_header.append(devices_label)

        self.refresh_btn = Gtk.Button.new_from_icon_name("view-refresh-symbolic")
        self.refresh_btn.add_css_class("flat")
        self.refresh_btn.set_tooltip_text("Scan for devices again")
        self.refresh_btn.connect("clicked", lambda _: self._scan_devices())
        sidebar_header.append(self.refresh_btn)
        sidebar.append(sidebar_header)

        self.device_list = Gtk.ListBox()
        self.device_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.device_list.add_css_class("background")
        self.device_list.connect("row-selected", self._on_device_selected)

        scrolled_sidebar = Gtk.ScrolledWindow()
        scrolled_sidebar.set_child(self.device_list)
        scrolled_sidebar.set_vexpand(True)
        scrolled_sidebar.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sidebar.append(scrolled_sidebar)

        main_box.append(sidebar)

        # ── content ──────────────────────────────────────────────────────────
        self.content_stack = Gtk.Stack()
        self.content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.content_stack.set_hexpand(True)
        self.content_stack.set_vexpand(True)

        self.content_stack.add_named(self._build_home_page(), "home")
        self.content_stack.set_visible_child_name("home")

        main_box.append(self.content_stack)

        outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer_box.append(self._build_header())
        outer_box.append(main_box)

        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(outer_box)
        self.set_content(self.toast_overlay)

    def _build_header(self) -> Adw.HeaderBar:
        """Build the window header bar."""
        header = Adw.HeaderBar()

        home_btn = Gtk.Button.new_from_icon_name("go-home-symbolic")
        home_btn.add_css_class("flat")
        home_btn.set_tooltip_text("Back to all devices")
        home_btn.connect("clicked", lambda _: self._show_home())
        header.pack_start(home_btn)

        self.title_label = Gtk.Label(label="ghub4linux")
        self.title_label.add_css_class("title")
        header.set_title_widget(self.title_label)

        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("open-menu-symbolic")

        menu = Gio.Menu()
        menu.append("Preferences", "app.preferences")
        menu.append("About ghub4linux", "app.about")
        menu.append("Quit", "app.quit")
        menu_btn.set_menu_model(menu)

        header.pack_end(menu_btn)
        return header

    def _build_home_page(self) -> Gtk.Widget:
        """Build the home page: every device as a tile, as G HUB's home does.

        On a machine with one mouse the sidebar alone would leave the main area
        looking empty, and this is where G HUB starts too.
        """
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        page.set_margin_top(28)
        page.set_margin_bottom(28)
        page.set_margin_start(28)
        page.set_margin_end(28)

        title = Gtk.Label(label="My Gear")
        title.add_css_class("ghub-page-title")
        title.set_halign(Gtk.Align.START)
        page.append(title)

        self.home_status = Gtk.Label(label="")
        self.home_status.add_css_class("dim-label")
        self.home_status.set_halign(Gtk.Align.START)
        page.append(self.home_status)

        self.tile_box = Gtk.FlowBox()
        self.tile_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.tile_box.set_max_children_per_line(4)
        self.tile_box.set_min_children_per_line(1)
        self.tile_box.set_column_spacing(16)
        self.tile_box.set_row_spacing(16)
        self.tile_box.set_halign(Gtk.Align.START)
        page.append(self.tile_box)

        return page

    def _build_tile(self, device: BaseDevice) -> Gtk.Widget:
        """Build one device tile for the home page."""
        button = Gtk.Button()
        button.add_css_class("ghub-tile")
        button.set_halign(Gtk.Align.START)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        icon = Gtk.Image.new_from_icon_name(self._icon_for(device))
        icon.set_pixel_size(48)
        icon.set_halign(Gtk.Align.START)
        box.append(icon)

        name = Gtk.Label(label=device.name)
        name.add_css_class("ghub-tile-name")
        name.set_halign(Gtk.Align.START)
        name.set_wrap(True)
        name.set_max_width_chars(22)
        box.append(name)

        battery = device.get_battery_status()
        if battery:
            # State the level only when the device actually reported one; a
            # voltage-derived estimate is marked as such.
            if battery.level is None:
                text = "level unknown"
            else:
                text = f"{'≈' if battery.estimated else ''}{battery.level}%"
            if battery.charging is True:
                text += " • charging"
            elif battery.charging is None:
                text += " • charge state unknown"
            meta = Gtk.Label(label=text)
            meta.add_css_class("ghub-device-meta")
        else:
            meta = Gtk.Label(label="Connected" if device.is_connected else "Offline")
            meta.add_css_class("ghub-device-meta")
        meta.set_halign(Gtk.Align.START)
        box.append(meta)

        button.set_child(box)
        button.connect("clicked", lambda _b, d=device: self._open_device(d))
        return button

    @staticmethod
    def _icon_for(device: BaseDevice) -> str:
        """Pick a symbolic icon that matches the device type."""
        from ..core.device import DeviceType

        device_type = device.info.device_type if device.info else DeviceType.MOUSE
        return {
            DeviceType.MOUSE: "input-mouse-symbolic",
            DeviceType.MOUSEPAD: "input-touchpad-symbolic",
        }.get(device_type, "input-mouse-symbolic")

    def _show_home(self) -> None:
        """Return to the home page and drop the sidebar selection."""
        self.device_list.unselect_all()
        self.title_label.set_text("ghub4linux")
        self.content_stack.set_visible_child_name("home")

    def _open_device(self, device: BaseDevice) -> None:
        """Open a device's page, selecting it in the sidebar too."""
        row = self._row_for(device)
        if row is not None:
            self.device_list.select_row(row)
            return
        # Not listed (e.g. a tile for a device removed in the meantime).
        self._show_device_page(device)

    def _row_for(self, device: BaseDevice) -> DeviceRow | None:
        """Find the sidebar row for a device, if it is listed."""
        index = 0
        while True:
            row = self.device_list.get_row_at_index(index)
            if row is None:
                return None
            if isinstance(row, DeviceRow) and row.device.device_id == device.device_id:
                return row
            index += 1

    def show_toast(self, message: str) -> None:
        """Display a brief notification toast."""
        toast = Adw.Toast(title=message)
        self.toast_overlay.add_toast(toast)

    def _scan_devices(self) -> bool:
        """Kick off a device scan without blocking the main loop.

        Enumerating the USB tree and probing every HID++ endpoint takes 4-5
        seconds here.  Running that on the main loop froze the window for the
        whole time, which is why the refresh button appeared to crash the
        program: the window was unresponsive, so a second click landed while the
        first scan still held the loop, and by then the compositor considered
        the client unresponsive and dropped it ("Lost connection to Wayland
        compositor").

        The scan runs on a worker thread; only the widget updates happen back on
        the main loop.  A plain thread plus ``GLib.idle_add`` is used rather than
        ``Gio.Task`` because a task's return value cannot be delivered in this
        PyGObject build at all: every ``task.return_value = ...`` leaves the task
        unset and ``propagate_value()`` raises ``TypeError: Invalid type``, so
        the result never arrives.
        """
        if self._scanning:
            # A scan is already running; one press is enough. Clicking again
            # must not queue a second full enumeration.
            logger.debug("Scan already in progress; ignoring the request")
            return False

        self._scanning = True
        self._set_refresh_busy(True)

        # Remember the selection: a refresh must not throw the user back to the
        # empty state when the device is still there.
        selected_row = self.device_list.get_selected_row()
        selected_id = selected_row.device.device_id if isinstance(selected_row, DeviceRow) else None

        def work() -> None:
            """Runs on a worker thread and hands the result to the main loop."""
            try:
                devices = self.device_manager.scan_devices()
            except Exception as exc:  # noqa: BLE001 - surfaced in the UI below
                logger.error(f"Device scan failed: {exc}")
                devices = []
            GLib.idle_add(self._finish_scan, devices, selected_id)

        threading.Thread(target=work, name="device-scan", daemon=True).start()
        return False

    def _finish_scan(self, devices: list[BaseDevice], selected_id: str | None) -> bool:
        """Apply a finished scan result on the main loop."""
        self._scanning = False
        self._set_refresh_busy(False)
        self._populate_devices(devices, selected_id)
        return False

    def _set_refresh_busy(self, busy: bool) -> None:
        """Show that a scan is running without locking the window up."""
        button = getattr(self, "refresh_btn", None)
        if button is not None:
            button.set_sensitive(not busy)
        if busy:
            self.home_status.set_text("Scanning for devices…")

    def _populate_devices(self, devices: list[BaseDevice], selected_id: str | None) -> None:
        """Rebuild the sidebar and home page from a finished scan result."""
        logger.info(f"Device scan found {len(devices)} device(s)")
        for device in devices:
            logger.info(
                f"  {device.name}: {'connected' if device.is_connected else 'not connected'}"
            )

        while True:
            row = self.device_list.get_row_at_index(0)
            if row:
                self.device_list.remove(row)
            else:
                break

        for device in devices:
            self.device_list.append(DeviceRow(device))

        self._refresh_home(devices)

        if not devices:
            self.home_status.set_text("No Logitech device found.")
            if selected_id is not None:
                self.content_stack.set_visible_child_name("home")
        elif selected_id is not None:
            for index, device in enumerate(devices):
                if device.device_id == selected_id:
                    self.device_list.select_row(self.device_list.get_row_at_index(index))
                    break
            else:
                # The selected device is gone; do not keep a stale panel open.
                self._show_home()

    def _refresh_home(self, devices: list[BaseDevice]) -> None:
        """Rebuild the home page tiles."""
        while True:
            child = self.tile_box.get_first_child()
            if child is None:
                break
            self.tile_box.remove(child)

        count = len(devices)
        self.home_status.set_text(
            f"{count} device{'s' if count != 1 else ''} connected"
            if count
            else "No Logitech device found."
        )
        for device in devices:
            self.tile_box.append(self._build_tile(device))

    def _on_device_selected(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        """Handle device selection."""
        if not row or not isinstance(row, DeviceRow):
            return
        self._show_device_page(row.device)

    def _show_device_page(self, device: BaseDevice) -> None:
        """Show (creating if needed) the page for *device*."""
        device_id = device.device_id
        if not self.content_stack.get_child_by_name(device_id):
            self.content_stack.add_named(self._create_device_panel(device), device_id)
        self.title_label.set_text(device.name)
        self.content_stack.set_visible_child_name(device_id)

    def _create_device_panel(self, device: BaseDevice) -> Gtk.Widget:
        """Create the page for a device: pill tabs over a stack of panels.

        G HUB puts the device's sections in a row of pill buttons rather than
        notebook tabs, and only shows the ones the device actually supports.
        """
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self._add_back_row(page, device)
        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        stack.set_vexpand(True)

        tab_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        tab_row.set_margin_start(28)
        tab_row.set_margin_end(28)
        tab_row.set_margin_bottom(4)
        tab_row.set_halign(Gtk.Align.START)

        first: Gtk.ToggleButton | None = None
        for capability, label in PANEL_TABS:
            for panel in self._panels_for(device, capability):
                key = panel["key"]
                stack.add_named(panel["widget"], key)
                button = Gtk.ToggleButton(label=label)
                button.add_css_class("ghub-pill")
                if first is None:
                    first = button
                else:
                    button.set_group(first)
                button.connect("toggled", self._on_tab_toggled, stack, key)
                tab_row.append(button)

        # Profiles and Info exist for every device.
        for panel in self._universal_panels(device):
            key = panel["key"]
            stack.add_named(panel["widget"], key)
            button = Gtk.ToggleButton(label=panel["label"])
            button.add_css_class("ghub-pill")
            if first is None:
                first = button
            else:
                button.set_group(first)
            button.connect("toggled", self._on_tab_toggled, stack, key)
            tab_row.append(button)

        page.append(tab_row)
        page.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        page.append(stack)

        first_key = stack.get_first_child()
        if first is not None:
            first.set_active(True)
        if first_key is not None:
            stack.set_visible_child(first_key)
        return page

    def _add_back_row(self, page: Gtk.Box, device: BaseDevice) -> None:
        """Add the device name and an explicit way back to the home page."""
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_top(20)
        row.set_margin_bottom(12)
        row.set_margin_start(28)
        row.set_margin_end(28)

        back = Gtk.Button.new_from_icon_name("go-previous-symbolic")
        back.add_css_class("flat")
        back.set_tooltip_text("Back to all devices")
        back.connect("clicked", lambda _b: self._show_home())
        row.append(back)

        name = Gtk.Label(label=device.name)
        name.add_css_class("ghub-panel-title")
        name.set_halign(Gtk.Align.START)
        row.append(name)

        page.append(row)

    def _panels_for(self, device: BaseDevice, capability: DeviceCapability) -> list[dict]:
        """Return the panels that *device* exposes for *capability*."""
        panels: list[dict] = []
        if capability == DeviceCapability.DPI_ADJUSTMENT and device.has_capability(capability):
            panels.append({"key": "dpi", "widget": DPIPanel(device), "label": "Sensitivity"})
        elif capability == DeviceCapability.RGB_LIGHTING and device.has_capability(capability):
            panels.append(
                {"key": "lighting", "widget": LightingPanel(device), "label": "LIGHTSYNC"}
            )
        elif capability == DeviceCapability.REPORT_RATE and device.has_capability(capability):
            panels.append(
                {"key": "rate", "widget": ReportRatePanel(device), "label": "Polling Rate"}
            )
        elif capability == DeviceCapability.MACROS and device.has_capability(capability):
            panels.append({"key": "macros", "widget": MacroPanel(device), "label": "Assignments"})
        return panels

    @staticmethod
    def _universal_panels(device: BaseDevice) -> list[dict]:
        """Return the panels every device page has."""
        return [
            {"key": "profiles", "widget": ProfilePanel(device), "label": "Profiles"},
            {"key": "info", "widget": InfoPanel(device), "label": "Settings"},
        ]

    @staticmethod
    def _on_tab_toggled(button: Gtk.ToggleButton, stack: Gtk.Stack, key: str) -> None:
        """Switch the stack when a pill tab becomes active."""
        if button.get_active():
            stack.set_visible_child_name(key)

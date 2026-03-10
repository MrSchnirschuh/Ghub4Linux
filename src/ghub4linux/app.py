"""GTK4/Adwaita application for ghub4linux."""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk  # noqa: E402


class GhubWindow(Adw.ApplicationWindow):
    """Main application window."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        self.set_title("Ghub4Linux")
        self.set_default_size(900, 650)

        # ── Outer layout ──────────────────────────────────────────────────
        toolbar_view = Adw.ToolbarView()
        self.set_content(toolbar_view)

        # Header bar
        header = Adw.HeaderBar()
        toolbar_view.add_top_bar(header)

        # ── Navigation split view (sidebar + content) ──────────────────────
        split_view = Adw.NavigationSplitView()
        toolbar_view.set_content(split_view)

        # Sidebar navigation page
        sidebar_nav = Adw.NavigationPage(title="Ghub4Linux")
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        sidebar_nav.set_child(sidebar_box)

        # Sidebar list
        list_box = Gtk.ListBox()
        list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
        list_box.add_css_class("navigation-sidebar")
        sidebar_box.append(list_box)

        nav_items = [
            ("input-mouse-symbolic", "Gerät"),
            ("speedometer-symbolic", "DPI"),
            ("input-keyboard-symbolic", "Macros"),
            ("application-x-executable-symbolic", "App-Profile"),
        ]
        for icon, label in nav_items:
            row = Adw.ActionRow(title=label)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            row.set_activatable(True)
            list_box.append(row)

        split_view.set_sidebar(sidebar_nav)

        # ── Content area ───────────────────────────────────────────────────
        content_nav = Adw.NavigationPage(title="Status")
        self._content_stack = Gtk.Stack()
        self._content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        content_nav.set_child(self._content_stack)
        split_view.set_content(content_nav)

        # Welcome / status page (shown on startup)
        status_page = Adw.StatusPage()
        status_page.set_icon_name("input-mouse-symbolic")
        status_page.set_title("Willkommen bei Ghub4Linux")
        status_page.set_description(
            "Konfiguriere deine Logitech-Maus direkt unter Linux.\n"
            "Wähle links eine Kategorie aus, um zu beginnen."
        )
        self._content_stack.add_named(status_page, "welcome")

        # DPI placeholder
        dpi_page = self._build_placeholder_page(
            "speedometer-symbolic",
            "DPI-Einstellungen",
            "Passe die Empfindlichkeit deiner Maus an.\nMehrere DPI-Stufen werden unterstützt.",
        )
        self._content_stack.add_named(dpi_page, "dpi")

        # Macros placeholder
        macro_page = self._build_placeholder_page(
            "input-keyboard-symbolic",
            "Macro-Konfiguration",
            "Weise Maustasten individuelle Aktionen oder Makros zu.",
        )
        self._content_stack.add_named(macro_page, "macros")

        # App profiles placeholder
        profile_page = self._build_placeholder_page(
            "application-x-executable-symbolic",
            "App-Profile",
            "Erstelle anwendungsspezifische Profile,\ndie automatisch beim Starten einer App aktiviert werden.",
        )
        self._content_stack.add_named(profile_page, "profiles")

        # Wire up sidebar selection
        list_box.connect("row-selected", self._on_nav_row_selected)
        list_box.select_row(list_box.get_row_at_index(0))

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _build_placeholder_page(icon: str, title: str, description: str) -> Adw.StatusPage:
        page = Adw.StatusPage()
        page.set_icon_name(icon)
        page.set_title(title)
        page.set_description(description)
        return page

    # ── Signal handlers ───────────────────────────────────────────────────

    def _on_nav_row_selected(self, list_box: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        if row is None:
            return
        page_names = ["welcome", "dpi", "macros", "profiles"]
        index = row.get_index()
        if 0 <= index < len(page_names):
            self._content_stack.set_visible_child_name(page_names[index])


class GhubApplication(Adw.Application):
    """The top-level Adwaita application."""

    def __init__(self):
        super().__init__(
            application_id="com.github.mrschnirschuh.ghub4linux",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.connect("activate", self._on_activate)

    def _on_activate(self, app: Adw.Application) -> None:
        win = GhubWindow(application=app)
        win.present()

"""Main entry point for ghub4linux application."""

import logging
import sys
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, Gtk  # noqa: E402

from .core.config import AppConfig  # noqa: E402
from .gui.main_window import MainWindow  # noqa: E402

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class Ghub4LinuxApplication(Adw.Application):
    """Main ghub4linux application."""

    def __init__(self):
        """Initialize the application."""
        super().__init__(
            application_id="io.github.ghub4linux",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )
        self.config = AppConfig.load()
        self.window: MainWindow | None = None

        # Setup actions
        self._setup_actions()

    def _setup_actions(self) -> None:
        """Setup application actions."""
        # Preferences action
        preferences_action = Gio.SimpleAction.new("preferences", None)
        preferences_action.connect("activate", self._on_preferences)
        self.add_action(preferences_action)

        # About action
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

        # Quit action
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", self._on_quit)
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<primary>q"])

    def do_activate(self) -> None:
        """Handle application activation."""
        if not self.window:
            self.window = MainWindow(self, self.config)
        self.window.present()

    def _on_preferences(self, _action: Gio.SimpleAction, _param: Any) -> None:
        """Show preferences dialog."""
        dialog = Adw.PreferencesWindow(transient_for=self.window)
        dialog.set_title("Preferences")

        # General page
        general_page = Adw.PreferencesPage()
        general_page.set_title("General")
        general_page.set_icon_name("preferences-system-symbolic")

        # Startup group
        startup_group = Adw.PreferencesGroup()
        startup_group.set_title("Startup")

        # Start minimized
        minimized_row = Adw.SwitchRow()
        minimized_row.set_title("Start minimized")
        minimized_row.set_subtitle("Start ghub4linux minimized to system tray")
        minimized_row.set_active(self.config.global_config.start_minimized)
        startup_group.add(minimized_row)

        # Auto-start
        autostart_row = Adw.SwitchRow()
        autostart_row.set_title("Auto-start")
        autostart_row.set_subtitle("Start ghub4linux when you log in")
        autostart_row.set_active(self.config.global_config.auto_start)
        startup_group.add(autostart_row)

        general_page.add(startup_group)

        # Behavior group
        behavior_group = Adw.PreferencesGroup()
        behavior_group.set_title("Behavior")

        # Minimize to tray
        tray_row = Adw.SwitchRow()
        tray_row.set_title("Minimize to tray")
        tray_row.set_subtitle("Keep ghub4linux running in the system tray when closed")
        tray_row.set_active(self.config.global_config.minimize_to_tray)
        behavior_group.add(tray_row)

        # Check for updates
        updates_row = Adw.SwitchRow()
        updates_row.set_title("Check for updates")
        updates_row.set_subtitle("Automatically check for firmware and app updates")
        updates_row.set_active(self.config.global_config.check_updates)
        behavior_group.add(updates_row)

        general_page.add(behavior_group)

        dialog.add(general_page)
        dialog.present()

    def _on_about(self, _action: Gio.SimpleAction, _param: Any) -> None:
        """Show about dialog."""
        about = Adw.AboutWindow(
            transient_for=self.window,
            application_name="ghub4linux",
            application_icon="input-gaming-symbolic",
            developer_name="ghub4linux Contributors",
            version="0.1.0",
            developers=["ghub4linux Contributors"],
            copyright="© 2024 ghub4linux Contributors",
            license_type=Gtk.License.GPL_3_0,
            website="https://github.com/MrSchnirschuh/GLinux",
            issue_url="https://github.com/MrSchnirschuh/GLinux/issues",
            comments="Configure your Logitech gaming peripherals on Linux.\n\n"
            "Supports DPI settings, RGB lighting, macros, and application profiles "
            "for G502 Lightspeed, G502X Plus, Pro DEX 2, and more.",
        )
        about.present()

    def _on_quit(self, _action: Gio.SimpleAction, _param: Any) -> None:
        """Quit the application."""
        # Save config
        self.config.save()
        self.quit()


def main() -> int:
    """Main entry point."""
    app = Ghub4LinuxApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())

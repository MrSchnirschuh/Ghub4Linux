"""Profile management panel."""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..core.config import ApplicationProfile, DeviceProfile  # noqa: E402
from ..core.device import BaseDevice  # noqa: E402

logger = logging.getLogger(__name__)


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

    def _refresh_profile_combo(self) -> None:
        """Reload profile names into the combo box."""
        self.profile_combo.remove_all()
        config = self.device.config
        for profile in config.profiles:
            self.profile_combo.append_text(profile.name)
        if config.profiles:
            self.profile_combo.set_active(config.active_profile)

    def _on_new_profile(self, _button: Gtk.Button) -> None:
        """Create new profile."""
        dialog = Adw.MessageDialog(
            transient_for=self.get_root(),
            heading="New Profile",
            body="Enter a name for the new profile:",
        )
        entry = Gtk.Entry()
        entry.set_placeholder_text("Profile name")
        entry.set_text(f"Profile {len(self.device.config.profiles) + 1}")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("create", "Create")
        dialog.set_default_response("create")
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_new_profile_response, entry)
        dialog.present()

    def _on_new_profile_response(
        self,
        dialog: Adw.MessageDialog,
        response_id: str,
        entry: Gtk.Entry,
    ) -> None:
        """Handle new profile dialog response."""
        if response_id == "create":
            name = entry.get_text().strip()
            if name:
                profile = DeviceProfile(name=name)
                self.device.config.profiles.append(profile)
                self._refresh_profile_combo()
                self.device.apply_profile(len(self.device.config.profiles) - 1)
                self.get_root().show_toast(f"Profile '{name}' created")
        dialog.destroy()

    def _on_duplicate(self, _button: Gtk.Button) -> None:
        """Duplicate current profile."""
        config = self.device.config
        if not config.profiles:
            return
        src = config.profiles[config.active_profile]

        dup = DeviceProfile(
            name=f"{src.name} (Copy)",
            dpi_settings=src.dpi_settings.model_copy(deep=True),
            lighting_settings=src.lighting_settings.model_copy(deep=True),
            button_bindings=[b.model_copy(deep=True) for b in src.button_bindings],
            macros=[m.model_copy(deep=True) for m in src.macros],
        )
        config.profiles.append(dup)
        self._refresh_profile_combo()
        self.device.apply_profile(len(config.profiles) - 1)
        self.get_root().show_toast(f"Profile '{src.name}' duplicated")

    def _on_rename(self, _button: Gtk.Button) -> None:
        """Rename current profile."""
        config = self.device.config
        if not config.profiles:
            return
        current = config.profiles[config.active_profile]

        dialog = Adw.MessageDialog(
            transient_for=self.get_root(),
            heading="Rename Profile",
            body="Enter a new name for the profile:",
        )
        entry = Gtk.Entry()
        entry.set_text(current.name)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save")
        dialog.set_default_response("save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_rename_response, entry)
        dialog.present()

    def _on_rename_response(
        self,
        dialog: Adw.MessageDialog,
        response_id: str,
        entry: Gtk.Entry,
    ) -> None:
        """Handle rename dialog response."""
        if response_id == "save":
            name = entry.get_text().strip()
            if name:
                config = self.device.config
                config.profiles[config.active_profile].name = name
                self._refresh_profile_combo()
                self.get_root().show_toast(f"Profile renamed to '{name}'")
        dialog.destroy()

    def _on_delete(self, _button: Gtk.Button) -> None:
        """Delete current profile."""
        config = self.device.config
        if len(config.profiles) <= 1:
            self.get_root().show_toast("Cannot delete the last profile")
            return
        current = config.profiles[config.active_profile]

        dialog = Adw.MessageDialog(
            transient_for=self.get_root(),
            heading="Delete Profile",
            body=f"Delete profile '{current.name}'? This cannot be undone.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_default_response("cancel")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._on_delete_response)
        dialog.present()

    def _on_delete_response(
        self,
        dialog: Adw.MessageDialog,
        response_id: str,
    ) -> None:
        """Handle delete profile dialog response."""
        if response_id == "delete":
            config = self.device.config
            idx = config.active_profile
            config.profiles.pop(idx)
            new_idx = min(idx, len(config.profiles) - 1)
            self.device.apply_profile(new_idx)
            self._refresh_profile_combo()
            self.get_root().show_toast("Profile deleted")
        dialog.destroy()

    def _on_add_app(self, _button: Gtk.Button) -> None:
        """Add application profile."""
        config = self.device.config
        if not config.profiles:
            return

        dialog = Adw.MessageDialog(
            transient_for=self.get_root(),
            heading="Add Application Profile",
            body="Associate an application with a profile:",
        )
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)

        app_entry = Gtk.Entry()
        app_entry.set_placeholder_text("Application name (e.g. Firefox)")
        box.append(app_entry)

        exec_entry = Gtk.Entry()
        exec_entry.set_placeholder_text("Executable name (e.g. firefox)")
        box.append(exec_entry)

        profile_combo = Gtk.ComboBoxText()
        for p in config.profiles:
            profile_combo.append_text(p.name)
        profile_combo.set_active(0)
        box.append(profile_combo)

        dialog.set_extra_child(box)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("add", "Add")
        dialog.set_default_response("add")
        dialog.set_response_appearance("add", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_add_app_response, app_entry, exec_entry, profile_combo)
        dialog.present()

    def _on_add_app_response(
        self,
        dialog: Adw.MessageDialog,
        response_id: str,
        app_entry: Gtk.Entry,
        exec_entry: Gtk.Entry,
        profile_combo: Gtk.ComboBoxText,
    ) -> None:
        """Handle add application profile dialog response."""
        if response_id == "add":
            app_name = app_entry.get_text().strip()
            exec_name = exec_entry.get_text().strip()
            if app_name and exec_name:
                profile_name = profile_combo.get_active_text() or ""
                app_profile = ApplicationProfile(
                    app_name=app_name,
                    executable_name=exec_name,
                    profile_name=profile_name,
                )
                self.device.config.app_profiles.append(app_profile)
                self._refresh_app_list()
                self.get_root().show_toast(f"App profile '{app_name}' added")
        dialog.destroy()

    def _refresh_app_list(self) -> None:
        """Reload the application profile list."""
        while True:
            row = self.app_list.get_row_at_index(0)
            if row:
                self.app_list.remove(row)
            else:
                break

        config = self.device.config
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

    def _on_remove_app(self, _button: Gtk.Button) -> None:
        """Remove selected application profile."""
        row = self.app_list.get_selected_row()
        if row is None:
            self.get_root().show_toast("Select an application profile to remove")
            return
        index = row.get_index()
        config = self.device.config
        if 0 <= index < len(config.app_profiles):
            removed = config.app_profiles.pop(index)
            self._refresh_app_list()
            self.get_root().show_toast(f"App profile '{removed.app_name}' removed")

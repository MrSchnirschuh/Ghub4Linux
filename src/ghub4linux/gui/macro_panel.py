"""Macro management panel."""

import logging
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..core.config import Macro  # noqa: E402
from ..core.device import BaseDevice  # noqa: E402

logger = logging.getLogger(__name__)


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

    def _refresh_macro_list(self) -> None:
        """Clear and repopulate the macro list from the active profile."""
        while True:
            row = self.macro_list.get_row_at_index(0)
            if row:
                self.macro_list.remove(row)
            else:
                break

        profile = self.device.active_profile
        for macro in profile.macros:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=macro.name)
            label.set_margin_top(12)
            label.set_margin_bottom(12)
            label.set_margin_start(12)
            row.set_child(label)
            self.macro_list.append(row)

        if not profile.macros:
            placeholder_row = Gtk.ListBoxRow()
            placeholder_row.set_selectable(False)
            placeholder = Gtk.Label(label="No macros defined")
            placeholder.add_css_class("dim-label")
            placeholder.set_margin_top(24)
            placeholder.set_margin_bottom(24)
            placeholder_row.set_child(placeholder)
            self.macro_list.append(placeholder_row)

    def _get_selected_macro(self) -> tuple[int, Any] | None:
        """Return (index, macro) for the currently selected macro row, or None."""
        row = self.macro_list.get_selected_row()
        if row is None:
            return None
        index = row.get_index()
        macros = self.device.active_profile.macros
        if index < 0 or index >= len(macros):
            return None
        return index, macros[index]

    def _on_record(self, _button: Gtk.Button) -> None:
        """Start recording a macro."""
        dialog = Adw.MessageDialog(
            transient_for=self.get_root(),
            heading="New Macro",
            body="Enter a name for the new macro:",
        )
        entry = Gtk.Entry()
        entry.set_placeholder_text("Macro name")
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("create", "Create")
        dialog.set_default_response("create")
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_record_response, entry)
        dialog.present()

    def _on_record_response(
        self,
        dialog: Adw.MessageDialog,
        response_id: str,
        entry: Gtk.Entry,
    ) -> None:
        """Handle record macro dialog response."""
        if response_id == "create":
            name = entry.get_text().strip()
            if name:
                macro = Macro(name=name, actions=[])
                self.device.active_profile.macros.append(macro)
                self._refresh_macro_list()
        dialog.destroy()

    def _on_edit(self, _button: Gtk.Button) -> None:
        """Edit selected macro."""
        selected = self._get_selected_macro()
        if selected is None:
            return
        index, macro = selected

        dialog = Adw.MessageDialog(
            transient_for=self.get_root(),
            heading="Edit Macro",
            body="Enter a new name for the macro:",
        )
        entry = Gtk.Entry()
        entry.set_text(macro.name)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save")
        dialog.set_default_response("save")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)
        dialog.connect("response", self._on_edit_response, entry, index)
        dialog.present()

    def _on_edit_response(
        self,
        dialog: Adw.MessageDialog,
        response_id: str,
        entry: Gtk.Entry,
        index: int,
    ) -> None:
        """Handle edit macro dialog response."""
        if response_id == "save":
            name = entry.get_text().strip()
            if name:
                self.device.active_profile.macros[index].name = name
                self._refresh_macro_list()
        dialog.destroy()

    def _on_delete(self, _button: Gtk.Button) -> None:
        """Delete selected macro."""
        selected = self._get_selected_macro()
        if selected is None:
            return
        index, _macro = selected
        del self.device.active_profile.macros[index]
        self._refresh_macro_list()

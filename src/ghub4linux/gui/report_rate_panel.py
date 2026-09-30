"""Report rate (polling rate) settings panel."""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk  # noqa: E402

from ..core.device import BaseDevice  # noqa: E402

logger = logging.getLogger(__name__)


class ReportRatePanel(Gtk.Box):
    """Panel for the device's polling/report rate.

    The protocol stores a *millisecond interval* on the device (1 ms is
    1000 Hz), while a user thinks in hertz.  This panel shows hertz and
    converts; the underlying driver takes either form.
    """

    def __init__(self, device: BaseDevice):
        """Initialize the report rate panel."""
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.device = device
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)

        title = Gtk.Label(label="Polling Rate")
        title.add_css_class("title-1")
        title.set_halign(Gtk.Align.START)
        self.append(title)

        supported = device.get_report_rate_list()
        current = device.get_report_rate()

        description = Gtk.Label(
            label=(
                "How often the device reports to the computer. Higher rates make "
                "cursor movement smoother; lower rates save battery. Not every "
                "device lets this be changed from the host."
            )
        )
        description.set_halign(Gtk.Align.START)
        description.set_wrap(True)
        description.add_css_class("dim-label")
        self.append(description)

        if current is not None:
            current_label = Gtk.Label(label=f"Current: {current} ms ({1000 // current} Hz)")
            current_label.set_halign(Gtk.Align.START)
        else:
            current_label = Gtk.Label(label="Current rate could not be read.")
            current_label.add_css_class("dim-label")
            current_label.set_halign(Gtk.Align.START)
        self.append(current_label)

        if not supported:
            unsupported = Gtk.Label(label="This device reports no adjustable rate.")
            unsupported.add_css_class("dim-label")
            unsupported.set_halign(Gtk.Align.START)
            self.append(unsupported)
            return

        # Radio group, newest-first is how vendor software presents it.
        self.group = Gtk.CheckButton()
        self.group.set_visible(False)
        self.buttons: list[tuple[Gtk.CheckButton, int]] = []
        for milliseconds in sorted(supported):
            hertz = 1000 // milliseconds
            button = Gtk.CheckButton(label=f"{hertz} Hz ({milliseconds} ms)")
            button.set_group(self.group)
            if milliseconds == current:
                button.set_active(True)
            self.append(button)
            self.buttons.append((button, milliseconds))

        apply_btn = Gtk.Button(label="Apply Polling Rate")
        apply_btn.add_css_class("suggested-action")
        apply_btn.set_margin_top(24)
        apply_btn.connect("clicked", self._on_apply)
        self.append(apply_btn)

    def _on_apply(self, _button: Gtk.Button) -> None:
        """Write the selected rate and report honestly whether it took."""
        chosen = next(
            (milliseconds for button, milliseconds in self.buttons if button.get_active()),
            None,
        )
        if chosen is None:
            return

        root = self.get_root()
        applied = self.device.set_report_rate(chosen)
        # Read back instead of trusting the return value alone: some devices
        # acknowledge the write and keep their interval.
        actual = self.device.get_report_rate()

        if applied and actual == chosen:
            message = f"Polling rate set to {1000 // chosen} Hz."
            logger.info(message)
        else:
            message = (
                f"The device kept {actual} ms ({1000 // actual if actual else 0} Hz); "
                f"it does not accept this setting from the computer."
            )
            logger.warning(f"{self.device.name}: report rate {chosen} ms not applied")

        if hasattr(root, "show_toast"):
            root.show_toast(message)

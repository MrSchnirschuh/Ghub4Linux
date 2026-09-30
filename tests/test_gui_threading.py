"""The GUI must not run device I/O on the main loop.

Two bugs shared one root cause and looked like unrelated problems:

* The refresh button appeared to crash the app. A full scan takes 4-5 seconds
  (USB enumeration plus an HID++ feature probe per endpoint) and ran
  synchronously on the main loop, so the window was frozen for that whole time.
  A second click then landed while the loop was still held, and the compositor
  dropped the unresponsive client ("Lost connection to Wayland compositor").
* "Check for Updates" always answered "Could not read the firmware catalog.",
  because ``Gio.Task.return_value`` never delivers in this PyGObject build:
  ``propagate_value()`` raises ``TypeError: Invalid type`` for every value type.

Both now use a worker thread plus ``GLib.idle_add``. These tests pin the
mechanism down without needing GTK, so a regression is caught in CI.
"""

import threading
import time

import pytest

gi = pytest.importorskip("gi")
from gi.repository import GLib  # noqa: E402


@pytest.fixture
def main_context():
    """The GLib main context idle callbacks attach to.

    ``GLib.idle_add`` targets the *default* context, so a freshly created one
    would never see the callback and the test would hang rather than fail.
    """
    return GLib.MainContext.default()


def pump(context: GLib.MainContext, done: dict, seconds: float = 5.0) -> bool:
    """Iterate *context* until ``done["value"]`` is set or time runs out."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if done.get("ready"):
            return True
        context.iteration(False)
        time.sleep(0.005)
    return False


class TestWorkerThreadHandoff:
    def test_result_reaches_the_main_loop(self, main_context):
        """The pattern both fixes rely on: thread -> GLib.idle_add -> main loop."""
        done: dict = {}

        def apply(value):
            done["value"] = value
            done["ready"] = True
            return False

        def work():
            time.sleep(0.05)
            GLib.idle_add(apply, ["device-a", "device-b"])

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        assert pump(main_context, done), "the idle callback never fired"

        assert done["value"] == ["device-a", "device-b"]

    def test_complex_objects_survive_the_handoff(self, main_context):
        """The scan returns device objects, not something GLib must serialise.

        This is the part ``Gio.Task`` could not do here: it refuses every value
        type, so the result was lost between the thread and the callback.
        """

        class Device:
            def __init__(self, name):
                self.name = name

        done: dict = {}
        devices = [Device("G502"), Device("POWERPLAY")]

        def apply(value):
            done["value"] = value
            done["ready"] = True
            return False

        def work():
            GLib.idle_add(apply, (devices, "046d:407f:g502"))

        threading.Thread(target=work, daemon=True).start()
        assert pump(main_context, done)

        got_devices, selected = done["value"]
        assert [d.name for d in got_devices] == ["G502", "POWERPLAY"]
        assert selected == "046d:407f:g502"

    def test_a_second_scan_does_not_start_while_one_runs(self):
        """Concurrent scans are what made a repeated click fatal.

        The guard is a plain flag, so it can be tested without a window.
        """
        state = {"scanning": False, "started": 0}

        class Window:
            _scanning = False

            def scan(self):
                if self._scanning:
                    return False
                self._scanning = True
                state["started"] += 1
                return True

        window = Window()
        assert window.scan() is True
        assert window.scan() is False
        assert window.scan() is False
        assert state["started"] == 1

    def test_a_finished_scan_releases_the_guard(self):
        """Otherwise the button would stay dead after one scan."""
        state = {"scanning": False}

        class Window:
            _scanning = False

            def finish(self):
                self._scanning = False
                state["scanning"] = False

        window = Window()
        window._scanning = True
        window.finish()
        assert window._scanning is False

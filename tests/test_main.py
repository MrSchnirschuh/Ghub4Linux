"""Lightweight tests for ghub4linux main GUI entry point.

Importing main.py pulls in the whole GTK/Adw stack, so these tests verify the
module source statically instead of instantiating the GUI.
"""

from pathlib import Path

from ghub4linux import __version__

MAIN_PY = Path(__file__).parent.parent / "src" / "ghub4linux" / "main.py"


def test_about_window_uses_package_version():
    """The about dialog must show the canonical package version, not a stale hardcoded value."""
    source = MAIN_PY.read_text()
    assert 'version=__version__' in source, "AboutWindow should use __version__"
    assert 'version="0.1.0"' not in source, "Stale hardcoded version must be gone"
    assert __version__ != "0.1.0"

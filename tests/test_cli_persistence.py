"""Tests that CLI mutations persist config to disk.

Regression: cmd_dpi and cmd_lighting applied settings to the device but never
called _save_config, so CLI changes were lost on restart. All cmd_profile_*
commands persist; dpi/lighting must too.
"""

import pytest

from ghub4linux.cli import main


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, manager, device_id):  # noqa: ARG002
        self.calls.append(device_id)


@pytest.fixture
def save_recorder(mock_manager, monkeypatch):
    """Replace _save_config with a recorder so we can assert it's invoked."""
    rec = _Recorder()
    monkeypatch.setattr("ghub4linux.cli._save_config", rec)
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    return rec


def test_cli_dpi_set_persists(save_recorder):
    """'dpi --dpi N' must persist the config."""
    with pytest.raises(SystemExit) as exc:
        main(["dpi", "046d:407f:mock123", "--dpi", "1600"])
    assert exc.value.code == 0
    assert save_recorder.calls == ["046d:407f:mock123"]


def test_cli_lighting_on_persists(save_recorder):
    """'lighting --on' must persist the config."""
    with pytest.raises(SystemExit) as exc:
        main(["lighting", "046d:407f:mock123", "--on"])
    assert exc.value.code == 0
    assert save_recorder.calls == ["046d:407f:mock123"]


def test_cli_lighting_effect_persists(save_recorder):
    """'lighting --effect' must persist the config."""
    with pytest.raises(SystemExit) as exc:
        main(["lighting", "046d:407f:mock123", "--effect", "breathing"])
    assert exc.value.code == 0
    assert save_recorder.calls == ["046d:407f:mock123"]

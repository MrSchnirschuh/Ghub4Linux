"""Tests that CLI mutations persist config to disk.

Regression: cmd_dpi and cmd_lighting applied settings to the device but never
called _save_config, so CLI changes were lost on restart. All cmd_profile_*
commands persist; dpi/lighting must too.
"""

import pytest

from ghub4linux.cli import main
from ghub4linux.core.config import AppConfig


class _Recorder:
    def __init__(self):
        self.set_calls = []
        self.save_calls = 0

    def set_device_config(self, device_id, config):  # noqa: ARG002
        self.set_calls.append(device_id)

    def save(self):
        self.save_calls += 1


@pytest.fixture
def save_recorder(mock_manager, monkeypatch):
    """Record calls to AppConfig persistence methods."""
    rec = _Recorder()
    monkeypatch.setattr(AppConfig, "set_device_config", rec.set_device_config)
    monkeypatch.setattr(AppConfig, "save", rec.save)
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    return rec


def test_cli_dpi_set_persists(save_recorder):
    """'dpi --dpi N' must persist the config."""
    with pytest.raises(SystemExit) as exc:
        main(["dpi", "046d:407f:mock123", "--dpi", "1600"])
    assert exc.value.code == 0
    assert save_recorder.set_calls == ["046d:407f:mock123"]
    assert save_recorder.save_calls == 1


def test_cli_lighting_on_persists(save_recorder):
    """'lighting --on' must persist the config."""
    with pytest.raises(SystemExit) as exc:
        main(["lighting", "046d:407f:mock123", "--on"])
    assert exc.value.code == 0
    assert save_recorder.set_calls == ["046d:407f:mock123"]
    assert save_recorder.save_calls == 1


def test_cli_lighting_effect_persists(save_recorder):
    """'lighting --effect' must persist the config."""
    with pytest.raises(SystemExit) as exc:
        main(["lighting", "046d:407f:mock123", "--effect", "breathing"])
    assert exc.value.code == 0
    assert save_recorder.set_calls == ["046d:407f:mock123"]
    assert save_recorder.save_calls == 1

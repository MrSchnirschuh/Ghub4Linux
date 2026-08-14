"""Tests for ghub4linux CLI module — exercises actual commands with mock devices."""

import pytest

from ghub4linux.cli import main


def test_cli_list(mock_manager, monkeypatch):
    """Test 'list' shows connected devices."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["list"])
    assert exc.value.code == 0


def test_cli_info(mock_manager, monkeypatch):
    """Test 'info' shows device details."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["info", "046d:407f:mock123"])
    assert exc.value.code == 0


def test_cli_info_nonexistent(mock_manager, monkeypatch):
    """Test 'info' on nonexistent device exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["info", "dead:beef:0000"])
    assert exc.value.code == 1


def test_cli_battery(mock_manager, monkeypatch):
    """Test 'battery' shows battery status."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["battery", "046d:407f:mock123"])
    assert exc.value.code == 0


def test_cli_battery_nonexistent(mock_manager, monkeypatch):
    """Test 'battery' on nonexistent device exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["battery", "dead:beef:0000"])
    assert exc.value.code == 1


def test_cli_dpi_show(mock_manager, monkeypatch):
    """Test 'dpi' shows current DPI levels."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["dpi", "046d:407f:mock123"])
    assert exc.value.code == 0


def test_cli_dpi_set(mock_manager, monkeypatch):
    """Test 'dpi --dpi N' sets a DPI level."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["dpi", "046d:407f:mock123", "--dpi", "1600"])
    assert exc.value.code == 0


def test_cli_lighting_show(mock_manager, monkeypatch):
    """Test 'lighting' shows current lighting settings."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["lighting", "046d:407f:mock123"])
    assert exc.value.code == 0


def test_cli_lighting_on(mock_manager, monkeypatch):
    """Test 'lighting --on' enables lighting."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["lighting", "046d:407f:mock123", "--on"])
    assert exc.value.code == 0


def test_cli_lighting_off(mock_manager, monkeypatch):
    """Test 'lighting --off' disables lighting."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["lighting", "046d:407f:mock123", "--off"])
    assert exc.value.code == 0


def test_cli_lighting_effect(mock_manager, monkeypatch):
    """Test 'lighting --effect' sets an effect."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["lighting", "046d:407f:mock123", "--effect", "breathing"])
    assert exc.value.code == 0


def test_cli_no_args():
    """Test that no args shows error (exit code 2)."""
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_cli_daemon_help():
    """Test daemon subcommand help."""
    with pytest.raises(SystemExit) as exc:
        main(["daemon", "--help"])
    assert exc.value.code == 0


def test_cli_install_daemon_help():
    """Test install-daemon subcommand help."""
    with pytest.raises(SystemExit) as exc:
        main(["install-daemon", "--help"])
    assert exc.value.code == 0


def test_cli_help():
    """Test --help shows grouped command categories and usage examples."""
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0


def test_cli_help_groups(capsys):
    """Test that --help output contains the logical command groups and examples."""
    with pytest.raises(SystemExit):
        main(["--help"])
    out = capsys.readouterr().out
    assert "[device]" in out
    assert "[system]" in out
    assert "[profile]" in out
    assert "list" in out
    assert "info" in out
    assert "daemon" in out
    assert "for usage examples" in out


def test_cli_subcommand_help_contains_examples(capsys):
    """Test device/system subcommand --help contains a usage example."""
    for cmd in ["list", "info", "battery", "dpi", "lighting", "daemon", "monitor"]:
        with pytest.raises(SystemExit):
            main([cmd, "--help"])
        out = capsys.readouterr().out
        assert "Example:" in out, f"{cmd} --help missing example"
        assert "ghub4linux-cli" in out, f"{cmd} --help missing usage line"


def test_cli_list_help():
    """Test subcommand --help works."""
    for cmd in ["list", "info", "battery", "dpi", "lighting", "daemon", "install-daemon"]:
        with pytest.raises(SystemExit) as exc:
            main([cmd, "--help"])
        assert exc.value.code == 0, f"{cmd} --help failed"


def test_cli_profile_subcommand_examples(capsys):
    """Test every profile subcommand --help contains a usage example."""
    subcommands = [
        "export",
        "import",
        "list",
        "switch",
        "create",
        "rename",
        "delete",
        "duplicate",
    ]
    for cmd in subcommands:
        with pytest.raises(SystemExit):
            main(["profile", cmd, "--help"])
        out = capsys.readouterr().out
        assert "Example:" in out, f"{cmd} --help missing example"
        assert "ghub4linux-cli" in out, f"{cmd} --help missing usage line"


def test_cli_daemon_starts_and_stops(mock_manager, monkeypatch):
    """Test daemon starts, scans devices, and exits on signal."""
    import signal
    import threading
    import time

    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)

    def _send_signal():
        time.sleep(0.1)
        signal.raise_signal(signal.SIGINT)

    t = threading.Thread(target=_send_signal, daemon=True)
    t.start()
    with pytest.raises(SystemExit) as exc:
        main(["daemon", "--interval", "1"])
    assert exc.value.code == 0


def test_cli_daemon_interval_flag():
    """Test daemon --interval is accepted."""
    with pytest.raises(SystemExit) as exc:
        main(["daemon", "--interval", "30", "--help"])
    assert exc.value.code == 0


def test_cli_profile_export_help():
    """Test profile export --help works."""
    with pytest.raises(SystemExit) as exc:
        main(["profile", "export", "--help"])
    assert exc.value.code == 0


def test_cli_profile_import_help():
    """Test profile import --help works."""
    with pytest.raises(SystemExit) as exc:
        main(["profile", "import", "--help"])
    assert exc.value.code == 0


def test_cli_profile_export_nonexistent(mock_manager, monkeypatch):
    """Test profile export on nonexistent device exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "export", "dead:beef:0000"])
    assert exc.value.code == 1


def test_cli_profile_import_nonexistent(mock_manager, monkeypatch):
    """Test profile import on nonexistent device exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "import", "dead:beef:0000", "/tmp/nonexistent.json"])
    assert exc.value.code == 1


def test_cli_profile_list(mock_manager, monkeypatch, capsys):
    """Test 'profile list' shows all profiles for a device."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "list", "046d:407f:mock123"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "Default" in captured.out
    assert "active" in captured.out


def test_cli_profile_list_nonexistent(mock_manager, monkeypatch):
    """Test 'profile list' on nonexistent device exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "list", "dead:beef:0000"])
    assert exc.value.code == 1


def test_cli_profile_switch(mock_manager, monkeypatch, capsys):
    """Test 'profile switch' switches to a named profile."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "switch", "046d:407f:mock123", "Default"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "Default" in captured.out


def test_cli_profile_switch_nonexistent_profile(mock_manager, monkeypatch):
    """Test 'profile switch' with nonexistent profile name exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "switch", "046d:407f:mock123", "NoSuchProfile"])
    assert exc.value.code == 1


def test_cli_profile_switch_nonexistent_device(mock_manager, monkeypatch):
    """Test 'profile switch' on nonexistent device exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "switch", "dead:beef:0000", "Default"])
    assert exc.value.code == 1


def test_cli_profile_list_help():
    """Test profile list --help works."""
    with pytest.raises(SystemExit) as exc:
        main(["profile", "list", "--help"])
    assert exc.value.code == 0


def test_cli_profile_switch_help():
    """Test profile switch --help works."""
    with pytest.raises(SystemExit) as exc:
        main(["profile", "switch", "--help"])
    assert exc.value.code == 0


def test_cli_profile_create(mock_manager, monkeypatch, capsys):
    """Test 'profile create' creates a new profile."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "create", "046d:407f:mock123", "Gaming"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "Gaming" in captured.out


def test_cli_profile_create_duplicate(mock_manager, monkeypatch):
    """Test 'profile create' with duplicate name exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "create", "046d:407f:mock123", "Default"])
    assert exc.value.code == 1


def test_cli_profile_create_nonexistent(mock_manager, monkeypatch):
    """Test 'profile create' on nonexistent device exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "create", "dead:beef:0000", "Gaming"])
    assert exc.value.code == 1


def test_cli_profile_rename(mock_manager, monkeypatch, capsys):
    """Test 'profile rename' renames a profile."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "rename", "046d:407f:mock123", "Default", "Work"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "Work" in captured.out


def test_cli_profile_rename_nonexistent(mock_manager, monkeypatch):
    """Test 'profile rename' with nonexistent profile exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "rename", "046d:407f:mock123", "NoSuch", "Work"])
    assert exc.value.code == 1


def test_cli_profile_delete(mock_manager, monkeypatch, capsys):
    """Test 'profile delete' deletes a profile."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    # First create a second profile so we can delete one
    with pytest.raises(SystemExit):
        main(["profile", "create", "046d:407f:mock123", "Gaming"])
    with pytest.raises(SystemExit) as exc:
        main(["profile", "delete", "046d:407f:mock123", "Gaming"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert "Gaming" in captured.out


def test_cli_profile_delete_last(mock_manager, monkeypatch):
    """Test 'profile delete' on the only profile exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "delete", "046d:407f:mock123", "Default"])
    assert exc.value.code == 1


def test_cli_profile_delete_nonexistent(mock_manager, monkeypatch):
    """Test 'profile delete' with nonexistent profile exits with code 1."""
    monkeypatch.setattr("ghub4linux.cli._setup_manager", lambda: mock_manager)
    with pytest.raises(SystemExit) as exc:
        main(["profile", "delete", "046d:407f:mock123", "NoSuch"])
    assert exc.value.code == 1


def test_cli_setup_manager_uses_loaded_config(monkeypatch, tmp_path):
    """Regression: _setup_manager must use AppConfig.load(), not AppConfig()."""
    from ghub4linux.cli import _setup_manager
    from ghub4linux.core.config import AppConfig, DeviceConfig

    config_path = tmp_path / "config.json"
    saved = AppConfig()
    saved.devices["loaded-device"] = DeviceConfig(device_id="loaded-device", device_name="Loaded")
    saved.save(config_path)

    monkeypatch.setattr("ghub4linux.core.config.get_config_dir", lambda: tmp_path)
    manager = _setup_manager()
    assert manager.app_config.get_device_config("loaded-device") is not None
    assert manager.app_config.get_device_config("loaded-device").device_name == "Loaded"


def test_cli_profile_create_help():
    """Test profile create --help works."""
    with pytest.raises(SystemExit) as exc:
        main(["profile", "create", "--help"])
    assert exc.value.code == 0


def test_cli_profile_rename_help():
    """Test profile rename --help works."""
    with pytest.raises(SystemExit) as exc:
        main(["profile", "rename", "--help"])
    assert exc.value.code == 0


def test_cli_profile_delete_help():
    """Test profile delete --help works."""
    with pytest.raises(SystemExit) as exc:
        main(["profile", "delete", "--help"])
    assert exc.value.code == 0

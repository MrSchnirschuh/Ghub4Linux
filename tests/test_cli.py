"""Tests for ghub4linux CLI module."""
import pytest

from ghub4linux.cli import main


def test_cli_list_help():
    """Test that --help works without hardware."""
    with pytest.raises(SystemExit) as exc:
        main(["list", "--help"])
    assert exc.value.code == 0


def test_cli_info_help():
    """Test info subcommand help."""
    with pytest.raises(SystemExit) as exc:
        main(["info", "--help"])
    assert exc.value.code == 0


def test_cli_battery_help():
    """Test battery subcommand help."""
    with pytest.raises(SystemExit) as exc:
        main(["battery", "--help"])
    assert exc.value.code == 0


def test_cli_dpi_help():
    """Test dpi subcommand help."""
    with pytest.raises(SystemExit) as exc:
        main(["dpi", "--help"])
    assert exc.value.code == 0


def test_cli_lighting_help():
    """Test lighting subcommand help."""
    with pytest.raises(SystemExit) as exc:
        main(["lighting", "--help"])
    assert exc.value.code == 0


def test_cli_no_args():
    """Test that no args shows error."""
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2  # argparse error

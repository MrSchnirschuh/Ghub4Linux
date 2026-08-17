"""Tests for ghub4linux CLI refactor helpers."""

import argparse

import pytest

from ghub4linux.cli import CLI_COMMANDS, PROFILE_COMMANDS, _add_subcommand, main


def test_add_subcommand_with_short_flag():
    """Short flag aliases are registered correctly."""
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()

    def handler(args):
        args.handled = True

    _add_subcommand(
        sub,
        "demo",
        "Demo command",
        [
            ("device_id", None, {"help": "Device ID"}),
            ("--output", ("-o",), {"default": None, "help": "Output file"}),
        ],
        handler,
    )

    args = parser.parse_args(["demo", "abc", "-o", "out.json"])
    assert args.device_id == "abc"
    assert args.output == "out.json"


def test_profile_export_short_flag_parses():
    """`profile export -o FILE` works after refactor."""
    with pytest.raises(SystemExit) as exc:
        main(["profile", "export", "--help"])
    assert exc.value.code == 0


def test_command_tables_are_non_empty():
    """CLI_COMMANDS and PROFILE_COMMANDS are populated."""
    assert CLI_COMMANDS
    assert PROFILE_COMMANDS
    names = {name for name, _, _ in CLI_COMMANDS}
    assert {"list", "info", "dpi", "lighting", "monitor"} <= names


def test_subcommand_help_contains_examples(capsys):
    """Every top-level and profile subcommand --help shows a usage example."""
    from ghub4linux.cli import CLI_EXAMPLES, PROFILE_EXAMPLES, main

    for cmd in CLI_EXAMPLES:
        with pytest.raises(SystemExit):
            main([cmd, "--help"])
        out = capsys.readouterr().out
        assert "Example:" in out, f"{cmd} --help missing example"
        assert "ghub4linux-cli" in out, f"{cmd} --help missing usage line"

    for cmd in PROFILE_EXAMPLES:
        with pytest.raises(SystemExit):
            main(["profile", cmd, "--help"])
        out = capsys.readouterr().out
        assert "Example:" in out, f"profile {cmd} --help missing example"

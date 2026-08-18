"""Tests for terminal styling helpers."""

from unittest.mock import patch

import ghub4linux.style as style_module
from ghub4linux.style import style, bold, dim


def test_style_disabled_without_color():
    with patch.object(style_module, "_COLOR_ENABLED", False):
        assert style("hello", color="red") == "hello"
        assert bold("hello") == "**hello**"
        assert dim("hello") == "hello"


def test_style_red_bold():
    with patch.object(style_module, "_COLOR_ENABLED", True):
        assert style("hello", color="red", bold=True) == "[1;31mhello[0m"


def test_bold_without_color():
    with patch.object(style_module, "_COLOR_ENABLED", True):
        assert bold("hello") == "**hello**"


def test_bold_with_color():
    with patch.object(style_module, "_COLOR_ENABLED", True):
        assert style("hello", color="green", bold=True) == "[1;32mhello[0m"


def test_dim():
    with patch.object(style_module, "_COLOR_ENABLED", True):
        assert dim("hello") == "[2mhello[0m"

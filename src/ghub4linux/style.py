"""Central terminal styling helpers.

Ponytail: no colorama/rich dependency; use plain ANSI when supported and
fallback to no-ops so output stays readable in pipes or non-tty environments.
"""

import os
import sys


def _supports_color() -> bool:
    """Return True when stderr is a tty and NO_COLOR is not set."""
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stderr.isatty()


_COLOR_ENABLED = _supports_color()


def style(text: str, *, bold: bool = False, color: str | None = None) -> str:
    """Style *text* with optional ANSI bold/color if color is enabled.

    Colors: "red", "green", "yellow", "blue", "cyan", "magenta".
    """
    if not _COLOR_ENABLED or not color:
        return f"**{text}**" if bold else text
    codes: list[int] = []
    if bold:
        codes.append(1)
    color_code = {
        "red": 31,
        "green": 32,
        "yellow": 33,
        "blue": 34,
        "magenta": 35,
        "cyan": 36,
    }.get(color)
    if color_code is not None:
        codes.append(color_code)
    if not codes:
        return text
    return f"\033[{';'.join(str(c) for c in codes)}m{text}\033[0m"


def bold(text: str) -> str:
    """Bold *text* if color is enabled."""
    return style(text, bold=True)


def dim(text: str) -> str:
    """Dim *text* if color is enabled, else return it unchanged."""
    return f"\033[2m{text}\033[0m" if _COLOR_ENABLED else text

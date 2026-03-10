"""Entry point for ghub4linux – runnable as `ghub4linux` or `python -m ghub4linux`."""

import sys

from ghub4linux.app import GhubApplication


def main() -> None:
    """Start the Ghub4Linux GTK4/Adwaita application."""
    app = GhubApplication()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()

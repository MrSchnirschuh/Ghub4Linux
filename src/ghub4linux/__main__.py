"""Allow running ghub4linux as a module: python -m ghub4linux."""

import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())

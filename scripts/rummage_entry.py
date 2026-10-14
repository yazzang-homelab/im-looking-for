"""Entry point for the standalone (PyInstaller) build."""

import sys

from rummage.cli import main

if __name__ == "__main__":
    sys.exit(main())

"""Entry point for the standalone (PyInstaller) build."""

import sys

from im_looking_for.cli import main

if __name__ == "__main__":
    sys.exit(main())

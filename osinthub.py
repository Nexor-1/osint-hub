"""OSINT Hub launcher (also the PyInstaller entry point)."""

import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())

"""Enables `python -m llmscrape`."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())

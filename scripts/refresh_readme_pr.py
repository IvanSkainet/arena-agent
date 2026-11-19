#!/usr/bin/env python3
"""Thin entrypoint for the trusted README maintenance publisher."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.maintenance.readme_refresh import main  # noqa: E402 -- bootstrap source checkout.

if __name__ == "__main__":
    main()

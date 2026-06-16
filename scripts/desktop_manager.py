#!/usr/bin/env python3
"""Thin wrapper for the modular Arena desktop manager CLI."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arena.desktop.cli.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

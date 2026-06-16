#!/usr/bin/env python3
"""Thin wrapper for modular Arena memory recall CLI."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arena.memory.recall_cli import main  # noqa: E402
from arena.memory.recall_score import score  # noqa: E402,F401
from arena.memory.recall_sources import recall_facts  # noqa: E402,F401

if __name__ == "__main__":
    raise SystemExit(main())

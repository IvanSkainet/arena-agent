#!/usr/bin/env python3
"""Thin wrapper for modular agent helper utilities."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arena.agent_helpers.cli import main  # noqa: E402
from arena.agent_helpers.files import backup_file, patch_block, patch_replace, safe_write, verify_bash, verify_python  # noqa: E402,F401
from arena.agent_helpers.runtime import load_facts, put_fact, run_local  # noqa: E402,F401

if __name__ == "__main__":
    raise SystemExit(main())

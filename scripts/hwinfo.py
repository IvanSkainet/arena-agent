#!/usr/bin/env python3
"""Thin wrapper for modular hwinfo collector."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from arena.system.hwinfo_cli import main  # noqa: E402
from arena.system.hwinfo_collect import collect_full, collect_standard  # noqa: E402,F401
from arena.system.hwinfo_cim import get_cim_all_list, get_uptime  # noqa: E402,F401

if __name__ == "__main__":
    main()

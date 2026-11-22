#!/usr/bin/env python3
"""Run one explicit full-suite benchmark and retain its evidence outside Git."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.governance.benchmark_runner import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

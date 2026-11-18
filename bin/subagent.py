#!/usr/bin/env python3
"""Source-checkout entry point; implementation is shipped in the wheel."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from arena.subagent_cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

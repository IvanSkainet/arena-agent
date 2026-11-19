#!/usr/bin/env python3
"""Fail closed if a filtered upstream contract silently stops selecting tests."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.boe_upstream_results import (  # noqa: E402, F401 -- compatibility for existing report consumers
    REQUIRED_TESTS,
    check_results,
)

if __name__ == "__main__":
    check_results(Path(sys.argv[1]))
    print("all three upstream contracts selected and passed")

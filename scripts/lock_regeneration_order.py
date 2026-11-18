#!/usr/bin/env python3
"""Print the dependency-safe root requirements compilation order (T73)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.lock_regeneration import regeneration_order


def main() -> int:
    try:
        ordered = regeneration_order(Path(__file__).resolve().parents[1])
    except (OSError, ValueError) as exc:
        print(f"lock regeneration order: {exc}", file=sys.stderr)
        return 1
    print("\n".join(ordered))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

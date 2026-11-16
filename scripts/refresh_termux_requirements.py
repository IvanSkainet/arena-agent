#!/usr/bin/env python3
"""CLI for Termux locks; first install the generator prerequisite: packaging."""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    """Resolve the source checkout and delegate to the implementation."""
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
    from arena.termux_requirements import main as generate

    return generate()


if __name__ == "__main__":
    sys.exit(main())

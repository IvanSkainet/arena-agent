#!/usr/bin/env python3
"""Fail closed when SECURITY.md drifts from ARENA_* source references."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Bounded E402: direct script execution must bootstrap the repository root
# before importing the project package; no other imports are deferred.
from arena.governance.security_env_inventory import (  # noqa: E402
    SecurityEnvInventoryError,
    verify_inventory,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.repo_root.resolve()
    try:
        verify_inventory(root, root / "SECURITY.md")
    except (OSError, SyntaxError, SecurityEnvInventoryError) as exc:
        print(f"security environment inventory failed: {exc}", file=sys.stderr)
        return 1
    print("security environment inventory: source and SECURITY.md agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

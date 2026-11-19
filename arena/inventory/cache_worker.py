#!/usr/bin/env python3
"""Thin detached entrypoint for the two fixed slow inventory probes."""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)
    from arena.inventory.probe_agent_ctx import get_git_repos, get_python_venvs
    from arena.inventory.slow_probe_cache import refresh_probe

    collectors = {"python_venvs": get_python_venvs, "git_repos": get_git_repos}
    if len(sys.argv) != 3 or sys.argv[1] not in collectors:
        return 2
    try:
        refresh_probe(sys.argv[1], Path(sys.argv[2]), collectors[sys.argv[1]])
    except (OSError, ValueError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

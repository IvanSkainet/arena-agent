#!/usr/bin/env python3
"""Extract runtime + full-extras dep specs from pyproject.toml.

Prints one requirement per line, suitable for
``pip-audit --requirement -``. Kept as a scriptlet so both the
Makefile and the CI workflow use the exact same extraction --
if we ever add a new required dep, both codepaths pick it up
automatically.
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    py = root / "pyproject.toml"
    if not py.exists():
        print(f"error: pyproject.toml not found at {py}", file=sys.stderr)
        return 2
    d = tomllib.loads(py.read_text())
    proj = d.get("project", {})
    deps = list(proj.get("dependencies", []))
    extras = proj.get("optional-dependencies", {}).get("full", [])
    for spec in deps + extras:
        print(spec)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Sanity-check requirements-ci.lock for environment-marker coverage.

Why this exists: uv's --universal resolver (0.12.1 observed) can drop
marker-forked dependencies on cold caches, producing a lock that
silently lacks pins such as async-timeout (aiohttp, py<3.11). Hash-mode
pip then fails only on the affected matrix images - exactly the class
of bug this lock was created to prevent. Generation alone cannot be
trusted; the artifact must be verified.

Checks are cheap and stdlib-only; run before every hash-mode install.
"""
from __future__ import annotations

import re
from pathlib import Path

LOCK = Path(__file__).resolve().parent.parent / "requirements-ci.lock"

# package name -> a regex its pin line must satisfy (marker guard)
REQUIRED_MARKER_PINS = {
    # aiohttp's dep for Python without asyncio.timeout; needed on 3.10 cells
    "async-timeout": r"async-timeout==[\d.]+\s*;\s*python.*<\s*'3\.11'",
    # pytest/hypothesis dep on older interpreters
    "exceptiongroup": r"exceptiongroup==[\d.]+\s*;\s*python.*<\s*'3\.11'",
    # pytest/mypy on <3.11, coverage on <=3.11
    "tomli": r"tomli==[\d.]+\s*;\s*python.*<\s*=?\s*'3\.11",
}
# packages that must simply be present (no marker expectation)
REQUIRED_PINS = ["aiohttp", "pytest", "colorama", "requests", "ruff"]


def main() -> int:
    text = LOCK.read_text(encoding="utf-8")
    pin_lines = [ln for ln in text.splitlines() if re.match(r"^[a-zA-Z0-9_-]+==", ln)]
    problems = []

    for name, pattern in REQUIRED_MARKER_PINS.items():
        if not any(re.search(pattern, ln) for ln in pin_lines):
            problems.append(
                f"missing/wrong marker pin: {name} (expect `{pattern}`). "
                "The lock likely suffered the cold-cache marker-drop; "
                "regenerate it (see requirements-ci.in header) and rerun this check."
            )
    for name in REQUIRED_PINS:
        if not any(ln.startswith(f"{name}==") for ln in pin_lines):
            problems.append(f"missing pin: {name}")

    if problems:
        print("requirements-ci.lock FAILED marker-coverage check:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK: lock has {len(pin_lines)} pins incl. all marker-guarded deps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

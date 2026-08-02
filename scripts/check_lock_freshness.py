#!/usr/bin/env python3
"""Fail-closed guard: every `.in` requirement must be pinned in its `.lock`.

Why this exists
---------------
CI installs exclusively from the `.lock` files (`pip install --require-hashes
-r requirements-ci.lock`). The `.in` files are inputs to the generator and are
never installed, so editing one without regenerating its lock is invisible:
the new dependency simply is not there, CI stays green, and the failure
surfaces later as an ImportError in whatever job first needs it.

Demonstrated before writing this: appending `attrs==25.4.0` to
requirements-ci.in left the existing lock guard reporting
"OK: lock has 77 pins" and the whole pipeline green.

This is the same class of check as `uv lock --check` / `cargo`'s lockfile
verification, adapted to the pip-compile pair layout this repo uses.

What is checked, for each `<name>.in` / `<name>.lock` pair:
  1. every requirement declared in the `.in` appears as a `==` pin in the lock;
  2. the pinned VERSION matches the version the `.in` demands (a stale lock
     that pins an older release is just as broken as a missing entry);
  3. every lock entry carries at least one `--hash=` (hash-mode installs abort
     on the first unhashed requirement, and finding that out on a CI runner
     costs a full matrix cycle).

What is deliberately NOT checked: transitive closure correctness. Proving the
lock resolves the full dependency graph means running the resolver, which is
the generator's job; the real proof stays the `--require-hashes` install on
the oldest supported interpreter.

Usage:  python3 scripts/check_lock_freshness.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Requirement line in a `.in`: name==version, optional extras/marker.
IN_REQ = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?P<extras>\[[^\]]+\])?"
    r"==(?P<version>[^\s;#]+)"
)
# Pinned line in a `.lock` (pip-compile/uv style, may carry a marker).
LOCK_PIN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;\\]+)"
)


def canonical(name: str) -> str:
    """PEP 503 normalisation: import-linter == import_linter == Import.Linter."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_in(path: Path) -> dict[str, str]:
    reqs: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = IN_REQ.match(line)
        if m:
            reqs[canonical(m.group("name"))] = m.group("version")
    return reqs


def parse_lock(path: Path) -> tuple[dict[str, str], set[str]]:
    """Return ({canonical name: version}, {names carrying a --hash=})."""
    pins: dict[str, str] = {}
    hashed: set[str] = set()
    current: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        m = LOCK_PIN.match(line)
        if m:
            current = canonical(m.group("name"))
            pins[current] = m.group("version")
            if "--hash=" in line:
                hashed.add(current)
            continue
        if current and "--hash=" in line:
            hashed.add(current)
        elif line and not line.startswith(("#", "--hash=", "\\")):
            current = None
    return pins, hashed


def check_pair(stem: str) -> list[str]:
    in_path = ROOT / f"{stem}.in"
    lock_path = ROOT / f"{stem}.lock"
    if not in_path.exists() or not lock_path.exists():
        return [f"{stem}: missing .in or .lock of the pair"]

    declared = parse_in(in_path)
    pinned, hashed = parse_lock(lock_path)
    problems: list[str] = []

    for name, want in declared.items():
        got = pinned.get(name)
        if got is None:
            problems.append(
                f"{in_path.name} declares '{name}=={want}' but {lock_path.name} "
                f"has no pin for it — the lock was not regenerated. "
                f"See the .in header for the exact command."
            )
        elif got != want:
            problems.append(
                f"{in_path.name} wants '{name}=={want}' but {lock_path.name} "
                f"pins {got} — stale lock; regenerate it."
            )

    unhashed = sorted(set(pinned) - hashed)
    if unhashed:
        problems.append(
            f"{lock_path.name}: {len(unhashed)} pin(s) carry no --hash= "
            f"({', '.join(unhashed[:5])}{'...' if len(unhashed) > 5 else ''}). "
            "A --require-hashes install aborts on the first one."
        )
    return problems


def main() -> int:
    stems = sorted(p.with_suffix("").name for p in ROOT.glob("requirements-*.in"))
    if not stems:
        print("no requirements-*.in files found — guard is looking in the "
              "wrong place, fix it before trusting it", file=sys.stderr)
        return 2

    all_problems: list[str] = []
    for stem in stems:
        all_problems.extend(check_pair(stem))

    if all_problems:
        print("LOCK FRESHNESS FAILURES:", file=sys.stderr)
        for p in all_problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    print(f"OK: {len(stems)} .in/.lock pair(s) agree, every pin is hashed "
          f"({', '.join(stems)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

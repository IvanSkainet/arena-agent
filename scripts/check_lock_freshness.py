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

Pairs are discovered as `requirements-*.in` in the repository root, plus the
explicit entries in EXTRA_PAIRS. The explicit list exists because
`ci/guarddog/requirements.{in,txt}` is deliberately outside the root -- it is
excluded from Dependabot so its per-package bumps stop breaking the required
GuardDog check (#307) -- and a lock that no gate reads is a lock that can
drift. Discovery by glob would have silently dropped it the moment it moved.

Usage:  python3 scripts/check_lock_freshness.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (.in, .lock) pairs that do not follow the root `requirements-<name>.{in,lock}`
# convention. Listed by hand, not globbed: each one is outside the root for a
# reason recorded next to it, and a gate that discovers its own inputs stops
# noticing when one disappears.
EXTRA_PAIRS: tuple[tuple[Path, Path], ...] = (
    # Outside the root so Dependabot's pip ecosystem cannot propose
    # per-package bumps of guarddog's own transitive pins -- those made
    # `pip install --require-hashes` fail with ResolutionImpossible before
    # the scanner ran, turning the required GuardDog check red while no
    # malware scan happened (#285, #307). The lock is regenerated whole,
    # alongside a guarddog bump.
    #
    # What this entry buys, precisely: the direct pin in the `.in` must
    # match the lock, and every lock entry must carry a hash. It does NOT
    # prove the transitive closure came from a real compile -- an edited
    # transitive pin that keeps a syntactically valid `--hash=` passes
    # here, and would then fail at install time when the hash does not
    # match the artifact on PyPI. That is the same guarantee the root
    # pairs get; proving the closure means running the resolver, which is
    # the generator's job and is deliberately out of scope (see the module
    # docstring).
    (ROOT / "ci" / "guarddog" / "requirements.in",
     ROOT / "ci" / "guarddog" / "requirements.txt"),
)

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


def pin_problems(
    declared: dict[str, str],
    pinned: dict[str, str],
    in_path: Path,
    lock_path: Path,
) -> list[str]:
    """Checks 1 and 2: every declared requirement is pinned, at that version."""
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
    return problems


def hash_problems(
    pinned: dict[str, str], hashed: set[str], lock_path: Path
) -> list[str]:
    """Check 3: a hash-mode install aborts on the first unhashed requirement."""
    unhashed = sorted(set(pinned) - hashed)
    if not unhashed:
        return []
    return [
        f"{lock_path.name}: {len(unhashed)} pin(s) carry no --hash= "
        f"({', '.join(unhashed[:5])}{'...' if len(unhashed) > 5 else ''}). "
        "A --require-hashes install aborts on the first one."
    ]


def check_paths(in_path: Path, lock_path: Path) -> list[str]:
    missing = [
        path.relative_to(ROOT).as_posix()
        for path in (in_path, lock_path)
        if not path.exists()
    ]
    if missing:
        # Name the actual files. The guarddog pair's lock is called
        # `requirements.txt`, so a hardcoded ".lock" would send the reader
        # looking for a file that never existed.
        return [f"{', '.join(missing)}: missing from the pair"]

    declared = parse_in(in_path)
    pinned, hashed = parse_lock(lock_path)
    return (
        pin_problems(declared, pinned, in_path, lock_path)
        + hash_problems(pinned, hashed, lock_path)
    )


def check_pair(stem: str) -> list[str]:
    """Root-convention pair: `requirements-<stem>.in` / `.lock`."""
    return check_paths(ROOT / f"{stem}.in", ROOT / f"{stem}.lock")


def check_extra_pairs() -> list[str]:
    """The pairs that do not live in the root, listed in EXTRA_PAIRS.

    A missing entry is a failure, not a skip: an entry listed here and then
    deleted is exactly the drift this guard exists to notice.
    """
    problems: list[str] = []
    for in_path, lock_path in EXTRA_PAIRS:
        if not in_path.exists():
            problems.append(
                f"{in_path.relative_to(ROOT).as_posix()} is listed in "
                "EXTRA_PAIRS but does not exist — if the pair moved, move the "
                "entry with it; if it is gone, delete the entry deliberately."
            )
            continue
        problems.extend(check_paths(in_path, lock_path))
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
    all_problems.extend(check_extra_pairs())

    if all_problems:
        print("LOCK FRESHNESS FAILURES:", file=sys.stderr)
        for p in all_problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    names = stems + [p.relative_to(ROOT).as_posix() for p, _ in EXTRA_PAIRS]
    print(f"OK: {len(names)} .in/.lock pair(s) agree, every pin is hashed "
          f"({', '.join(names)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

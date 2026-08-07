#!/usr/bin/env python3
"""Forbid delivering a queued file before the claim on it has succeeded.

The bug this exists for, twice
------------------------------

v4.166.0, `arena/relay/store.py::claim_next`: the Windows CI matrix
reported ``lost -29 message(s)``. A *negative* loss -- messages were
delivered more than once. The claim was `os.rename`, and the platforms
disagree about what that guarantees under a race.

v4.166.2, `arena/relay/store.py::read_replies` (bug #73): the exact same
shape, in the mirror-image direction, untouched -- because the first fix
was scoped to the direction that had gone red rather than to the
property. Measured on the unfixed code: 300 replies drained by 16
threads produced **542 deliveries, 96 of them duplicates**.

One defect found twice in one file is a class, not an incident. This is
the ratchet that makes the third instance fail before it ships.

What is actually checked
------------------------

Not "read before delete". The bytes *must* be read while the file still
exists, so that ordering is mandatory and flagging it would be noise --
a detector with false positives is worse than no detector at all, and
the first draft of this script flagged the already-fixed `read_replies`
for exactly that reason.

The real property is narrower:

    In a loop over a directory listing, a value must not escape --
    returned, yielded, or appended to an accumulator -- before the
    statement that claims the file (unlink/remove/rename/replace/move)
    has run.

Claiming is what makes delivery exclusive. If the value escapes first,
two workers racing the same entry both deliver it, and a
``missing_ok=True`` on the later delete erases the evidence. Delivery
must be downstream of the claim.

A loop with no claim at all is not this shape -- read-only scans are
fine. A loop that claims but delivers nothing is housekeeping, also
fine. Only claim-and-deliver in the wrong order fails.

Escape hatch: a loop whose enclosing function takes an ``O_EXCL`` lock
is already exclusive by a stronger mechanism (that is how `claim_next`
is written), so the ordering inside it does not matter.

Usage:
    python scripts/claim_order_ratchet.py
    python scripts/claim_order_ratchet.py --verbose   # show scanned loops
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Directories whose *.py files are runtime code worth guarding.
SCAN_ROOTS = ("arena", "bin")

# Calls that take exclusive ownership of a directory entry.
CLAIM_CALLS = frozenset({"unlink", "remove", "rename", "replace", "move"})

# Calls that hand a value to the caller / an accumulator.
ESCAPE_CALLS = frozenset({"append", "extend", "add"})

# Iterating one of these means "walk a directory listing".
LISTING_MARKERS = ("glob", "iterdir", "listdir", "scandir")


def _is_listing_loop(loop: ast.For) -> bool:
    dumped = ast.dump(loop.iter)
    return any(marker in dumped for marker in LISTING_MARKERS)


def _first_index(body: list[ast.stmt], predicate) -> int | None:
    """Index of the first top-level statement in `body` matching predicate."""
    for index, stmt in enumerate(body):
        if predicate(stmt):
            return index
    return None


def _contains_claim(stmt: ast.stmt) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in CLAIM_CALLS
        for node in ast.walk(stmt)
    )


def _contains_escape(stmt: ast.stmt) -> bool:
    for node in ast.walk(stmt):
        if isinstance(node, (ast.Return, ast.Yield, ast.YieldFrom)):
            return True
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ESCAPE_CALLS):
            return True
    return False


def _has_excl_lock(func: ast.AST) -> bool:
    """True when the function guards itself with O_CREAT|O_EXCL."""
    for node in ast.walk(func):
        if isinstance(node, ast.Attribute) and node.attr == "O_EXCL":
            return True
    return False


def scan_file(path: pathlib.Path) -> list[tuple[str, int]]:
    """Return (function name, line) for every offending loop in `path`."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        # Unparseable files are the linter's problem, not this gate's.
        return []

    offenders: list[tuple[str, int]] = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if _has_excl_lock(func):
            continue
        for loop in ast.walk(func):
            if not isinstance(loop, ast.For) or not _is_listing_loop(loop):
                continue
            claim_at = _first_index(loop.body, _contains_claim)
            escape_at = _first_index(loop.body, _contains_escape)
            if claim_at is None or escape_at is None:
                continue
            if escape_at < claim_at:
                offenders.append((func.name, loop.lineno))
    return offenders


def iter_sources() -> list[pathlib.Path]:
    found: list[pathlib.Path] = []
    for name in SCAN_ROOTS:
        base = ROOT / name
        if base.is_dir():
            found.extend(sorted(base.rglob("*.py")))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true",
                        help="report how many files were scanned")
    args = parser.parse_args()

    failures: list[str] = []
    scanned = 0
    for path in iter_sources():
        scanned += 1
        for func_name, lineno in scan_file(path):
            rel = path.relative_to(ROOT)
            failures.append(f"{rel}:{lineno}  {func_name}()")

    if args.verbose:
        print(f"scanned {scanned} files under {', '.join(SCAN_ROOTS)}")

    if failures:
        print("claim-order ratchet FAILED -- a value escapes before the "
              "file is claimed:\n")
        for line in failures:
            print(f"  {line}")
        print("\nThis is bug #73 (and the v4.166.0 `lost -29`) reappearing: "
              "two workers\nracing the same entry both deliver it. Claim "
              "first -- unlink/rename must\nsucceed before the value is "
              "returned or appended -- and skip the entry when\nthe claim "
              "loses. See arena/relay/store.py::read_replies.")
        return 1

    print(f"claim order ok ({scanned} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

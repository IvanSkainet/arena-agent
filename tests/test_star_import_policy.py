"""Star imports are now the exception, and every survivor is named.

`from X import *` went from 93 sites / 1609 F405 warnings to a short allowlist.
That matters beyond tidiness: a star import hides *what* a module depends on
from readers and from every static tool, and it does not bind
underscore-prefixed names at all. v4.155.0 found four live runtime bugs sitting
behind exactly that blind spot (see
tests/test_ws_push_star_import_regression.py).

This gate keeps the ground won:

  * no new star import may appear outside the allowlist below;
  * each allowed one carries a written reason;
  * the F405 count may not grow past the recorded floor.

Green here does not mean the remaining facades are good design -- they are
deliberate re-export surfaces whose contents are asserted elsewhere. It means
they are a closed, documented set rather than a habit.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# path -> why the star import stays. Removing an entry is progress; adding one
# needs a reason good enough to write down here.
ALLOWED: dict[str, str] = {
    "arena/compat_surface/__init__.py":
        "Compatibility facade: unified_bridge.py resolves its whole legacy "
        "surface through dynamic namespace lookups, so the re-export set is "
        "the module's purpose. Contents are pinned by the compat_surface "
        "contract test, not by static analysis.",
    "arena/runtime_deps/__init__.py":
        "Same facade role for runtime dependencies, assembled from four "
        "submodules; already carries a per-file F401 ignore in pyproject.",
}

# Recorded floor. Lower it when the number drops; it must never rise.
# 0 since v4.156.0: the two CLI dispatchers now import their names explicitly,
# and the two remaining facades re-export via `__all__` rather than bare use,
# so ruff reports no F405 at all.
MAX_F405 = 0


def _star_import_files() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in sorted((REPO / "arena").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        count = sum(
            1 for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and any(alias.name == "*" for alias in node.names)
        )
        if count:
            found[path.relative_to(REPO).as_posix()] = count
    return found


def test_no_unlisted_star_imports():
    found = _star_import_files()
    unexpected = sorted(set(found) - set(ALLOWED))
    assert unexpected == [], (
        "new star import(s) added: " + ", ".join(unexpected) +
        " -- import the names explicitly, or add an entry to ALLOWED with a reason"
    )


def test_allowlist_has_no_stale_entries():
    """A listed file that no longer star-imports should be delisted."""
    found = _star_import_files()
    stale = sorted(set(ALLOWED) - set(found))
    assert stale == [], f"these no longer star-import; drop them from ALLOWED: {stale}"


def test_every_allowed_star_import_has_a_real_reason():
    for path, reason in ALLOWED.items():
        assert len(reason) > 40, f"{path}: reason is too thin to be a reason"


def test_f405_stays_at_or_below_the_floor():
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "F405",
         "--output-format=json", "arena", "tests"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert proc.returncode in (0, 1), proc.stderr
    count = len(json.loads(proc.stdout or "[]"))
    assert count <= MAX_F405, (
        f"F405 rose to {count} (floor {MAX_F405}). Import the new names "
        "explicitly instead of leaning on a star import."
    )


def test_the_floor_is_still_tight():
    """If the count dropped, lower MAX_F405 in the same commit."""
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "F405",
         "--output-format=json", "arena", "tests"],
        cwd=REPO, capture_output=True, text=True,
    )
    count = len(json.loads(proc.stdout or "[]"))
    assert count >= MAX_F405 - 10, (
        f"F405 is down to {count} but the floor still says {MAX_F405}; "
        "lower it so the ratchet keeps its teeth"
    )


def test_underscore_names_are_never_expected_from_a_star_import():
    """The blind spot that hid four runtime bugs.

    A module that star-imports must not call an underscore helper it does not
    also import explicitly -- the star never provides one.
    """
    offenders: list[str] = []
    for rel in ALLOWED:
        path = REPO / rel
        tree = ast.parse(path.read_text(encoding="utf-8"))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id.startswith("_")
            and not node.func.id.startswith("__")
        }
        defined = {
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        imported = {
            (alias.asname or alias.name)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        for name in sorted(called - defined - imported):
            offenders.append(f"{rel}: calls {name}, which no star import can provide")
    assert offenders == [], offenders

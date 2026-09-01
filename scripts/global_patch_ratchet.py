#!/usr/bin/env python3
"""Gate: tests must not patch a stdlib module through a production alias.

`import subprocess` inside `arena/admin/bore.py` does not create a
private copy. `bore_mod.subprocess` **is** the global `subprocess`
module, so

    monkeypatch.setattr(bore_mod.subprocess, "Popen", fake)

replaces `Popen` for the whole process, not for bore. It reads like a
scoped substitution and is not one.

That has now cost two releases:

* **#230** -- a test patched `lm.time.time` with a three-entry timeline.
  Concurrent code drew from it and the assertion failed with `102.0`,
  intermittently, on Windows, on two different Python versions.
* **#235** -- a test patched `bore_mod.subprocess.Popen` and recorded
  the argv it saw. A runtime probe in `arena/workbench/runtimes.py`
  spawned `go version` through `subprocess.run` (which calls `Popen`),
  and the bore test recorded *that* argv instead.

Both were Windows-only in symptom and neither was a Windows bug: the
coarser clock and different scheduling just made the interleaving
likelier. Both were diagnosed the slow way.

The escape only *bites* when something else runs concurrently, so this
gate flags the intersection: an aliased-stdlib patch in a test whose
production module starts a thread, a task, or a pool. That is the
population where the next #235 comes from.

It is a ratchet, not a ban. The current count lives in
`scripts/global_patch_baseline.json`; rewriting every site in one change
would be a large, risky diff touching tests unrelated to any live
defect. The count may fall and must never rise: a new one is
a new latent flake, and the fix is a module-local seam (`_spawn()`,
`_now()`) that a test can patch without reaching outside the module.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS = REPO_ROOT / "tests"
ARENA = REPO_ROOT / "arena"
BASELINE = REPO_ROOT / "scripts" / "global_patch_baseline.json"

# Stdlib modules a production module commonly imports and a test commonly
# wants to fake. Patching any of these through an alias is process-wide.
STDLIB_NAMES = frozenset({
    "asyncio", "json", "os", "platform", "random", "select", "shutil",
    "signal", "socket", "ssl", "subprocess", "sys", "tempfile",
    "threading", "time",
})

# What makes an escaped patch observable by someone else.
_CONCURRENCY = re.compile(
    r"threading\.Thread\(|asyncio\.create_task\(|ThreadPoolExecutor\(")

MIN_TEST_FILES = 50


def _imported_by_any(stem: str, starters: set[str],
                     sources: dict[str, str]) -> bool:
    """True if any thread-starting module imports `stem`.

    Then `stem`'s globals can be reached from a concurrent context even
    though it starts nothing itself -- which is exactly #230.
    """
    pattern = (rf"\bimport\s+{re.escape(stem)}\b|"
               rf"\bfrom\s+[\w.]*\b{re.escape(stem)}\s+import\b")
    return any(re.search(pattern, sources[starter]) for starter in starters)


def concurrent_modules() -> set[str]:
    """Modules whose code can run while another test holds a patch.

    Two ways in. A module qualifies if it starts a thread, task or pool
    itself -- or if a module that *does* imports it. The second half is
    not padding: it is exactly what #230 was.

    `arena/observability/live_metrics.py` starts nothing. The ~1Hz push
    loop lives in `live_metrics_handler.py`, which imports it and calls
    `live_metrics_snapshot()` from a task. A test patching
    `lm.time.time` therefore handed its three-entry timeline to that
    loop. Judging live_metrics on its own source would have called it
    safe and missed the defect entirely -- verified against the pre-fix
    commit, where the narrow rule reported zero findings for it.
    """
    starters: set[str] = set()
    sources: dict[str, str] = {}
    for path in sorted(ARENA.rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        sources[path.stem] = text
        if _CONCURRENCY.search(text):
            starters.add(path.stem)

    return starters | {
        stem for stem in sources
        if stem not in starters
        and _imported_by_any(stem, starters, sources)
    }


def _plain_import_aliases(node: ast.Import) -> dict[str, str]:
    """`import arena.admin.bore as bore_mod` -> {bore_mod: arena.admin.bore}."""
    return {a.asname or a.name.split(".")[0]: a.name
            for a in node.names if a.name.startswith("arena")}


def _from_import_aliases(node: ast.ImportFrom) -> dict[str, str]:
    """`from arena.admin import bore` -> {bore: arena.admin.bore}."""
    module = node.module or ""
    if not module.startswith("arena"):
        return {}
    return {a.asname or a.name: f"{module}.{a.name}" for a in node.names}


def _arena_aliases(tree: ast.AST) -> dict[str, str]:
    """Local name -> dotted arena module it refers to."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(_plain_import_aliases(node))
        elif isinstance(node, ast.ImportFrom):
            out.update(_from_import_aliases(node))
    return out


def _is_setattr_call(node: ast.Call) -> bool:
    """True for `<anything>.setattr(<target>, ...)` with at least one arg."""
    return (isinstance(node.func, ast.Attribute)
            and node.func.attr == "setattr"
            and bool(node.args))


def _patched_stdlib_alias(node: ast.Call) -> tuple[str, str] | None:
    """(alias, stdlib name) if `node` is `setattr(alias.stdlib, ...)`.

    Returns None for `setattr(mod, "_spawn", ...)` -- patching the module
    itself is the seam this gate recommends, and flagging it would make
    the advice unfollowable.
    """
    if not _is_setattr_call(node):
        return None
    target = node.args[0]
    if not isinstance(target, ast.Attribute):
        return None            # setattr(mod, "_spawn", ...) -- the seam
    if not isinstance(target.value, ast.Name):
        return None            # setattr(a.b.c, ...) -- not an alias patch
    if target.attr not in STDLIB_NAMES:
        return None            # patching a non-stdlib attribute is fine
    return target.value.id, target.attr


def _file_findings(path: Path, concurrent: set[str]) -> list[str]:
    """Escaping patches in one test file, aimed at exposed modules."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        # A test that will not parse is pytest's problem to report, not a
        # reason for this gate to call the file clean.
        return []
    aliases = _arena_aliases(tree)
    rel = path.relative_to(REPO_ROOT).as_posix()
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        found = _patched_stdlib_alias(node)
        if found is None:
            continue
        alias, stdlib_name = found
        module = aliases.get(alias)
        if not module or module.rsplit(".", 1)[-1] not in concurrent:
            continue
        out.append(f"{rel}:{node.lineno}: {alias}.{stdlib_name} -> {module}")
    return out


def findings() -> tuple[list[str], int]:
    """Every aliased-stdlib patch aimed at a module that runs concurrently."""
    concurrent = concurrent_modules()
    hits: list[str] = []
    scanned = 0
    for path in sorted(TESTS.rglob("test_*.py")):
        scanned += 1
        hits.extend(_file_findings(path, concurrent))
    return hits, scanned


def load_baseline() -> int:
    if not BASELINE.is_file():
        raise SystemExit(f"global patch ratchet: baseline missing: {BASELINE}")
    return int(json.loads(BASELINE.read_text(encoding="utf-8"))["allowed"])


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    hits, scanned = findings()
    if scanned < MIN_TEST_FILES:
        print(f"global patch ratchet: FAIL -- scanned only {scanned} test files "
              f"(expected at least {MIN_TEST_FILES}); the scan is broken")
        return 1

    if "--write-baseline" in argv:
        BASELINE.write_text(
            json.dumps({"allowed": len(hits)}, indent=2) + "\n", encoding="utf-8")
        print(f"global patch ratchet: baseline written ({len(hits)})")
        return 0

    allowed = load_baseline()
    if len(hits) > allowed:
        print(f"global patch ratchet: FAIL -- {len(hits)} sites, baseline {allowed}")
        print()
        for line in hits:
            print(f"  {line}")
        print()
        print("  A test patched a stdlib module through a production alias.")
        print("  `mod.subprocess` IS the global subprocess module, so the")
        print("  substitution applies process-wide and any concurrent code")
        print("  in that module observes it (#230, #235).")
        print()
        print("  Add a module-local seam and patch that instead:")
        print("      def _spawn(argv, **kw): return subprocess.Popen(argv, **kw)")
        print("      monkeypatch.setattr(mod, '_spawn', fake)")
        return 1

    if len(hits) < allowed:
        print(f"global patch ratchet: OK -- {len(hits)} sites, below the "
              f"baseline of {allowed}. Lower it:")
        print("  python scripts/global_patch_ratchet.py --write-baseline")
        return 0

    print(f"global patch ratchet: OK ({len(hits)} sites, {scanned} test files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

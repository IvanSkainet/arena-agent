#!/usr/bin/env python3
"""Keep the count of never-referenced public functions from growing.

170 releases in, nothing had ever been deleted from this codebase. A
sweep with Serena's `find_referencing_symbols` -- which resolves real
symbol references rather than matching text -- found twelve public
functions with **zero** callers anywhere: not in `arena/`, not in
tests, not in the dashboard, not through any registry or string
dispatch. Two of them were written the previous day, by me.

That is the real failure mode. Dead code does not arrive in a big
batch; it accumulates one abandoned helper at a time, and each one
looks reasonable on the day it is written. Nobody notices because
nothing breaks -- an unused function is invisible until someone reads
the file and wonders whether it matters.

So this is a ratchet, not a checker. It records the current count and
fails when it goes up. Removing dead code lowers the floor; adding a
helper nobody calls raises it and has to be justified.

Why a text prefilter and not an import graph
--------------------------------------------

Anything reachable by `getattr`, a name in a registry dict, an MCP tool
table, or a Dashboard fetch is *referenced* even though no Python
expression names it. A pure AST call-graph would report all of those as
dead and the gate would be uninstallable within a week -- a detector
with false positives is worse than no detector.

Counting every identifier-shaped token across every source file in the
repo is crude, but it errs the safe way: a function mentioned anywhere,
in any form, is not reported. Everything it *does* report was verified
by hand and by Serena before the floor was set.

Usage:
    python scripts/dead_code_ratchet.py
    python scripts/dead_code_ratchet.py --list
    python scripts/dead_code_ratchet.py --write-baseline
"""
from __future__ import annotations

import argparse
import ast
import collections
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE = ROOT / ".dead-code-baseline.json"

# Where public API lives. Tests and scripts are excluded: a test helper
# used by one test is normal, and a script's `main` is called by a shell.
SCAN_ROOT = ROOT / "arena"

# Extensions that can plausibly reference a Python function: other
# Python, dashboard JS, MCP/tool JSON, docs that name an entry point.
REFERENCE_GLOBS = ("*.py", "*.js", "*.json", "*.md", "*.html", "*.sh",
                   "*.yml", "*.yaml", "*.cmd", "*.bat")

SKIP_DIR_PARTS = ("/.git/", "node_modules", "/.serena/", "/__pycache__/",
                  "/.ruff_cache/", "/.pytest_cache/")

# Names that are entry points by convention: called by frameworks, shells
# or the interpreter, never by a sibling function.
CONVENTIONAL_ENTRY_POINTS = frozenset({
    "main", "run", "handle", "setup", "teardown",
    "__init__", "__call__",
})

# Methods a framework calls by name, which therefore have no caller in
# this repository and never will. Reporting them would be a false
# positive, and a false positive is how a gate gets switched off.
#
#   do_GET / do_POST / ...  -- http.server dispatches on the verb
#   https_open / http_open  -- urllib picks the handler by method name
#   do_AUTHHEAD             -- same family
FRAMEWORK_OVERRIDES = re.compile(
    r"^(do_[A-Z]+|https?_open|https?_request|https?_response|"
    r"handle_one_request|log_message|address_string)$"
)

IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def public_functions() -> dict[str, tuple[str, int]]:
    """Every public function defined under `arena/`, by name."""
    found: dict[str, tuple[str, int]] = {}
    for path in sorted(SCAN_ROOT.rglob("*.py")):
        if any(part in str(path).replace("\\", "/") for part in SKIP_DIR_PARTS):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = node.name
            if name.startswith("_") or name.startswith("test_"):
                continue
            if name in CONVENTIONAL_ENTRY_POINTS:
                continue
            if FRAMEWORK_OVERRIDES.match(name):
                continue
            found.setdefault(name, (str(path.relative_to(ROOT)), node.lineno))
    return found


def identifier_counts() -> collections.Counter:
    """How often every identifier-shaped token appears repo-wide."""
    counts: collections.Counter = collections.Counter()
    for pattern in REFERENCE_GLOBS:
        for path in ROOT.rglob(pattern):
            text = str(path).replace("\\", "/")
            if any(part in text for part in SKIP_DIR_PARTS):
                continue
            try:
                counts.update(IDENTIFIER.findall(
                    path.read_text(encoding="utf-8", errors="ignore")))
            except OSError:
                continue
    return counts


def orphans() -> list[tuple[str, str, int]]:
    """(name, file, line) for functions whose only mention is their def."""
    defined = public_functions()
    counts = identifier_counts()
    return sorted(
        (name, where, line)
        for name, (where, line) in defined.items()
        if counts[name] <= 1
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true",
                        help="print every candidate")
    parser.add_argument("--write-baseline", action="store_true",
                        help="record the current count as the new floor")
    args = parser.parse_args()

    found = orphans()
    count = len(found)

    if args.list:
        for name, where, line in found:
            print(f"  {where}:{line}  {name}()")
        print(f"\n{count} never-referenced public functions")
        return 0

    if args.write_baseline:
        BASELINE.write_text(
            json.dumps({"max_orphans": count,
                        "note": "raise only with a reason; lower it freely"},
                       indent=2) + "\n", encoding="utf-8")
        print(f"baseline set to {count}")
        return 0

    if not BASELINE.is_file():
        print(f"no baseline at {BASELINE.name}; run --write-baseline",
              file=sys.stderr)
        return 2

    floor = json.loads(BASELINE.read_text(encoding="utf-8"))["max_orphans"]
    if count > floor:
        print(f"dead code grew: {count} never-referenced public functions "
              f"(baseline {floor})\n")
        for name, where, line in found:
            print(f"  {where}:{line}  {name}()")
        print("\nEither call them, delete them, or -- if something reaches "
              "them\ndynamically that this scan cannot see -- raise the "
              "baseline with a\nnote saying what.")
        return 1

    if count < floor:
        print(f"dead code shrank: {count} < {floor}. "
              f"Run --write-baseline to lock it in.")
        return 0

    print(f"dead code ok ({count} candidates, baseline {floor})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

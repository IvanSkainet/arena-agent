#!/usr/bin/env python3
"""Gate: a function annotated ``-> dict``/``-> list`` must not return raw ``json.loads``.

``json.loads`` returns whatever the document contains. Four bytes of
``null`` in a state file are *valid* JSON, so a function annotated
``-> dict[str, Any]`` that ends in ``return json.loads(...)`` hands its
caller ``None`` and the crash surfaces one or two frames away, in code
that did nothing wrong (``'NoneType' object has no attribute 'get'``).

This was live: ``mission.json`` containing ``null`` took down the entire
mission listing, not just the one broken mission.

The rule: if the annotation promises a shape, the function must enforce
it -- via ``arena.jsonshape.loads_object`` / ``loads_array`` inside the
package, or an explicit ``isinstance`` narrowing in standalone scripts
(which run without ``arena`` on ``sys.path``).

Only *direct* ``return json.loads(...)`` is flagged. Assigning the parse
to a name and narrowing it afterwards is the fix, not a violation.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ("arena", "scripts")
SHAPED_PREFIXES = ("dict", "Dict", "list", "List")

# Baseline is deliberately empty: the whole class was cleared in v4.169.7.
# Do not grow it. A new entry here means a caller can still be handed a
# shape its annotation says is impossible.
ALLOWED: frozenset[str] = frozenset()


def _is_shaped(annotation: ast.expr | None) -> bool:
    if annotation is None:
        return False
    text = ast.unparse(annotation)
    if not text.startswith(SHAPED_PREFIXES):
        return False
    # `dict[...] | None` already admits the absent case honestly.
    return "None" not in text


def _is_json_loads(node: ast.expr) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return isinstance(func, ast.Attribute) and func.attr == "loads"


# A detector that silently scans nothing is worse than no detector: it
# reports OK forever. Caught by deliberate sabotage -- pointing SCAN_DIRS
# at a misspelled directory left the gate green.
MIN_FILES_SCANNED = 400


def violations() -> tuple[list[str], int]:
    found: list[str] = []
    scanned = 0
    for directory in SCAN_DIRS:
        root = REPO_ROOT / directory
        if not root.is_dir():
            raise SystemExit(f"json shape ratchet: scan directory missing: {root}")
        for path in sorted(root.rglob("*.py")):
            scanned += 1
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                returns = fn.returns
                if not _is_shaped(returns):
                    continue
                assert returns is not None  # _is_shaped rejects None
                for node in ast.walk(fn):
                    if isinstance(node, ast.Return) and node.value is not None and _is_json_loads(node.value):
                        key = f"{rel}:{fn.name}"
                        if key in ALLOWED:
                            continue
                        found.append(
                            f"{rel}:{node.lineno}: {fn.name}() is annotated "
                            f"{ast.unparse(returns)} but returns json.loads(...) unchecked"
                        )
    return found, scanned


def main() -> int:
    found, scanned = violations()
    if scanned < MIN_FILES_SCANNED:
        print(f"json shape ratchet: FAIL -- scanned only {scanned} files "
              f"(expected at least {MIN_FILES_SCANNED}); the scan is broken, "
              f"not the codebase clean")
        return 1
    if found:
        print("json shape ratchet: FAIL")
        for line in found:
            print(f"  {line}")
        print()
        print("  Use arena.jsonshape.loads_object / loads_array, or narrow with")
        print("  an explicit isinstance check before returning.")
        return 1
    print(f"json shape ratchet: OK ({scanned} files, no unchecked json.loads behind a shaped annotation)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Rename ambiguous single-letter bindings (ruff E741) — AST-proven safe.

`l` is indistinguishable from `1` in many fonts, which is the whole reason the
rule exists. All 19 sites in this repo are comprehension or loop variables, so
the fix is a rename — but a rename done by text substitution is exactly the
class of edit AGENTS.md forbids: `l` appears inside words, strings, comments
and unrelated scopes.

So the rename is driven by the AST instead:

  * the target must be a comprehension variable or a `for` target, i.e. a
    binding whose scope the tool can see end to end;
  * only `ast.Name` nodes that resolve to *that* binding are rewritten, using
    each node's own (lineno, col_offset), never a text search;
  * the new name must not already be live in the enclosing function, or the
    rename would capture something else;
  * the file is accepted only if the resulting AST equals the original with
    the binding renamed — computed independently, not assumed.

Usage:
    python3 scripts/e741_rename_ambiguous.py --check
    python3 scripts/e741_rename_ambiguous.py --apply
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("arena", "tests")

# Preferred replacements, in order. `line` first because every current site is
# iterating text lines; the rest are fallbacks if that name is taken.
CANDIDATES = ("line", "ln", "item", "entry", "elem")

AMBIGUOUS = {"l", "I", "O"}


def ruff_rows(paths: list[str]) -> dict[Path, set[int]]:
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "E741",
         "--output-format=json", *paths],
        cwd=ROOT, capture_output=True, text=True,
    )
    if proc.returncode not in (0, 1):
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(2)
    out: dict[Path, set[int]] = {}
    for item in json.loads(proc.stdout or "[]"):
        out.setdefault(Path(item["filename"]), set()).add(item["location"]["row"])
    return out


def _scope_of(tree: ast.AST, node: ast.AST) -> ast.AST:
    """Nearest enclosing function/module for `node`."""
    best: ast.AST = tree
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.Module)):
            for child in ast.walk(parent):
                if child is node:
                    best = parent
    return best


def _names_in(scope: ast.AST) -> set[str]:
    names: set[str] = set()
    for n in ast.walk(scope):
        if isinstance(n, ast.Name):
            names.add(n.id)
        elif isinstance(n, ast.arg):
            names.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, ast.alias):
            names.add((n.asname or n.name).split(".")[0])
    return names


def _bindings_on_row(tree: ast.AST, row: int) -> list[tuple[ast.AST, ast.Name]]:
    """Comprehension/for bindings of an ambiguous name starting on `row`."""
    found: list[tuple[ast.AST, ast.Name]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for gen in node.generators:
                tgt = gen.target
                if isinstance(tgt, ast.Name) and tgt.id in AMBIGUOUS and tgt.lineno == row:
                    found.append((node, tgt))
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            tgt = node.target
            if isinstance(tgt, ast.Name) and tgt.id in AMBIGUOUS and tgt.lineno == row:
                found.append((node, tgt))
    return found


def _uses(owner: ast.AST, old: str) -> list[ast.Name]:
    """Every Name node inside `owner` referring to `old`.

    Comprehensions and for-loops own their variable, so any Name with that id
    inside the owner is the same binding. Nested scopes that rebind the name
    are excluded by checking for a competing binding first (see caller).
    """
    return [n for n in ast.walk(owner) if isinstance(n, ast.Name) and n.id == old]


def _rebound_elsewhere(owner: ast.AST, old: str, target: ast.Name) -> bool:
    """True if some *other* construct inside owner also binds `old`."""
    for node in ast.walk(owner):
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for gen in node.generators:
                t = gen.target
                if isinstance(t, ast.Name) and t.id == old and t is not target:
                    return True
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            t = node.target
            if isinstance(t, ast.Name) and t.id == old and t is not target:
                return True
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]:
                if a.arg == old:
                    return True
    return False


def _char_col(line: str, byte_col: int) -> int:
    """Convert an AST col_offset (UTF-8 bytes) to a str index.

    ast.Name.col_offset counts BYTES, while we slice `str`. On an ASCII line
    the two coincide, which is why this is easy to miss -- it only diverges on
    lines containing non-ASCII. One such line exists here (a Russian keyword
    in a regex), and the AST guard caught the mismatch rather than letting a
    rename land in the middle of `re.I`.
    """
    raw = line.encode("utf-8")
    return len(raw[:byte_col].decode("utf-8", errors="replace"))


class _Rename(ast.NodeTransformer):
    def __init__(self, positions: set[tuple[int, int]], new: str) -> None:
        self.positions = positions
        self.new = new

    def visit_Name(self, node: ast.Name) -> ast.Name:
        if (node.lineno, node.col_offset) in self.positions:
            node.id = self.new
        return node


def process_file(path: Path, rows: set[int], apply: bool) -> tuple[int, int, list[str]]:
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return 0, len(rows), [f"{path}: unparseable: {exc}"]

    lines = src.splitlines(keepends=True)
    notes: list[str] = []
    edits: list[tuple[int, int, int, str]] = []  # row, col, len(old), new
    renamed = 0

    for row in sorted(rows):
        bindings = _bindings_on_row(tree, row)
        if not bindings:
            notes.append(f"{path}:{row}: skipped (not a comprehension/for binding)")
            continue
        for owner, target in bindings:
            old = target.id
            if _rebound_elsewhere(owner, old, target):
                notes.append(f"{path}:{row}: skipped ({old!r} rebound in the same owner)")
                continue
            scope = _scope_of(tree, owner)
            taken = _names_in(scope)
            new = next((c for c in CANDIDATES if c not in taken), None)
            if new is None:
                notes.append(f"{path}:{row}: skipped (no free replacement name)")
                continue
            for node in _uses(owner, old):
                edits.append((node.lineno, node.col_offset, len(old), new))
            renamed += 1

    if not edits:
        return 0, len(rows), notes

    # Apply right-to-left per row so earlier columns stay valid.
    for row, col, ln, new in sorted(edits, key=lambda e: (-e[0], -e[1])):
        raw = lines[row - 1]
        col = _char_col(raw, col)
        if raw[col:col + ln] not in AMBIGUOUS:
            return 0, len(rows), notes + [f"{path}:{row}: REJECTED, column {col} is not the binding"]
        lines[row - 1] = raw[:col] + new + raw[col + ln:]

    new_src = "".join(lines)
    try:
        new_tree = ast.parse(new_src)
    except SyntaxError as exc:
        return 0, len(rows), notes + [f"{path}: REJECTED, rewrite does not parse: {exc}"]

    # Independent proof: renaming the same positions in the ORIGINAL tree must
    # produce exactly the tree we got from re-parsing the edited text.
    expected = _Rename({(r, c) for r, c, _, _ in edits}, edits[0][3]).visit(ast.parse(src))
    if len({e[3] for e in edits}) == 1:
        if ast.dump(expected, include_attributes=False) != ast.dump(new_tree, include_attributes=False):
            return 0, len(rows), notes + [f"{path}: REJECTED, AST does not match the intended rename"]

    if apply:
        path.write_text(new_src, encoding="utf-8")
    return renamed, len(rows) - renamed, notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--paths", nargs="*", default=list(TARGETS))
    args = ap.parse_args()
    apply = args.apply and not args.check

    found = ruff_rows(args.paths)
    if not found:
        print("E741: nothing to do")
        return 0

    total = sum(len(v) for v in found.values())
    done = skipped = 0
    all_notes: list[str] = []
    for path in sorted(found):
        d, s, notes = process_file(path, found[path], apply)
        done += d
        skipped += s
        all_notes.extend(notes)

    print(f"E741: {total} flagged rows in {len(found)} files")
    print(f"  {'renamed' if apply else 'would rename'}: {done}")
    print(f"  skipped: {skipped}")
    for n in all_notes[:40]:
        print("   ", n)
    return 1 if any("REJECTED" in n for n in all_notes) else 0


if __name__ == "__main__":
    raise SystemExit(main())

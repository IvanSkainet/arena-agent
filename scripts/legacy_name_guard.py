"""Legacy bare-name guard for the MCP dispatch layer.

v4.67.0 added the four namespaced aliases
``exec.ping`` / ``exec.echo`` / ``exec.exec`` / ``exec.snapshot``
to the catalogue. The dispatch layer was updated to accept both
the namespaced form and the legacy bare form
(``ping`` / ``echo`` / ``exec`` / ``snapshot``).

v4.69.0 marks the bare form as **deprecated**. Dispatch keeps
working so existing chat-extension adapters don't break, but:

* the catalogue entry now carries a ``deprecationMessage``;
* the catalogue ``description`` carries a ``(DEPRECATED v4.69.0;
  use exec.X)`` suffix;
* the dispatch site emits a ``PendingDeprecationWarning`` at
  call time so server logs surface the regression.

This guard exists so a future maintainer who reaches for a bare
name in a NEW code path (rather than in the already-whitelisted
legacy dispatch sites) trips a CI red X at PR time, instead of
silently expanding the deprecation surface.

Mechanism
---------

1. Walk every ``arena/mcp/tool_*.py`` file.
2. AST-parse each file. For each function, collect the set of
   string literals compared against ``name`` (the standard
   dispatcher parameter name across this codebase).
3. For each "tool name tuple" literal (a tuple/in ``in (...,)``)
   on a comparison with the ``name`` parameter, split into
   the bare form (e.g. ``"ping"``) and the namespaced form
   (``"exec.ping"``).
4. **Fail** if a bare name appears in a *new* dispatch site
   that is NOT in the ``_WHITELISTED_DISPATCH_FUNCS`` allowlist
   below. The whitelist is the original v4.67.0 set of sites
   that have always accepted both forms.

The check is intentionally simple: it does not try to evaluate
control flow, it just looks for string literals compared
against ``name``. False positives are possible if someone writes
``if name == "ping":`` in unrelated code, but that's the kind of
accident the guard is here to catch.

Exit codes
----------

* 0 — every bare-name reference is in a whitelisted dispatch
  function.
* 1 — at least one bare-name reference is in non-whitelisted
  code (caller is expected to either namespace it or add the
  function to the whitelist with a comment explaining why).
* 2 — script can't import the registry / can't find the package
  directory.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Iterable

# v4.67.0: the only dispatch sites that ever accepted both bare
# and namespaced forms. Any new file/function that adds a bare
# name reference will be flagged by the guard. The test
# ``tests/test_legacy_name_deprecation.py`` checks that every
# entry in this set exists in the source tree; if a file is
# renamed or a function is removed, the test fails so the
# maintainer has to consciously update both ends.
_WHITELISTED_DISPATCH_FUNCS: frozenset[tuple[str, str]] = frozenset({
})


# v4.78.0: mem.set / mem.get removed from the
# bare-name set (the bare names themselves were
# removed from the catalogue and the dispatchers in
# v4.78.0). The set is now empty — all bare-name
# deprecations have expired.
_BARE_NAMES: frozenset[str] = frozenset()


def _iter_dispatch_files(repo_root: Path) -> Iterable[Path]:
    """Yield every Python file in arena/mcp/ that may carry a dispatcher.

    The convention is ``tool_*.py`` for handlers, but a few files
    predate the convention (``standalone_tools.py``,
    ``standalone_common.py``). Scanning the whole directory keeps
    the guard robust against future renames.
    """
    pkg = repo_root / "arena" / "mcp"
    for path in sorted(pkg.glob("*.py")):
        # Skip the catalogue / registry modules: they import
        # MCP_TOOLS data but never compare ``name`` to a bare
        # literal in dispatch code.
        if path.name in {"__init__.py", "tool_utils.py"}:
            continue
        yield path


def _collect_bare_name_refs(tree: ast.AST) -> dict[str, list[tuple[str, int]]]:
    """Return a mapping bare_name → list of (function_name, lineno).

    Walks every Compare / BoolOp node in the tree, looks for
    string-literal operands on comparisons against an identifier
    that looks like the dispatcher ``name`` parameter, and records
    any bare name that shows up.

    We intentionally do NOT inspect the function's argument list
    to confirm the parameter is literally named ``name`` — that
    would miss the case where the function destructures kwargs
    or aliases the parameter. The reality is: every dispatcher in
    this codebase takes a ``name`` parameter as the first
    positional, so a string literal on the left of ``==`` /
    right of ``in (...,)`` is overwhelmingly likely to be a tool
    name. False positives are easy to triage from the line number
    reported in the guard output.
    """
    out: dict[str, list[tuple[str, int]]] = {n: [] for n in _BARE_NAMES}
    for node in ast.walk(tree):
        # Track the enclosing function so we can attribute each
        # reference to a function name.
        # The simple approach: walk FunctionDef bodies and capture
        # bare-name references per function.
        pass

    # Do it per-function so we can attribute line numbers to
    # the enclosing dispatcher.
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for ref in _scan_function_for_bare_names(func):
            for bare in ref.bare_names:
                out[bare].append((func.name, ref.lineno))
    return out


class _BareNameRef:
    __slots__ = ("bare_names", "lineno")

    def __init__(self, bare_names: list[str], lineno: int) -> None:
        self.bare_names = bare_names
        self.lineno = lineno


def _scan_function_for_bare_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[_BareNameRef]:
    """Walk a single function body, return a list of bare-name refs.

    A "ref" is any Compare / BoolOp expression that compares a
    string-literal bare name against something. We collect the
    LHS/RHS string literals, and for each tuple/in-expr we record
    which bare names appear.
    """
    refs: list[_BareNameRef] = []

    class _Visitor(ast.NodeVisitor):
        def visit_Compare(self, node: ast.Compare) -> None:
            bare = _bare_names_in_compare(node)
            if bare:
                refs.append(_BareNameRef(bare, node.lineno))
            self.generic_visit(node)

        def visit_BoolOp(self, node: ast.BoolOp) -> None:
            # ``if name in ("a", "b") or name == "c":`` —
            # BoolOp wraps multiple Compare nodes. We still want
            # to flag any bare name in any of them, but each
            # Compare has already been visited by the visitor
            # recursion. So we only need to handle the case
            # where someone writes an ``in`` against a Tuple
            # *directly* (without going through Compare), which
            # is rare in practice. Skip for now.
            self.generic_visit(node)

    _Visitor().visit(func)
    return refs


def _bare_names_in_compare(node: ast.Compare) -> list[str]:
    """Return any bare name (from _BARE_NAMES) that appears in this Compare."""
    found: list[str] = []

    def _consider(value: ast.AST) -> None:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            if value.value in _BARE_NAMES:
                found.append(value.value)
        elif isinstance(value, ast.Tuple):
            for elt in value.elts:
                _consider(elt)

    for op, comparator in zip(node.ops, node.comparators):
        _consider(node.left)
        _consider(comparator)
        # No-op: we just want to cover == and ``in`` against tuples
        # of strings. The above handles both because both left and
        # right operands are walked.
    return found


def _run(repo_root: Path) -> int:
    pkg = repo_root / "arena" / "mcp"
    if not pkg.is_dir():
        print(f"[ERR] {pkg} not found; run from the repo root.", file=sys.stderr)
        return 2

    violations: list[tuple[str, str, int, str]] = []  # (file, func, lineno, bare_name)
    whitelisted_hits = 0
    for path in _iter_dispatch_files(repo_root):
        rel = path.relative_to(repo_root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            print(f"[ERR] failed to parse {rel}: {exc}", file=sys.stderr)
            return 2
        refs = _collect_bare_name_refs(tree)
        for bare, hits in refs.items():
            for func_name, lineno in hits:
                if (rel, func_name) in _WHITELISTED_DISPATCH_FUNCS:
                    whitelisted_hits += 1
                else:
                    violations.append((rel, func_name, lineno, bare))

    # Sanity-check the whitelist: every (file, function) entry in
    # _WHITELISTED_DISPATCH_FUNCS must actually exist in the
    # current source tree. If a file is renamed or a function is
    # removed without updating the whitelist, this trips so the
    # maintainer has to consciously update both ends.
    missing_in_tree: list[tuple[str, str]] = []
    for rel, func_name in _WHITELISTED_DISPATCH_FUNCS:
        path = repo_root / rel
        if not path.is_file():
            missing_in_tree.append((rel, func_name))
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        found = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                found = True
                break
        if not found:
            missing_in_tree.append((rel, func_name))
    if missing_in_tree:
        print("Legacy bare-name guard: FAIL", file=sys.stderr)
        print(
            "The following (file, function) entries in "
            "_WHITELISTED_DISPATCH_FUNCS do not exist in the current "
            "source tree. Either the file/function was renamed/removed "
            "(update the whitelist) or this is a stale entry from a "
            "previous refactor.",
            file=sys.stderr,
        )
        for rel, func_name in missing_in_tree:
            print(f"  ({rel!r}, {func_name!r})", file=sys.stderr)
        return 1

    if violations:
        print("Legacy bare-name guard: FAIL", file=sys.stderr)
        print("", file=sys.stderr)
        print(
            "The following references to bare tool names are in "
            "non-whitelisted dispatch code. v4.69.0 deprecated the bare "
            "forms in favour of exec.ping / exec.echo / exec.exec / "
            "exec.snapshot. Either namespace the reference (preferred) "
            "or, if this is a legitimate new dispatch site that has to "
            "accept both forms, add (file, function) to "
            "_WHITELISTED_DISPATCH_FUNCS in scripts/legacy_name_guard.py "
            "with a comment explaining why.",
            file=sys.stderr,
        )
        for file, func, lineno, bare in sorted(violations):
            print(f"  {file}:{lineno} in {func}() — bare name {bare!r}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "whitelisted_dispatch_hits": whitelisted_hits,
                "files_scanned": len(list(_iter_dispatch_files(repo_root))),
            }
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Path to the repo root (default: current directory)",
    )
    args = parser.parse_args()
    return _run(Path(args.repo_root).resolve())


if __name__ == "__main__":
    sys.exit(main())

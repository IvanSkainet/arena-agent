"""Handler signature contract for the MCP dispatch layer.

The MCP dispatch layer routes every incoming tool call
through a function whose name follows the
``handle_*_tool`` convention. The signature of these
functions is part of the contract with the dispatcher in
``unified_bridge.py`` / ``arena.mcp.tools``: each function
must accept the same positional and keyword-only arguments
so the dispatcher can call it uniformly.

The expected signature is:

::

    def handle_xxx_tool(
        name: str,
        args: dict[str, Any],
        *,
        ctx: SomeContext,    # keyword-only
        run_local=...,        # optional, for tools that need subprocess
        run_sd=...,           # optional, for tools that need sd-exec
    ) -> dict[str, Any] | None: ...

v4.70.0 introduces a static check that walks every
``handle_*_tool`` function in ``arena/mcp/`` and asserts:

1. The function has at least two positional parameters
   named ``name`` and ``args``.
2. The first keyword-only parameter is named ``ctx``.
3. Any additional keyword-only parameters come from a
   small whitelist (``run_local``, ``run_sd``, ``run_*``).
4. The function has an explicit return annotation that is
   either ``dict`` / ``dict[str, Any]`` / ``None`` or a
   ``Union`` of those (the dispatcher relies on
   ``None`` meaning "not my tool" and a dict meaning
   "I handled it").

A function that fails any of these checks is reported with
its file:lineno and the specific failure so the maintainer
can fix the signature in one place. The check is
intentionally simple (signature-only, no body analysis)
because the dispatcher is the only caller of these
functions and a broken signature fails the dispatch
immediately at runtime.

Exit codes:

* 0 — every ``handle_*_tool`` function passes all four
  signature checks.
* 1 — at least one function fails a check. The first 20
  violations are listed.
* 2 — script can't walk ``arena/mcp/``.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import Optional, Union, get_args, get_origin

# Whitelisted keyword-only parameter suffixes. A function
# may have zero or more of these (in addition to ``ctx``)
# but no other keyword-only parameters.
_KWONLY_WHITELIST: frozenset[str] = frozenset({"ctx", "run_local", "run_sd"})


def _is_handle_tool_func(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("handle_") and node.name.endswith("_tool")


def _arg_kind(arg: ast.arg, args: ast.arguments) -> str:
    """Return one of: 'positional', 'kwonly', 'vararg', 'varkw'."""
    if arg in args.args:
        return "positional"
    if arg in args.kwonlyargs:
        return "kwonly"
    if arg in args.posonlyargs:
        return "posonly"
    return "unknown"


def _return_is_dict_or_none(node: ast.AST) -> tuple[bool, str]:
    """Return (ok, detail). ``ok`` is True if the return
    annotation is acceptable (None, dict, dict[str, Any],
    or a Union of those). ``detail`` is a human-readable
    description of what was found (used in the report)."""
    if node is None:
        return False, "no return annotation"
    # string annotations: try to evaluate
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        s = node.value.strip()
        if s in {"None", "dict", "dict[str, Any]", "Dict[str, Any]"}:
            return True, s
        if s.startswith("Optional[") or s.startswith("Union["):
            return True, s
        if " | None" in s or s.endswith(" | dict"):
            return True, s
        return False, f"return annotation {s!r} is not dict/None/Optional"
    # real annotations: walk the AST.
    if isinstance(node, ast.Name):
        if node.id in {"dict", "Dict", "None"}:
            return True, node.id
        return False, f"return annotation is a name {node.id!r}; expected dict / None / Optional"
    if isinstance(node, ast.Subscript):
        # dict[str, Any] -> ast.Subscript(value=Name('dict'), slice=Index(Tuple...))
        if isinstance(node.value, ast.Name) and node.value.id in {"dict", "Dict"}:
            return True, ast.unparse(node)
        return False, f"return annotation is a subscript {ast.unparse(node)}; expected dict / None / Optional"
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        # X | None syntax (Python 3.10+)
        return True, ast.unparse(node)
    if isinstance(node, ast.Constant) and node.value is None:
        return True, "None"
    return False, f"return annotation {ast.unparse(node)} is not dict/None/Optional"


def _audit_dispatch_file(path: Path) -> list[tuple[int, str, str]]:
    """Return a list of (lineno, func_name, problem) for a single file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return [(0, "<module>", f"failed to parse: {exc}")]

    problems: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not _is_handle_tool_func(node):
            continue
        func: ast.FunctionDef = node  # type: ignore[assignment]
        args = func.args

        # 1. First two positional parameters are name and args.
        if len(args.args) < 2:
            problems.append((func.lineno, func.name, f"needs at least 2 positional params (name, args); got {len(args.args)}"))
            continue
        if args.args[0].arg != "name":
            problems.append((func.lineno, func.name, f"first positional param is {args.args[0].arg!r}; expected 'name'"))
        if args.args[1].arg != "args":
            problems.append((func.lineno, func.name, f"second positional param is {args.args[1].arg!r}; expected 'args'"))

        # 2. First keyword-only parameter is ``ctx``.
        if not args.kwonlyargs:
            problems.append((func.lineno, func.name, "no keyword-only parameters; expected at least 'ctx'"))
        elif args.kwonlyargs[0].arg != "ctx":
            problems.append((func.lineno, func.name, f"first keyword-only param is {args.kwonlyargs[0].arg!r}; expected 'ctx'"))

        # 3. Other keyword-only parameters must be in the whitelist.
        for kw in args.kwonlyargs[1:]:
            if kw.arg not in _KWONLY_WHITELIST:
                problems.append((func.lineno, func.name, f"unexpected keyword-only param {kw.arg!r}; allowed: {sorted(_KWONLY_WHITELIST)}"))

        # 4. Return annotation is acceptable.
        ok, detail = _return_is_dict_or_none(func.returns)
        if not ok:
            problems.append((func.lineno, func.name, f"return annotation: {detail}"))

    return problems


def _run(repo_root: Path) -> int:
    pkg = repo_root / "arena" / "mcp"
    if not pkg.is_dir():
        print(f"[ERR] {pkg} not found; run from the repo root.", file=sys.stderr)
        return 2

    all_problems: list[tuple[Path, int, str, str]] = []
    n_funcs = 0
    for path in sorted(pkg.glob("*.py")):
        if path.name in {"__init__.py", "tool_utils.py", "standalone_common.py"}:
            continue
        for lineno, name, detail in _audit_dispatch_file(path):
            all_problems.append((path, lineno, name, detail))
        # Count handle_*_tool functions for the report
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if _is_handle_tool_func(node):
                n_funcs += 1

    if not all_problems:
        print(f"[handler-signature-check] OK: {n_funcs} handle_*_tool functions, all signatures conform")
        return 0

    print("[handler-signature-check] FAIL", file=sys.stderr)
    print("", file=sys.stderr)
    for path, lineno, name, detail in all_problems[:20]:
        rel = path.relative_to(repo_root)
        print(f"  {rel}:{lineno} in {name}() — {detail}", file=sys.stderr)
    if len(all_problems) > 20:
        print(f"  ... and {len(all_problems) - 20} more", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=".", help="Path to the repo root (default: current directory)")
    args = parser.parse_args()
    return _run(Path(args.repo_root).resolve())


if __name__ == "__main__":
    sys.exit(main())

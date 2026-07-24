"""Handler-namespace consistency check for the MCP dispatch layer.

Each ``handle_*_tool`` function lives in a file and has a
name. The convention is that the function is responsible
for one or more tool namespaces; the names of the tools it
handles share a common prefix (``fs`` for filesystem tools,
``git`` for git tools, etc.). A function that handles
``fs.read`` and ``desktop.ocr`` is a smell — the namespace
boundary is broken, and a maintainer looking for
``fs.write`` would never guess to also look in the
desktop handler.

This check enforces the convention in two modes:

**Hard fail (default):**

* **Shadow-namespace detection.** If a function handles
  tools from two namespaces whose relationship looks like
  legacy/canonical (``mem.*`` vs ``memory.*``,
  ``secrets.*`` vs ``admin.*``), the guard fails. The
  pattern is: the function body mentions tools from
  namespace A AND namespace B, where both A and B are
  in the catalogue, AND there exists a tool in namespace
  A whose description has the same verb as a tool in
  namespace B (e.g. ``mem.set`` ↔ ``memory.import``,
  ``mem.get`` ↔ ``memory.recall``). This catches the
  case where the catalogue has two namespaces for one
  concept (the dispatcher is forced to handle both
  because the catalogue exposes both).
* **Uncovered namespaces.** If a namespace is in the
  catalogue but no function references any of its tools,
  the guard fails (this is the v4.70.0 dead-dispatch
  check restated from a function-centric angle).

**Soft warn:**

* **Mixed-namespace dispatch.** A function that handles
  tools from two unrelated namespaces (e.g.
  ``handle_net_tool`` handles ``net.*`` AND
  ``admin.*``) is reported but not failed. This pattern
  is legitimate in some dispatchers (the ``misc`` and
  ``net`` handlers group related cross-cutting concerns
  on purpose) so the guard leaves the call to the
  maintainer.

The script also recognises three known cross-namespace
patterns that are explicitly OK and are not reported in
either mode:

* ``handle_exec_tool`` handles ``ping`` / ``echo`` /
  ``exec`` — the v4.69.0 deprecation puts the bare
  names and their namespaced twins in the same
  dispatcher.
* ``handle_misc_tool`` handles ``sys`` / ``skill`` /
  ``hooks`` / ``subagent`` / ``snapshot`` — the misc
  dispatcher groups unrelated cross-cutting concerns
  on purpose.
* ``handle_agentic_tool`` handles ``react`` / ``reflect``
  — both are agentic commands.

The whitelist is explicit and is in this script. If a
new cross-namespace dispatcher is added, the maintainer
either adds it to the whitelist with a comment, or
splits it into per-namespace functions.

Exit codes:

* 0 — every function passes the hard checks, and the
  soft-warn list is empty (or the script is in
  soft-warn-only mode).
* 1 — at least one hard-fail violation.
* 2 — script can't import MCP_TOOLS.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path


# v4.69.0: bare names are in the catalogue and in the
# dispatcher. They are exempt from the per-namespace
# check (they live in the v4.67.0 dispatch sites that
# accept both bare and namespaced forms).
_BARE_NAMES: frozenset[str] = frozenset({"ping", "echo", "exec", "snapshot"})


_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


# Functions that are allowed to handle multiple
# namespaces because the cross-namespace dispatch is
# intentional. Each entry is ``(file, function_name,
# reason)``. The test
# ``tests/test_handler_namespace_consistency.py``
# asserts the whitelist is in lockstep with the source
# tree, so a renamed function trips a clear red X.
_WHITELISTED_MIXED: frozenset[tuple[str, str, str]] = frozenset({
    ("arena/mcp/tool_exec.py", "handle_exec_tool", "v4.69.0 deprecation: bare names + namespaced twins live in the same dispatch"),
    ("arena/mcp/tool_misc.py", "handle_misc_tool", "Misc dispatcher groups sys / skill / hooks / subagent / snapshot on purpose"),
    ("arena/mcp/tool_net.py", "handle_net_tool", "Net dispatcher groups net / admin / secrets / sudo on purpose (cross-cutting network ops)"),
    ("arena/mcp/tool_agentic.py", "handle_agentic_tool", "Agentic dispatcher handles both react.* and reflect.* on purpose"),
    ("arena/mcp/tool_memory.py", "handle_memory_tool", "v4.71.0 deprecation: mem.* (deprecated) + memory.* (canonical) live in the same dispatch"),
})


def _is_handle_tool_func(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("handle_") and node.name.endswith("_tool")


def _namespace_of(name: str) -> str:
    return name.split(".", 1)[0]


def _looks_like_tool_name(s: str, known_namespaces: frozenset[str]) -> bool:
    if len(s) > 40:
        return False
    if s in _BARE_NAMES:
        return True
    if not _TOOL_NAME_RE.match(s):
        return False
    return _namespace_of(s) in known_namespaces


def _names_handled_by_func(func: ast.AST, known_namespaces: frozenset[str]) -> set[str]:
    """Walk the function body, return every tool name literal that
    appears in a Compare / Tuple / Set / Dict-key position.

    The same heuristic as the dead-dispatch check: we only
    look at positions that resemble a tool-name check, and
    we only consider literals whose namespace is in the
    known set. This drops SQL, error messages, and binary
    names like ``whisper.cpp`` from the analysis.
    """
    out: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Compare):
            for child in (node.left, *node.comparators):
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    if _looks_like_tool_name(child.value, known_namespaces):
                        out.add(child.value)
                elif isinstance(child, (ast.Tuple, ast.Set)):
                    for elt in child.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            if _looks_like_tool_name(elt.value, known_namespaces):
                                out.add(elt.value)
        elif isinstance(node, (ast.Tuple, ast.Set)):
            for elt in node.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    if _looks_like_tool_name(elt.value, known_namespaces):
                        out.add(elt.value)
        elif isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    if _looks_like_tool_name(k.value, known_namespaces):
                        out.add(k.value)
    return out


def _detect_shadow_namespaces(mcp_tools) -> list[tuple[str, str, str, str]]:
    """Return a list of (namespace_a, tool_a, namespace_b, tool_b) where
    the same concept is exposed under two different namespaces.

    The heuristic is intentionally conservative: a shadow
    is only flagged when the two namespaces look like
    variants of the same root word AND at least one tool
    pair has matching actions (``set`` / ``get`` /
    ``list`` / ``read`` / ``write`` / ``create`` /
    ``delete`` / ``update``).

    The "namespace variants" test:

    * one namespace is a prefix of the other
      (``mem`` ↔ ``memory``, ``sub`` ↔ ``subagent``);
    * or both are anagrams / near-anagrams
      (e.g. ``asr`` ↔ ``ras`` — but this is rare);
    * or one is the singular of the other
      (``hook`` ↔ ``hooks``).

    This is conservative on purpose: ``fs.read`` and
    ``browser.read`` are NOT flagged as shadows (different
    domain, different actions), but ``mem.set`` and
    ``memory.import`` ARE flagged (the same domain —
    memory — exposed under two namespaces).

    The list is not exhaustive — it catches the obvious
    cases (``mem.*`` ↔ ``memory.*``) and surfaces them
    for the maintainer to confirm.
    """
    by_ns: dict[str, list[dict]] = {}
    for entry in mcp_tools:
        if not isinstance(entry, dict):
            continue
        n = entry.get("name")
        if not isinstance(n, str) or "." not in n:
            continue
        # v4.71.0: skip entries that are explicitly marked
        # deprecated. A deprecated entry is by definition
        # the "shadow" side of a shadow pair — the catalogue
        # already says "use the other one". Counting it as a
        # shadow on top of that would be a double-flag for
        # the same deprecation.
        if isinstance(entry.get("deprecationMessage"), str) and entry["deprecationMessage"].strip():
            continue
        ns = n.split(".", 1)[0]
        by_ns.setdefault(ns, []).append(entry)

    verbs = {"set", "get", "import", "export", "recall", "digest", "list", "read", "write", "create", "delete", "update", "store", "load", "save", "run", "spawn", "info", "status", "show"}

    def _looks_like_variant(a: str, b: str) -> bool:
        if a == b:
            return False
        if a.startswith(b) or b.startswith(a):
            return True
        # One is singular, other is plural
        if a + "s" == b or a == b + "s" or a + "y" == b or a == b + "y":
            return True
        return False

    shadows: list[tuple[str, str, str, str]] = []
    ns_list = sorted(by_ns.keys())
    for i, a in enumerate(ns_list):
        for b in ns_list[i + 1:]:
            if not _looks_like_variant(a, b):
                continue
            # Compare tools pairwise; flag a pair if the
            # actions match OR the descriptions share a
            # common verb.
            for ta in by_ns[a]:
                action_a = ta["name"].split(".", 1)[1]
                desc_a = (ta.get("description") or "").lower()
                for tb in by_ns[b]:
                    action_b = tb["name"].split(".", 1)[1]
                    desc_b = (tb.get("description") or "").lower()
                    if action_a == action_b:
                        shadows.append((a, ta["name"], b, tb["name"]))
                        continue
                    # Or descriptions share a strong verb
                    verbs_a = {w for w in verbs if w in desc_a}
                    verbs_b = {w for w in verbs if w in desc_b}
                    if verbs_a & verbs_b:
                        shadows.append((a, ta["name"], b, tb["name"]))
    return shadows


def _run(repo_root: Path) -> int:
    pkg = repo_root / "arena" / "mcp"
    if not pkg.is_dir():
        print(f"[ERR] {pkg} not found; run from the repo root.", file=sys.stderr)
        return 2

    sys.path.insert(0, str(repo_root))
    try:
        from arena.mcp.tool_registry import MCP_TOOLS  # type: ignore[import-not-found]
    except Exception as exc:
        print(f"[handler-namespace-consistency] FATAL: cannot import MCP_TOOLS: {exc}", file=sys.stderr)
        return 2

    catalogue_names: set[str] = {t["name"] for t in MCP_TOOLS if isinstance(t, dict) and isinstance(t.get("name"), str)}
    known_namespaces: frozenset[str] = frozenset(n.split(".", 1)[0] for n in catalogue_names if "." in n)

    # Walk every file, collect per-function namespace set.
    func_namespaces: dict[tuple[Path, str], set[str]] = {}
    handled_namespaces: set[str] = set()
    for path in sorted(pkg.glob("*.py")):
        if path.name in {"__init__.py", "tool_utils.py", "standalone_common.py"}:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not _is_handle_tool_func(node):
                continue
            names = _names_handled_by_func(node, known_namespaces)
            nss = {_namespace_of(n) for n in names}
            func_namespaces[(path, node.name)] = nss
            handled_namespaces |= nss

    # Sanity-check the whitelist: every (file, function) entry
    # in _WHITELISTED_MIXED must exist in the source tree.
    missing_in_tree: list[tuple[str, str]] = []
    for rel, func_name, _reason in _WHITELISTED_MIXED:
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
        print("[handler-namespace-consistency] FAIL: stale whitelist", file=sys.stderr)
        for rel, func_name in missing_in_tree:
            print(f"  ({rel!r}, {func_name!r}) not in source tree", file=sys.stderr)
        return 1

    # Hard checks.
    hard_failures: list[str] = []
    # 1. Shadow namespaces.
    shadows = _detect_shadow_namespaces(MCP_TOOLS)
    if shadows:
        for a, ta, b, tb in shadows:
            hard_failures.append(f"shadow namespace: {a}.* ({ta!r}) and {b}.* ({tb!r}) describe the same operation; pick one canonical namespace and deprecate the other")
    # 2. Uncovered namespaces.
    uncovered = known_namespaces - handled_namespaces - {"exec"}  # exec is the deprecation twin
    if uncovered:
        for ns in sorted(uncovered):
            hard_failures.append(f"namespace {ns!r} is in the catalogue but no handle_*_tool function references any of its tools")

    # Soft checks (warn only).
    soft_warnings: list[str] = []
    whitelisted_keys = {(repo_root / rel, fn) for rel, fn, _ in _WHITELISTED_MIXED}
    for (path, name), nss in func_namespaces.items():
        if len(nss) <= 1:
            continue
        if (path, name) in whitelisted_keys:
            continue
        rel = path.relative_to(repo_root)
        soft_warnings.append(f"{rel}::{name}() handles multiple namespaces: {sorted(nss)}; consider splitting per-namespace or adding to the whitelist with a comment")

    if not hard_failures and not soft_warnings:
        n_funcs = len(func_namespaces)
        n_namespaces = len(known_namespaces)
        print(f"[handler-namespace-consistency] OK: {n_funcs} handle_*_tool functions, {n_namespaces} namespaces, all consistent")
        return 0

    if hard_failures:
        print("[handler-namespace-consistency] FAIL", file=sys.stderr)
        for f in hard_failures:
            print(f"  {f}", file=sys.stderr)
    if soft_warnings:
        print("[handler-namespace-consistency] WARN", file=sys.stderr)
        for w in soft_warnings:
            print(f"  {w}", file=sys.stderr)
    return 1 if hard_failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=".", help="Path to the repo root (default: current directory)")
    args = parser.parse_args()
    return _run(Path(args.repo_root).resolve())


if __name__ == "__main__":
    sys.exit(main())

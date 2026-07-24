"""Dead-dispatch detector for the MCP tool registry.

For every tool name in the catalogue, the dispatcher must
have a code path that handles it. If a tool is registered in
``MCP_TOOLS`` but no dispatch file mentions its name in a
string literal that looks like a handler branch
(``if name == "foo"`` / ``if name in ("foo", ...)``), the
tool is dead: it shows up in the catalogue but every call
silently returns ``None`` from the dispatcher.

The reverse case is also reported: dispatch files that
reference a tool name string literal that is NOT in the
catalogue. That is dead code — a string literal nobody is
listening for. In practice the references are typos in
handler conditionals, leftovers from a previous refactor, or
a handler that was renamed without removing the old
literal. None of them break behaviour at runtime (the
dispatcher will just return ``None`` for the unrecognised
name) but they are misleading to anyone reading the code.

The check is intentionally simpler than full data-flow
analysis:

* It walks every ``arena/mcp/*.py`` file that contains at
  least one ``handle_*_tool`` function (the dispatchers).
* It collects every string-literal value that looks like a
  tool name (``namespace.action`` pattern, a bare-name
  whitelist entry, OR a name whose ``namespace`` part is
  one of the namespaces already in ``MCP_TOOLS``) and
  appears in a Compare / Tuple / Set / Dict-key position.
* It compares that set against the names in ``MCP_TOOLS``
  to find dead tools (catalogue says yes, dispatcher says
  no) and dead references (dispatcher says yes, catalogue
  says no).

The four bare names (``ping`` / ``echo`` / ``exec`` /
``snapshot``) are excluded from the dead-reference check
because they ARE in the catalogue (deprecated but still
shipped) and they ARE handled (the bare-name branches in
``tool_exec`` / ``tool_misc``).

The dead-tool check is the hard one in practice: catching a
tool that was added to the catalogue but the handler branch
was never written (or was deleted in a refactor that left
the catalogue entry behind). The dead-reference check is
softer: it can produce false positives for legitimate
constants (binary names like ``whisper.cpp``, version
strings like ``aria2c.1``, etc.) that happen to match the
``namespace.action`` regex. The namespace-from-catalogue
filter cuts most of those — if the first component of the
literal is not in the catalogue's known namespace set, we
skip it.

Exit codes:

* 0 — every catalogue entry has a corresponding dispatch
  branch, and every dispatch branch corresponds to a
  catalogue entry.
* 1 — at least one dead tool (hard fail) or dead reference
  (hard fail; can be promoted to a soft warn in
  ``--soft-refs`` mode if a maintainer needs to triage
  incrementally).
* 2 — script can't import MCP_TOOLS.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path


# v4.69.0: bare names are in the catalogue and in the
# dispatcher. They are exempt from the dead-reference check.
_BARE_NAMES: frozenset[str] = frozenset({"ping", "echo", "exec", "snapshot"})


# Tool names match ``namespace.action`` (lowercase letters,
# digits, underscores, exactly one dot). Anything that doesn't
# match this pattern (or isn't a whitelisted bare name) is not
# a tool name and shouldn't be considered a dispatch reference.
_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def _looks_like_tool_name(s: str, known_namespaces: frozenset[str]) -> bool:
    """Heuristic: a string literal is a candidate tool name if:

    * it is short (≤ 40 chars — the longest tool name in the
      catalogue is ~25 chars);
    * it is either in the bare-name whitelist or matches the
      ``namespace.action`` regex AND its ``namespace`` part
      is one of the namespaces already in use in the
      catalogue.

    The second filter is what makes the check precise
    enough to be useful: the regex alone would match
    strings like ``whisper.cpp`` (the name of a binary
    searched via ``shutil.which()``) or
    ``git.log.1`` (a manpage reference) that are not tool
    names. The known-namespace filter cuts all of those
    because ``whisper`` and ``git.log`` are not namespaces
    in the catalogue (well, ``git`` IS — but ``git.log.1``
    has a three-component name, which the regex rejects).

    SQL fragments, error messages, and prose strings are
    excluded because they are long, contain whitespace, or
    contain non-identifier characters.
    """
    if len(s) > 40:
        return False
    if s in _BARE_NAMES:
        return True
    if not _TOOL_NAME_RE.match(s):
        return False
    namespace = s.split(".", 1)[0]
    return namespace in known_namespaces


def _is_dispatcher_file(path: Path) -> bool:
    """A dispatcher file is any .py under arena/mcp/ that
    defines a top-level function whose name starts with
    ``handle_`` and ends with ``_tool``.

    We don't try to be smarter than that (e.g. matching
    specific function names) because the project has
    accumulated many dispatcher functions over many
    releases and the convention is the only stable thing.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return False
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("handle_") and node.name.endswith("_tool"):
                return True
    return False


def _collect_referenced_names(tree: ast.AST, known_namespaces: frozenset[str]) -> set[str]:
    """Walk an AST, return every string literal that *looks like*
    a tool name and appears in a Compare / Tuple / Set / Dict-key
    position that resembles a tool-name check.

    We collect string constants from:

    * ``Compare.left`` and ``Compare.comparators`` (so
      ``name == "foo"`` and ``name in ("foo", "bar")`` both
      work);
    * ``Tuple.elts`` and ``Set.elts`` that appear as a
      Compare comparator (so ``("foo", "bar")`` inside
      ``in`` is captured);
    * Standalone ``Tuple`` and ``Set`` literals (so
      ``_DISPATCH = {"foo", "bar"}`` constants are
      captured);
    * Dict keys (so dispatch tables like
      ``{"foo": handle_a, "bar": handle_b}`` are captured).

    Every candidate literal is filtered through
    ``_looks_like_tool_name`` to drop SQL fragments, error
    messages, binary names, and prose strings. False
    positives remain possible but the known-namespace
    filter keeps them rare; false negatives are avoided by
    the broad whitelist of "looks like a tool name"
    patterns.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
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


def _run(repo_root: Path) -> int:
    pkg = repo_root / "arena" / "mcp"
    if not pkg.is_dir():
        print(f"[ERR] {pkg} not found; run from the repo root.", file=sys.stderr)
        return 2

    sys.path.insert(0, str(repo_root))
    try:
        from arena.mcp.tool_registry import MCP_TOOLS  # type: ignore[import-not-found]
    except Exception as exc:
        print(f"[dead-dispatch] FATAL: cannot import MCP_TOOLS: {exc}", file=sys.stderr)
        return 2

    catalogue_names: set[str] = {t["name"] for t in MCP_TOOLS if isinstance(t, dict) and isinstance(t.get("name"), str)}
    # Build the known-namespace set from the catalogue so the
    # "looks like a tool name" filter can cut obvious
    # non-tool names like ``whisper.cpp``.
    known_namespaces: frozenset[str] = frozenset(
        n.split(".", 1)[0] for n in catalogue_names if "." in n
    )

    referenced: set[str] = set()
    for path in sorted(pkg.glob("*.py")):
        if path.name in {"__init__.py", "tool_utils.py"}:
            continue
        if not _is_dispatcher_file(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        referenced |= _collect_referenced_names(tree, known_namespaces)

    # Dead tools: in catalogue but not referenced.
    dead_tools = catalogue_names - referenced

    # Dead references: in dispatcher but not in catalogue.
    # (Exclude bare names — they are deprecated but shipped.)
    dead_refs = (referenced - catalogue_names) - _BARE_NAMES

    if not dead_tools and not dead_refs:
        print(f"[dead-dispatch] OK: {len(catalogue_names)} catalogue entries, {len(referenced)} referenced in dispatchers")
        return 0

    print("[dead-dispatch] FAIL", file=sys.stderr)
    if dead_tools:
        print("", file=sys.stderr)
        print(f"--- {len(dead_tools)} dead tool(s): in catalogue but not handled anywhere ---", file=sys.stderr)
        for n in sorted(dead_tools):
            print(f"  {n}", file=sys.stderr)
    if dead_refs:
        print("", file=sys.stderr)
        print(f"--- {len(dead_refs)} dead reference(s): in dispatcher but not in catalogue ---", file=sys.stderr)
        for n in sorted(dead_refs):
            print(f"  {n}", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=".", help="Path to the repo root (default: current directory)")
    args = parser.parse_args()
    return _run(Path(args.repo_root).resolve())


if __name__ == "__main__":
    sys.exit(main())

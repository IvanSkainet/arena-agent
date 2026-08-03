"""Catalogue consistency guard for the MCP tool registry.

v4.67.0 added the catalogue-harden guard (every object-typed
inputSchema has additionalProperties: false). v4.69.0 added the
legacy-name guard (no new dispatch code uses bare names).

v4.70.0 adds a broader consistency check that bundles five
separate invariants into a single audit, with each invariant
reported as its own line so a CI failure points the maintainer
straight at the offending property. The five invariants:

1. **Naming convention.** Every ``name`` matches the
   ``namespace.action`` pattern (lowercase letters, digits,
   underscores, exactly one dot). The four bare names
   (``ping`` / ``echo`` / ``exec`` / ``snapshot``) are
   whitelisted because v4.69.0 deprecated them; v4.75.0
   will remove the whitelist.

2. **Name uniqueness.** No two entries share the same
   ``name``. A duplicate would silently shadow one of them
   in the dispatch layer.

3. **Description is a non-empty string.** A blank
   description shows up as a broken tooltip in MCP
   inspectors.

4. **additionalProperties hardening.** Every object-typed
   ``inputSchema`` has ``additionalProperties: false`` on
   its top level. This is the v4.67.0 invariant, retained
   here so the audit is self-contained and re-runnable from
   a single script.

5. **Deprecation metadata consistency.** If an entry carries
   a ``deprecationMessage`` field, its description must
   carry a ``[DEPRECATED`` marker (and vice-versa). The
   two flags are coupled: a description that says
   "DEPRECATED" without a ``deprecationMessage`` is
   misleading, and a ``deprecationMessage`` without a
   description marker is invisible to clients that read
   the description first.

Exit codes:

* 0 — every invariant passes.
* 1 — at least one invariant fails. The first 20 violations
  per invariant are printed to stderr.
* 2 — the script can't import MCP_TOOLS (e.g. not running
  from the repo root).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# v4.69.0: bare names are deprecated but still dispatched. The
# plan in the CHANGELOG is to remove them in v4.75.0. Until
# then they are exempt from the namespace.action regex.
_BARE_NAMES: frozenset[str] = frozenset({"ping", "echo", "exec", "snapshot"})

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def _audit(mcp_tools) -> list[tuple[str, str, str]]:
    """Run the five-invariant audit. Return a list of violations.

    Each violation is ``(invariant, tool_name, detail)``. The
    caller is expected to group by ``invariant`` and print a
    header per group.
    """
    violations: list[tuple[str, str, str]] = []
    seen_names: dict[str, int] = {}

    for entry in mcp_tools:
        if not isinstance(entry, dict):
            violations.append(("schema", "?", f"entry is not a dict: {type(entry).__name__}"))
            continue
        name = entry.get("name", "<missing>")
        if not isinstance(name, str) or not name:
            violations.append(("schema", str(name), "missing or non-string 'name'"))
            continue

        # 1. Naming convention.
        if name not in _BARE_NAMES and not _NAME_RE.match(name):
            violations.append((
                "naming",
                name,
                "does not match 'namespace.action' (lowercase letters, digits, underscores, one dot)",
            ))

        # 2. Name uniqueness.
        if name in seen_names:
            violations.append((
                "uniqueness",
                name,
                f"duplicate 'name' (also at catalogue position {seen_names[name]}); dispatch layer will shadow one",
            ))
        else:
            seen_names[name] = seen_names.get(name, 0)  # record position below

        # Track the position of the first occurrence so the
        # uniqueness message can say "also at position N".
        if name not in seen_names or seen_names.get(name) == 0:
            # First occurrence; record its position.
            if name in seen_names:
                # The dict already had 0 as a sentinel; rewrite
                # it to the actual first-seen position.
                pass
        # Always update the position to the latest seen, so
        # the message reads "duplicate at position N (first
        # seen at M)".
        seen_names[name] = seen_names.get(name, 0) + 1

        # 3. Description.
        desc = entry.get("description")
        if not isinstance(desc, str) or not desc.strip():
            violations.append((
                "description",
                name,
                "missing or empty 'description' field",
            ))

        # 4. inputSchema hardening.
        schema = entry.get("inputSchema")
        if isinstance(schema, dict) and schema.get("type") == "object":
            if schema.get("additionalProperties") is not False:
                violations.append((
                    "hardening",
                    name,
                    f"object-typed inputSchema lacks additionalProperties: false (got: {schema.get('additionalProperties')!r})",
                ))

        # 5. Deprecation metadata consistency.
        has_dep_msg = isinstance(entry.get("deprecationMessage"), str) and entry["deprecationMessage"].strip()
        desc_str = desc if isinstance(desc, str) else ""
        has_dep_marker = "DEPRECATED" in desc_str
        if has_dep_msg and not has_dep_marker:
            violations.append((
                "deprecation",
                name,
                "has deprecationMessage but description does not carry a [DEPRECATED marker; clients reading the description will miss the deprecation",
            ))
        if has_dep_marker and not has_dep_msg:
            violations.append((
                "deprecation",
                name,
                "description marks the entry as DEPRECATED but no deprecationMessage is set; the deprecation will be invisible to JSON-schema-aware clients",
            ))

    return violations


def _run(repo_root: Path) -> int:
    pkg = repo_root / "arena" / "mcp"
    if not pkg.is_dir():
        print(f"[ERR] {pkg} not found; run from the repo root.", file=sys.stderr)
        return 2
    sys.path.insert(0, str(repo_root))
    try:
        from arena.mcp.tool_registry import MCP_TOOLS  # type: ignore[import-not-found]
    except Exception as exc:
        print(f"[catalogue-consistency] FATAL: cannot import MCP_TOOLS: {exc}", file=sys.stderr)
        return 2

    violations = _audit(MCP_TOOLS)
    if not violations:
        print(f"[catalogue-consistency] OK: {len(MCP_TOOLS)} entries, all 5 invariants hold")
        return 0

    # Group by invariant, print a header per group, then the
    # first 20 entries.
    by_invariant: dict[str, list[tuple[str, str]]] = {}
    for inv, name, detail in violations:
        by_invariant.setdefault(inv, []).append((name, detail))

    print("[catalogue-consistency] FAIL", file=sys.stderr)
    print("", file=sys.stderr)
    for inv, items in by_invariant.items():
        print(f"--- invariant: {inv} ({len(items)} violation{'s' if len(items) != 1 else ''}) ---", file=sys.stderr)
        for name, detail in items[:20]:
            print(f"  {name}: {detail}", file=sys.stderr)
        if len(items) > 20:
            print(f"  ... and {len(items) - 20} more", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", default=".", help="Path to the repo root (default: current directory)")
    args = parser.parse_args()
    return _run(Path(args.repo_root).resolve())


if __name__ == "__main__":
    sys.exit(main())

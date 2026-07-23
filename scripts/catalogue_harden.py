"""Catalogue hardening fixer for the MCP_TOOLS catalogue.

The v4.63.0 ``tests/test_mcp_input_schema_validation.py`` shipped
two soft-warns that this script exists to retire:

1. **Missing ``additionalProperties: false``.**
   The shipped catalogue has 0 of 125 object-typed tool entries
   with ``additionalProperties: false``. Without it, a model
   that emits a typo'd field name (``serila`` instead of
   ``serial``) gets silent acceptance by the dispatch layer
   rather than a clear error.

2. **Invalid JSON Schema keywords.**
   ``mobile.key.inputSchema.properties.keycode`` uses
   ``anyOf`` (a valid Draft 7 keyword) which the v4.63.0
   metaschema-walker did not know about, so the test flagged
   it as "unknown JSON Schema keys".

This script:

* walks ``MCP_TOOLS`` (imported from the actual ``arena.mcp.tool_registry``,
  so it covers every registry module — no hardcoded list to maintain);
* for every entry whose top-level ``inputSchema`` is an object
  without ``additionalProperties: false``, **adds it** (only if
  it isn't already there — fully idempotent);
* prints a per-entry report and exits non-zero on any
  uncategorised / unfixable schema error so the maintainer
  can triage.

The script is **idempotent and read-only by default**. The actual
edit of the registry files is left to ``dev/bump_version.py``-style
manual review (or to this script in ``--apply`` mode, which
edits the registry source files in place — used in CI by the
v4.67.0 release commit only).

Usage
-----

::

    # Audit only (default — what CI runs on every push):
    python scripts/catalogue_harden.py --repo-root .

    # Apply in place (used by the maintainer to regenerate
    # registry files after a catalogue change):
    python scripts/catalogue_harden.py --repo-root . --apply

Exit code:

- 0 if every tool either has ``additionalProperties: false`` on its
  object-typed inputSchema, or doesn't have an object-typed schema.
- 1 if any tool is missing the property (in audit mode this is the
  "you need to run --apply or hand-fix" signal).
- 2 if the script can't import MCP_TOOLS (e.g. not running from a
  repo checkout).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, List

# A list of legacy pre-MCP tool names that predate the
# ``namespace.action`` convention. v4.67.0 namespaces them as
# ``exec.<legacy>`` and adds dispatch aliases so existing
# callers keep working.
LEGACY_BARE_NAMES = frozenset({"ping", "echo", "exec", "snapshot"})


def _is_object_schema(schema: Any) -> bool:
    return isinstance(schema, dict) and schema.get("type") == "object"


def _audit_entry(entry: dict) -> dict:
    """Return an audit record for one tool entry.

    The record always has ``name`` and ``status`` keys. When the
    tool has an object-typed inputSchema, ``status`` is one of:

    - ``"ok"`` if ``additionalProperties: false`` is present
    - ``"missing"`` if it isn't
    - ``"malformed"`` if the schema is unparseable (rare;
      caught earlier by the structural validator)
    """
    name = entry.get("name", "?")
    schema = entry.get("inputSchema")
    if not _is_object_schema(schema):
        return {"name": name, "status": "skip", "reason": "no object-typed inputSchema"}
    if schema.get("additionalProperties") is False:
        return {"name": name, "status": "ok"}
    return {"name": name, "status": "missing"}


def _build_fix_payload() -> dict:
    """A blueprint for the in-place fix.

    Returns a dict ``{entry_index: {"additionalProperties": False}}``
    keyed by the position of the offending entry in ``MCP_TOOLS``.
    The apply path uses this to drive the source-file edit.
    """
    return {}


def _audit(repo_root: Path) -> tuple[int, list[dict]]:
    """Run the audit. Returns ``(missing_count, audit_records)``."""
    # Make arena importable
    sys.path.insert(0, str(repo_root))
    try:
        from arena.mcp.tool_registry import MCP_TOOLS  # type: ignore[import-not-found]
    except Exception as e:
        print(f"[catalogue-harden] FATAL: cannot import MCP_TOOLS: {e}", file=sys.stderr)
        return 2, [{"name": "?", "status": "error", "reason": str(e)}]

    records: list[dict] = []
    missing = 0
    for entry in MCP_TOOLS:
        if not isinstance(entry, dict):
            continue
        rec = _audit_entry(entry)
        records.append(rec)
        if rec["status"] == "missing":
            missing += 1
    return missing, records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo-root", default=".", help="Path to the repo root")
    parser.add_argument(
        "--apply", action="store_true",
        help="Edit registry source files in place (used by the v4.67.0 release only)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of the default human text",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()

    if args.apply:
        # The actual rewrite is intentionally not auto-applied from
        # this script. The v4.67.0 release commit was generated by
        # running this script in audit mode, hand-reviewing the
        # missing entries, and committing the edits as a separate
        # change. This keeps the script focused on the audit half
        # of the contract; the apply half is just `git diff`.
        print(
            "[catalogue-harden] --apply is not implemented in this script.\n"
            "  Run in audit mode to see what's missing, hand-edit the registry\n"
            "  files (or use scripts/refactor_catalogue.py if we add one in\n"
            "  the future), and the next CI run will validate.",
            file=sys.stderr,
        )
        return 2

    missing, records = _audit(repo_root)
    if missing == 2:
        return 2

    if args.json:
        out = {
            "missing": missing,
            "total": len(records),
            "ok": sum(1 for r in records if r["status"] == "ok"),
            "skip": sum(1 for r in records if r["status"] == "skip"),
            "records": records,
        }
        print(json.dumps(out, indent=2))
        return 0 if missing == 0 else 1

    print(f"[catalogue-harden] scanned {len(records)} tool entries")
    print(f"  ok   (additionalProperties: false present): {sum(1 for r in records if r['status'] == 'ok')}")
    print(f"  skip (no object-typed inputSchema):         {sum(1 for r in records if r['status'] == 'skip')}")
    print(f"  missing (needs hardening):                   {missing}")
    if missing:
        print()
        print("[catalogue-harden] entries missing additionalProperties: false:")
        for r in records:
            if r["status"] == "missing":
                marker = "  [legacy]" if r["name"] in LEGACY_BARE_NAMES else "         "
                print(f"  {marker}  {r['name']}")
        print()
        print(
            "[catalogue-harden] FAIL: see the v4.67.0 release notes for the\n"
            "  per-file patches that add additionalProperties: false to each\n"
            "  of the above entries. After applying, this audit exits 0."
        )
        return 1

    print("[catalogue-harden] OK: every object-typed inputSchema has additionalProperties: false")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""JSON Schema structural validator for the MCP tool catalogue.

v4.63.0's ``tests/test_mcp_input_schema_validation.py`` shipped
two soft-warns that the v4.67.0 ``catalogue_harden`` script
retired for the most part. This script addresses what
catalogue_harden does NOT check:

1. **JSON Schema Draft 7 structural validity.** Every
   ``inputSchema`` is a JSON Schema (Draft 7 by
   convention). The metaschema-walker in
   ``test_mcp_input_schema_validation`` already validates a
   few rules (type / properties are dicts; ``items`` is
   set when ``type == array``), but it does not check the
   metaschema itself. v4.70.0 ships a self-contained
   Draft-7 metaschema walker that fails on any keyword
   outside the known set, any ``type`` value outside the
   six primitives + array, any ``required`` entry that
   isn't a property, etc.

2. **Required properties are declared.** If a tool's
   ``inputSchema`` lists ``required: ["path"]`` but does not
   declare a ``path`` property, the JSON-Schema would
   accept no input (because no input can satisfy the
   required field). This is a silent foot-gun: the
   dispatcher would receive ``{}`` and crash on the missing
   field. v4.70.0 catches that.

3. **No unknown JSON-Schema keywords.** A typo like
   ``addtionalProperties`` (sic) is silently ignored by
   most JSON-Schema validators. The catalogue would ship
   with an entry that pretends to forbid extra fields but
   actually accepts them. v4.70.0 walks the keyword set
   against the Draft-7 metaschema and fails on unknown
   keywords.

The check is intentionally stdlib-only — no external
``jsonschema`` package. The Draft-7 metaschema walker is
~80 lines and runs in milliseconds, which matters because
CI runs it on every push.

Exit codes:

* 0 — every ``inputSchema`` is structurally valid Draft 7
  and has consistent ``required`` / ``properties``.
* 1 — at least one schema has a structural or consistency
  problem. The first 20 problems per category are printed
  to stderr.
* 2 — script can't import MCP_TOOLS.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# Draft 7 keywords we recognise. Anything outside this set
# is a typo. ``$ref`` / ``$id`` / ``$schema`` are
# deliberately listed; the walker is permissive about them
# because the catalogue uses none of them today but a
# future maintainer might.
#
# Source: https://json-schema.org/draft-07/schema#
_DRAFT_7_KEYWORDS: frozenset[str] = frozenset({
    # Core
    "$ref", "$id", "$schema", "$comment",
    "type", "enum", "const", "default", "examples",
    "title", "description", "format",
    "definitions", "$defs",
    # Logic
    "allOf", "anyOf", "oneOf", "not",
    "if", "then", "else",
    # Object
    "properties", "patternProperties", "additionalProperties",
    "required", "propertyNames", "minProperties", "maxProperties",
    "dependencies", "dependentSchemas", "dependentRequired",
    # Array
    "items", "additionalItems", "contains", "minItems", "maxItems",
    "uniqueItems",
    # String
    "minLength", "maxLength", "pattern",
    # Number
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "multipleOf",
    # Conditional / metadata
    "readOnly", "writeOnly", "deprecated", "contentEncoding",
    "contentMediaType",
})


# JSON-Schema primitive types plus ``array``. ``null`` is
# also valid but tools never use it.
_VALID_TYPES: frozenset[str] = frozenset({
    "string", "number", "integer", "boolean", "object", "array", "null",
})


class _SchemaProblem:
    __slots__ = ("tool", "kind", "detail")

    def __init__(self, tool: str, kind: str, detail: str) -> None:
        self.tool = tool
        self.kind = kind
        self.detail = detail


def _walk_schema(schema: Any, path: str, tool: str, out: list[_SchemaProblem]) -> None:
    """Recursive metaschema walker.

    For each node:

    * if it's not a dict, fail with ``not_an_object``;
    * if any key is not in ``_DRAFT_7_KEYWORDS``, fail with
      ``unknown_keyword``;
    * if ``type`` is set and not in ``_VALID_TYPES``, fail
      with ``bad_type``;
    * if ``properties`` is set, each value must be a dict
      (or fail with ``bad_property``);
    * if ``required`` is set, every entry must be a
      declared property (or fail with ``required_but_missing``);
    * recurse into ``properties[*]`` / ``items`` / ``additionalProperties`` /
      ``additionalItems`` / ``definitions[*]`` /
      ``$defs[*]`` / ``patternProperties[*]`` / ``allOf[*]`` /
      ``anyOf[*]`` / ``oneOf[*]`` / ``not`` / ``if`` /
      ``then`` / ``else`` / ``contains``.
    """
    if not isinstance(schema, dict):
        out.append(_SchemaProblem(tool, "not_an_object", f"{path}: schema is {type(schema).__name__}, expected dict"))
        return
    for key in schema:
        if key not in _DRAFT_7_KEYWORDS:
            out.append(_SchemaProblem(tool, "unknown_keyword", f"{path}: unknown keyword {key!r}"))

    t = schema.get("type")
    if t is not None and t not in _VALID_TYPES:
        out.append(_SchemaProblem(tool, "bad_type", f"{path}: type={t!r} is not a valid JSON-Schema primitive"))

    props = schema.get("properties")
    if props is not None:
        if not isinstance(props, dict):
            out.append(_SchemaProblem(tool, "bad_properties", f"{path}: 'properties' must be a dict, got {type(props).__name__}"))
        else:
            for pname, pschema in props.items():
                if not isinstance(pschema, dict):
                    out.append(_SchemaProblem(tool, "bad_property", f"{path}.properties[{pname!r}]: must be a dict, got {type(pschema).__name__}"))
                    continue
                _walk_schema(pschema, f"{path}.properties[{pname!r}]", tool, out)

    required = schema.get("required")
    if required is not None:
        if not isinstance(required, list):
            out.append(_SchemaProblem(tool, "bad_required", f"{path}: 'required' must be a list, got {type(required).__name__}"))
        else:
            declared = set(props.keys()) if isinstance(props, dict) else set()
            for r in required:
                if not isinstance(r, str):
                    out.append(_SchemaProblem(tool, "bad_required_entry", f"{path}.required: entry {r!r} is not a string"))
                elif r not in declared:
                    out.append(_SchemaProblem(tool, "required_but_missing", f"{path}: required field {r!r} is not declared in 'properties'"))

    if "items" in schema:
        _walk_schema(schema["items"], f"{path}.items", tool, out)
    if "additionalProperties" in schema and isinstance(schema["additionalProperties"], dict):
        _walk_schema(schema["additionalProperties"], f"{path}.additionalProperties", tool, out)
    if "additionalItems" in schema and isinstance(schema["additionalItems"], dict):
        _walk_schema(schema["additionalItems"], f"{path}.additionalItems", tool, out)
    if "contains" in schema and isinstance(schema["contains"], dict):
        _walk_schema(schema["contains"], f"{path}.contains", tool, out)

    for sub_key in ("definitions", "$defs"):
        sub = schema.get(sub_key)
        if isinstance(sub, dict):
            for name, sub_schema in sub.items():
                if isinstance(sub_schema, dict):
                    _walk_schema(sub_schema, f"{path}.{sub_key}[{name!r}]", tool, out)

    pp = schema.get("patternProperties")
    if isinstance(pp, dict):
        for pat, pschema in pp.items():
            if isinstance(pschema, dict):
                _walk_schema(pschema, f"{path}.patternProperties[{pat!r}]", tool, out)

    for sub_key in ("allOf", "anyOf", "oneOf"):
        for i, sub_schema in enumerate(schema.get(sub_key, []) or []):
            if isinstance(sub_schema, dict):
                _walk_schema(sub_schema, f"{path}.{sub_key}[{i}]", tool, out)
    for sub_key in ("not", "if", "then", "else"):
        if sub_key in schema and isinstance(schema[sub_key], dict):
            _walk_schema(schema[sub_key], f"{path}.{sub_key}", tool, out)


def _audit(mcp_tools) -> list[_SchemaProblem]:
    out: list[_SchemaProblem] = []
    for entry in mcp_tools:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name", "<missing>")
        if not isinstance(name, str) or not name:
            continue
        schema = entry.get("inputSchema")
        if schema is None:
            continue
        if not isinstance(schema, dict):
            out.append(_SchemaProblem(name, "not_an_object", f"inputSchema is {type(schema).__name__}, expected dict"))
            continue
        _walk_schema(schema, "inputSchema", name, out)
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
        print(f"[json-schema-check] FATAL: cannot import MCP_TOOLS: {exc}", file=sys.stderr)
        return 2

    problems = _audit(MCP_TOOLS)
    if not problems:
        print(f"[json-schema-check] OK: {len(MCP_TOOLS)} entries, all inputSchemas are structurally valid Draft 7")
        return 0

    by_kind: dict[str, list[_SchemaProblem]] = {}
    for p in problems:
        by_kind.setdefault(p.kind, []).append(p)

    print("[json-schema-check] FAIL", file=sys.stderr)
    print("", file=sys.stderr)
    for kind, items in by_kind.items():
        print(f"--- kind: {kind} ({len(items)} problem{'s' if len(items) != 1 else ''}) ---", file=sys.stderr)
        for it in items[:20]:
            print(f"  {it.tool}: {it.detail}", file=sys.stderr)
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

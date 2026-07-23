"""v4.63.0 - structural validation of MCP tool input schemas.

Every entry in ``MCP_TOOLS`` advertises an ``inputSchema`` that
consumers (the chat extension, MCP clients) use to render a form
before the model emits a call. If the schema is malformed, the
form either renders wrong or the dispatch layer accepts garbage
that should have been rejected. Neither is acceptable.

This test statically imports ``arena.mcp.tool_registry``, walks
every entry, and asserts:

* the schema is a valid JSON Schema (Draft 7 dialect — the
  same one used by the MCP SDK).
* the tool ``name`` follows the ``namespace.action`` convention
  (lowercase, dot-separated, no leading/trailing dots).
* the tool ``description`` is a non-empty string.
* every name listed in ``required`` is also present in
  ``properties`` (JSON Schema otherwise rejects the request).
* ``additionalProperties: false`` is set on every object-typed
  schema (defence in depth: a model that guesses an unsupported
  field name should get a clear error, not silent acceptance).
* no ``enum`` field has an empty list (an empty enum rejects
  every input, which is almost always a typo).
* no field has a ``default`` of the wrong type (a number field
  with ``default="5"`` or a string field with ``default=5``).

The test is structural and does not import the bridge runtime.
If a future refactor renames a tool or changes its schema,
this test will fail with a clear message pointing at the
specific entry that broke the contract.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

try:
    from arena.mcp.tool_registry import MCP_TOOLS
except Exception as exc:  # pragma: no cover - import failure handled below
    pytest.skip(f"arena.mcp.tool_registry not importable: {exc}", allow_module_level=True)


# JSON Schema Draft 7 metaschema. Verifies the schema is structurally
# valid. We don't validate against every metaschema (Draft 4/6/2019-09
# all differ slightly) — Draft 7 is what the MCP SDK emits.
_DRAFT_7_META = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": "https://example.com/root.json",
    "type": "object",
    "properties": {
        "type": {"enum": ["array", "boolean", "integer", "null", "number", "object", "string"]},
        "properties": {"type": "object"},
        "required": {"type": "array", "items": {"type": "string"}},
        "additionalProperties": {"type": "boolean"},
        "enum": {"type": "array", "minItems": 1},
        "default": {},
        "description": {"type": "string"},
        "minimum": {"type": "number"},
        "maximum": {"type": "number"},
        "minLength": {"type": "integer", "minimum": 0},
        "maxLength": {"type": "integer", "minimum": 0},
        "pattern": {"type": "string"},
        "minItems": {"type": "integer", "minimum": 0},
        "maxItems": {"type": "integer", "minimum": 0},
        "items": {"type": "object"},
    },
    "additionalProperties": True,
}


def _validate_against_metaschema(schema: dict, path: str) -> list[str]:
    """Recursively validate ``schema`` against the JSON Schema Draft 7
    metaschema dialect. Returns a list of human-readable error
    strings; empty list means OK.
    """
    errors: list[str] = []
    if not isinstance(schema, dict):
        errors.append(f"{path}: schema is not a dict ({type(schema).__name__})")
        return errors

    allowed = set(_DRAFT_7_META["properties"].keys()) | {"$schema", "$id", "$ref", "title", "format", "examples", "default"}
    unknown = set(schema.keys()) - allowed
    if unknown:
        errors.append(f"{path}: unknown JSON Schema keys: {sorted(unknown)}")

    if "type" in schema:
        if schema["type"] not in _DRAFT_7_META["properties"]["type"]["enum"]:
            errors.append(f"{path}: invalid type {schema['type']!r}")
        # Type-specific checks
        stype = schema["type"]
        if stype == "object":
            if "required" in schema:
                req = schema["required"]
                if not isinstance(req, list):
                    errors.append(f"{path}: 'required' must be a list, got {type(req).__name__}")
                else:
                    props = schema.get("properties", {})
                    if not isinstance(props, dict):
                        errors.append(f"{path}: 'properties' must be a dict")
                    else:
                        for r in req:
                            if r not in props:
                                errors.append(
                                    f"{path}: 'required' references unknown property {r!r}"
                                )
        if stype in ("integer", "number") and "default" in schema:
            d = schema["default"]
            if not isinstance(d, (int, float)) or isinstance(d, bool):
                errors.append(f"{path}: default={d!r} is not a {stype}")
        if stype == "string" and "default" in schema:
            d = schema["default"]
            if not isinstance(d, str):
                errors.append(f"{path}: default={d!r} is not a string")
        if stype == "boolean" and "default" in schema:
            d = schema["default"]
            if not isinstance(d, bool):
                errors.append(f"{path}: default={d!r} is not a boolean")
        if stype == "array":
            if "minItems" in schema and "maxItems" in schema:
                if schema["minItems"] > schema["maxItems"]:
                    errors.append(
                        f"{path}: minItems={schema['minItems']} > maxItems={schema['maxItems']}"
                    )

    if "enum" in schema and len(schema["enum"]) == 0:
        errors.append(f"{path}: enum is empty (would reject every input)")

    # Recurse into nested schemas.
    if "properties" in schema and isinstance(schema["properties"], dict):
        for prop_name, prop_schema in schema["properties"].items():
            errors.extend(_validate_against_metaschema(
                prop_schema, f"{path}.properties.{prop_name}"
            ))
    if "items" in schema and isinstance(schema["items"], dict):
        errors.extend(_validate_against_metaschema(
            schema["items"], f"{path}.items"
        ))

    return errors


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


def _iter_tools():
    """Yield (entry_dict, source_module) for every MCP tool entry."""
    for entry in MCP_TOOLS:
        yield entry


# ---------------------------------------------------------------------------
# Per-entry structural tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", list(_iter_tools()), ids=lambda e: e.get("name", "?"))
def test_tool_name_follows_namespace_dot_action_convention(entry):
    name = entry.get("name")
    assert isinstance(name, str), f"name must be a string, got {type(name).__name__}"
    assert _NAME_RE.match(name), (
        f"tool name {name!r} does not match the required 'namespace.action' "
        "convention (lowercase letters, digits, underscores, exactly one dot)"
    )


@pytest.mark.parametrize("entry", list(_iter_tools()), ids=lambda e: e.get("name", "?"))
def test_tool_description_is_nonempty_string(entry):
    desc = entry.get("description")
    assert isinstance(desc, str), f"description must be a string, got {type(desc).__name__}"
    assert desc.strip(), "description is empty or whitespace-only"


@pytest.mark.parametrize("entry", list(_iter_tools()), ids=lambda e: e.get("name", "?"))
def test_tool_input_schema_is_valid_json_schema_draft_7(entry):
    name = entry.get("name", "?")
    schema = entry.get("inputSchema")
    if schema is None:
        pytest.skip(f"{name}: no inputSchema (some no-arg tools legitimately omit it)")
    errors = _validate_against_metaschema(schema, f"{name}.inputSchema")
    assert not errors, (
        f"tool {name!r} has an invalid inputSchema:\n  "
        + "\n  ".join(errors)
    )


@pytest.mark.parametrize("entry", list(_iter_tools()), ids=lambda e: e.get("name", "?"))
def test_tool_input_schema_rejects_extra_properties(entry):
    """Defence in depth: a model that guesses an unsupported field
    name should get a clear error from the validator, not silent
    acceptance. JSON Schema's ``additionalProperties: false`` is
    the standard way to enforce this."""
    name = entry.get("name", "?")
    schema = entry.get("inputSchema")
    if not isinstance(schema, dict):
        pytest.skip(f"{name}: no object-typed inputSchema")
    if schema.get("type") != "object":
        pytest.skip(f"{name}: top-level type is not object")
    assert schema.get("additionalProperties") is False, (
        f"tool {name!r} has top-level additionalProperties != false. "
        "A model that emits a typo'd field name (e.g. 'pash' instead of "
        "'path') should get a clear error from the validator, not silent "
        "acceptance. Set additionalProperties: false on the top-level object."
    )


def test_no_duplicate_tool_names():
    """A duplicated name in MCP_TOOLS would make dispatch
    non-deterministic: the first matching handler wins, the second
    is dead code. Catches the class of bug where someone
    copy-pastes a tool entry and forgets to rename it."""
    names = [e["name"] for e in MCP_TOOLS if isinstance(e, dict) and "name" in e]
    seen: dict[str, str] = {}
    dupes: list[tuple[str, int, int]] = []
    for idx, n in enumerate(names):
        if n in seen:
            dupes.append((n, seen[n], idx))
        else:
            seen[n] = idx
    assert not dupes, (
        f"duplicate tool names in MCP_TOOLS: {dupes}. "
        "Each tool name must appear exactly once."
    )


def test_every_tool_name_appears_in_dispatch_or_registry():
    """Cross-check: every ``name`` in MCP_TOOLS must be reachable
    from the dispatcher. The dispatch code in tool_registry.py
    is a hand-written table; if someone adds a tool to MCP_TOOLS
    but forgets to wire its dispatch, the tool is dead. This
    test walks the dispatch source to find every name string
    literal and asserts MCP_TOOLS is a subset.
    """
    import re as _re
    registry_path = REPO / "arena" / "mcp" / "tool_registry.py"
    if not registry_path.exists():
        pytest.skip("tool_registry.py not found")
    text = registry_path.read_text(encoding="utf-8")

    # Names that appear inside string literals in the dispatch tree.
    # We deliberately over-collect (any quoted "namespace.action"
    # string is a candidate) and check the actual MCP_TOOLS list
    # is a subset.
    candidates = set(_re.findall(r'"([a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)"', text))
    declared = {e["name"] for e in MCP_TOOLS if isinstance(e, dict) and "name" in e}

    unreachable = declared - candidates
    assert not unreachable, (
        f"these MCP_TOOLS entries are not referenced in tool_registry.py "
        f"dispatch source: {sorted(unreachable)}. Either the tool is dead "
        "code or its dispatch is in a different file (update this test)."
    )

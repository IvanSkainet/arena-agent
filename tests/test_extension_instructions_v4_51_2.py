"""Regression guards for v4.51.2.

Three fixes from Ivan's post-v4.51.1 tour scans + full redesign
of extension_instructions.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from arena.extension_bridge.instructions import (
    extension_instructions,
    json_schema_to_csn,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _ext_read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------
# Fix 1: z.ai orphan-sweep regression fixed (accepts parent anchor)
# ------------------------------------------------------------------

def test_orphan_sweep_accepts_parent_anchor():
    content = _ext_read("content.js")
    # The isAnchored check must now consider BOTH previousElementSibling
    # AND parentElement (v4.51.2 fix for z.ai appendChild pattern).
    m = re.search(
        r"function sweepDuplicateToolbars.*?function ",
        content,
        flags=re.DOTALL,
    )
    assert m, "sweep helper must exist"
    body = m.group(0)
    assert "parentElement" in body
    assert "parent && parent.dataset?.arenaToolControlsMounted" in body


# ------------------------------------------------------------------
# Fix 2: visible-text sentinel + widened selector + fence-root
# ------------------------------------------------------------------

def test_format_insert_uses_visible_text_sentinel():
    content = _ext_read("content.js")
    # New sentinel is visible text, not HTML comment.
    assert "ARENA_RESULT_V1" in content
    assert "arena-tool-result" in content


def test_collapse_supports_legacy_and_new_sentinels():
    content = _ext_read("content.js")
    m = re.search(
        r"function collapseToolResultsInHistory.*?^\}",
        content,
        flags=re.DOTALL | re.MULTILINE,
    )
    assert m
    body = m.group(0)
    assert "'ARENA_RESULT_V1'" in body
    # Legacy sentinel still recognised for messages sent from v4.51.0/1.
    assert "'<!-- arena:tool-result -->'" in body


def test_collapse_selector_widened_for_gemini_kimi_qwen():
    content = _ext_read("content.js")
    # Gemini custom element.
    assert 'code-block' in content
    # Kimi language-jsonl.
    assert 'class*="language-"' in content
    # Qwen qwen-markdown-code.
    assert 'qwen-markdown-code' in content
    # Gemini formatted-code-block wrapper.
    assert 'formatted-code-block' in content


def test_collapse_walks_to_fence_root():
    content = _ext_read("content.js")
    # Target is now fenceRoot (outer container) when found.
    assert "fenceRoot" in content
    assert "let target = block" in content


# ------------------------------------------------------------------
# Fix 3: flicker — collapse hooked into MutationObserver
# ------------------------------------------------------------------

def test_collapse_runs_from_mutation_observer():
    content = _ext_read("content.js")
    # MutationObserver callback must call collapseToolResultsInHistory
    # BEFORE scheduleScan so the fold is synchronous with mutation.
    m = re.search(
        r"const obs = new MutationObserver.*?scheduleScan\(\);",
        content,
        flags=re.DOTALL,
    )
    assert m
    body = m.group(0)
    assert "collapseToolResultsInHistory()" in body


# ------------------------------------------------------------------
# instructions.py redesign: CSN + MCP SA-style system prompt
# ------------------------------------------------------------------

def test_csn_converts_basic_types():
    assert json_schema_to_csn({"type": "string"}) == "s"
    assert json_schema_to_csn({"type": "integer"}) == "i"
    assert json_schema_to_csn({"type": "boolean"}) == "b"
    assert json_schema_to_csn({"type": "array", "items": {"type": "string"}}) == "a[s]"


def test_csn_converts_object_with_required_and_default():
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "depth": {"type": "integer", "default": 2},
        },
        "required": ["path"],
        "additionalProperties": False,
    }
    csn = json_schema_to_csn(schema)
    assert "o {p {" in csn
    assert "path:s r" in csn
    assert "depth:i" in csn and "d=2" in csn
    assert "ap f" in csn


def test_csn_converts_enum_and_union():
    csn = json_schema_to_csn({"enum": ["a", "b", "c"]})
    assert csn == 'e["a", "b", "c"]'
    csn = json_schema_to_csn({"anyOf": [{"type": "string"}, {"type": "integer"}]})
    assert csn == "u[s, i]"


def test_instructions_include_mcp_sa_style_system_preamble():
    result = extension_instructions()
    text = result["text"]
    assert "[Start Fresh Session from here" in text
    assert "<SYSTEM>" in text
    assert "```arena-tool" in text
    assert "```jsonl" in text
    # CSN quick-guide included.
    assert "CSN notation guide" in text or "CSN" in text


def test_catalog_uses_csn_notation():
    result = extension_instructions(category="safe")
    text = result["catalog_text"]
    assert text
    # Every entry gets a `schema: \`csn\`` line.
    assert "schema:" in text
    # CSN one-liners like `o {p {` should appear.
    assert "o {p {" in text or "o{p{" in text or "s r" in text


def test_catalog_still_returns_entries_and_examples():
    result = extension_instructions(category="safe")
    assert result["catalog"]
    for entry in result["catalog"]:
        assert "csn" in entry, f"{entry['name']} missing csn"
        assert entry["risk"] == "safe"


# ------------------------------------------------------------------
# Backward compat: no-category still returns valid shape
# ------------------------------------------------------------------

def test_no_category_still_returns_empty_catalog():
    result = extension_instructions()
    assert result["catalog"] == []
    assert result["catalog_text"] == ""
    assert result["category"] == ""
    # Base examples still present.
    assert "arena" in result["examples"]
    assert "jsonl" in result["examples"]


# ------------------------------------------------------------------
# Version pins
# ------------------------------------------------------------------

def test_versions_pinned_to_0_14_31():
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.32'" in _ext_read("content.js")
    manifest = json.loads(_ext_read("manifest.json"))
    assert manifest["version"] == "0.14.32"
    assert "return '0.14.32';" in _ext_read("insert_strategies.js")

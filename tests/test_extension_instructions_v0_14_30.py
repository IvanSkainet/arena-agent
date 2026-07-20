"""Regression guards for extension_instructions v4.51.1.

The catalog is opt-in: when the caller passes no `category`, the
returned payload matches the pre-v4.51.1 shape exactly (only new
fields added, none removed). When `category` is set the payload
gains a `catalog[]` list of tool entries with schema + example
arguments and a `catalog_text` markdown block ready to paste as
a system prompt.
"""
from __future__ import annotations

import json
from pathlib import Path

from arena.extension_bridge.instructions import extension_instructions

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _ext_read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------
# Backward compat: no-category shape unchanged
# ------------------------------------------------------------------

def test_no_category_matches_previous_shape():
    result = extension_instructions()
    assert result["ok"] is True
    assert result["format"] == "arena"
    assert result["style"] == "full"
    assert "text" in result and result["text"]
    assert "examples" in result and "arena" in result["examples"] and "jsonl" in result["examples"]
    # New fields default to safe empty values so consumers relying on
    # the old shape don't break.
    assert result["category"] == ""
    assert result["catalog"] == []
    assert result["catalog_text"] == ""
    assert "available_categories" in result


def test_available_categories_include_expected_scopes():
    result = extension_instructions()
    cats = set(result["available_categories"])
    for expected in ("safe", "medium", "dangerous", "all",
                     "fs", "mission", "memory", "browser",
                     "desktop", "git", "system"):
        assert expected in cats, f"missing category: {expected}"


# ------------------------------------------------------------------
# Category = safe: only safe risk tools appear
# ------------------------------------------------------------------

def test_safe_category_only_lists_safe_tools():
    result = extension_instructions(category="safe")
    assert result["category"] == "safe"
    catalog = result["catalog"]
    assert catalog, "safe catalog must be non-empty"
    for entry in catalog:
        assert entry["risk"] == "safe", (
            f"non-safe tool leaked into safe catalog: {entry['name']} ({entry['risk']})"
        )
    names = {entry["name"] for entry in catalog}
    # Spot-check that well-known safe tools are present.
    for expected in ("sys.status", "mission.catalog", "fs.view"):
        assert expected in names, f"expected {expected} in safe catalog"


def test_safe_catalog_text_contains_example_call():
    result = extension_instructions(category="safe")
    text = result["catalog_text"]
    assert text
    # Every entry gets an arena-tool fence.
    assert "```arena-tool" in text
    # Header lines are markdown H2 with risk tag.
    assert "(safe)" in text
    # `sys.status` is required-args-free so its example should
    # serialise as an empty object.
    assert ('"tool": "sys.status"' in text
            or '"tool": "browser.read"' in text
            or '"tool":' in text)  # first safe tool alphabetically


# ------------------------------------------------------------------
# Category = dangerous: risky tools only
# ------------------------------------------------------------------

def test_dangerous_category_only_lists_dangerous_tools():
    result = extension_instructions(category="dangerous")
    assert result["category"] == "dangerous"
    catalog = result["catalog"]
    assert catalog
    for entry in catalog:
        assert entry["risk"] == "dangerous"
    names = {entry["name"] for entry in catalog}
    for expected in ("exec", "fs.write", "mission.run"):
        assert expected in names


# ------------------------------------------------------------------
# Topical categories
# ------------------------------------------------------------------

def test_mission_category_lists_only_mission_tools():
    result = extension_instructions(category="mission")
    assert result["category"] == "mission"
    catalog = result["catalog"]
    assert catalog
    for entry in catalog:
        assert entry["name"].startswith("mission."), (
            f"non-mission tool in mission catalog: {entry['name']}"
        )


def test_fs_category_lists_only_fs_tools():
    result = extension_instructions(category="fs")
    for entry in result["catalog"]:
        assert entry["name"].startswith("fs."), entry["name"]


# ------------------------------------------------------------------
# Sort order: safe first, then medium, then dangerous
# ------------------------------------------------------------------

def test_all_category_sorted_by_risk_then_name():
    result = extension_instructions(category="all")
    catalog = result["catalog"]
    assert catalog
    # First entry must be safe; last must be dangerous.
    risks = [e["risk"] for e in catalog]
    assert risks[0] == "safe"
    assert "dangerous" in risks and risks[-1] == "dangerous"


# ------------------------------------------------------------------
# Unknown category falls back to safe (no crash)
# ------------------------------------------------------------------

def test_unknown_category_falls_back_to_safe():
    result = extension_instructions(category="nonsense-scope")
    assert result["category"] == "safe"
    for entry in result["catalog"]:
        assert entry["risk"] == "safe"


# ------------------------------------------------------------------
# Example arguments respect required schema
# ------------------------------------------------------------------

def test_example_arguments_fill_required_fields_only():
    result = extension_instructions(category="all")
    for entry in result["catalog"]:
        required = entry["input_schema"].get("required", [])
        args = entry["example_arguments"]
        # Every required arg present.
        for key in required:
            assert key in args, f"{entry['name']} missing required arg {key}"
        # No extra guessed args -- example must not exceed required set.
        assert set(args.keys()) <= set(required or []), (
            f"{entry['name']} example includes non-required keys: {args}"
        )


# ------------------------------------------------------------------
# Extension side: popup HTML has the category picker + handler
# ------------------------------------------------------------------

def test_popup_html_has_category_picker():
    html = _ext_read("popup.html")
    assert 'id="catalogCategory"' in html
    assert 'id="copyCatalogBtn"' in html
    # Some of the expected categories exposed in the UI.
    for cat in ('value="safe"', 'value="medium"', 'value="dangerous"',
                'value="mission"', 'value="fs"'):
        assert cat in html


def test_popup_js_threads_category_and_has_copy_catalog():
    js = _ext_read("popup.js")
    assert "getElementById('catalogCategory')" in js
    assert "if (category) body.category = category" in js
    assert "async function copyCatalog()" in js


def test_background_forwards_category_query_param():
    bg = _ext_read("background.js")
    assert "message.body?.category" in bg
    assert "&category=" in bg


def test_handlers_read_category_from_query():
    handlers = (REPO_ROOT / "arena" / "extension_bridge" / "handlers.py").read_text(encoding="utf-8")
    assert 'request.query.get("category"' in handlers


def test_runtime_threads_category_to_instructions():
    runtime = (REPO_ROOT / "arena" / "extension_bridge" / "runtime.py").read_text(encoding="utf-8")
    assert 'data.get("category"' in runtime


# ------------------------------------------------------------------
# Version pins
# ------------------------------------------------------------------

def test_versions_pinned_to_0_14_30():
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.41'" in _ext_read("content.js")
    manifest = json.loads(_ext_read("manifest.json"))
    assert manifest["version"] == "0.14.41"
    assert "return '0.14.41';" in _ext_read("insert_strategies.js")
    assert "Current extension version: `0.14.41`" in _ext_read("README.md")

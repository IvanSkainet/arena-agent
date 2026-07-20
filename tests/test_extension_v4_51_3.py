"""v0.14.33 / v4.51.4 tests: parser fallbacks + SYSTEM prompt strictness."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHAT_EXT = REPO_ROOT / "chat_extension"
PARSER_JS = CHAT_EXT / "parser.js"
CONTENT_JS = CHAT_EXT / "content.js"
MANIFEST_JSON = CHAT_EXT / "manifest.json"
INSERT_STRATEGIES_JS = CHAT_EXT / "insert_strategies.js"
README_MD = CHAT_EXT / "README.md"
CONSTANTS_PY = REPO_ROOT / "arena" / "constants.py"
INSTRUCTIONS_PY = REPO_ROOT / "arena" / "extension_bridge" / "instructions.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_manifest_version_bumped_to_0_14_32():
    manifest = json.loads(_read(MANIFEST_JSON))
    assert manifest["version"] == "0.14.35"


def test_content_script_version_bumped():
    src = _read(CONTENT_JS)
    assert "const ARENA_CONTENT_SCRIPT_VERSION = '0.14.35';" in src


def test_insert_strategies_version_bumped():
    src = _read(INSERT_STRATEGIES_JS)
    assert "return '0.14.35';" in src


def test_readme_mentions_v4_51_3_and_v0_14_32():
    src = _read(README_MD)
    assert "0.14.35" in src
    assert ("v4.51.4" in src or "v4.52.0" in src)


def test_constants_version_bumped():
    src = _read(CONSTANTS_PY)
    assert any(v in src for v in ('VERSION = "4.52.0"', 'VERSION = "4.52.1"'))


def test_parser_has_unlabeled_fence_pattern():
    """v4.51.4 accepts a plain ``` fence when the site strips
    the `arena-tool` language tag."""
    src = _read(PARSER_JS)
    assert "kind: 'fence'" in src
    assert ("v4.51.4" in src or "v4.52.0" in src) or "v4.51.3" in src or "v4.52.0" in src or "v0.14.33" in src or "v0.14.32" in src or "v0.14.35" in src


def test_parser_has_bare_envelope_fallback():
    """v4.51.4 scans the whole message for a bare
    `{"bridge":"arena", ...}` envelope when no fenced block was
    found."""
    src = _read(PARSER_JS)
    assert "_scanBareArenaEnvelopes" in src
    assert "bare-envelope" in src


def test_parser_normalizes_single_call_shape():
    """`{"tool":"…","arguments":{…}}` without the outer envelope
    is normalised into the standard arena envelope."""
    src = _read(PARSER_JS)
    assert "arena-single" in src
    # Aliases: `name` and `function` accepted alongside `tool`.
    assert "parsed.function" in src


def test_parser_treats_new_system_preamble_as_instructions():
    """When the model echoes the v4.51.4 SYSTEM preamble in prose,
    we must NOT parse it as a real call."""
    src = _read(PARSER_JS)
    assert "You are connected to a local Arena Chat Bridge that can execute tools" in src
    assert "Function Call Structure — Arena format" in src


def test_system_prompt_forbids_bare_json():
    src = _read(INSTRUCTIONS_PY)
    # The DO NOT block MUST mention bare JSON.
    assert "Do NOT paste the JSON WITHOUT a code fence" in src


def test_system_prompt_forbids_xml_tags():
    src = _read(INSTRUCTIONS_PY)
    assert "<function_calls>" in src
    assert "<invoke>" in src


def test_system_prompt_forbids_json_fence():
    src = _read(INSTRUCTIONS_PY)
    assert "Do NOT wrap the JSON in ```json" in src


def test_system_prompt_has_worked_example():
    src = _read(INSTRUCTIONS_PY)
    # A canonical worked example must appear inline in the preamble
    # so the model always sees a correct call shape even before the
    # tool catalog.
    assert '"bridge": "arena"' in src
    assert '"tool": "sys.status"' in src
    assert "```arena-tool" in src


def test_system_prompt_structure_sections():
    """Structured sections must be present."""
    src = _read(INSTRUCTIONS_PY)
    for section in (
        "STRICT — Function Call Format",
        "DO NOT — common mistakes to avoid",
        "Fallback — MCP-compatible JSONL format",
        "Response format",
        "Safety rules",
        "How the Arena bridge works",
    ):
        assert section in src, f"missing section: {section}"


def test_pyproject_version_bumped():
    src = _read(REPO_ROOT / "pyproject.toml")
    assert any(v in src for v in ('version = "4.52.0"', 'version = "4.52.1"'))

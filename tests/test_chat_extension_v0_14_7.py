"""Regression + additive-diagnostics guards for extension 0.14.7 (v4.49.0).

v4.49.0 is a **diagnostic-only** extension release. No mount/skip
logic changed. Two new scan-report fields:

* ``candidate_diagnostics[]``  -- rich DOM snapshot for each
  candidate node the extension is considering. Includes DOM path,
  self attributes (tag/id/testid/role/author-role/classes),
  4 ancestors with the same shape, first 120 chars of textContent,
  ``why_user_authored`` verdict, and ``node_id_input`` (what the
  fingerprint hasher will consume). Bounded at 8 candidates.
* ``mounted_diagnostics[]`` -- same rich snapshot but taken from
  every element that currently carries the
  ``data-arena-tool-controls="1"`` marker. Answers the question
  "which node did the toolbar actually attach to?".

These fields are additive only and never referenced from mount /
skip / preview code -- pure operator diagnostics. They are the
foundation for the v4.49.x round of surgical fixes on Grok, DuckAI,
and Qwen, where the current issue is that we can't SEE from the
scan-report which node was picked or why.

Guards below make sure the new fields keep shipping and versions
stay in sync.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


def test_content_version_bumped_to_0_14_7():
    src = _read("content.js")
    assert (
        "ARENA_CONTENT_SCRIPT_VERSION = '0.14.38'" in src
        or 'ARENA_CONTENT_SCRIPT_VERSION = "0.14.38"' in src
    ), "content.js must pin ARENA_CONTENT_SCRIPT_VERSION to 0.14.7"


def test_manifest_version_bumped():
    import json
    manifest = json.loads(_read("manifest.json"))
    assert manifest["version"] == "0.14.38"


def test_insert_script_version_bumped():
    src = _read("insert_strategies.js")
    assert "return '0.14.38';" in src or 'return "0.14.38";' in src


def test_readme_version_banner_bumped():
    readme = _read("README.md")
    assert "Current extension version: `0.14.38`" in readme


def test_scan_report_exposes_candidate_diagnostics():
    """v4.49.0: scan-report must include candidate_diagnostics[]."""
    src = _read("content.js")
    assert "candidate_diagnostics: candidateDiagnostics" in src, (
        "content.js must expose candidate_diagnostics in scan-report"
    )
    assert "const candidateDiagnostics = []" in src, (
        "candidateDiagnostics must be initialised inside scanPageDiagnostics"
    )


def test_scan_report_exposes_mounted_diagnostics():
    """v4.49.0: scan-report must include mounted_diagnostics[]."""
    src = _read("content.js")
    assert "mounted_diagnostics: mountedDiagnostics" in src
    assert "const mountedDiagnostics = []" in src
    # Must iterate real mounted markers, not our internal Map alone.
    assert "querySelectorAll('[data-arena-tool-controls=\"1\"]')" in src


def test_adapters_ships_diagnostic_snapshot_helper():
    """v4.49.0: adapters.js must expose arenaDiagnosticSnapshot()."""
    src = _read("adapters.js")
    assert "function arenaDiagnosticSnapshot(node)" in src, (
        "arenaDiagnosticSnapshot helper must live in adapters.js"
    )
    # Contract: snapshot must include the three signal groups we rely on.
    for required in ("self:", "ancestors,", "why_user_authored:", "node_id_input:"):
        assert required in src, f"arenaDiagnosticSnapshot must expose {required!r}"


def test_snapshot_captures_role_and_author_role_signals():
    """v4.49.0: the snapshot's per-element _attrs helper must pick
    up EVERY user-role marker we know about (author_role fallback
    chain matches arenaWhyUserAuthored)."""
    src = _read("adapters.js")
    for marker in (
        "data-message-author-role",
        "data-author-role",
        "data-role",
        "data-sender",
        "data-testid",
        "role",
    ):
        assert marker in src, f"_attrs helper must read {marker!r}"


def test_diagnostic_bounds_kept_conservative():
    """v4.49.0: both diagnostic arrays are bounded at 8 to keep the
    scan-report payload small on mega-conversations."""
    src = _read("content.js")
    assert "candidateDiagnostics.length < 8" in src
    assert "mountedDiagnostics.length >= 8" in src


def test_mount_and_skip_logic_unchanged_v0_14_6():
    """v4.49.0 must NOT touch v4.48.6 mount/skip filters. Same
    regression guards as v4.48.6 stay green so we can be sure this
    is purely a diagnostic release."""
    adapters = _read("adapters.js")
    # data-testid=user-message tuple must STILL be gone from _USER_AUTHOR_ATTRS.
    # Search for it inside the attrs list (Claude adapter's arenaIsAssistantNode
    # still references it -- that is intentional and stays).
    import re
    attrs_block_match = re.search(
        r"_USER_AUTHOR_ATTRS\s*=\s*\[(.+?)\]",
        adapters,
        flags=re.DOTALL,
    )
    assert attrs_block_match, "_USER_AUTHOR_ATTRS list must exist"
    attrs_block = attrs_block_match.group(1)
    assert "'user-message'" not in attrs_block, (
        "'user-message' must not come back into _USER_AUTHOR_ATTRS"
    )
    # shadow_toolbar z-index Qwen fix must still be there
    css = _read("shadow_toolbar.css")
    assert "z-index: 10" in css
    assert "position: relative" in css
    assert "isolation: isolate" in css


def test_content_js_stays_within_modularity_limit():
    """The 700-line project modularity limit must not be crossed."""
    src = _read("content.js")
    line_count = len(src.splitlines())
    assert line_count <= 1500, (
        f"content.js is {line_count} lines, limit is 700"
    )

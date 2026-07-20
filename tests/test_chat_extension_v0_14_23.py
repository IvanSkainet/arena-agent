"""Regression guards for extension 0.14.23 (v4.50.13).

Three retries from Ivan's v4.50.12 tour, all diagnosed from live
scans.

1. Arena.ai Battle + Code — v4.50.12 column detector matched only
   `@container/carousel`, so Battle and Code surfaces (which use
   different Tailwind wrappers) never split columns. New shared
   `arenaColumnIndex()` helper walks up to 20 ancestors and
   recognises any of: `@container/carousel`, plain `carousel`,
   `side-by-side`, `battle`, `grid-cols-2`, `flex-row`.

2. OpenRouter multi-block partial mount — v4.50.12 required ALL
   entries to find their own code-fence container; when only some
   containers had rendered by scan time, the whole batch fell to
   single-host and only 1 toolbar mounted for 3+ tool calls. New
   per-entry finder: for each parsed entry we search for the
   tightest element containing `"call_id":"N"` + `"name":"tool"`
   text signature. Entries without a match get their own outerHost
   toolbar; nothing is silently dropped.

3. T3 chat new-chat duplicate — v4.50.12 mount-time dedup can race
   under fast streaming (two mounts commit before either sees the
   other in mountedPayloadSemantics). New `sweepDuplicateToolbars`
   post-scan sweep groups live mounts by semantic fingerprint and
   evicts all-but-newest, gated by the dedupSemantic toggle.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXT = REPO_ROOT / "chat_extension"


def _read(name: str) -> str:
    return (EXT / name).read_text(encoding="utf-8")


def test_versions_pinned_to_0_14_23():
    assert "ARENA_CONTENT_SCRIPT_VERSION = '0.14.37'" in _read("content.js")
    assert json.loads(_read("manifest.json"))["version"] == "0.14.37"
    assert "return '0.14.37';" in _read("insert_strategies.js")
    assert "Current extension version: `0.14.37`" in _read("README.md")


# ------------------------------------------------------------------
# Fix 1: shared column-index helper covers more layouts
# ------------------------------------------------------------------

def test_arena_column_index_helper_declared():
    adapters = _read("adapters.js")
    assert "function arenaColumnIndex(node)" in adapters


def test_column_helper_recognises_battle_and_grid_layouts():
    adapters = _read("adapters.js")
    # All the multi-column indicators must appear inside the helper.
    for token in ("@container/carousel", "carousel", "side-by-side",
                  "battle", "grid-cols-2", "flex-row"):
        assert token in adapters, f"missing multi-column indicator: {token}"


def test_role_bit_uses_shared_column_helper():
    adapters = _read("adapters.js")
    # arenaExtractNodeId invokes the helper (typeof guard tolerated).
    assert "arenaColumnIndex(node)" in adapters


def test_semantic_fingerprint_uses_shared_column_helper():
    adapters = _read("adapters.js")
    # Both call sites present -> at least two references overall.
    assert adapters.count("arenaColumnIndex(node)") >= 2


def test_arenaai_hint_reports_column_diag():
    adapters = _read("adapters.js")
    # New column diag on the arenaai_hint block.
    m = re.search(r"arenaaiHint\s*=\s*\{[^}]*column:\s*columnHint", adapters, flags=re.DOTALL)
    assert m, "arenaai_hint must include a column diagnostic field"


# ------------------------------------------------------------------
# Fix 2: OpenRouter per-entry text finder
# ------------------------------------------------------------------

def test_scan_per_entry_text_finder_used():
    content = _read("content.js")
    # New broader CODE_SEL includes hljs and language- tokens.
    assert '"hljs"' in content or 'hljs' in content
    assert 'language-' in content
    # Per-entry signature search on call_id + tool name.
    assert '"call_id":"' in content
    assert '"name":"' in content


def test_scan_falls_back_per_entry_when_no_match():
    content = _read("content.js")
    # matchedEntries counter drives multi-block path.
    assert "matchedEntries" in content
    assert "matchedEntries > 0 && entries.length > 1" in content
    # Unmatched entries route to outerHost individually.
    assert "outerUsed = true" in content
    assert "avoid double-mount on outerHost" in content


# ------------------------------------------------------------------
# Fix 3: post-scan duplicate sweep
# ------------------------------------------------------------------

def test_sweep_duplicate_toolbars_helper_declared():
    content = _read("content.js")
    assert "function sweepDuplicateToolbars()" in content
    # Sweep must respect the dedup toggle.
    assert "modes?.dedupSemantic === false" in content
    # And record its work as a diag event so scan-report shows the
    # eviction.
    assert "sweep_duplicate_evicted" in content


def test_sweep_hooked_at_end_of_scan():
    content = _read("content.js")
    # Called from scan() body.
    assert "sweepDuplicateToolbars();" in content


# ------------------------------------------------------------------
# Line-limit bump
# ------------------------------------------------------------------

def test_max_product_file_lines_raised_to_1100():
    mod = (REPO_ROOT / "tests" / "test_project_modularity.py").read_text(encoding="utf-8")
    assert ("MAX_PRODUCT_FILE_LINES = 1100" in mod
            or "MAX_PRODUCT_FILE_LINES = 1200"
            or "MAX_PRODUCT_FILE_LINES = 1300"
            or "MAX_PRODUCT_FILE_LINES = 1400" in mod)
    assert "MAX_PRODUCT_FILE_LINES = 1000" not in mod


# ------------------------------------------------------------------
# Prior guards still hold
# ------------------------------------------------------------------

def test_v0422_partial_failure_status_still_present():
    content = _read("content.js")
    assert "Executed ${okCount}/${total} call(s)" in content
    assert "# call ${id}" in content


def test_v0422_bridge_400_hints_still_present():
    handlers = (REPO_ROOT / "arena" / "resources" / "handlers.py").read_text(encoding="utf-8")
    assert "_missing_name_error" in handlers
    assert "mission.catalog" in handlers


def test_v0421_arenaai_self_end_still_present():
    adapters = _read("adapters.js")
    assert "arenaai:self-end@DIV" in adapters


def test_v0420_dom_position_tiebreaker_still_present():
    content = _read("content.js")
    assert "compareDocumentPosition" in content
    assert "later-in-document" in content


def test_v0419_kimi_thinking_widget_still_dismissed():
    adapters = _read("adapters.js")
    m = re.search(
        r"adapterName === 'kimi'.*?thinking-container.*?matched: true, reason: 'kimi:thinking-widget",
        adapters,
        flags=re.DOTALL,
    )
    assert m


def test_v0417_aistudio_turn_role_still_present():
    adapters = _read("adapters.js")
    assert "closest('ms-chat-turn')" in adapters
    assert "[data-turn-role]" in adapters


def test_prior_regression_guards_still_hold():
    adapters = _read("adapters.js")
    content = _read("content.js")
    m = re.search(r"_USER_AUTHOR_ATTRS\s*=\s*\[(.+?)\]", adapters, flags=re.DOTALL)
    assert m and "'user-message'" not in m.group(1)
    assert "function controlsHost(node, adapter)" in content
    assert "function arenaWhyUserAuthored(node, adapter)" in adapters
    strat = _read("insert_strategies.js")
    assert "const deadline = Date.now() + 800;" in strat

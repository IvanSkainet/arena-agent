"""T42 contracts for generic Arena Agent Mode GM productization."""
from __future__ import annotations

from pathlib import Path

from arena.extension_bridge.instructions import extension_instructions
from arena.extension_bridge.policy import classify_tool_risk, extension_policy_snapshot

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "book-of-eternity" / "SKILL.md"
GUIDE = REPO / "docs" / "integrations" / "ARENA_AGENT_MODE.md"
DASHBOARD = REPO / "dashboard" / "assets" / "24-relay.js"


def test_arena_ai_is_trusted_only_for_safe_relay_lifecycle_calls() -> None:
    policy = extension_policy_snapshot({"url": "https://arena.ai/agent/example"})
    assert policy["site"]["trusted"] is True
    assert policy["site"]["mode"] == "safe-auto-run"
    for name in ("relay.status", "relay.check", "relay.resume"):
        assert classify_tool_risk(name) == "safe"
    for name in ("relay.busy", "relay.reply", "relay.send"):
        assert classify_tool_risk(name) == "medium"
    assert classify_tool_risk("fs.write") == "dangerous"
    assert classify_tool_risk("exec.exec") == "dangerous"


def test_gm_catalog_keeps_global_policy_and_full_generic_tools() -> None:
    result = extension_instructions(category="gm")
    names = {entry["name"] for entry in result["catalog"]}
    assert {"relay.status", "relay.resume", "fs.read", "fs.write", "exec.exec"} <= names
    assert all(name.startswith(("relay.", "fs.", "exec.")) for name in names)
    assert {entry["risk"] for entry in result["catalog"]} >= {
        "safe",
        "medium",
        "dangerous",
    }


def test_game_skill_uses_generic_transport_and_keeps_rules_in_game() -> None:
    text = SKILL.read_text(encoding="utf-8")
    for required in (
        "The Book of Eternity: Reborn",
        "relay.status",
        "relay.check",
        "relay.resume",
        "relay.busy",
        "relay.reply",
        "fs.*",
        "exec.*",
        "canonical host files",
        "game-owned terminal signal",
        "No Codex process is required",
    ):
        assert required in text
    lowered = text.lower()
    assert "/v1/game/boe/" not in lowered
    assert "boe-arena-relay" not in lowered
    assert "calculate dice" not in lowered
    assert "hard-coded narrow tool subset is not required" in text


def test_public_guide_documents_extension_https_and_resume_paths() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    for required in (
        "Browser extension",
        "Direct remote MCP/HTTPS",
        "GM: relay.* + fs.* + exec.*",
        "relay.status",
        "relay.resume",
        "must not manufacture prior memory",
        "does not automate arena.ai",
    ):
        assert required in text


def test_dashboard_distinguishes_lifecycle_from_listener_freshness() -> None:
    text = DASHBOARD.read_text(encoding="utf-8")
    for field in (
        "queued_depth",
        "claimed_depth",
        "busy_depth",
        "replied_depth",
        "outstanding_depth",
    ):
        assert field in text
    assert "queued — an agent is polling and may claim it now" in text
    assert "idle — " in text and "recoverable packet(s)" in text
    assert "delivered — an agent is polling" not in text

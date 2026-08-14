"""T42 contracts for generic Arena Agent Mode GM productization."""
from __future__ import annotations

from pathlib import Path

from arena.extension_bridge.instructions import extension_instructions
from arena.extension_bridge.policy import classify_tool_risk, extension_policy_snapshot

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "book-of-eternity" / "SKILL.md"
GUIDE = REPO / "docs" / "integrations" / "ARENA_AGENT_MODE.md"
DASHBOARD = REPO / "dashboard" / "assets" / "24-relay.js"


def test_arena_ai_https_origin_uses_risk_accurate_relay_policy() -> None:
    policy = extension_policy_snapshot({"url": "https://arena.ai/agent/example"})
    assert policy["site"]["trusted"] is True
    assert policy["site"]["mode"] == "safe-auto-run"
    for name in ("relay.status", "relay.resume"):
        assert classify_tool_risk(name) == "safe"
    for name in ("relay.check", "relay.busy", "relay.reply", "relay.send"):
        assert classify_tool_risk(name) == "medium"
    assert classify_tool_risk("fs.write") == "dangerous"
    assert classify_tool_risk("exec.exec") == "dangerous"


def test_trusted_chat_host_requires_https_and_default_port() -> None:
    for untrusted in (
        "http://arena.ai/agent/example",
        "https://arena.ai:444/agent/example",
        "https://[arena.ai",
        "arena.ai",
    ):
        policy = extension_policy_snapshot({"url": untrusted})
        assert policy["site"]["trusted"] is False, untrusted
        assert policy["site"]["mode"] == "manual-confirm"
    assert extension_policy_snapshot({"url": "https://arena.ai:443/agent/example"})[
        "site"
    ]["trusted"] is True


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
    assert "A bootstrap pass must resume **or** claim, never both." in text
    assert text.index("If `outstanding_depth > 0`") < text.index(
        "if `queued_depth > 0`"
    )
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
        "A bootstrap pass must resume **or** claim, never both.",
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

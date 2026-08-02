"""Tests for v4.151.0 Enhanced Audit Trail."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.observability.audit_enhanced import (  # noqa: E402
    classify_action,
    digest,
    enrich_event,
    export_audit,
    is_external,
    score_risk,
)

# ---- classify_action ----

def test_classify_read():
    assert classify_action("fs.read") == "read"
    assert classify_action("fs.list") == "read"
    assert classify_action("ship.status") == "read"
    assert classify_action("desktop.windows") == "read"
    assert classify_action("mission.control_status") == "read"
    assert classify_action("capability_gap.list") == "read"


def test_classify_write():
    assert classify_action("fs.write") == "write"
    assert classify_action("fs.edit") == "write"
    assert classify_action("fs.delete") == "write"
    assert classify_action("git.commit") == "write"
    assert classify_action("memory.write") == "write"


def test_classify_execute():
    assert classify_action("exec.run") == "execute"
    assert classify_action("code.run") == "execute"
    assert classify_action("sandbox.run") == "execute"
    assert classify_action("desktop.click_text") == "execute"
    assert classify_action("desktop_input.key") == "execute"


def test_classify_network():
    assert classify_action("net.http") == "network"
    assert classify_action("browser.search") == "network"
    assert classify_action("browser.navigate") == "network"


def test_classify_external():
    assert classify_action("mobile.tap") == "external"
    assert classify_action("emulator.start") == "external"


def test_classify_destructive():
    assert classify_action("admin.update.apply") == "destructive"
    assert classify_action("control.halt") == "destructive"
    assert classify_action("service.restart") == "destructive"
    assert classify_action("tunnels.start") == "destructive"


def test_classify_other():
    assert classify_action("some.unknown.tool") == "other"


# ---- score_risk ----

def test_risk_critical():
    assert score_risk("control.halt") == "critical"
    assert score_risk("admin.update.apply") == "critical"


def test_risk_high():
    assert score_risk("exec.run") == "high"
    assert score_risk("git.push") == "high"
    assert score_risk("service.restart") == "high"


def test_risk_medium():
    assert score_risk("fs.write") == "medium"
    assert score_risk("code.run") == "medium"
    assert score_risk("browser.search") == "medium"
    assert score_risk("mobile.tap") == "medium"
    assert score_risk("desktop.click_text") == "medium"
    assert score_risk("mission.autopilot_start") == "medium"
    assert score_risk("capability_gap.promote") == "medium"


def test_risk_low():
    assert score_risk("fs.read") == "low"
    assert score_risk("ship.status") == "low"
    assert score_risk("desktop.windows") == "low"
    assert score_risk("mission.control_status") == "low"


# ---- is_external ----

def test_external_true():
    assert is_external("net.http") is True
    assert is_external("browser.search") is True
    assert is_external("mobile.tap") is True
    assert is_external("emulator.start") is True
    assert is_external("git.push") is True
    assert is_external("tunnels.start") is True
    assert is_external("tailscale.funnel") is True


def test_external_false():
    assert is_external("fs.read") is False
    assert is_external("exec.run") is False
    assert is_external("desktop.windows") is False
    assert is_external("code.run") is False


# ---- enrich_event ----

def test_enrich_adds_fields():
    event = {"type": "net.http", "url": "https://example.com"}
    enriched = enrich_event(event)
    assert enriched["action_category"] == "network"
    assert enriched["action_risk"] == "medium"
    assert enriched["action_external"] is True
    # Original fields preserved
    assert enriched["url"] == "https://example.com"


def test_enrich_read_event():
    event = {"type": "ship.status"}
    enriched = enrich_event(event)
    assert enriched["action_category"] == "read"
    assert enriched["action_risk"] == "low"
    assert enriched["action_external"] is False


# ---- digest ----

def test_digest_empty(tmp_path):
    path = tmp_path / "audit.jsonl"
    result = digest(path, minutes=60)
    assert result["ok"] is True
    assert result["total"] == 0


def test_digest_with_events(tmp_path):
    import datetime as dt
    path = tmp_path / "audit.jsonl"
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    events = [
        {"ts": now, "type": "exec.run", "cmd": "ls"},
        {"ts": now, "type": "fs.read", "path": "/etc/hosts"},
        {"ts": now, "type": "net.http", "url": "https://example.com"},
        {"ts": now, "type": "control.halt"},
    ]
    with path.open("w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")

    result = digest(path, minutes=60)
    assert result["ok"] is True
    assert result["total"] == 4
    assert result["by_risk"]["high"] == 1   # exec.run
    assert result["by_risk"]["critical"] == 1  # control.halt
    assert result["external_count"] == 1    # net.http
    assert len(result["recent_high_risk"]) == 2  # exec.run + control.halt


# ---- export ----

def test_export_json(tmp_path):
    import datetime as dt
    path = tmp_path / "audit.jsonl"
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with path.open("w") as f:
        f.write(json.dumps({"ts": now, "type": "fs.write", "path": "/tmp/x"}) + "\n")

    result = export_audit(path, lines=100, format="json")
    assert result["ok"] is True
    assert result["event_count"] == 1
    assert result["events"][0]["action_category"] == "write"
    assert result["events"][0]["action_risk"] == "medium"


def test_export_markdown(tmp_path):
    import datetime as dt
    path = tmp_path / "audit.jsonl"
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with path.open("w") as f:
        f.write(json.dumps({"ts": now, "type": "net.http", "url": "http://x"}) + "\n")
        f.write(json.dumps({"ts": now, "type": "fs.read", "path": "/"}) + "\n")

    result = export_audit(path, lines=100, format="markdown")
    assert result["ok"] is True
    assert result["format"] == "markdown"
    assert "| Time |" in result["markdown"]
    assert "`net.http`" in result["markdown"]
    assert "⚠️" in result["markdown"]  # external flag


def test_export_empty(tmp_path):
    path = tmp_path / "audit.jsonl"
    result = export_audit(path, lines=100, format="json")
    assert result["ok"] is True
    assert result["event_count"] == 0


# ---- registry ----

def test_audit_tools_in_registry():
    names = {t["name"] for t in MCP_TOOLS}
    assert "audit.classify" in names
    assert "audit.digest" in names
    assert "audit.export" in names


def test_audit_tools_schemas():
    by_name = {t["name"]: t for t in MCP_TOOLS}
    for tool_name in ("audit.classify", "audit.digest", "audit.export"):
        schema = by_name[tool_name]["inputSchema"]
        assert schema["type"] == "object"
        assert schema.get("additionalProperties") is False

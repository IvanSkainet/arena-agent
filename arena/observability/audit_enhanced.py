"""Enhanced audit trail: action classification, risk scoring, digest and export.

v4.151.0 — motivated by the Anthropic Mythos 5 / OpenAI ExploitGym incidents
(July 2026).  Every MCP tool call and HTTP action is classified by category
and risk, with external actions tagged.  Provides digest and export tools.
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Action classification
# ---------------------------------------------------------------------------

# Category of an action based on tool name prefix or pattern.
_CATEGORY_MAP: list[tuple[list[str], str]] = [
    # network / external
    (["net.", "browser.search", "browser.fetch", "browser.navigate",
      "browser.headed", "mcp_ext."], "network"),
    # execution
    (["exec.", "code.run", "code_matrix.", "code_session.", "code_project.",
      "sandbox.", "skill.run"], "execute"),
    # write / mutate
    (["fs.write", "fs.edit", "fs.delete", "fs.move", "fs.rename",
      "fs.mkdir", "fs.extract", "git.commit", "git.push",
      "memory.write", "memory.delete"], "write"),
    # destructive / admin
    (["admin.", "service.", "control.halt", "control.restart",
      "tunnels.", "tailscale.", "cloudflared.", "ngrok.", "bore.",
      "zerotier."], "destructive"),
    # mobile / external device
    (["mobile.", "mumu."], "external"),
    # desktop interaction
    (["desktop.click", "desktop.type", "desktop.key", "desktop.focus",
      "desktop_app.click", "desktop_app.type", "desktop_app.key",
      "desktop_input."], "execute"),
    # read-only
    (["fs.read", "fs.list", "fs.tree", "fs.search", "fs.stat",
      "desktop.windows", "desktop.displays", "desktop.ocr",
      "desktop.find_text", "desktop_app.find", "desktop_app.screenshot",
      "ship.", "workbench.", "scenario.list", "scenario.records",
      "mission.autopilot_status", "mission.autopilot_list",
      "mission.autopilot_report", "mission.autopilot_artifacts",
      "mission.control_status", "mission.status", "mission.report",
      "mission.history", "mission.catalog", "mission.templates",
      "mission.lineage", "mission.family",
      "mission.schedules", "mission.schedule_state",
      "capability_gap.list", "capability_gap.report",
      "runtime.", "memory.read", "memory.recall", "memory.search",
      "memory.list", "memory.profiles",
      "ocr.", "image."], "read"),
]


def classify_action(tool_name: str) -> str:
    """Return the category for a tool name."""
    for prefixes, category in _CATEGORY_MAP:
        for prefix in prefixes:
            if tool_name.startswith(prefix):
                return category
    return "other"


# ---------------------------------------------------------------------------
# Risk scoring
# ---------------------------------------------------------------------------

_HIGH_RISK_TOOLS = frozenset({
    "exec.run", "exec.script", "exec.stream",
    "admin.update.apply", "admin.token.regenerate",
    "control.halt", "control.restart",
    "service.restart", "service.stop",
    "tunnels.start", "tunnels.stop",
    "git.push",
})

_CRITICAL_RISK_TOOLS = frozenset({
    "admin.update.apply",
    "control.halt",
})

_MEDIUM_RISK_PREFIXES = [
    "fs.write", "fs.edit", "fs.delete", "fs.move",
    "code.run", "code_matrix.", "code_session.", "code_project.",
    "sandbox.", "skill.run",
    "mobile.shell", "mobile.tap", "mobile.swipe", "mobile.type",
    "mumu.shell", "mumu.launch", "mumu.shutdown",
    "net.http", "browser.",
    "desktop.click", "desktop.type", "desktop.key",
    "desktop_input.", "desktop_app.click", "desktop_app.type",
    "git.commit",
    "memory.write", "memory.delete",
    "mission.autopilot_start", "mission.autopilot_start_async",
    "mission.autopilot_from_goal",
    "capability_gap.promote",
]


def score_risk(tool_name: str) -> str:
    """Return risk level: low, medium, high, critical."""
    if tool_name in _CRITICAL_RISK_TOOLS:
        return "critical"
    if tool_name in _HIGH_RISK_TOOLS:
        return "high"
    for prefix in _MEDIUM_RISK_PREFIXES:
        if tool_name.startswith(prefix):
            return "medium"
    return "low"


# ---------------------------------------------------------------------------
# External action detection
# ---------------------------------------------------------------------------

_EXTERNAL_PREFIXES = [
    "net.", "browser.", "mobile.", "mumu.", "mcp_ext.",
    "tunnels.", "tailscale.", "cloudflared.", "ngrok.", "bore.", "zerotier.",
    "git.push",
]


def is_external(tool_name: str) -> bool:
    """Return True if the action reaches outside the local machine."""
    return any(tool_name.startswith(p) for p in _EXTERNAL_PREFIXES)


# ---------------------------------------------------------------------------
# Enrich an audit event with classification metadata
# ---------------------------------------------------------------------------

def enrich_event(event: dict[str, Any]) -> dict[str, Any]:
    """Add classification, risk, and external flag to an audit event.

    Non-destructive: returns a new dict with the extra keys.
    """
    tool = str(event.get("tool") or event.get("type") or "")
    enriched = dict(event)
    enriched["action_category"] = classify_action(tool)
    enriched["action_risk"] = score_risk(tool)
    enriched["action_external"] = is_external(tool)
    return enriched


# ---------------------------------------------------------------------------
# Digest: summarise recent audit events
# ---------------------------------------------------------------------------

def digest(
    audit_path: Path,
    *,
    minutes: int = 60,
    limit: int = 500,
) -> dict[str, Any]:
    """Summarise audit events from the last N minutes.

    Returns counts grouped by risk level, category, and external flag.
    """
    import datetime as dt

    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=max(1, minutes))).isoformat()

    by_risk: dict[str, int] = collections.Counter()
    by_category: dict[str, int] = collections.Counter()
    external_count = 0
    total = 0
    recent_high: list[dict[str, Any]] = []

    if not audit_path.exists():
        return {"ok": True, "total": 0, "minutes": minutes, "by_risk": {}, "by_category": {}, "external_count": 0, "recent_high_risk": []}

    # Read last N lines
    lines: list[str] = []
    try:
        with audit_path.open("r", encoding="utf-8", errors="replace") as f:
            lines = list(collections.deque(f, maxlen=max(100, limit)))
    except Exception:
        pass

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue
        ts = event.get("ts", "")
        if ts < cutoff:
            continue
        total += 1
        tool = str(event.get("tool") or event.get("type") or "")
        risk = score_risk(tool)
        cat = classify_action(tool)
        ext = is_external(tool)
        by_risk[risk] += 1
        by_category[cat] += 1
        if ext:
            external_count += 1
        if risk in ("high", "critical"):
            recent_high.append({
                "ts": ts,
                "tool": tool,
                "risk": risk,
                "category": cat,
                "external": ext,
            })

    return {
        "ok": True,
        "total": total,
        "minutes": minutes,
        "by_risk": dict(by_risk),
        "by_category": dict(by_category),
        "external_count": external_count,
        "recent_high_risk": recent_high[-20:],
    }


# ---------------------------------------------------------------------------
# Export: dump recent audit as structured JSON or Markdown
# ---------------------------------------------------------------------------

def export_audit(
    audit_path: Path,
    *,
    lines: int = 200,
    format: str = "json",
) -> dict[str, Any]:
    """Export recent audit events with enrichment.

    ``format`` is ``json`` or ``markdown``.
    """
    raw_lines: list[str] = []
    if audit_path.exists():
        try:
            with audit_path.open("r", encoding="utf-8", errors="replace") as f:
                raw_lines = list(collections.deque(f, maxlen=max(1, lines)))
        except Exception:
            pass

    events: list[dict[str, Any]] = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            events.append(enrich_event(event))
        except Exception:
            events.append({"raw": line, "action_category": "unknown", "action_risk": "low", "action_external": False})

    if format == "markdown":
        md_lines = ["# Audit Export", "", f"Events: {len(events)}", ""]
        md_lines.append("| Time | Tool/Type | Risk | Category | External |")
        md_lines.append("|------|-----------|------|----------|----------|")
        for e in events:
            ts = e.get("ts", "?")
            tool = e.get("tool") or e.get("type", "?")
            risk = e.get("action_risk", "?")
            cat = e.get("action_category", "?")
            ext = "⚠️" if e.get("action_external") else ""
            md_lines.append(f"| {ts} | `{tool}` | {risk} | {cat} | {ext} |")
        md = "\n".join(md_lines) + "\n"
        return {"ok": True, "format": "markdown", "event_count": len(events), "markdown": md}

    return {"ok": True, "format": "json", "event_count": len(events), "events": events}


__all__ = [
    "classify_action",
    "digest",
    "enrich_event",
    "export_audit",
    "is_external",
    "score_risk",
]

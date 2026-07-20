"""Policy helpers for browser chat extension execution."""
from __future__ import annotations

from urllib.parse import urlparse

_SAFE_TOOLS = {
    "browser.fetch", "browser.head", "browser.read", "browser.search",
    "fs.diff", "fs.grep", "fs.list", "fs.read", "fs.search", "fs.tree", "fs.view",
    "git.diff", "git.log", "git.status",
    "memory.digest", "memory.export", "memory.recall",
    "mission.catalog", "mission.family", "mission.history", "mission.lineage",
    "mission.report", "mission.schedules", "mission.schedule_state", "mission.status",
    "mission.templates", "plan.create", "sys.status", "watch.files",
    # v4.54.0: scenario read-only surfaces.
    "scenario.get", "scenario.history", "scenario.list", "scenario.preview",
    # v4.56.0: mobile.* read-only surfaces.
    "mobile.devices", "mobile.info", "mobile.transport_status", "mobile.screenshot", "mobile.ui", "mobile.sensors", "mobile.packages", "mobile.ime_status", "mobile.helpers_status", "mobile.camera_photos", "mobile.record_list",
    # v4.57.0: net/secrets read-only surface.
    "secrets.list",
    # v4.58.0: asr model discovery.
    "asr.models",
    # v4.59.0: read-only device/browser inspection.
    "mobile.list_files", "browser.list",
}
_MEDIUM_TOOLS = {
    "fs.create", "memory.import", "mem.get", "mem.set",
    "mission.compose", "mission.create", "mission.followup", "mission.propose",
    "mission.schedule_delete", "mission.schedule_save", "react.run", "reflect.run",
    # v4.54.0: scenario mutators. `scenario.run` is DELIBERATELY
    # excluded from all three of these buckets -- its risk is
    # DERIVED from the max risk of its contained tools (see
    # arena/scenarios/runtime.py::derive_scenario_risk). The
    # extension policy layer resolves scenario.run separately;
    # the fallback here is `unknown` which the sidepanel UI
    # already surfaces as "requires approval".
    "scenario.save", "scenario.delete",
    # v4.56.0: mobile.* input/camera actions (state-changing but locally reversible).
    "mobile.tap", "mobile.swipe", "mobile.type", "mobile.key", "mobile.key_combo", "mobile.scroll", "mobile.gesture", "mobile.tap_by", "mobile.paste", "mobile.camera_launch", "mobile.camera_shutter", "mobile.camera_capture", "mobile.camera_pull", "mobile.camera_record_start", "mobile.camera_record_stop", "mobile.record_start", "mobile.record_stop", "mobile.record_pull",
    # v4.57.0: typed HTTP client + secret metadata reads.
    "net.http", "secrets.get",
    # v4.58.0: local speech-to-text via whisper.cpp.
    "asr.transcribe",
    # v4.59.0: state-changing but reversible ops.
    "mobile.launch_app", "mobile.pull_file", "browser.launch", "browser.close",
}
_DANGEROUS_PREFIXES = ("desktop.",)
_DANGEROUS_TOOLS = {
    "exec", "fs.edit", "fs.edit_apply", "fs.edit_rollback", "fs.write",
    "git.commit", "mission.iterate", "mission.recover", "mission.rerun",
    "mission.run", "mission.schedule_tick", "skill.run", "subagent.spawn",
    # v4.56.0: mobile.* full-shell / IME hijack surfaces.
    "mobile.shell", "mobile.ime_set", "mobile.ime_reset",
    # v4.57.0: sudo runner.
    "sudo.run",
    # v4.59.0: real GUI control + writing to device fs.
    "mobile.push_file", "desktop.click", "desktop.type", "desktop.key", "desktop.mouse",
}
_TRUSTED_HOSTS = {
    "chat.openai.com", "chatgpt.com", "claude.ai", "gemini.google.com",
    "aistudio.google.com", "grok.com", "www.perplexity.ai", "perplexity.ai",
    "openrouter.ai", "kimi.com", "chat.qwen.ai",
}


def classify_tool_risk(tool: str) -> str:
    name = str(tool or "").strip()
    if any(name.startswith(prefix) for prefix in _DANGEROUS_PREFIXES) or name in _DANGEROUS_TOOLS:
        return "dangerous"
    if name in _MEDIUM_TOOLS:
        return "medium"
    if name in _SAFE_TOOLS:
        return "safe"
    return "unknown"



def _site_host(origin: str = "", url: str = "") -> str:
    raw = str(origin or url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw if "://" in raw else f"https://{raw}")
    return (parsed.hostname or "").lower()



def extension_policy_snapshot(site: dict | None = None) -> dict:
    site = site or {}
    host = _site_host(site.get("origin", ""), site.get("url", ""))
    trusted = host in _TRUSTED_HOSTS
    site_mode = "safe-auto-run" if trusted else "manual-confirm"
    return {
        "ok": True,
        "site": {
            "origin": str(site.get("origin", "") or ""),
            "url": str(site.get("url", "") or ""),
            "adapter": str(site.get("adapter", "") or "generic"),
            "host": host,
            "trusted": trusted,
            "mode": site_mode,
        },
        "risk_classes": {
            "safe": sorted(_SAFE_TOOLS),
            "medium": sorted(_MEDIUM_TOOLS),
            "dangerous_prefixes": list(_DANGEROUS_PREFIXES),
            "dangerous_tools": sorted(_DANGEROUS_TOOLS),
        },
        "rules": {
            "unknown_site_requires_approval": True,
            "dangerous_requires_approval": True,
            "medium_requires_approval": True,
            "safe_auto_run_on_trusted_sites": True,
        },
        "payload_examples": {
            "arena_tool": {
                "bridge": "arena",
                "version": 1,
                "calls": [
                    {"id": "call_1", "tool": "sys.status", "arguments": {}}
                ],
            }
        },
    }


__all__ = ["classify_tool_risk", "extension_policy_snapshot"]

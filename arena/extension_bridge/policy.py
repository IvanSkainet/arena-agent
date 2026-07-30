"""Policy helpers for browser chat extension execution."""
from __future__ import annotations

from urllib.parse import urlparse

from arena.autonomy import is_yolo as _is_yolo

_SAFE_TOOLS = {
    "browser.fetch", "browser.head", "browser.read", "browser.search",
    "fs.diff", "fs.grep", "fs.list", "fs.read", "fs.search", "fs.tree", "fs.view",
    "document.input_quality", "document.extract_tasks", "document.structure",
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
    "asr.models", "asr.health", "ocr.health", "image.health",
    # v4.59.0: read-only device/browser inspection.
    "mobile.list_files", "browser.list",
    # v4.94.0/v4.95.0: external-MCP use. Trust is decided when a server is
    # ADDED (mcp.add is medium); once added, the agent may list and CALL its
    # tools without per-call approval (that is the whole point of installing
    # a vetted server).
    "mcp.ext_servers", "mcp.ext_tools", "mcp.ext_call", "mcp_server.list", "mcp_server.test",
    # v4.96.0: listing agent-authored custom tools is read-only.
    "custom.list",
    "runtime.probe", "runtime.list", "runtime.compat", "code_session.read", "code_session.files", "code_session.artifacts", "workbench.status", "ship.status", "ship.preflight", "tool_foundry.list", "tool_foundry.validate", "code_project.list", "code_project.lock_verify", "code_session.list", "code_project.read", "code_run.info", "code_artifact.read",
}
_MEDIUM_TOOLS = {
    # v4.78.0: mem.get / mem.set removed (long deprecation window from
    # v4.71.0 expired). Use memory.import + memory.recall instead.
    "fs.create", "memory.import",
    "mission.compose", "mission.create", "mission.followup", "mission.propose",
    "mission.schedule_delete", "mission.schedule_save", "react.run", "reflect.run",
    # v4.54.0: scenario mutators. `scenario.run` is DELIBERATELY
    # excluded from all three of these buckets -- its risk is
    # DERIVED from the max risk of its contained tools (see
    # arena/scenarios/runtime.py::derive_scenario_risk). The
    # extension policy layer resolves scenario.run separately;
    # the fallback here is `unknown` which the sidepanel UI
    # already surfaces as "requires approval".
    "scenario.save", "scenario.delete", "scenario.promote_from_run", "scenario.promote_from_history",
    # v4.56.0: mobile.* input/camera actions (state-changing but locally reversible).
    "mobile.tap", "mobile.swipe", "mobile.type", "mobile.key", "mobile.key_combo", "mobile.scroll", "mobile.gesture", "mobile.tap_by", "mobile.paste", "mobile.camera_launch", "mobile.camera_shutter", "mobile.camera_capture", "mobile.camera_pull", "mobile.camera_record_start", "mobile.camera_record_stop", "mobile.record_start", "mobile.record_stop", "mobile.record_pull", "mobile.voice_record",
    # v4.57.0: typed HTTP client + secret metadata reads.
    "net.http", "secrets.get",
    # v4.58.0: local speech-to-text via whisper.cpp.
    "asr.transcribe", "ocr.extract", "ocr.extract_best", "image.preprocess_for_ocr",
    # v4.59.0: state-changing but reversible ops.
    "mobile.launch_app", "mobile.pull_file", "browser.launch", "browser.close",
    # v4.94.0/v4.95.0: external-MCP lifecycle / trust decisions. Adding or
    # removing a server is the trust boundary (the agent then uses its tools
    # freely); stopping a running server is reversible.
    "mcp.ext_stop", "mcp.add", "mcp.remove", "mcp_server.create", "mcp_server.install",
    # v4.96.0: authoring / revoking a capability is a trust decision (the
    # call-time risk of a custom tool is DERIVED from the tool it wraps and
    # resolved separately in classify_tool_risk via custom_tools.risk_of).
    "custom.create", "custom.remove", "code_session.write", "tool_foundry.publish", "code_project.promote_tool", "code_run.promote_tool", "runtime.install", "code_session.stop", "code_session.stop_all", "code_session.sweep", "code_project.create", "code_project.write", "code_project.remove", "code_project.deps_install", "code_project.lock",
}
_DANGEROUS_PREFIXES = ("desktop.",)
_DANGEROUS_TOOLS = {
    # v4.75.0: bare "exec" replaced with "exec.exec"
    # (the bare form was removed in v4.75.0).
    "exec.exec", "code.run", "code_session.start", "code_session.exec", "code_matrix.run", "code_project.run", "asr.bootstrap", "ocr.bootstrap", "fs.edit", "fs.edit_apply", "fs.edit_rollback", "fs.write",
    "git.commit", "mission.iterate", "mission.recover", "mission.rerun",
    "mission.run", "mission.schedule_tick", "skill.run", "subagent.spawn",
    # v4.56.0: mobile.* full-shell / IME hijack surfaces.
    "mobile.shell", "mobile.ime_set", "mobile.ime_reset",
    # v4.57.0: sudo runner.
    "sudo.run", "admin.run",
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
    # v4.96.0: an agent-authored custom tool inherits the risk of the built-in
    # tool it wraps (same idea as scenarios.runtime.derive_scenario_risk).
    # Lazy import keeps policy<->custom_tools free of a load-time cycle; the
    # recursion terminates because a custom tool may only wrap a built-in.
    if name.startswith("custom."):
        from arena.mcp.custom_tools import risk_of
        derived = risk_of(name)
        if derived:
            return derived
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
        # v4.97.0: YOLO flag so the chat extension / sidepanel can auto-run
        # without a per-call confirmation prompt while YOLO is engaged.
        "yolo": _is_yolo(),
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

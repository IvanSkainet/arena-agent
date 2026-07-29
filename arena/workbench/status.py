"""Aggregated Code Workbench status / map."""
from __future__ import annotations

from typing import Any

from arena.autonomy import posture as _posture
from arena.workbench import artifacts, projects, runtime_compat, runtimes, sessions


def _artifact_store_summary(limit: int = 10) -> dict[str, Any]:
    root = artifacts.runs_root()
    rows = []
    total_files = 0
    total_bytes = 0
    for d in sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True):
        info = artifacts.run_info(d.name)
        if not info.get("ok"):
            continue
        arts = info.get("artifacts") or []
        total_files += len(arts)
        total_bytes += sum(int(a.get("bytes") or 0) for a in arts)
        if len(rows) < limit:
            rows.append({"run_id": d.name, "created_at": info.get("created_at"), "artifact_count": len(arts), "artifacts": arts[:5]})
    return {"ok": True, "root": str(root), "recent": rows, "total_artifact_files": total_files, "total_artifact_bytes": total_bytes}


def _known_limits(runtime_status: dict[str, Any] | None = None) -> list[dict[str, str]]:
    rt = (runtime_status or {}).get("runtimes", {})
    out = [
        {"component": "node.appcontainer", "status": "blocked", "reason": "Node probes C:\\ during startup and Windows AppContainer denies lstat/open."},
        {"component": "go.appcontainer", "status": "blocked", "reason": "Go toolchain opens Windows NUL during compilation; AppContainer denies the device."},
        {"component": "browseract", "status": "blocked", "reason": "BrowserAct auth/list works, but its local CDP proxy does not expose /json/version for the remote stealth browser."},
        {"component": "cdp.windows_service", "status": "degraded", "reason": "Headless Edge/Chrome can fail from Windows scheduled-task/service session isolation."},
    ]
    rust = rt.get("rustc") or {}
    if rust.get("available") and not rust.get("linker_available", True):
        out.append({"component": "rust.windows", "status": "incomplete", "reason": rust.get("diagnosis") or "rustc installed but linker unavailable"})
    return out


def status() -> dict[str, Any]:
    posture = _posture.get_posture()
    runtime_status = runtimes.probe()
    project_status = projects.list_projects()
    session_status = sessions.list_sessions()
    artifact_status = _artifact_store_summary()
    compat_status = runtime_compat.build(runtime_status)
    limits = _known_limits(runtime_status)
    next_actions = []
    if session_status.get("count", 0):
        next_actions.append("Inspect/stop live code sessions before changing posture or restarting.")
    if any(limit["component"] == "rust.windows" for limit in limits):
        next_actions.append("Install/verify a Windows Rust linker toolchain before expecting Rust compile proofs.")
    next_actions.append("Run a Workbench smoke: code.run AppContainer Python, code_project.run, code_matrix.run, code_session start/exec/stop.")
    next_actions.append("Next roadmap step: continue runtime/sandbox compatibility hardening after Runtime Compatibility Registry.")
    return {
        "ok": True,
        "posture": posture,
        "runtimes": runtime_status,
        "runtime_compat": compat_status,
        "projects": project_status,
        "sessions": session_status,
        "artifacts": artifact_status,
        "known_limits": limits,
        "next_actions": next_actions,
        "roadmap": "docs/dynamic_harness_roadmap.md",
    }

"""Runtime compatibility registry for Code Workbench.

This is the machine-readable replacement for scattered known-limit prose: it
answers "which runtime works under which posture/sandbox, why, and what should
an agent try next?" without launching arbitrary code.
"""
from __future__ import annotations

import platform as _platform
from typing import Any

from arena.workbench import runtimes

_SANDBOXES = ("appcontainer", "systemd", "off")
_RUNTIMES = ("python3", "python", "node", "deno", "zig", "lua", "go", "wasm", "wasmtime", "rustc", "cargo", "java")


def _available(rt: dict[str, Any], name: str) -> bool:
    item = rt.get(name) or {}
    if name == "cargo" and not item.get("available"):
        return bool((rt.get("rustc") or {}).get("available"))
    return bool(item.get("available"))


def _entry(runtime: str, sandbox: str, status: str, reason: str, *, suggested_posture: dict[str, Any] | None = None,
           next_action: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"runtime": runtime, "sandbox": sandbox, "status": status, "reason": reason}
    if suggested_posture:
        out["suggested_posture"] = suggested_posture
    if next_action:
        out["next_action"] = next_action
    return out


def _host_entry(runtime: str, available: bool) -> dict[str, Any]:
    if not available:
        return _entry(runtime, "off", "missing", "Runtime binary is not visible on PATH or in Arena-managed tools.")
    return _entry(runtime, "off", "supported", "Host/off execution uses the operator-selected unfenced posture; runtime availability is enough.")


def build(runtime_status: dict[str, Any] | None = None, *, platform_name: str | None = None) -> dict[str, Any]:
    runtime_status = runtime_status or runtimes.probe()
    rt = runtime_status.get("runtimes", {}) if isinstance(runtime_status, dict) else {}
    sysname = (platform_name or _platform.system()).lower()
    rows: list[dict[str, Any]] = []

    for name in _RUNTIMES:
        avail = _available(rt, name)
        rows.append(_host_entry(name, avail))
        if sysname == "windows":
            if name in {"python", "python3"}:
                rows.append(_entry(name, "appcontainer", "supported" if avail else "missing",
                                   "Python is live-proven in Windows AppContainer with scratch write and runtime read/execute grants." if avail else "Python runtime is not visible.",
                                   next_action="Use code.run/code_project.run in the default low AppContainer posture." if avail else "Install/repair Python."))
            elif name == "node":
                rows.append(_entry(name, "appcontainer", "blocked",
                                   "Node probes C:\\ during startup and Windows AppContainer denies lstat/open.",
                                   suggested_posture={"sandbox": "off"},
                                   next_action="Use explicit host/off posture for Node until a broker/compat shim exists."))
            elif name == "deno":
                rows.append(_entry(name, "appcontainer", "degraded" if avail else "missing",
                                   "Deno stdout execution is live-proven with denied net and scratch-local DENO_DIR; Deno filesystem writes still hit AppContainer/OS error 5 and remain a hardening item." if avail else "Deno runtime is not visible; install with runtime.install runtime=deno.",
                                   next_action="Use lang=deno for stdout-oriented TypeScript/JavaScript scripts; prefer stdout artifacts until file-write semantics are hardened." if avail else "Install managed Deno with runtime.install."))
            elif name == "zig":
                rows.append(_entry(name, "appcontainer", "blocked" if avail else "missing",
                                   "Managed Zig starts inside AppContainer but fails resolving its self executable path (live proof: 'unable to find zig self exe path: Unexpected')." if avail else "Zig runtime is not visible; install with runtime.install runtime=zig.",
                                   suggested_posture={"sandbox": "off"} if avail else None,
                                   next_action="Use explicit host/off posture for Zig until a broker/path fix exists." if avail else "Install managed Zig with runtime.install."))
            elif name == "lua":
                rows.append(_entry(name, "appcontainer", "supported" if avail else "missing",
                                   "Managed Lua is a small interpreter expected to run inside AppContainer with scratch write/runtime read grants." if avail else "Lua runtime is not visible; install with runtime.install runtime=lua.",
                                   next_action="Use lang=lua for small embedded scripts; promote status after live proof." if avail else "Install managed Lua with runtime.install."))
            elif name == "go":
                rows.append(_entry(name, "appcontainer", "blocked",
                                   "Go toolchain opens Windows NUL during compilation; AppContainer denies the device.",
                                   suggested_posture={"sandbox": "off"},
                                   next_action="Use explicit host/off posture for Go builds, or wait for broker/device-policy work."))
            elif name in {"wasm", "wasmtime"}:
                rows.append(_entry(name, "appcontainer", "supported" if avail else "missing",
                                   "Wasmtime runs WASI command modules from scratch; live proof required after managed install." if avail else "Wasmtime runtime is not visible; install with runtime.install runtime=wasmtime.",
                                   next_action="Use lang=wasm with a .wasm entry for WASI command modules." if avail else "Install managed Wasmtime with runtime.install."))
            elif name in {"rustc", "cargo"}:
                rust = rt.get("rustc") or {}
                if avail and rust.get("linker_available") is False:
                    rows.append(_entry(name, "appcontainer", "incomplete",
                                       rust.get("diagnosis") or "Rust compiler is installed but no Windows linker is available.",
                                       next_action="Install/verify MSVC, MinGW, or clang linker before Rust compile proofs."))
                else:
                    rows.append(_entry(name, "appcontainer", "unknown" if avail else "missing",
                                       "Rust AppContainer compatibility is not live-proven yet." if avail else "Rust runtime is not visible."))
            else:
                rows.append(_entry(name, "appcontainer", "unknown" if avail else "missing",
                                   "No Windows AppContainer proof is recorded for this runtime." if avail else "Runtime binary is not visible."))
        else:
            rows.append(_entry(name, "systemd", "supported" if avail else "missing",
                               "systemd-run fence is the POSIX default when available; runtime still must be present." if avail else "Runtime binary is not visible."))
    # Feature-level compatibility notes that are not pure runtime binaries.
    if sysname == "windows":
        rows.append(_entry("python_project_deps", "appcontainer", "supported",
                           "Project .deps/python cache is granted read/execute recursively while writes remain scratch-only and network remains denied."))
    return {
        "ok": True,
        "platform": sysname,
        "runtime_probe": runtime_status,
        "runtimes": sorted(set(r["runtime"] for r in rows)),
        "sandboxes": list(_SANDBOXES),
        "matrix": rows,
        "known_limits": known_limits(rows),
        "next_actions": next_actions(rows),
    }


def known_limits(rows: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    rows = rows or build()["matrix"]
    out = []
    for r in rows:
        if r.get("status") in {"blocked", "incomplete"}:
            out.append({
                "component": f"{r.get('runtime')}.{r.get('sandbox')}",
                "status": str(r.get("status")),
                "reason": str(r.get("reason", "")),
            })
    return out


def next_actions(rows: list[dict[str, Any]] | None = None) -> list[str]:
    rows = rows or build()["matrix"]
    seen = []
    for r in rows:
        a = r.get("next_action")
        if a and a not in seen:
            seen.append(str(a))
    if not seen:
        seen.append("Run runtime.compat before selecting a runtime/posture for new Workbench or Foundry work.")
    return seen

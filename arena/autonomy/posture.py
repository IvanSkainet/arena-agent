"""Operator execution-posture model -- the composable "cubes".

The operator composes per-axis controls that govern how agent-authored code
(``code.run``) executes. The agent CANNOT read or write the posture: the setter
endpoint is master-token-only and the ``autonomy/`` directory is on the
sensitive-file blocklist, so the agent cannot relax its own fence (reward-hacking
via posture is closed by construction).

Current enforcement is intentionally coarse but HONEST: on Linux a fenced
posture engages a *strict, fixed* systemd-run sandbox (private network, dropped
privileges, scratch-only writes, resource caps); on Windows it engages an
AppContainer with no capabilities and explicit scratch/runtime grants. Per-axis
granularity and microVMs are later slices. ``code.run`` is **fail-closed**: if
the active posture demands a sandbox the platform cannot
engage, execution is REFUSED rather than silently running unfenced. The
``sandbox=off`` posture is the labeled extreme the operator may choose
explicitly; on Windows it equals the pre-existing exec risk surface.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

AXES = ("sandbox", "network", "privilege", "filesystem", "runtime")
SANDBOX_VALUES = ("off", "appcontainer", "systemd", "microvm")
NETWORK_VALUES = ("deny", "allowlist", "open")
PRIVILEGE_VALUES = ("drop", "as-user", "elevated")
FS_VALUES = ("scratch-only", "home-read", "home-rw", "open")
RUNTIME_VALUES = ("allowlist", "any")
DEFAULT_RUNTIMES = ("python3", "python", "node", "go", "deno", "wasm")
DEFAULT_RESOURCES = {
    "cpu_seconds": 30, "memory_mb": 256,
    "output_bytes": 100 * 1024, "wall_seconds": 60,
}

PRESETS: dict[str, dict[str, str]] = {
    "strict":       {"sandbox": "systemd", "network": "deny",
                     "privilege": "drop", "filesystem": "scratch-only",
                     "runtime": "allowlist"},
    "balanced":     {"sandbox": "systemd", "network": "deny",
                     "privilege": "drop", "filesystem": "home-read",
                     "runtime": "allowlist"},
    "fenced-yolo":  {"sandbox": "appcontainer", "network": "deny",
                     "privilege": "drop", "filesystem": "scratch-only",
                     "runtime": "allowlist"},
    "naked":        {"sandbox": "off", "network": "open",
                     "privilege": "elevated", "filesystem": "open",
                     "runtime": "any"},
}

# Risk-scaled confirmation phrases. Low/medium need none; high/critical require
# the operator to type the exact phrase (server-enforced at apply time).
ACK_PHRASES = {
    "high": "I_ACCEPT_UNFENCED_OR_ELEVATED_RISK",
    "critical": "I_ACCEPT_FULL_HOST_RISK_NO_FENCE",
}

_cache: dict[str, Any] | None = None


def store_path() -> Path:
    root = Path(os.environ.get("ARENA_AGENT_HOME",
                               str(Path.home() / "arena-bridge"))).expanduser()
    return root / "autonomy" / "posture.json"


def _blank() -> dict[str, Any]:
    return {
        "sandbox": "systemd", "network": "deny", "privilege": "drop",
        "filesystem": "scratch-only", "runtime": "allowlist",
        "runtimes": list(DEFAULT_RUNTIMES),
        "resources": dict(DEFAULT_RESOURCES),
        "preset": "strict",
    }


def load_posture() -> dict[str, Any]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        data = json.loads(store_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    _cache = {**_blank(), **{k: data[k] for k in _blank() if k in data}}
    return _cache


def _reset_cache() -> None:
    global _cache
    _cache = None


def save_posture(p: dict[str, Any]) -> None:
    global _cache
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")
    _cache = dict(p)


def validate_posture(p: Any) -> str | None:
    if not isinstance(p, dict):
        return "posture must be an object"
    checks = {
        "sandbox": SANDBOX_VALUES, "network": NETWORK_VALUES,
        "privilege": PRIVILEGE_VALUES, "filesystem": FS_VALUES,
        "runtime": RUNTIME_VALUES,
    }
    for axis, allowed in checks.items():
        if p.get(axis) not in allowed:
            return f"axis '{axis}' must be one of {allowed}, got {p.get(axis)!r}"
    rt = p.get("runtimes", list(DEFAULT_RUNTIMES))
    if not isinstance(rt, list) or not rt or not all(isinstance(x, str) for x in rt):
        return "'runtimes' must be a non-empty list of strings"
    res = p.get("resources")
    if res is None:
        res = dict(DEFAULT_RESOURCES)
    if not isinstance(res, dict):
        return "'resources' must be an object"
    merged_res = {**DEFAULT_RESOURCES, **res}
    for k in DEFAULT_RESOURCES:
        v = merged_res.get(k)
        if not isinstance(v, (int, float)) or v <= 0:
            return f"resources.{k} must be a positive number"
    return None


def risk_level(p: dict[str, Any]) -> str:
    score = 0
    if p.get("sandbox") == "off":
        score += 3
    if p.get("privilege") == "elevated":
        score += 2
    if p.get("network") == "open":
        score += 2
    if p.get("filesystem") in ("home-rw", "open"):
        score += 2 if p.get("filesystem") == "open" else 1
    if p.get("runtime") == "any":
        score += 1
    if score >= 5:
        return "critical"
    if score >= 3:
        return "high"
    if score >= 1:
        return "medium"
    return "low"


def required_ack(p: dict[str, Any]) -> str | None:
    return ACK_PHRASES.get(risk_level(p))


def set_posture(p: dict[str, Any], ack: str | None = None) -> dict[str, Any]:
    err = validate_posture(p)
    if err:
        return {"ok": False, "error": err}
    need = required_ack(p)
    if need and ack != need:
        return {"ok": False, "error": "ack_required", "required_ack": need,
                "risk": risk_level(p),
                "message": (f"this posture is risk={risk_level(p)}; re-send with "
                            f"ack set to the required phrase to confirm.")}
    merged = {**_blank(), **p}
    save_posture(merged)
    return {"ok": True, "posture": merged, "risk": risk_level(merged)}


def get_posture() -> dict[str, Any]:
    p = load_posture()
    return {"ok": True, "posture": p, "risk": risk_level(p),
            "required_ack": required_ack(p),
            "presets": PRESETS,
            "axes": {"sandbox": SANDBOX_VALUES, "network": NETWORK_VALUES,
                     "privilege": PRIVILEGE_VALUES, "filesystem": FS_VALUES,
                     "runtime": RUNTIME_VALUES},
            "ack_phrases": ACK_PHRASES}

"""Real-machine smoke matrix for the Arena ship."""
from __future__ import annotations

import json
import platform
import time
from pathlib import Path
from typing import Any

from arena.autonomy import posture as _posture
from arena.autonomy import runner as _runner
from arena.constants import VERSION
from arena.mcp_client import get_manager
from arena.mobile import preflight as mobile_preflight
from arena.workbench import artifacts, runtime_compat, runtimes
from arena.workbench.runtimes import home


def _record_root() -> Path:
    p = home() / "flight-records"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _check(name: str, ok: bool, *, severity: str = "fail", detail: Any = None) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "severity": severity, "detail": detail}


def _safe(name: str, fn):
    try:
        return fn()
    except Exception as e:  # pragma: no cover - defensive aggregation
        return {"ok": False, "component": name, "error": f"{type(e).__name__}: {e}"}


def _code_smoke() -> dict[str, Any]:
    posture = _posture.load_posture()
    lang = "python3" if "python3" in (posture.get("runtimes") or []) else "python"
    code = """
import json, os
out = {"marker": "SHIP_SMOKE_PROOF", "value": 42}
print(json.dumps(out, sort_keys=True))
os.makedirs("out", exist_ok=True)
open("out/ship-smoke.json", "w", encoding="utf-8").write(json.dumps(out, sort_keys=True))
""".strip() + "\n"
    res = _runner.run_code_sync(code, lang, posture, timeout=45, artifacts=["out/ship-smoke.json"])
    artifact_read = None
    if res.get("artifacts"):
        first = res["artifacts"][0]
        artifact_read = artifacts.read_artifact(str(res.get("run_id") or ""), str(first.get("path") or ""), max_bytes=4096)
    ok = bool(res.get("ok")) and bool(artifact_read and artifact_read.get("ok"))
    return {"ok": ok, "run": res, "artifact_read": artifact_read}


def _mcp_registry() -> dict[str, Any]:
    mgr = get_manager()
    servers = []
    for name, cfg in sorted(mgr.servers().items()):
        st = mgr.status(name)
        servers.append({"name": name, "running": bool(st.get("running")), "command": cfg.get("command"), "args": cfg.get("args", [])})
    return {"ok": True, "count": len(servers), "servers": servers}


def run() -> dict[str, Any]:
    started = time.time()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(started))
    posture_view = _posture.get_posture()
    runtime_probe = _safe("runtime.probe", runtimes.probe)
    runtime_matrix = _safe("runtime.compat", lambda: runtime_compat.build(runtime_probe if isinstance(runtime_probe, dict) else None))
    mobile = _safe("mobile.preflight", mobile_preflight.preflight)
    code = _safe("code.run", _code_smoke)
    mcp = _safe("mcp.registry", _mcp_registry)
    ship_status = _safe("ship.status", lambda: __import__("arena.ship.status", fromlist=["status"]).status())
    ship_preflight = _safe("ship.preflight", lambda: __import__("arena.ship.status", fromlist=["preflight"]).preflight())
    linux_flight = None
    if platform.system().lower() == "linux":
        linux_flight = _safe("ship.linux_flight_check", lambda: __import__("arena.ship.linux_flight", fromlist=["status"]).status())

    checks = [
        _check("bridge.version", True, detail=VERSION),
        _check("posture.not_critical", posture_view.get("risk") != "critical", detail=posture_view.get("risk")),
        _check("code.fixed_fenced_run", bool(isinstance(code, dict) and code.get("ok")), detail=(code or {}).get("run", {}).get("sandbox_action") if isinstance(code, dict) else None),
        _check("code.artifact_read", bool(isinstance(code, dict) and (code.get("artifact_read") or {}).get("ok")), detail=(code.get("artifact_read") or {}).get("path") if isinstance(code, dict) else None),
        _check("runtime.compat", bool(isinstance(runtime_matrix, dict) and runtime_matrix.get("ok")), severity="warn"),
        _check("mobile.preflight", bool(isinstance(mobile, dict) and mobile.get("ok")), severity="warn", detail=(mobile or {}).get("mode") if isinstance(mobile, dict) else None),
        _check("mcp.registry", bool(isinstance(mcp, dict) and mcp.get("ok")), severity="warn", detail=(mcp or {}).get("count") if isinstance(mcp, dict) else None),
        _check("ship.status", bool(isinstance(ship_status, dict) and ship_status.get("ok")), severity="warn"),
        _check("ship.preflight", bool(isinstance(ship_preflight, dict) and ship_preflight.get("ok")), severity="warn", detail=(ship_preflight or {}).get("mode") if isinstance(ship_preflight, dict) else None),
    ]
    if linux_flight is not None:
        checks.append(_check("ship.linux_flight_check", bool(isinstance(linux_flight, dict) and linux_flight.get("ok")), severity="warn", detail=(linux_flight or {}).get("mode") if isinstance(linux_flight, dict) else None))

    failed = [c for c in checks if not c["ok"] and c["severity"] == "fail"]
    warnings = [c for c in checks if not c["ok"] and c["severity"] == "warn"]
    mode = "blocked" if failed else ("degraded" if warnings else "nominal")
    report = {
        "ok": not failed,
        "mode": mode,
        "version": VERSION,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_ms": int((time.time() - started) * 1000),
        "host": {"platform": platform.platform(), "hostname": platform.node(), "python": platform.python_version()},
        "posture": posture_view,
        "checks": checks,
        "failed": failed,
        "warnings": warnings,
        "proofs": {
            "code": code,
            "runtime_compat": runtime_matrix,
            "mobile_preflight": mobile,
            "mcp_registry": mcp,
            "ship_status": ship_status,
            "ship_preflight": ship_preflight,
            "linux_flight": linux_flight,
        },
    }
    path = _record_root() / f"{stamp}-ship-smoke.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    report["report_path"] = str(path)
    return report


def history(limit: int = 20) -> dict[str, Any]:
    rows = []
    for p in sorted(_record_root().glob("*-ship-smoke.json"), key=lambda x: x.stat().st_mtime, reverse=True)[: max(1, min(int(limit), 100))]:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        rows.append({"path": str(p), "ok": data.get("ok"), "mode": data.get("mode"), "version": data.get("version"), "started_at": data.get("started_at"), "failed": data.get("failed", []), "warnings": data.get("warnings", [])})
    return {"ok": True, "count": len(rows), "records": rows}


__all__ = ["run", "history"]

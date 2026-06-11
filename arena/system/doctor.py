"""System diagnostic checks for /v1/doctor."""
from __future__ import annotations

import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable


def check_internet(timeout: int = 3) -> bool:
    try:
        urllib.request.urlopen("https://www.google.com", timeout=timeout)
        return True
    except Exception:
        return False


def run_doctor(
    *,
    version: str,
    token: str,
    bridge_dir: Path,
    memory_dir: Path,
    missions_dir: Path,
    facts_count_fn: Callable[[], int],
    internet_check_fn: Callable[[], bool] = check_internet,
    home_dir: Path | None = None,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    checks.append({"name": "Bridge running", "ok": True, "detail": f"v{version}"})
    checks.append({"name": "Token", "ok": bool(token), "detail": f"{len(token)} chars" if token else "missing"})
    checks.append({"name": "Python", "ok": True, "detail": sys.version.split()[0]})
    for name, path in [("Bridge dir", bridge_dir), ("Memory dir", memory_dir), ("Missions dir", missions_dir)]:
        checks.append({"name": name, "ok": path.exists(), "detail": str(path)})

    try:
        fact_count = facts_count_fn()
    except Exception:
        fact_count = 0
    checks.append({"name": "Memory facts", "ok": True, "detail": f"{fact_count} entries", "status": "ok" if fact_count else "empty", "critical": False})

    internet_ok = internet_check_fn()
    checks.append({"name": "Internet", "ok": internet_ok, "detail": "available" if internet_ok else "not reachable"})

    if sys.platform == "win32":
        try:
            import winsound  # noqa: F401
            checks.append({"name": "Sound", "ok": True, "detail": "winsound available", "critical": False})
        except ImportError:
            checks.append({"name": "Sound", "ok": False, "detail": "winsound not available", "critical": False})
    else:
        sound_ok = bool(shutil.which("beep") or shutil.which("paplay"))
        checks.append({"name": "Sound", "ok": sound_ok, "detail": "beep/paplay available" if sound_ok else "no sound device", "critical": False})

    try:
        disk = shutil.disk_usage(str(home_dir or Path.home()))
        usage_pct = round(disk.used / disk.total * 100, 1) if disk.total > 0 else 0
        disk_ok = usage_pct < 80
        checks.append({"name": "Disk free", "ok": disk_ok, "detail": f"{disk.free // (1024**3)} GB free ({usage_pct}% used)"})
    except Exception:
        pass

    passed = sum(1 for check in checks if check["ok"] or not check.get("critical", True))
    return {"ok": True, "passed": passed, "total": len(checks), "checks": checks}

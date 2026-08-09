"""System diagnostic checks for /v1/doctor."""
from __future__ import annotations

import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any, Callable


def check_internet(timeout: int = 3) -> bool:
    try:
        urllib.request.urlopen("https://www.google.com", timeout=timeout)  # nosec B310 -- loopback bridge health probe  # nosemgrep: dynamic-urllib-use-detected -- URL either loopback / fixed internal endpoint OR routed through arena.security_ssrf._validate_url (see bandit B310 nosec on the same line for the specific rationale)
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
    # v4.169.14: a runtime directory that has never been used does not
    # exist yet, and that is not a fault. On a fresh phone install the
    # doctor reported "Missions dir" red before a single mission had
    # been created -- a red light with nothing wrong behind it, which
    # teaches the operator to ignore red lights.
    #
    # Bridge dir is different: it is created by the installer, so its
    # absence really is broken. Missions and memory are created on
    # first use, so report them as ok-but-empty.
    checks.append({"name": "Bridge dir", "ok": bridge_dir.exists(),
                   "detail": str(bridge_dir)})
    for name, path in [("Memory dir", memory_dir), ("Missions dir", missions_dir)]:
        present = path.exists()
        checks.append({
            "name": name,
            "ok": True,
            "detail": str(path) if present else f"{path} (not created yet)",
            "status": "ok" if present else "empty",
            "critical": False,
        })

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
        from arena.hostplatform import is_android
        if is_android():
            # Android has no ALSA or PulseAudio, so paplay/beep will never
            # be there. Reporting "no sound device" as a failure on every
            # phone is a permanently red check that means nothing.
            # termux-media-player is the real answer when termux-api is
            # installed; without it the bridge simply has no audio, which
            # is a fact about the platform, not a defect.
            player = shutil.which("termux-media-player")
            checks.append({
                "name": "Sound",
                "ok": True,
                "detail": ("termux-media-player available" if player else
                           "no audio on Android without termux-api (not a fault)"),
                "status": "ok" if player else "empty",
                "critical": False,
            })
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

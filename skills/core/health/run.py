#!/usr/bin/env python3
"""core/health — fast platform health check."""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME",
                           str(Path.home() / "arena-bridge"))).expanduser()

results: list[tuple[bool, str, str, bool]] = []  # (ok, name, detail, critical)


def add(ok: bool, name: str, detail: str = "", *, critical: bool = True) -> None:
    results.append((ok, name, detail, critical))


def check_http() -> None:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=3) as r:
            add(r.status == 200, "bridge_http", f"HTTP {r.status}")
    except Exception as e:
        add(False, "bridge_http", f"{type(e).__name__}: {e}")


def check_service(name: str) -> None:
    # Strip .service suffix if provided — systemctl adds it automatically
    clean_name = name.replace(".service", "")
    cp = subprocess.run(["systemctl", "--user", "is-active", clean_name],
                        capture_output=True, text=True)
    state = cp.stdout.strip()
    # Accept "active" or "activating" as healthy states
    add(state in ("active", "activating"), f"svc_{clean_name}", state)


def check_agentctl(p: Path) -> None:
    if not p.exists():
        # agentctl is optional/legacy — not a critical failure
        add(False, "agentctl_exists", "missing", critical=False)
        return
    cp = subprocess.run([sys.executable, "-m", "py_compile", str(p)], capture_output=True, text=True)
    add(cp.returncode == 0, "agentctl_syntax",
        cp.stderr.strip() or "ok")


def check_python3() -> None:
    """Check that system python3 is available."""
    py = shutil.which("python3")
    if not py:
        add(False, "python3", "not found")
        return
    cp = subprocess.run([py, "-c",
                         "import sys; print(sys.version.split()[0])"],
                        capture_output=True, text=True)
    add(cp.returncode == 0, "python3", cp.stdout.strip() or "fail")


def check_dirs() -> None:
    # Core directories that must exist
    for d in ["memory", "skills"]:
        p = ROOT / d
        add(p.is_dir(), f"{d}_dir", str(p))
    facts = ROOT / "memory" / "facts.jsonl"
    add(facts.exists(), "facts_jsonl",
        f"{facts.stat().st_size} bytes" if facts.exists() else "missing")
    # Audit log can be at root or in logs/
    audit = ROOT / "audit.jsonl"
    if not audit.exists():
        audit = ROOT / "logs" / "audit.jsonl"
    add(audit.exists() and os.access(audit, os.R_OK),
        "audit_readable", str(audit))


def check_disk() -> None:
    usage = shutil.disk_usage(str(Path.home()))
    free_mb = usage.free // (1024 * 1024)
    ok = free_mb >= 100
    detail = f"{free_mb} MB free"
    if free_mb < 1024 and ok:
        detail += " (warn: <1GB)"
    add(ok, "disk_free", detail)


def main() -> int:
    check_http()
    check_service("arena-bridge.service")
    check_agentctl(ROOT / "bin" / "agentctl")
    check_python3()
    check_dirs()
    check_disk()

    width = max(len(name) for _, name, _, _ in results)
    fails = 0
    critical_fails = 0
    for ok, name, detail, critical in results:
        tag = "OK  " if ok else "FAIL"
        if not ok:
            fails += 1
            if critical:
                critical_fails += 1
                tag = "CRIT"
        print(f"{tag}  {name.ljust(width)}  {detail}")
    print(f"--- {len(results) - fails}/{len(results)} checks passed, {critical_fails} critical ---")
    return 0 if critical_fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

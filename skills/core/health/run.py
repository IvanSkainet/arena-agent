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

results: list[tuple[bool, str, str]] = []


def add(ok: bool, name: str, detail: str = "") -> None:
    results.append((ok, name, detail))


def check_http() -> None:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=3) as r:
            add(r.status == 200, "bridge_http", f"HTTP {r.status}")
    except Exception as e:
        add(False, "bridge_http", f"{type(e).__name__}: {e}")


def check_service(name: str) -> None:
    cp = subprocess.run(["systemctl", "--user", "is-active", name],
                        capture_output=True, text=True)
    state = cp.stdout.strip()
    add(state == "active", f"svc_{name.replace('.service','')}", state)


def check_agentctl(p: Path) -> None:
    if not p.exists():
        add(False, "agentctl_exists", "missing")
        return
    cp = subprocess.run([sys.executable, "-m", "py_compile", str(p)], capture_output=True, text=True)
    add(cp.returncode == 0, "agentctl_syntax",
        cp.stderr.strip() or "ok")


def check_venv() -> None:
    py = ROOT / ".venv" / "bin" / "python"
    if not py.exists():
        add(False, "venv_python", "missing")
        return
    cp = subprocess.run([str(py), "-c",
                         "import sys; print(sys.version.split()[0])"],
                        capture_output=True, text=True)
    add(cp.returncode == 0, "venv_python", cp.stdout.strip() or "fail")


def check_dirs() -> None:
    sd = ROOT / "memory" / "sessions"
    add(sd.is_dir(), "sessions_dir", str(sd))
    if sd.is_dir():
        mode = oct(sd.stat().st_mode & 0o777)
        add(mode == "0o700", "sessions_perms", mode)
    facts = ROOT / "memory" / "facts.jsonl"
    add(facts.exists(), "facts_jsonl",
        f"{facts.stat().st_size} bytes" if facts.exists() else "missing")
    audit = Path.home() / "arena-bridge" / "audit.jsonl"
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
    check_service("arena-task-runner.service")
    check_agentctl(ROOT / "bin" / "agentctl")
    check_venv()
    check_dirs()
    check_disk()

    width = max(len(name) for _, name, _ in results)
    fails = 0
    for ok, name, detail in results:
        tag = "OK  " if ok else "FAIL"
        if not ok:
            fails += 1
        print(f"{tag}  {name.ljust(width)}  {detail}")
    print(f"--- {len(results) - fails}/{len(results)} checks passed ---")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

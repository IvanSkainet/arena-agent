#!/usr/bin/env python3
"""Cross-platform readiness check для Arena Agent.

Цель: одной командой увидеть, что есть/чего нет на ЛЮБОЙ OS, и какая команда
установит сервисы для текущей платформы.

Поддерживаемые цели:
  - Linux   (systemd user services + ydotool/wtype для GUI)
  - Windows (Task Scheduler + PowerShell + AutoHotkey/NirCmd для GUI)
  - macOS   (launchd plist + AppleScript/cliclick для GUI)

Запуск:  python3 cross_platform_check.py
"""
from __future__ import annotations
import json, os, platform, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-agent"))).expanduser()


def has(c: str) -> bool:
    return shutil.which(c) is not None


def cmd(c: str, t: int = 5) -> str:
    try:
        return subprocess.run(c, shell=True, text=True, capture_output=True, timeout=t).stdout.strip()
    except Exception as e:
        return f"<err: {type(e).__name__}>"


def detect_os() -> str:
    s = platform.system().lower()
    if s == "linux":   return "linux"
    if s == "darwin":  return "macos"
    if s.startswith("win") or s == "windows": return "windows"
    return "unknown"


def linux_check() -> dict:
    return {
        "init": "systemd" if has("systemctl") else ("runit" if has("sv") else "unknown"),
        "systemd_user": cmd("systemctl --user is-system-running") or "n/a",
        "gui_input":  {k: has(k) for k in ["ydotool", "ydotoold", "wtype", "xdotool"]},
        "screenshot": {k: has(k) for k in ["spectacle", "grim", "gnome-screenshot", "flameshot", "maim", "scrot"]},
        "display_server": os.environ.get("XDG_SESSION_TYPE", "?"),
        "wayland": bool(os.environ.get("WAYLAND_DISPLAY")),
        "x11":     bool(os.environ.get("DISPLAY")),
    }


def windows_check() -> dict:
    import subprocess
    
    # 1. Get Physical vs Logical Cores
    physical_cores = None
    try:
        res = subprocess.run("wmic cpu get NumberOfCores", capture_output=True, text=True, shell=True)
        lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
        if len(lines) > 1:
            physical_cores = int(lines[1])
    except:
        pass
        
    # 2. Get GPU Name
    gpu_name = None
    try:
        res = subprocess.run("wmic path win32_VideoController get name", capture_output=True, text=True, shell=True)
        lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
        if len(lines) > 1:
            gpu_name = lines[1]
    except:
        pass
        
    # 3. Get Total RAM
    total_ram_gb = None
    try:
        res = subprocess.run("wmic computersystem get TotalPhysicalMemory", capture_output=True, text=True, shell=True)
        lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
        if len(lines) > 1:
            total_ram_gb = round(int(lines[1]) / (1024**3), 2)
    except:
        pass
        
    # 4. Get Disk Drives Free Space
    disk_drives = {}
    try:
        res = subprocess.run("wmic logicaldisk get caption, freespace, size", capture_output=True, text=True, shell=True)
        for line in res.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) == 3 and parts[0].endswith(':'):
                caption = parts[0]
                try:
                    free = int(parts[1])
                    size = int(parts[2])
                    disk_drives[caption] = {
                        "free_gb": round(free / (1024**3), 2),
                        "total_gb": round(size / (1024**3), 2)
                    }
                except:
                    pass
    except:
        pass

    return {
        "init": "task-scheduler",
        "powershell": has("powershell") or has("pwsh"),
        "gui_input":  {"autohotkey": has("AutoHotkey") or has("autohotkey"), "nircmd": has("nircmd")},
        "hardware": {
            "physical_cores": physical_cores,
            "logical_processors": os.cpu_count(),
            "gpu_name": gpu_name,
            "total_ram_gb": total_ram_gb,
            "disk_drives": disk_drives
        },
        "screenshot_note": "use PowerShell System.Drawing or NirCmd savescreenshot",
    }


def macos_check() -> dict:
    return {
        "init": "launchd",
        "osascript":     has("osascript"),
        "screencapture": has("screencapture"),
        "cliclick":      has("cliclick"),
    }


def main() -> int:
    o = detect_os()
    checks = {
        "platform": (f"Windows 11 (Build {platform.version().split('.')[-1]})" if platform.system() == "Windows" and int(platform.version().split('.')[-1]) >= 22000 else f"Windows 10 (Build {platform.version().split('.')[-1]})" if platform.system() == "Windows" else platform.platform()),
        "os_major": ("Windows 11" if platform.system() == "Windows" and int(platform.version().split('.')[-1]) >= 22000 else "Windows 10" if platform.system() == "Windows" else platform.system()),
        "os": o,
        "python": sys.version.split()[0],
        "paths": {"home": str(Path.home()), "agent_root": str(ROOT), "exists": ROOT.exists()},
        "core_commands": {c: has(c) for c in ["python3", "python", "node", "npm", "git", "curl", "wget", "tailscale"]},
        "arena_files": {
            "agentctl":        (ROOT / "bin/agentctl").exists() if ROOT.exists() else False,
            "sd-exec":         (ROOT / "bin/sd-exec").exists() if ROOT.exists() else False,
            "py_browser":      (ROOT / "bin/py_browser.py").exists() if ROOT.exists() else False,
            "bridge":          (Path.home() / "arena-local-bridge/local_bridge.py").exists(),
            "mcp_stream":      (ROOT / "scripts/mcp_stream_server.py").exists() if ROOT.exists() else False,
            "mcp_ws":          (ROOT / "scripts/mcp_ws_server.py").exists() if ROOT.exists() else False,
            "win_installer":   (ROOT / "scripts/install_windows_service.ps1").exists() if ROOT.exists() else False,
            "macos_installer": (ROOT / "scripts/install_macos_service.sh").exists() if ROOT.exists() else False,
            "linux_installer": (ROOT / "scripts/install_linux_service.sh").exists() if ROOT.exists() else False,
        },
    }
    if o == "linux":   checks["linux"]   = linux_check()
    if o == "windows": checks["windows"] = windows_check()
    if o == "macos":   checks["macos"]   = macos_check()

    install_map = {
        "linux":   str(ROOT / "scripts/install_linux_service.sh"),
        "windows": str(ROOT / "scripts/install_windows_service.ps1"),
        "macos":   str(ROOT / "scripts/install_macos_service.sh"),
    }
    ready = {
        "bridge_can_run":     has("python3") or has("python"),
        "mcp_can_run":        has("python3"),
        "curl_available":     has("curl"),
        "install_for_this_os": install_map.get(o),
    }
    print(json.dumps({"ok": True, "checks": checks, "ready": ready}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

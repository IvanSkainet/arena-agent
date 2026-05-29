#!/usr/bin/env python3
"""
inventory.py — Comprehensive cross-platform system inventory.

Cross-platform replacement for inventory.sh. Works on Windows / Linux / macOS / FreeBSD.

Output:
    Default: human-readable text report (like old inventory.sh)
    --json:  full JSON dump
    --section <name>: only one section (identity/os/cpu/memory/gpu/disks/network/
                                       runtimes/package_managers/browsers/displays/
                                       env/services/python_env)
    --quiet: don't print to stdout (use with --output)
    --output FILE: write to file

Usage:
    inventory.py
    inventory.py --json > inventory.json
    inventory.py --section runtimes
"""
from __future__ import annotations
import os
import sys
import json
import re
import shutil
import socket
import platform
import argparse
import subprocess
import getpass
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional


# ============================================================
# Helpers
# ============================================================

def _run(cmd: list[str], timeout: float = 5.0, capture_stderr: bool = False) -> str:
    """Run a command, return stdout (str) or empty string on failure."""
    try:
        kwargs: dict = {
            "capture_output": True,
            "text": True,
            "timeout": timeout,
        }
        if platform.system() == "Windows":
            # Hide console window
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        r = subprocess.run(cmd, **kwargs)
        out = r.stdout or ""
        if capture_stderr and r.stderr:
            out += r.stderr
        return out
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return ""


def _which(name: str) -> Optional[str]:
    return shutil.which(name)


def _ver(cmd_name: str, version_arg: str = "--version", timeout: float = 3.0) -> Optional[str]:
    """Get first line of `cmd --version` output if the command exists."""
    path = _which(cmd_name)
    if not path:
        return None
    out = _run([path, version_arg], timeout=timeout)
    if not out:
        # Some tools (e.g. node, java) only respond to -v or --version on stderr
        out = _run([path, version_arg], timeout=timeout, capture_stderr=True)
    line = out.strip().splitlines()[0] if out.strip() else ""
    return line or path  # at least confirm presence


def _parse_wmic_list(text: str) -> list[dict]:
    """Parse 'wmic ... /format:list' output (Win text-mode produces \\n\\n separators)."""
    text = text.replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "")
    blocks: list[dict] = []
    current: dict = {}
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k in current:
            blocks.append(current)
            current = {}
        current[k] = v
    if current:
        blocks.append(current)
    return blocks


# ============================================================
# Section: identity
# ============================================================

def get_identity() -> dict:
    return {
        "user": getpass.getuser(),
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "cwd": str(Path.cwd()),
        "home": str(Path.home()),
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "gid": os.getgid() if hasattr(os, "getgid") else None,
        "tty": os.environ.get("TERM_PROGRAM") or os.environ.get("TERM") or "",
        "shell": os.environ.get("SHELL") or os.environ.get("COMSPEC") or "",
    }


# ============================================================
# Section: os
# ============================================================

def get_os() -> dict:
    sys_name = platform.system()
    info: dict[str, Any] = {
        "system": sys_name,
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform_string": platform.platform(),
    }
    if sys_name == "Linux":
        # /etc/os-release
        try:
            os_rel = {}
            with open("/etc/os-release") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        os_rel[k] = v.strip('"')
            info["distro"] = {
                "name": os_rel.get("NAME") or os_rel.get("ID"),
                "id": os_rel.get("ID"),
                "version": os_rel.get("VERSION") or os_rel.get("VERSION_ID"),
                "pretty": os_rel.get("PRETTY_NAME"),
                "codename": os_rel.get("VERSION_CODENAME"),
            }
        except Exception:
            pass
        # Kernel build
        info["kernel"] = _run(["uname", "-srvmo"]).strip()
        # Uptime
        try:
            with open("/proc/uptime") as f:
                up = float(f.read().split()[0])
            info["uptime_seconds"] = int(up)
        except Exception:
            pass
    elif sys_name == "Darwin":
        info["product_name"] = _run(["sw_vers", "-productName"]).strip()
        info["product_version"] = _run(["sw_vers", "-productVersion"]).strip()
        info["build_version"] = _run(["sw_vers", "-buildVersion"]).strip()
    elif sys_name == "Windows":
        # win32_operatingsystem for build/caption
        out = _run(["wmic", "os", "get",
                    "Caption,Version,BuildNumber,OSArchitecture,InstallDate,LastBootUpTime",
                    "/format:list"])
        blocks = _parse_wmic_list(out)
        if blocks:
            d = blocks[0]
            info["caption"] = d.get("Caption", "")
            info["build_number"] = d.get("BuildNumber", "")
            info["architecture"] = d.get("OSArchitecture", "")
            # 20210513120000.000000+000 → 2021-05-13 12:00:00 UTC+0
            for key, src in [("install_date", "InstallDate"), ("last_boot", "LastBootUpTime")]:
                v = d.get(src, "")
                if len(v) >= 14:
                    info[key] = f"{v[0:4]}-{v[4:6]}-{v[6:8]} {v[8:10]}:{v[10:12]}:{v[12:14]}"
    return info


# ============================================================
# Section: cpu
# ============================================================

def get_cpu() -> dict:
    sys_name = platform.system()
    info: dict[str, Any] = {
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cores_logical": os.cpu_count() or 0,
        "cores_physical": None,
        "name": None,
        "max_ghz": None,
        "load_avg": None,
    }
    if hasattr(os, "getloadavg"):
        try:
            info["load_avg"] = list(os.getloadavg())
        except Exception:
            pass

    if sys_name == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                cpuinfo = f.read()
            m = re.search(r"model name\s*:\s*(.+)", cpuinfo)
            if m:
                info["name"] = m.group(1).strip()
            cores = set(re.findall(r"core id\s*:\s*(\d+)", cpuinfo))
            phys = set(re.findall(r"physical id\s*:\s*(\d+)", cpuinfo))
            info["cores_physical"] = len(cores) * max(1, len(phys)) if cores else None
            mh = re.search(r"cpu MHz\s*:\s*([\d.]+)", cpuinfo)
            if mh:
                info["current_ghz"] = round(float(mh.group(1)) / 1000.0, 2)
        except Exception:
            pass
        # /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq is in kHz
        try:
            with open("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq") as f:
                khz = int(f.read().strip())
            info["max_ghz"] = round(khz / 1_000_000.0, 2)
        except Exception:
            pass
    elif sys_name == "Darwin":
        info["name"] = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        try:
            info["cores_physical"] = int(_run(["sysctl", "-n", "hw.physicalcpu"]).strip() or "0")
        except Exception:
            pass
        try:
            hz = int(_run(["sysctl", "-n", "hw.cpufrequency_max"]).strip() or "0")
            if hz:
                info["max_ghz"] = round(hz / 1e9, 2)
        except Exception:
            pass
    elif sys_name == "Windows":
        out = _run(["wmic", "cpu", "get",
                    "Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,Manufacturer",
                    "/format:list"])
        blocks = _parse_wmic_list(out)
        if blocks:
            d = blocks[0]
            info["name"] = d.get("Name", "").strip()
            info["manufacturer"] = d.get("Manufacturer", "").strip()
            try:
                info["cores_physical"] = int(d.get("NumberOfCores", "0"))
            except Exception:
                pass
            try:
                mh = int(d.get("MaxClockSpeed", "0"))
                if mh:
                    info["max_ghz"] = round(mh / 1000.0, 2)
            except Exception:
                pass
    return info


# ============================================================
# Section: memory
# ============================================================

def get_memory() -> dict:
    sys_name = platform.system()
    info: dict[str, Any] = {
        "total_gb": None,
        "available_gb": None,
        "used_gb": None,
        "modules": [],
    }
    if sys_name == "Linux":
        try:
            mem: dict[str, int] = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    if ":" in line:
                        k, rest = line.split(":", 1)
                        m = re.search(r"(\d+)", rest)
                        if m:
                            mem[k.strip()] = int(m.group(1))
            total_kb = mem.get("MemTotal", 0)
            avail_kb = mem.get("MemAvailable", 0)
            info["total_gb"] = round(total_kb / 1024 / 1024, 2)
            info["available_gb"] = round(avail_kb / 1024 / 1024, 2)
            info["used_gb"] = round((total_kb - avail_kb) / 1024 / 1024, 2)
            info["swap_total_gb"] = round(mem.get("SwapTotal", 0) / 1024 / 1024, 2)
            info["swap_free_gb"] = round(mem.get("SwapFree", 0) / 1024 / 1024, 2)
        except Exception:
            pass
        # dmidecode requires root, skip if no sudo
        dmi = _run(["dmidecode", "-t", "memory"], timeout=3)
        if dmi:
            for block in re.split(r"\n\s*Memory Device\s*\n", dmi):
                size_m = re.search(r"Size:\s*(\d+)\s*(GB|MB)", block)
                if not size_m:
                    continue
                size = int(size_m.group(1))
                unit = size_m.group(2)
                size_gb = float(size) if unit == "GB" else round(size / 1024.0, 1)
                if size_gb == 0:
                    continue
                speed = re.search(r"Speed:\s*(\d+)\s*MT/s", block)
                mfg = re.search(r"Manufacturer:\s*(\S.*)", block)
                pn = re.search(r"Part Number:\s*(\S.*)", block)
                info["modules"].append({
                    "size_gb": size_gb,
                    "speed_mhz": int(speed.group(1)) if speed else 0,
                    "manufacturer": mfg.group(1).strip() if mfg else "",
                    "part_number": pn.group(1).strip() if pn else "",
                })
    elif sys_name == "Darwin":
        try:
            total = int(_run(["sysctl", "-n", "hw.memsize"]).strip() or "0")
            info["total_gb"] = round(total / (1024**3), 2)
        except Exception:
            pass
    elif sys_name == "Windows":
        # totals
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_uint64),
                            ("ullAvailPhys", ctypes.c_uint64),
                            ("ullTotalPageFile", ctypes.c_uint64),
                            ("ullAvailPageFile", ctypes.c_uint64),
                            ("ullTotalVirtual", ctypes.c_uint64),
                            ("ullAvailVirtual", ctypes.c_uint64),
                            ("ullAvailExtendedVirtual", ctypes.c_uint64)]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            info["total_gb"] = round(stat.ullTotalPhys / (1024**3), 2)
            info["available_gb"] = round(stat.ullAvailPhys / (1024**3), 2)
            info["used_gb"] = round((stat.ullTotalPhys - stat.ullAvailPhys) / (1024**3), 2)
            info["load_percent"] = stat.dwMemoryLoad
        except Exception:
            pass
        # modules via wmic
        out = _run(["wmic", "memorychip", "get",
                    "Capacity,Speed,Manufacturer,PartNumber,DeviceLocator,ConfiguredClockSpeed",
                    "/format:list"])
        for d in _parse_wmic_list(out):
            cap = d.get("Capacity", "")
            try:
                cap_gb = round(int(cap) / (1024**3), 1)
            except Exception:
                continue
            info["modules"].append({
                "size_gb": cap_gb,
                "speed_mhz": int(d.get("Speed", "0") or 0),
                "configured_mhz": int(d.get("ConfiguredClockSpeed", "0") or 0),
                "manufacturer": d.get("Manufacturer", "").strip(),
                "part_number": d.get("PartNumber", "").strip(),
                "slot": d.get("DeviceLocator", "").strip(),
            })
    return info


# ============================================================
# Section: gpu
# ============================================================

def get_gpu() -> dict:
    sys_name = platform.system()
    info: dict[str, Any] = {"gpus": [], "nvidia": None}
    if sys_name == "Linux":
        lspci = _run(["lspci"])
        for line in lspci.splitlines():
            if re.search(r"VGA compatible controller|3D controller|Display controller", line, re.I):
                m = re.search(r":\s*(.+)", line)
                if m:
                    info["gpus"].append({"name": m.group(1).strip(), "vram_mb": 0})
    elif sys_name == "Darwin":
        out = _run(["system_profiler", "SPDisplaysDataType"], timeout=10)
        # Very rough parse
        for line in out.splitlines():
            m = re.match(r"\s+Chipset Model:\s*(.+)", line)
            if m:
                info["gpus"].append({"name": m.group(1).strip(), "vram_mb": 0})
            mv = re.match(r"\s+VRAM \(.*\):\s*(\d+)\s*(GB|MB)", line)
            if mv and info["gpus"]:
                size = int(mv.group(1))
                unit = mv.group(2)
                info["gpus"][-1]["vram_mb"] = size * 1024 if unit == "GB" else size
    elif sys_name == "Windows":
        out = _run(["wmic", "path", "win32_VideoController", "get",
                    "Name,AdapterRAM,DriverVersion,VideoProcessor", "/format:list"])
        for d in _parse_wmic_list(out):
            if not d.get("Name"):
                continue
            try:
                vram_mb = int(d.get("AdapterRAM", "0")) // (1024 * 1024)
            except Exception:
                vram_mb = 0
            info["gpus"].append({
                "name": d["Name"],
                "vram_mb": vram_mb,
                "driver_version": d.get("DriverVersion", ""),
                "video_processor": d.get("VideoProcessor", ""),
            })

    # NVIDIA-SMI works on all 3 OSes if installed
    if _which("nvidia-smi"):
        out = _run(["nvidia-smi",
                    "--query-gpu=name,driver_version,memory.total,memory.used,memory.free,temperature.gpu,utilization.gpu",
                    "--format=csv,noheader,nounits"], timeout=5)
        cards = []
        for line in out.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 7:
                continue
            cards.append({
                "name": parts[0],
                "driver": parts[1],
                "vram_total_mb": int(parts[2] or 0),
                "vram_used_mb": int(parts[3] or 0),
                "vram_free_mb": int(parts[4] or 0),
                "temperature_c": int(parts[5] or 0),
                "utilization_pct": int(parts[6] or 0),
            })
        if cards:
            info["nvidia"] = cards

    return info


# ============================================================
# Section: motherboard / bios (Windows + Linux dmidecode)
# ============================================================

def get_motherboard() -> dict:
    sys_name = platform.system()
    info: dict[str, Any] = {"motherboard": None, "bios": None}
    if sys_name == "Windows":
        out = _run(["wmic", "baseboard", "get",
                    "Manufacturer,Product,Version,SerialNumber", "/format:list"])
        blocks = _parse_wmic_list(out)
        if blocks:
            d = blocks[0]
            info["motherboard"] = {
                "manufacturer": d.get("Manufacturer", "").strip(),
                "product": d.get("Product", "").strip(),
                "version": d.get("Version", "").strip(),
                "serial": d.get("SerialNumber", "").strip(),
            }
        out2 = _run(["wmic", "bios", "get",
                     "Manufacturer,SMBIOSBIOSVersion,ReleaseDate", "/format:list"])
        bblocks = _parse_wmic_list(out2)
        if bblocks:
            d = bblocks[0]
            rd = d.get("ReleaseDate", "")
            if len(rd) >= 8:
                rd = f"{rd[0:4]}-{rd[4:6]}-{rd[6:8]}"
            info["bios"] = {
                "manufacturer": d.get("Manufacturer", "").strip(),
                "version": d.get("SMBIOSBIOSVersion", "").strip(),
                "release_date": rd,
            }
    elif sys_name == "Linux":
        # dmidecode requires root, but try sysfs
        try:
            base = Path("/sys/class/dmi/id")
            if base.exists():
                def _read(p: Path) -> str:
                    try:
                        return p.read_text().strip()
                    except Exception:
                        return ""
                info["motherboard"] = {
                    "manufacturer": _read(base / "board_vendor"),
                    "product": _read(base / "board_name"),
                    "version": _read(base / "board_version"),
                    "serial": _read(base / "board_serial"),
                }
                info["bios"] = {
                    "manufacturer": _read(base / "bios_vendor"),
                    "version": _read(base / "bios_version"),
                    "release_date": _read(base / "bios_date"),
                }
        except Exception:
            pass
    elif sys_name == "Darwin":
        info["motherboard"] = {
            "manufacturer": "Apple",
            "product": _run(["sysctl", "-n", "hw.model"]).strip(),
        }
    return info


# ============================================================
# Section: disks
# ============================================================

def get_disks() -> list[dict]:
    sys_name = platform.system()
    disks: list[dict] = []
    if sys_name == "Linux":
        out = _run(["df", "-B1", "--output=source,target,fstype,size,used,avail"], timeout=5)
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 6 and parts[0].startswith("/"):
                try:
                    size = int(parts[3])
                    used = int(parts[4])
                    avail = int(parts[5])
                    if size < 1024**3:  # < 1 GB → skip tmpfs
                        continue
                    disks.append({
                        "device": parts[0],
                        "mount": parts[1],
                        "filesystem": parts[2],
                        "total_gb": round(size / (1024**3), 1),
                        "used_gb": round(used / (1024**3), 1),
                        "free_gb": round(avail / (1024**3), 1),
                        "used_pct": round(used / size * 100, 1) if size else 0,
                    })
                except Exception:
                    continue
    elif sys_name == "Darwin":
        out = _run(["df", "-k"], timeout=5)
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 9 and parts[0].startswith("/"):
                try:
                    size_kb = int(parts[1])
                    used_kb = int(parts[2])
                    avail_kb = int(parts[3])
                    if size_kb * 1024 < 1024**3:
                        continue
                    disks.append({
                        "device": parts[0],
                        "mount": parts[8],
                        "filesystem": "",
                        "total_gb": round(size_kb / (1024**2), 1),
                        "used_gb": round(used_kb / (1024**2), 1),
                        "free_gb": round(avail_kb / (1024**2), 1),
                        "used_pct": round(used_kb / size_kb * 100, 1) if size_kb else 0,
                    })
                except Exception:
                    continue
    elif sys_name == "Windows":
        out = _run(["wmic", "logicaldisk", "get",
                    "DeviceID,Size,FreeSpace,FileSystem,VolumeName,DriveType",
                    "/format:list"])
        for d in _parse_wmic_list(out):
            if not d.get("DeviceID") or not d.get("Size"):
                continue
            try:
                size = int(d["Size"])
                free = int(d.get("FreeSpace", "0") or 0)
                disks.append({
                    "device": d["DeviceID"],
                    "mount": d["DeviceID"],
                    "filesystem": d.get("FileSystem", "").strip(),
                    "volume": d.get("VolumeName", "").strip(),
                    "drive_type": int(d.get("DriveType", "0") or 0),
                    "total_gb": round(size / (1024**3), 1),
                    "used_gb": round((size - free) / (1024**3), 1),
                    "free_gb": round(free / (1024**3), 1),
                    "used_pct": round((size - free) / size * 100, 1) if size else 0,
                })
            except Exception:
                continue
    return disks


# ============================================================
# Section: network
# ============================================================

def get_network() -> dict:
    sys_name = platform.system()
    info: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "interfaces": [],
    }
    # local hostname-resolved IP
    try:
        info["primary_ip"] = socket.gethostbyname(socket.gethostname())
    except Exception:
        info["primary_ip"] = None

    if sys_name == "Linux":
        out = _run(["ip", "-o", "-4", "addr"], timeout=3)
        for line in out.splitlines():
            m = re.search(r"\d+:\s+(\S+)\s+inet\s+([\d.]+/\d+)", line)
            if m:
                info["interfaces"].append({
                    "name": m.group(1),
                    "ipv4": m.group(2),
                })
    elif sys_name == "Darwin":
        out = _run(["ifconfig"], timeout=3)
        cur = None
        for line in out.splitlines():
            m = re.match(r"^(\S+):\s+flags=", line)
            if m:
                cur = m.group(1)
            elif cur:
                mi = re.search(r"inet\s+([\d.]+)", line)
                if mi:
                    info["interfaces"].append({"name": cur, "ipv4": mi.group(1)})
    elif sys_name == "Windows":
        # PowerShell Get-NetIPAddress is locale-independent and structured
        out = _run([
            "powershell", "-NoProfile", "-Command",
            "Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
            "Where-Object {$_.IPAddress -ne '127.0.0.1'} | "
            "Select-Object InterfaceAlias, IPAddress, PrefixLength | "
            "ConvertTo-Json -Compress"
        ], timeout=10)
        try:
            j = json.loads(out) if out else []
            if isinstance(j, dict):
                j = [j]
            for item in j:
                info["interfaces"].append({
                    "name": item.get("InterfaceAlias", ""),
                    "ipv4": f"{item.get('IPAddress', '')}/{item.get('PrefixLength', '')}",
                })
        except Exception:
            # Fallback to ipconfig
            out = _run(["ipconfig"], timeout=5)
            cur_name = None
            for raw in out.splitlines():
                line = raw.rstrip()
                if not line:
                    continue
                if not line.startswith(" "):
                    m = re.match(r"^.+?:\s*$", line)
                    if m:
                        cur_name = line.rstrip(":").strip()
                    continue
                if cur_name:
                    mi = re.search(r":\s*(\d+\.\d+\.\d+\.\d+)", line)
                    if mi:
                        info["interfaces"].append({"name": cur_name, "ipv4": mi.group(1).strip()})

    return info


# ============================================================
# Section: runtimes / package managers / browsers
# ============================================================

RUNTIMES = [
    "python3", "python", "python2", "node", "npm", "pnpm", "yarn", "bun", "deno",
    "uv", "pip", "pipx", "git", "rustc", "cargo", "go", "java", "javac",
    "dotnet", "ruby", "perl", "php", "swift", "scala", "kotlin", "erl", "elixir",
    "lua", "Rscript", "julia",
]

PACKAGE_MANAGERS = [
    # Linux
    "apt", "apt-get", "dpkg", "pacman", "yay", "paru", "dnf", "yum", "zypper",
    "apk", "emerge", "xbps-install", "nix-env", "snap", "flatpak",
    # Cross
    "docker", "podman", "distrobox", "lxc", "lxd",
    # macOS
    "brew", "port", "mas",
    # Windows
    "winget", "choco", "scoop",
]

BROWSERS = [
    # Generic
    "chromium", "google-chrome", "google-chrome-stable", "chrome",
    "firefox", "firefox-developer-edition", "firefox-nightly",
    "brave", "brave-browser", "librewolf", "vivaldi", "vivaldi-stable",
    "opera", "tor-browser",
    # macOS apps (won't be in PATH but checked separately)
]

# Windows: browsers often only as .exe in Program Files
WINDOWS_BROWSER_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Mozilla Firefox\firefox.exe",
    r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    r"C:\Program Files\LibreWolf\librewolf.exe",
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files\Vivaldi\Application\vivaldi.exe",
    r"C:\Program Files\Tor Browser\Browser\firefox.exe",
]

# macOS .app paths
MACOS_BROWSER_APPS = [
    "/Applications/Google Chrome.app",
    "/Applications/Firefox.app",
    "/Applications/Safari.app",
    "/Applications/Brave Browser.app",
    "/Applications/LibreWolf.app",
    "/Applications/Vivaldi.app",
    "/Applications/Tor Browser.app",
    "/Applications/Microsoft Edge.app",
]


def get_runtimes() -> dict:
    found: dict[str, str] = {}
    for name in RUNTIMES:
        # Some need -v / -version instead of --version
        if name == "node":
            v = _ver(name, "--version")
        elif name in ("java", "javac"):
            # java -version writes to stderr
            v = _ver(name, "-version")
        elif name == "scala":
            v = _ver(name, "-version")
        else:
            v = _ver(name)
        if v:
            found[name] = v
    return found


def get_package_managers() -> dict:
    found: dict[str, str] = {}
    for name in PACKAGE_MANAGERS:
        if name == "snap":
            v = _ver(name, "version")
        elif name == "winget":
            v = _ver(name, "--version")
        elif name == "scoop":
            # scoop is a PowerShell function in some shells; check PATH only
            p = _which("scoop")
            if p:
                v = p
            else:
                continue
        else:
            v = _ver(name)
        if v:
            found[name] = v
    return found


def get_browsers() -> dict:
    found: dict[str, str] = {}
    sys_name = platform.system()
    # First PATH-based check (works on Linux/macOS)
    for name in BROWSERS:
        v = _ver(name, "--version", timeout=4)
        if v:
            found[name] = v
    if sys_name == "Windows":
        for p in WINDOWS_BROWSER_PATHS:
            if os.path.isfile(p):
                # Try to get version via PowerShell file properties
                name = Path(p).stem
                vers = _run([
                    "powershell", "-NoProfile", "-Command",
                    f"(Get-Item '{p}').VersionInfo.ProductVersion"
                ], timeout=5).strip()
                found[name + " (exe)"] = f"{p} {('v' + vers) if vers else ''}".strip()
    elif sys_name == "Darwin":
        for app in MACOS_BROWSER_APPS:
            if os.path.isdir(app):
                # Read CFBundleShortVersionString from Info.plist
                plist = Path(app) / "Contents" / "Info.plist"
                vers = ""
                if plist.exists():
                    try:
                        import plistlib
                        with open(plist, "rb") as f:
                            d = plistlib.load(f)
                        vers = d.get("CFBundleShortVersionString", "")
                    except Exception:
                        pass
                found[Path(app).stem] = f"{app}" + (f" v{vers}" if vers else "")
    return found


# ============================================================
# Section: displays / GUI environment
# ============================================================

def get_displays() -> dict:
    sys_name = platform.system()
    info: dict[str, Any] = {}
    if sys_name == "Linux":
        for v in ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "WAYLAND_DISPLAY",
                  "DISPLAY", "DESKTOP_SESSION", "GDMSESSION"):
            val = os.environ.get(v)
            if val:
                info[v] = val
        # xrandr if available
        if _which("xrandr"):
            out = _run(["xrandr", "--current"], timeout=3)
            screens = []
            for line in out.splitlines():
                m = re.match(r"^(\S+)\s+connected\s+(?:primary\s+)?(\d+x\d+\+\d+\+\d+)", line)
                if m:
                    screens.append({"output": m.group(1), "geometry": m.group(2)})
            if screens:
                info["screens"] = screens
    elif sys_name == "Darwin":
        out = _run(["system_profiler", "SPDisplaysDataType"], timeout=10)
        # Extract resolutions
        resolutions = re.findall(r"Resolution:\s*(\d+\s*x\s*\d+)", out)
        if resolutions:
            info["resolutions"] = resolutions
    elif sys_name == "Windows":
        out = _run(["wmic", "desktopmonitor", "get",
                    "ScreenWidth,ScreenHeight,Name", "/format:list"])
        screens = []
        for d in _parse_wmic_list(out):
            w = d.get("ScreenWidth")
            h = d.get("ScreenHeight")
            if w and h:
                screens.append({"name": d.get("Name", ""), "resolution": f"{w}x{h}"})
        if screens:
            info["screens"] = screens
    return info


# ============================================================
# Section: env (selected vars only)
# ============================================================

ENV_KEYS_OF_INTEREST = [
    "PATH", "HOME", "USER", "USERNAME", "USERPROFILE", "LANG", "LC_ALL",
    "SHELL", "TERM", "EDITOR", "VISUAL", "PAGER", "BROWSER",
    "PYTHON", "PYTHONPATH", "NODE_ENV", "JAVA_HOME", "GOPATH", "GOROOT",
    "CARGO_HOME", "RUSTUP_HOME",
    "ARENA_AGENT_HOME", "ARENA_BRIDGE_URL", "ARENA_BRIDGE_PORT", "ARENA_PROFILE",
    "TZ", "PWD", "OLDPWD",
    "TMPDIR", "TEMP", "TMP",
    "DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP",
]


def get_env() -> dict:
    env: dict[str, str] = {}
    for k in ENV_KEYS_OF_INTEREST:
        v = os.environ.get(k)
        if v is not None:
            env[k] = v
    # Trim PATH to make it readable
    if "PATH" in env:
        sep = os.pathsep
        parts = env["PATH"].split(sep)
        env["PATH_entries"] = len(parts)
        env["PATH_dirs"] = parts
    return env


# ============================================================
# Section: services / scheduled tasks (best-effort, platform-specific)
# ============================================================

def get_services() -> dict:
    sys_name = platform.system()
    info: dict[str, Any] = {}
    if sys_name == "Linux":
        out = _run(["systemctl", "--user", "--no-pager",
                    "--no-legend", "list-units", "--type=service",
                    "--state=running"], timeout=5)
        units = []
        for line in out.splitlines():
            parts = line.split()
            if parts and parts[0].endswith(".service"):
                units.append(parts[0])
        info["systemd_user_running"] = units
    elif sys_name == "Darwin":
        out = _run(["launchctl", "list"], timeout=5)
        agents = []
        for line in out.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 3 and parts[2].strip().startswith("com."):
                agents.append(parts[2].strip())
        info["launchctl_loaded"] = agents[:50]  # cap
    elif sys_name == "Windows":
        out = _run(["schtasks", "/Query", "/FO", "CSV", "/NH"], timeout=10)
        tasks = []
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if parts and parts[0].startswith("\\"):
                tasks.append(parts[0].lstrip("\\"))
        # Filter Arena-related tasks
        info["scheduled_tasks_arena"] = [t for t in tasks if "arena" in t.lower()]
        info["scheduled_tasks_total"] = len(tasks)
    return info


# ============================================================
# Section: python_env (current Python interpreter info)
# ============================================================

def get_python_env() -> dict:
    info: dict[str, Any] = {
        "executable": sys.executable,
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "is_venv": sys.prefix != sys.base_prefix,
        "argv": sys.argv,
        "site_packages": [],
        "installed_pkgs_count": None,
    }
    try:
        import site
        info["site_packages"] = list(site.getsitepackages()) if hasattr(site, "getsitepackages") else []
    except Exception:
        pass
    # Try pip list (best-effort)
    pip_path = _which("pip3") or _which("pip")
    if pip_path:
        out = _run([pip_path, "list", "--format=freeze"], timeout=10)
        if out:
            pkgs = [p for p in out.splitlines() if "==" in p]
            info["installed_pkgs_count"] = len(pkgs)
            info["installed_pkgs_top20"] = pkgs[:20]
    return info


# ============================================================
# Assemble & format
# ============================================================

SECTIONS = [
    ("identity", get_identity),
    ("os", get_os),
    ("cpu", get_cpu),
    ("memory", get_memory),
    ("motherboard", get_motherboard),
    ("gpu", get_gpu),
    ("disks", get_disks),
    ("network", get_network),
    ("runtimes", get_runtimes),
    ("package_managers", get_package_managers),
    ("browsers", get_browsers),
    ("displays", get_displays),
    ("env", get_env),
    ("services", get_services),
    ("python_env", get_python_env),
]


def collect(only_section: Optional[str] = None) -> dict:
    result: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": "arena-inventory",
        "tool_version": "1.0.0",
    }
    for name, fn in SECTIONS:
        if only_section and name != only_section:
            continue
        try:
            result[name] = fn()
        except Exception as e:
            result[name] = {"error": str(e)}
    return result


def format_text(data: dict) -> str:
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append(f"  Arena System Inventory — generated {data.get('generated_at', '')}")
    lines.append("=" * 70)

    if "identity" in data:
        i = data["identity"]
        lines.append("\n### Identity")
        lines.append(f"  User      : {i.get('user', '?')}")
        lines.append(f"  Hostname  : {i.get('hostname', '?')} ({i.get('fqdn', '')})")
        lines.append(f"  Home      : {i.get('home', '')}")
        lines.append(f"  CWD       : {i.get('cwd', '')}")
        lines.append(f"  Shell     : {i.get('shell', '')}")

    if "os" in data:
        o = data["os"]
        lines.append("\n### OS")
        lines.append(f"  System    : {o.get('system')} {o.get('release')} ({o.get('machine')})")
        if o.get("distro"):
            lines.append(f"  Distro    : {o['distro'].get('pretty')}")
        if o.get("caption"):
            lines.append(f"  Edition   : {o['caption']} build {o.get('build_number', '')}")
        if o.get("uptime_seconds"):
            up = o["uptime_seconds"]
            d, r = divmod(up, 86400); h, r = divmod(r, 3600); m, _ = divmod(r, 60)
            lines.append(f"  Uptime    : {d}d {h}h {m}m")
        lines.append(f"  Python    : {o.get('python_version')} ({o.get('python_implementation')})")

    if "cpu" in data:
        c = data["cpu"]
        lines.append("\n### CPU")
        lines.append(f"  Name      : {c.get('name', '?')}")
        lines.append(f"  Cores     : {c.get('cores_physical', '?')} physical, "
                     f"{c.get('cores_logical', '?')} logical")
        if c.get("max_ghz"):
            lines.append(f"  Max Freq  : {c['max_ghz']} GHz")
        if c.get("load_avg"):
            la = c["load_avg"]
            lines.append(f"  Load Avg  : {la[0]:.2f}, {la[1]:.2f}, {la[2]:.2f}")

    if "memory" in data:
        m = data["memory"]
        lines.append("\n### Memory")
        if m.get("total_gb"):
            lines.append(f"  Total     : {m.get('total_gb')} GB")
            if m.get("used_gb") is not None:
                lines.append(f"  Used      : {m.get('used_gb')} GB")
            if m.get("available_gb") is not None:
                lines.append(f"  Available : {m.get('available_gb')} GB")
        if m.get("swap_total_gb"):
            lines.append(f"  Swap      : {m.get('swap_free_gb')} free of {m.get('swap_total_gb')} GB")
        for i, mod in enumerate(m.get("modules", []), 1):
            lines.append(f"  Slot {i}    : {mod.get('size_gb')} GB"
                         + (f" @ {mod['speed_mhz']} MHz" if mod.get('speed_mhz') else "")
                         + (f" — {mod['manufacturer']}" if mod.get('manufacturer') else "")
                         + (f" ({mod['part_number']})" if mod.get('part_number') else ""))

    if "motherboard" in data:
        mb = data["motherboard"]
        if mb.get("motherboard"):
            b = mb["motherboard"]
            lines.append("\n### Motherboard")
            lines.append(f"  Vendor    : {b.get('manufacturer', '')}")
            lines.append(f"  Product   : {b.get('product', '')}")
            if b.get("version"):
                lines.append(f"  Version   : {b['version']}")
        if mb.get("bios"):
            b = mb["bios"]
            lines.append("\n### BIOS")
            lines.append(f"  Vendor    : {b.get('manufacturer', '')}")
            lines.append(f"  Version   : {b.get('version', '')}")
            if b.get("release_date"):
                lines.append(f"  Released  : {b['release_date']}")

    if "gpu" in data and data["gpu"].get("gpus"):
        lines.append("\n### GPU")
        for g in data["gpu"]["gpus"]:
            line = f"  • {g.get('name', '?')}"
            if g.get("vram_mb"):
                line += f" ({g['vram_mb']/1024:.1f} GB VRAM)"
            if g.get("driver_version"):
                line += f" — driver {g['driver_version']}"
            lines.append(line)
        if data["gpu"].get("nvidia"):
            for n in data["gpu"]["nvidia"]:
                lines.append(f"  NVIDIA: {n['name']} — {n['vram_used_mb']}/{n['vram_total_mb']} MB used, "
                             f"{n['temperature_c']}°C, {n['utilization_pct']}% utilization")

    if "disks" in data and data["disks"]:
        lines.append("\n### Disks")
        for d in data["disks"]:
            lines.append(f"  {d['device']:<10} {d.get('mount', ''):<15} "
                         f"{d.get('filesystem', ''):<7} "
                         f"{d['free_gb']:.1f}/{d['total_gb']:.1f} GB free ({d['used_pct']}% used)")

    if "network" in data:
        n = data["network"]
        lines.append("\n### Network")
        lines.append(f"  Hostname  : {n.get('hostname')} ({n.get('fqdn')})")
        for iface in n.get("interfaces", []):
            lines.append(f"  {iface.get('name', '?'):<20} {iface.get('ipv4', '')}")

    if "runtimes" in data and data["runtimes"]:
        lines.append("\n### Runtimes")
        for name, v in sorted(data["runtimes"].items()):
            lines.append(f"  {name:<12} {v}")

    if "package_managers" in data and data["package_managers"]:
        lines.append("\n### Package managers / containers")
        for name, v in sorted(data["package_managers"].items()):
            lines.append(f"  {name:<12} {v}")

    if "browsers" in data and data["browsers"]:
        lines.append("\n### Browsers")
        for name, v in sorted(data["browsers"].items()):
            lines.append(f"  {name:<20} {v}")

    if "displays" in data and data["displays"]:
        lines.append("\n### Display / GUI")
        d = data["displays"]
        for k, v in d.items():
            if k != "screens":
                lines.append(f"  {k:<22} {v}")
        for s in d.get("screens", []) or []:
            lines.append(f"  screen                 {s}")

    if "services" in data and data["services"]:
        lines.append("\n### Services")
        for k, v in data["services"].items():
            if isinstance(v, list):
                lines.append(f"  {k} ({len(v)}):")
                for item in v[:10]:
                    lines.append(f"      - {item}")
                if len(v) > 10:
                    lines.append(f"      ... and {len(v) - 10} more")
            else:
                lines.append(f"  {k}: {v}")

    if "python_env" in data:
        pe = data["python_env"]
        lines.append("\n### Python environment")
        lines.append(f"  Executable: {pe.get('executable')}")
        lines.append(f"  Version   : {pe.get('version')} ({pe.get('implementation')})")
        lines.append(f"  In venv   : {pe.get('is_venv')}")
        if pe.get("installed_pkgs_count") is not None:
            lines.append(f"  Packages  : {pe['installed_pkgs_count']} installed")

    if "env" in data:
        e = data["env"]
        lines.append("\n### Environment (selected)")
        for k in sorted(e.keys()):
            if k in ("PATH_dirs", "PATH"):
                continue
            v = e[k]
            if isinstance(v, str) and len(v) > 100:
                v = v[:100] + "..."
            lines.append(f"  {k:<22} {v}")
        if "PATH_entries" in e:
            lines.append(f"  PATH                   ({e['PATH_entries']} entries)")

    lines.append("\n" + "=" * 70)
    return "\n".join(lines)


def main():
    # On Windows console, force UTF-8 so dashes/bullets don't become mojibake
    if platform.system() == "Windows":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass
    p = argparse.ArgumentParser(description="Cross-platform system inventory")
    p.add_argument("--json", action="store_true", help="JSON output")
    p.add_argument("--section", help="Only one section")
    p.add_argument("-o", "--output", help="Write to file")
    p.add_argument("-q", "--quiet", action="store_true", help="Don't print to stdout")
    args = p.parse_args()

    data = collect(only_section=args.section)
    out_text = json.dumps(data, indent=2, ensure_ascii=False) if args.json else format_text(data)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out_text)
        if not args.quiet:
            print(f"[inventory] Wrote {len(out_text)} chars to {args.output}", file=sys.stderr)
    elif not args.quiet:
        print(out_text)


if __name__ == "__main__":
    main()

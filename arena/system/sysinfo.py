"""System information collection helpers."""
from __future__ import annotations

import ctypes
import json
import multiprocessing
import os
import platform
import re
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any, Callable


def sysinfo_cim_cpu_counts(*, subprocess_kwargs_fn: Callable[[], dict] = lambda: {}) -> tuple[int, int]:
    """Run CIM cmdlets for Windows CPU core/thread counts."""
    cpu_physical = multiprocessing.cpu_count()
    cpu_logical = multiprocessing.cpu_count()
    try:
        cmd = [
            "powershell", "-NoProfile", "-NonInteractive", "-Command",
            "Get-CimInstance Win32_Processor | Select-Object NumberOfCores,NumberOfLogicalProcessors | ConvertTo-Json -Compress",
        ]
        out_bytes = subprocess.check_output(cmd, **subprocess_kwargs_fn())
        out = ""
        for enc in ["utf-8", "utf-16", "cp866"]:
            try:
                out = out_bytes.decode(enc, errors="ignore").strip()
                if out:
                    break
            except Exception:
                continue
        if out:
            data = json.loads(out)
            if isinstance(data, list):
                cpu_physical = sum(int(item.get("NumberOfCores", 0) or 0) for item in data)
                cpu_logical = sum(int(item.get("NumberOfLogicalProcessors", 0) or 0) for item in data)
            elif isinstance(data, dict):
                cpu_physical = int(data.get("NumberOfCores", 0) or 0)
                cpu_logical = int(data.get("NumberOfLogicalProcessors", 0) or 0)
            if cpu_physical == 0:
                cpu_physical = multiprocessing.cpu_count()
            if cpu_logical == 0:
                cpu_logical = multiprocessing.cpu_count()
    except Exception:
        pass
    return cpu_physical, cpu_logical


def _windows_memory() -> tuple[int, int]:
    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64),
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return int(stat.ullTotalPhys), int(stat.ullAvailPhys)
    except Exception:
        return 0, 0


def _linux_memory() -> tuple[int, int]:
    if not os.path.exists("/proc/meminfo"):
        return 0, 0
    try:
        text = Path("/proc/meminfo").read_text()
        mt = re.search(r"MemTotal:\s+(\d+)", text)
        ma = re.search(r"MemAvailable:\s+(\d+)", text)
        return (int(mt.group(1)) * 1024 if mt else 0, int(ma.group(1)) * 1024 if ma else 0)
    except Exception:
        return 0, 0


def _windows_cpu_percent(*, subprocess_kwargs_fn: Callable[[], dict] = lambda: {}) -> float:
    try:
        r = subprocess.run(
            ["powershell", "-Command", "(Get-WmiObject Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average"],
            capture_output=True, text=True, timeout=5, **subprocess_kwargs_fn(),
        )
        return float(r.stdout.strip()) if r.stdout.strip() else 0.0
    except Exception:
        return 0.0


def collect_sysinfo(
    *,
    root: str | Path,
    clean_platform_name_fn: Callable[[], str],
    subprocess_kwargs_fn: Callable[[], dict] = lambda: {},
) -> dict[str, Any]:
    """Collect compact cross-platform sysinfo for /v1/sysinfo."""
    disk = shutil.disk_usage(str(root))
    if sys_platform := (platform.system().lower() == "windows"):
        mem_total, mem_avail = _windows_memory()
    else:
        mem_total, mem_avail = _linux_memory()

    cpu_physical = multiprocessing.cpu_count()
    cpu_logical = multiprocessing.cpu_count()
    if platform.system() == "Windows":
        cpu_physical, cpu_logical = sysinfo_cim_cpu_counts(subprocess_kwargs_fn=subprocess_kwargs_fn)

    cpu_percent = 0.0
    load_avg = [0.0, 0.0, 0.0]
    if platform.system() == "Windows":
        cpu_percent = _windows_cpu_percent(subprocess_kwargs_fn=subprocess_kwargs_fn)
    else:
        load_avg = list(getattr(os, "getloadavg", lambda: (0.0, 0.0, 0.0))())
        cpu_percent = load_avg[0] * 100 / max(cpu_logical, 1) if load_avg[0] > 0 else 0.0

    return {
        "ok": True,
        "hostname": socket.gethostname(),
        "python_version": platform.python_version(),
        "os_build": clean_platform_name_fn(),
        "platform": platform.machine(),
        "cpu_cores": cpu_physical,
        "cpu_threads": cpu_logical,
        "cpu_percent": round(cpu_percent, 1),
        "load_avg": load_avg,
        "mem_total_mb": mem_total // (1024 * 1024),
        "mem_avail_mb": mem_avail // (1024 * 1024),
        "disk_total_gb": disk.total // (1024 ** 3),
        "disk_free_gb": disk.free // (1024 ** 3),
        "disk_usage_percent": round(disk.used / disk.total * 100, 1) if disk.total > 0 else 0,
    }

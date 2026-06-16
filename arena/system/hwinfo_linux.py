"""Linux legacy hardware info collection."""
from __future__ import annotations

import re

from arena.system.hwinfo_common import run_text


def _fill_cpu(info: dict) -> None:
    try:
        with open("/proc/cpuinfo") as f:
            cpuinfo = f.read()
        mname = re.search(r"model name\s*:\s*(.+)", cpuinfo)
        ncpus = len(re.findall(r"^processor\s*:", cpuinfo, re.M))
        ncores_set = set(re.findall(r"core id\s*:\s*(\d+)", cpuinfo))
        info["cpu"] = {
            "name": mname.group(1).strip() if mname else "Unknown",
            "cores": len(ncores_set) or ncpus,
            "threads": ncpus,
            "max_ghz": 0,
        }
    except Exception:
        pass


def _fill_ram(info: dict) -> None:
    try:
        with open("/proc/meminfo") as f:
            meminfo = f.read()
        mt = re.search(r"MemTotal:\s+(\d+)", meminfo)
        ma = re.search(r"MemAvailable:\s+(\d+)", meminfo)
        if mt:
            total = int(mt.group(1)) * 1024
            avail = int(ma.group(1)) * 1024 if ma else 0
            info["ram_total_gb"] = round(total / (1024 ** 3), 1)
            info["ram_avail_gb"] = round(avail / (1024 ** 3), 1)
            info["ram_used_gb"] = round((total - avail) / (1024 ** 3), 1)
    except Exception:
        pass


def fill_linux_hwinfo(info: dict, *, subprocess_kwargs_fn) -> dict:
    _fill_cpu(info)
    _fill_ram(info)

    dmi = run_text(["dmidecode", "-t", "baseboard"], timeout=5, subprocess_kwargs_fn=subprocess_kwargs_fn)
    if dmi:
        mfg = re.search(r"Manufacturer:\s*(.+)", dmi)
        prod = re.search(r"Product Name:\s*(.+)", dmi)
        if mfg or prod:
            info["motherboard"] = {
                "manufacturer": mfg.group(1).strip() if mfg else "",
                "product": prod.group(1).strip() if prod else "",
                "version": "",
            }

    lspci = run_text(["lspci"], timeout=5, subprocess_kwargs_fn=subprocess_kwargs_fn)
    gpu_match = re.search(r"VGA compatible controller:\s*(.+)", lspci)
    if gpu_match:
        info["gpu"] = {"name": gpu_match.group(1).strip(), "vram_mb": 0}
        info["gpus"].append(info["gpu"])

    df = run_text(["df", "-B1", "--output=source,target,fstype,size,avail"], timeout=5, subprocess_kwargs_fn=subprocess_kwargs_fn)
    for line in df.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 5 and parts[0].startswith("/"):
            try:
                size = int(parts[3])
                avail = int(parts[4])
                if size < 1024 ** 3:
                    continue
                info["disks"].append({
                    "device": parts[0],
                    "volume": parts[1],
                    "filesystem": parts[2],
                    "total_gb": round(size / (1024 ** 3), 1),
                    "free_gb": round(avail / (1024 ** 3), 1),
                    "used_pct": round((size - avail) / size * 100, 1) if size else 0,
                })
            except Exception:
                continue
    return info

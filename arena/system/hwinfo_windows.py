"""Windows hardware info collection via CIM."""
from __future__ import annotations

import json

from arena.system.hwinfo_common import run_text


def get_cim_json(class_name: str, properties: str, *, subprocess_kwargs_fn) -> list[dict]:
    cmd = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        f"Get-CimInstance {class_name} | Select-Object {properties} | ConvertTo-Json -Compress",
    ]
    try:
        out = run_text(cmd, timeout=10, subprocess_kwargs_fn=subprocess_kwargs_fn)
        if not out or not out.strip():
            return []
        data = json.loads(out.strip())
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def fill_windows_hwinfo(info: dict, *, subprocess_kwargs_fn) -> dict:
    mb_blocks = get_cim_json("Win32_BaseBoard", "Manufacturer,Product,Version", subprocess_kwargs_fn=subprocess_kwargs_fn)
    if mb_blocks and mb_blocks[0].get("Manufacturer"):
        data = mb_blocks[0]
        info["motherboard"] = {
            "manufacturer": str(data.get("Manufacturer") or ""),
            "product": str(data.get("Product") or ""),
            "version": str(data.get("Version") or ""),
        }

    bios_blocks = get_cim_json("Win32_BIOS", "SMBIOSBIOSVersion,Manufacturer,ReleaseDate", subprocess_kwargs_fn=subprocess_kwargs_fn)
    if bios_blocks and bios_blocks[0].get("SMBIOSBIOSVersion"):
        data = bios_blocks[0]
        release_date = str(data.get("ReleaseDate") or "")
        if isinstance(data.get("ReleaseDate"), dict) and "DateTime" in data["ReleaseDate"]:
            release_date = str(data["ReleaseDate"]["DateTime"])
        info["bios"] = {
            "version": str(data.get("SMBIOSBIOSVersion") or ""),
            "manufacturer": str(data.get("Manufacturer") or ""),
            "release_date": release_date[:8] if len(release_date) >= 8 else release_date,
        }

    cpu_blocks = get_cim_json("Win32_Processor", "Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed", subprocess_kwargs_fn=subprocess_kwargs_fn)
    if cpu_blocks and cpu_blocks[0].get("Name"):
        data = cpu_blocks[0]
        try:
            cores = int(data.get("NumberOfCores") or 0)
        except Exception:
            cores = 0
        try:
            threads = int(data.get("NumberOfLogicalProcessors") or 0)
        except Exception:
            threads = 0
        try:
            ghz = round(int(data.get("MaxClockSpeed") or 0) / 1000.0, 2)
        except Exception:
            ghz = 0
        info["cpu"] = {"name": str(data.get("Name") or ""), "cores": cores, "threads": threads, "max_ghz": ghz}

    for data in get_cim_json("Win32_VideoController", "Name,AdapterRAM", subprocess_kwargs_fn=subprocess_kwargs_fn):
        if data.get("Name"):
            try:
                vram_mb = int(data.get("AdapterRAM") or 0) // (1024 * 1024)
            except Exception:
                vram_mb = 0
            info["gpus"].append({"name": str(data.get("Name") or ""), "vram_mb": vram_mb})
    if info["gpus"]:
        info["gpu"] = info["gpus"][0]

    total_bytes = 0
    for data in get_cim_json("Win32_PhysicalMemory", "Capacity,Speed,Manufacturer,PartNumber", subprocess_kwargs_fn=subprocess_kwargs_fn):
        if data.get("Capacity"):
            try:
                cap = int(data["Capacity"])
                total_bytes += cap
                info["ram_modules"].append({
                    "size_gb": round(cap / (1024 ** 3), 1),
                    "speed_mhz": int(data.get("Speed") or 0),
                    "manufacturer": str(data.get("Manufacturer") or "").strip(),
                    "part_number": str(data.get("PartNumber") or "").strip(),
                })
            except Exception:
                pass
    if total_bytes:
        info["ram_total_gb"] = round(total_bytes / (1024 ** 3), 1)

    for data in get_cim_json("Win32_LogicalDisk", "DeviceID,Size,FreeSpace,FileSystem,VolumeName", subprocess_kwargs_fn=subprocess_kwargs_fn):
        if data.get("DeviceID") and data.get("Size"):
            try:
                size = int(data["Size"])
                free = int(data.get("FreeSpace") or 0)
                info["disks"].append({
                    "device": str(data.get("DeviceID") or ""),
                    "volume": str(data.get("VolumeName") or "").strip(),
                    "filesystem": str(data.get("FileSystem") or "").strip(),
                    "total_gb": round(size / (1024 ** 3), 1),
                    "free_gb": round(free / (1024 ** 3), 1),
                    "used_pct": round((size - free) / size * 100, 1) if size else 0,
                })
            except Exception:
                pass
    return info

"""Inventory probe group."""
from __future__ import annotations

from arena.inventory.probe_common import *  # noqa: F401,F403

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
        for d in _get_cim_json("Win32_LogicalDisk", "DeviceID,Size,FreeSpace,FileSystem,VolumeName,Description,DriveType"):
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

def get_storage_devices() -> list[dict]:
    """Physical/block storage devices, not just mounted filesystems."""
    sys_name = platform.system()
    devices: list[dict[str, Any]] = []
    if sys_name == "Linux":
        if _which("lsblk"):
            out = _run([
                "lsblk", "-J", "-b", "-o",
                "NAME,PATH,TYPE,SIZE,MODEL,SERIAL,TRAN,ROTA,RM,FSTYPE,MOUNTPOINTS,LABEL,UUID",
            ], timeout=5)
            try:
                data = json.loads(out) if out else {}
                def walk(items: list[dict], parent: str | None = None) -> None:
                    for item in items or []:
                        size = item.get("size")
                        try:
                            size_gb = round(int(size) / (1024**3), 2) if size is not None else None
                        except Exception:
                            size_gb = None
                        devices.append({
                            "name": item.get("name"),
                            "path": item.get("path"),
                            "type": item.get("type"),
                            "parent": parent,
                            "size_gb": size_gb,
                            "model": (item.get("model") or "").strip(),
                            "serial": (item.get("serial") or "").strip(),
                            "transport": item.get("tran"),
                            "rotational": bool(item.get("rota")) if item.get("rota") is not None else None,
                            "removable": bool(item.get("rm")) if item.get("rm") is not None else None,
                            "filesystem": item.get("fstype"),
                            "mountpoints": item.get("mountpoints") or [],
                            "label": item.get("label"),
                            "uuid": item.get("uuid"),
                        })
                        walk(item.get("children") or [], item.get("name"))
                walk(data.get("blockdevices") or [])
            except Exception:
                pass
    elif sys_name == "Windows":
        for d in _get_cim_json("Win32_DiskDrive", "Model,SerialNumber,InterfaceType,MediaType,Size,Partitions,Status"):
            try:
                size_gb = round(int(d.get("Size") or 0) / (1024**3), 2) if d.get("Size") else None
            except Exception:
                size_gb = None
            devices.append({
                "model": str(d.get("Model", "")).strip(),
                "serial": str(d.get("SerialNumber", "")).strip(),
                "interface": str(d.get("InterfaceType", "")).strip(),
                "media_type": str(d.get("MediaType", "")).strip(),
                "size_gb": size_gb,
                "partitions": d.get("Partitions"),
                "status": d.get("Status"),
            })
    elif sys_name == "Darwin":
        out = _run(["diskutil", "list", "-plist"], timeout=8)
        if out:
            try:
                import plistlib
                data = plistlib.loads(out.encode("utf-8", errors="replace"))
                for disk in data.get("AllDisksAndPartitions", []):
                    devices.append({
                        "name": disk.get("DeviceIdentifier"),
                        "size_gb": round(int(disk.get("Size") or 0) / (1024**3), 2) if disk.get("Size") else None,
                        "partitions": len(disk.get("Partitions") or []),
                    })
            except Exception:
                pass
    return devices

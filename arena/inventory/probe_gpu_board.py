"""Inventory probe group."""
from __future__ import annotations

from arena.inventory.probe_common import *  # noqa: F401,F403

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
        for d in _get_cim_json("Win32_VideoController", "Name,AdapterRAM,DriverVersion,VideoProcessor,CurrentHorizontalResolution,CurrentVerticalResolution"):
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
                "resolution": (f"{d.get('CurrentHorizontalResolution')}x{d.get('CurrentVerticalResolution')}"
                               if d.get('CurrentHorizontalResolution') and d.get('CurrentVerticalResolution') else ""),
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

def get_motherboard() -> dict:
    sys_name = platform.system()
    info: dict[str, Any] = {"motherboard": None, "bios": None}
    if sys_name == "Windows":
        blocks = _get_cim_json("Win32_BaseBoard", "Manufacturer,Product,Version,SerialNumber")
        if blocks:
            d = blocks[0]
            info["motherboard"] = {
                "manufacturer": d.get("Manufacturer", "").strip(),
                "product": d.get("Product", "").strip(),
                "version": d.get("Version", "").strip(),
                "serial": d.get("SerialNumber", "").strip(),
            }
        bblocks = _get_cim_json("Win32_BIOS", "SMBIOSBIOSVersion,Manufacturer,ReleaseDate")
        if bblocks:
            d = bblocks[0]
            rd = _cim_dt(d.get("ReleaseDate", ""))
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

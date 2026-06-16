"""Inventory probe group."""
from __future__ import annotations

from arena.inventory.probe_common import *  # noqa: F401,F403

def _classify_pci(text: str) -> str:
    low = text.lower()
    if any(x in low for x in ("vga", "3d controller", "display")):
        return "gpu"
    if any(x in low for x in ("ethernet", "network", "wireless", "wi-fi")):
        return "network"
    if any(x in low for x in ("sata", "nvme", "raid", "storage")):
        return "storage"
    if "audio" in low:
        return "audio"
    if "usb" in low:
        return "usb"
    if "bridge" in low:
        return "bridge"
    return "other"

def get_pci_devices() -> list[dict]:
    """PCI/PNP hardware inventory, capped and categorized."""
    sys_name = platform.system()
    devices: list[dict[str, Any]] = []
    if sys_name == "Linux" and _which("lspci"):
        out = _run(["lspci", "-nn"], timeout=5)
        for line in out.splitlines()[:200]:
            m = re.match(r"^(\S+)\s+(.+?):\s+(.+)$", line)
            if not m:
                continue
            cls = m.group(2).strip()
            desc = m.group(3).strip()
            devices.append({
                "slot": m.group(1),
                "class": cls,
                "category": _classify_pci(cls + " " + desc),
                "description": desc,
            })
    elif sys_name == "Windows":
        ps_class_filter = "'Display','Net','HDC','SCSIAdapter','USB','MEDIA','Bluetooth'"
        ps = (
            "Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue | "
            f"Where-Object {{$_.PNPClass -in @({ps_class_filter})}} | "
            "Select-Object Name,PNPClass,Manufacturer,DeviceID,Status | ConvertTo-Json -Compress -Depth 4"
        )
        out = _run(_powershell_utf8_command(ps), timeout=15)
        try:
            data = json.loads(out) if out else []
            if isinstance(data, dict):
                data = [data]
            for d in data[:200]:
                devices.append({
                    "class": d.get("PNPClass"),
                    "category": _classify_pci(str(d.get("PNPClass", "")) + " " + str(d.get("Name", ""))),
                    "name": d.get("Name"),
                    "manufacturer": d.get("Manufacturer"),
                    "status": d.get("Status"),
                    "device_id": d.get("DeviceID"),
                })
        except Exception:
            pass
    return devices

def get_usb_devices() -> list[dict]:
    sys_name = platform.system()
    devices: list[dict[str, Any]] = []
    if sys_name == "Linux" and _which("lsusb"):
        out = _run(["lsusb"], timeout=5)
        for line in out.splitlines()[:200]:
            m = re.match(r"Bus\s+(\d+)\s+Device\s+(\d+):\s+ID\s+([0-9a-fA-F:]+)\s*(.*)", line)
            if m:
                devices.append({"bus": m.group(1), "device": m.group(2), "id": m.group(3), "name": m.group(4).strip()})
    elif sys_name == "Windows":
        ps = (
            "Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue | "
            "Where-Object {$_.PNPClass -eq 'USB'} | "
            "Select-Object Name,Manufacturer,DeviceID,Status | ConvertTo-Json -Compress -Depth 4"
        )
        out = _run(_powershell_utf8_command(ps), timeout=15)
        try:
            data = json.loads(out) if out else []
            if isinstance(data, dict):
                data = [data]
            for d in data[:200]:
                devices.append({"name": d.get("Name"), "manufacturer": d.get("Manufacturer"), "status": d.get("Status"), "device_id": d.get("DeviceID")})
        except Exception:
            pass
    elif sys_name == "Darwin":
        out = _run(["system_profiler", "SPUSBDataType"], timeout=12)
        for line in out.splitlines():
            if line.startswith("        ") and line.strip().endswith(":"):
                devices.append({"name": line.strip().rstrip(":")})
    return devices

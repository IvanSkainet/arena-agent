"""Inventory probe group."""
from __future__ import annotations

from arena.inventory.probe_common import *  # noqa: F401,F403

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
        blocks = _get_cim_json("Win32_Processor", "Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed,Manufacturer")
        if blocks:
            d = blocks[0]
            info["name"] = str(d.get("Name", "")).strip()
            info["manufacturer"] = str(d.get("Manufacturer", "")).strip()
            try:
                info["cores_physical"] = int(d.get("NumberOfCores") or 0)
            except Exception:
                pass
            try:
                mh = int(d.get("MaxClockSpeed") or 0)
                if mh:
                    info["max_ghz"] = round(mh / 1000.0, 2)
            except Exception:
                pass
    return info

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
        # modules via CIM
        for d in _get_cim_json("Win32_PhysicalMemory", "Capacity,Speed,ConfiguredClockSpeed,Manufacturer,PartNumber,DeviceLocator,BankLabel,SerialNumber"):
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

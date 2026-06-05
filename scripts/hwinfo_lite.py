import os
import sys
import platform
import subprocess
import json

def get_cim_data(class_name, properties):
    try:
        # Construct powershell command to fetch CIM instance and convert to JSON
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
               f"Get-CimInstance {class_name} | Select-Object {properties} | ConvertTo-Json -Compress"]
        # Standardize execution flags and options
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            data = json.loads(r.stdout.strip())
            if isinstance(data, dict):
                return [data]
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []

def collect_all():
    info = {
        "os": {
            "name": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "architecture": platform.machine(),
            "node": platform.node()
        },
        "motherboard": {},
        "cpu": {},
        "gpu": {},
        "ram": {},
        "storage": {},
        "network": {}
    }
    
    # OS Version override for Windows 11
    if info["os"]["name"] == "Windows":
        try:
            build = int(info["os"]["version"].split('.')[-1])
            if build >= 22000:
                info["os"]["name_pretty"] = "Windows 11"
            else:
                info["os"]["name_pretty"] = "Windows 10"
            info["os"]["build"] = build
        except:
            info["os"]["name_pretty"] = "Windows " + info["os"]["release"]
    else:
        info["os"]["name_pretty"] = platform.platform()

    if platform.system() == "Windows":
        # 1. Motherboard & BIOS (Wmi -> Cim)
        try:
            mb_list = get_cim_data("Win32_BaseBoard", "Manufacturer,Product")
            if mb_list:
                for k, v in mb_list[0].items():
                    info["motherboard"][k.strip().lower()] = v
                    
            bios_list = get_cim_data("Win32_BIOS", "Manufacturer,Name,Version")
            if bios_list:
                for k, v in bios_list[0].items():
                    info["motherboard"][f"bios_{k.strip().lower()}"] = v
        except Exception:
            pass

        # 2. CPU Details (Wmi -> Cim)
        try:
            cpu_list = get_cim_data("Win32_Processor", "Name,MaxClockSpeed,NumberOfCores,NumberOfLogicalProcessors,L2CacheSize,L3CacheSize")
            if cpu_list:
                for k, v in cpu_list[0].items():
                    val = v
                    if isinstance(val, str) and val.isdigit():
                        val = int(val)
                    info["cpu"][k.strip().lower()] = val
        except Exception:
            pass
        
        # 3. GPU Details (Wmi -> Cim)
        try:
            gpu_list = get_cim_data("Win32_VideoController", "Name,DriverVersion,AdapterRAM,VideoProcessor,VideoModeDescription")
            gpus = []
            for item in gpu_list:
                gpu_dict = {}
                for k, v in item.items():
                    val = v
                    if isinstance(val, str) and val.isdigit():
                        val = int(val)
                    gpu_dict[k.strip().lower()] = val
                gpus.append(gpu_dict)
                
            for g in gpus:
                if "adapterram" in g and isinstance(g["adapterram"], (int, float)):
                    g["vram_mb"] = round(abs(g["adapterram"]) / (1024**2), 1)
            info["gpu"] = gpus
        except Exception:
            pass

        # 4. RAM details (Wmi -> Cim)
        try:
            os_list = get_cim_data("Win32_OperatingSystem", "TotalVisibleMemorySize,FreePhysicalMemory")
            if os_list:
                for k, v in os_list[0].items():
                    val = v
                    if isinstance(val, str) and val.isdigit():
                        val = int(val)
                    info["ram"][k.strip().lower()] = val
                    
            if "totalvisiblememorysize" in info["ram"]:
                total = info["ram"]["totalvisiblememorysize"]
                free = info["ram"].get("freephysicalmemory", 0)
                info["ram"]["total_gb"] = round(total / (1024**2), 2)
                info["ram"]["free_gb"] = round(free / (1024**2), 2)
                info["ram"]["used_gb"] = round((total - free) / (1024**2), 2)
                info["ram"]["used_pct"] = round(((total - free) / total) * 100, 1)
        except Exception:
            pass

        # 5. Storage details (Wmi -> Cim)
        try:
            disk_list = get_cim_data("Win32_LogicalDisk", "DeviceID,Size,FreeSpace,FileSystem")
            cleaned_disks = {}
            for d in disk_list:
                dev_id = d.get("DeviceID")
                size_str = d.get("Size")
                free_str = d.get("FreeSpace")
                if dev_id and size_str:
                    try:
                        size = int(size_str)
                        free = int(free_str or 0)
                        fs = d.get("FileSystem") or "NTFS"
                        cleaned_disks[dev_id] = {
                            "filesystem": fs,
                            "total_gb": round(size / (1024**3), 2),
                            "free_gb": round(free / (1024**3), 2),
                            "used_gb": round((size - free) / (1024**3), 2),
                            "used_pct": round(((size - free) / size) * 100, 1) if size else 0
                        }
                    except Exception:
                        pass
            info["storage"] = cleaned_disks
        except Exception:
            pass

        # 6. Network details
        try:
            net_res = subprocess.run("powershell -NoProfile -Command \"Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -notmatch '127.0.0.1' | Select-Object IPAddress, InterfaceAlias | ConvertTo-Json\"", capture_output=True, text=True, shell=True)
            if net_res.stdout.strip():
                net_data = json.loads(net_res.stdout)
                info["network"]["adapters"] = net_data
        except Exception:
            pass

    else:
        # Simple generic fallback for Linux/macOS
        info["cpu"]["logical_processors"] = os.cpu_count()
        info["ram"]["total_gb"] = "N/A (Linux/macOS fallback)"
        
    return info

if __name__ == "__main__":
    print(json.dumps(collect_all(), indent=2, ensure_ascii=False))

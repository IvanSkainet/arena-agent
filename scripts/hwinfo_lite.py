import os
import sys
import platform
import subprocess
import json

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
        # 1. Motherboard & BIOS
        try:
            m_res = subprocess.run("wmic baseboard get manufacturer, product /format:list", capture_output=True, text=True, shell=True)
            for line in m_res.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    info["motherboard"][k.strip().lower()] = v.strip()
            b_res = subprocess.run("wmic bios get manufacturer, name, version /format:list", capture_output=True, text=True, shell=True)
            for line in b_res.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    info["motherboard"][f"bios_{k.strip().lower()}"] = v.strip()
        except: pass

        # 2. CPU Details
        try:
            cpu_res = subprocess.run("wmic cpu get name, maxclockspeed, NumberOfCores, NumberOfLogicalProcessors, L2CacheSize, L3CacheSize /format:list", capture_output=True, text=True, shell=True)
            for line in cpu_res.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    val = v.strip()
                    # Try to convert to int if numeric
                    if val.isdigit(): val = int(val)
                    info["cpu"][k.strip().lower()] = val
        except: pass
        
        # 3. GPU Details
        try:
            gpu_res = subprocess.run("wmic path win32_VideoController get name, DriverVersion, AdapterRAM, VideoProcessor, VideoModeDescription /format:list", capture_output=True, text=True, shell=True)
            gpus = []
            current_gpu = {}
            for line in gpu_res.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    val = v.strip()
                    if val.isdigit(): val = int(val)
                    current_gpu[k.strip().lower()] = val
                elif not line.strip() and current_gpu:
                    gpus.append(current_gpu)
                    current_gpu = {}
            if current_gpu:
                gpus.append(current_gpu)
            # Filter and convert VRAM to MB
            for g in gpus:
                if "adapterram" in g and isinstance(g["adapterram"], int):
                    g["vram_mb"] = round(abs(g["adapterram"]) / (1024**2), 1)
            info["gpu"] = gpus
        except: pass

        # 4. RAM details
        try:
            ram_res = subprocess.run("wmic os get TotalVisibleMemorySize, FreePhysicalMemory /format:list", capture_output=True, text=True, shell=True)
            for line in ram_res.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    val = int(v.strip())
                    info["ram"][k.strip().lower()] = val
            if "totalvisiblememorysize" in info["ram"]:
                total = info["ram"]["totalvisiblememorysize"]
                free = info["ram"].get("freephysicalmemory", 0)
                info["ram"]["total_gb"] = round(total / (1024**2), 2)
                info["ram"]["free_gb"] = round(free / (1024**2), 2)
                info["ram"]["used_gb"] = round((total - free) / (1024**2), 2)
                info["ram"]["used_pct"] = round(((total - free) / total) * 100, 1)
        except: pass

        # 5. Storage details (Robust tabular parsing)
        try:
            disk_res = subprocess.run("wmic logicaldisk get caption, filesystem, freespace, size", capture_output=True, text=True, shell=True)
            cleaned_disks = {}
            for line in disk_res.stdout.splitlines():
                parts = line.strip().split()
                if len(parts) >= 3 and parts[0].endswith(':'):
                    cap = parts[0]
                    try:
                        size = int(parts[-1])
                        free = int(parts[-2])
                        fs = parts[1] if len(parts) == 4 else "NTFS"
                        cleaned_disks[cap] = {
                            "filesystem": fs,
                            "total_gb": round(size / (1024**3), 2),
                            "free_gb": round(free / (1024**3), 2),
                            "used_gb": round((size - free) / (1024**3), 2),
                            "used_pct": round(((size - free) / size) * 100, 1)
                        }
                    except:
                        pass
            info["storage"] = cleaned_disks
        except: pass

        # 6. Network details
        try:
            net_res = subprocess.run("powershell -NoProfile -Command \"Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -notmatch '127.0.0.1' | Select-Object IPAddress, InterfaceAlias | ConvertTo-Json\"", capture_output=True, text=True, shell=True)
            if net_res.stdout.strip():
                net_data = json.loads(net_res.stdout)
                info["network"]["adapters"] = net_data
        except: pass

    else:
        # Simple generic fallback for Linux/macOS
        info["cpu"]["logical_processors"] = os.cpu_count()
        info["ram"]["total_gb"] = "N/A (Linux/macOS fallback)"
        
    return info

if __name__ == "__main__":
    print(json.dumps(collect_all(), indent=2, ensure_ascii=False))

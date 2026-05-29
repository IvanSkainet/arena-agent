import os
import sys
import platform
import subprocess
import json
import datetime

def get_wmic_all_list(class_name):
    """Utility to run wmic class get and parse all properties as dictionary list cleanly aggregated"""
    try:
        res = subprocess.run(f"wmic {class_name} get /format:list", capture_output=True, text=True, shell=True)
        items = []
        current = {}
        for line in res.stdout.splitlines():
            line_str = line.strip()
            if "=" in line_str:
                k, v = line_str.split("=", 1)
                key = k.strip().lower()
                val = v.strip()
                if val.isdigit(): val = int(val)
                
                # If key is already in current, it means we transitioned to a new instance!
                if key in current:
                    items.append(current)
                    current = {}
                current[key] = val
        if current:
            items.append(current)
        return items
    except Exception:
        return []

def get_uptime():
    try:
        res = subprocess.run("wmic os get LastBootUpTime /format:list", capture_output=True, text=True, shell=True)
        for line in res.stdout.splitlines():
            if "LastBootUpTime=" in line:
                boot_str = line.split("=", 1)[1].strip().split('.')[0]
                y = int(boot_str[0:4])
                m = int(boot_str[4:6])
                d = int(boot_str[6:8])
                hh = int(boot_str[8:10])
                mm = int(boot_str[10:12])
                ss = int(boot_str[12:14])
                boot_time = datetime.datetime(y, m, d, hh, mm, ss)
                now = datetime.datetime.now()
                delta = now - boot_time
                hours = delta.seconds // 3600
                minutes = (delta.seconds % 3600) // 60
                return f"{delta.days} days, {hours} hours, {minutes} minutes"
    except Exception:
        pass
    return "Unknown"

def collect_standard():
    info = collect_full()
    
    os_data = info.get("os", {})
    board = info.get("motherboard", {})
    cpu = info.get("cpu", [{}])[0] if info.get("cpu") else {}
    gpu = info.get("gpu", [{}])[0] if info.get("gpu") else {}
    ram = info.get("ram", {})
    disks = info.get("storage", {})
    network = info.get("network", {}).get("adapters", [])
    
    return {
        "os": {
            "name_pretty": os_data.get("name_pretty"),
            "build": os_data.get("build"),
            "architecture": os_data.get("architecture"),
            "uptime": os_data.get("uptime")
        },
        "motherboard": {
            "manufacturer": board.get("manufacturer"),
            "product": board.get("product"),
            "bios_name": board.get("bios_name")
        },
        "cpu": {
            "name": cpu.get("name"),
            "physical_cores": cpu.get("numberofcores"),
            "logical_processors": cpu.get("numberoflogicalprocessors")
        },
        "gpu": {
            "name": gpu.get("name"),
            "vram_mb": gpu.get("vram_mb")
        },
        "ram": {
            "used_gb": ram.get("used_gb"),
            "total_gb": ram.get("total_gb"),
            "used_pct": ram.get("used_pct")
        },
        "storage": disks,
        "network": {
            "adapters": network
        }
    }

def collect_full():
    info = {
        "os": {
            "name": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "architecture": platform.machine(),
            "node": platform.node(),
            "uptime": get_uptime()
        },
        "motherboard": {},
        "cpu": {},
        "gpu": {},
        "ram": {},
        "storage": {},
        "network": {},
        "processes": {}
    }
    
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
        # 1. Motherboard & BIOS Full
        try:
            m_res = subprocess.run("wmic baseboard get /format:list", capture_output=True, text=True, shell=True)
            for line in m_res.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    info["motherboard"][k.strip().lower()] = v.strip()
            info["motherboard"]["bios_name"] = info["motherboard"].get("product", "")
            b_res = subprocess.run("wmic bios get /format:list", capture_output=True, text=True, shell=True)
            for line in b_res.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    info["motherboard"][f"bios_{k.strip().lower()}"] = v.strip()
        except: pass

        # 2. CPU Full Details
        info["cpu"] = get_wmic_all_list("cpu")
        
        # 3. GPU Full Details
        gpus = get_wmic_all_list("path win32_VideoController")
        for g in gpus:
            if "adapterram" in g and isinstance(g["adapterram"], int):
                g["vram_mb"] = round(abs(g["adapterram"]) / (1024**2), 1)
        info["gpu"] = gpus

        # 4. RAM Full Details
        try:
            ram_os = {}
            ram_res = subprocess.run("wmic os get TotalVisibleMemorySize, FreePhysicalMemory, TotalVirtualMemorySize, FreeVirtualMemory /format:list", capture_output=True, text=True, shell=True)
            for line in ram_res.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    val = int(v.strip())
                    ram_os[k.strip().lower()] = val
            if "totalvisiblememorysize" in ram_os:
                total = ram_os["totalvisiblememorysize"]
                free = ram_os.get("freephysicalmemory", 0)
                ram_os["total_gb"] = round(total / (1024**2), 2)
                ram_os["free_gb"] = round(free / (1024**2), 2)
                ram_os["used_gb"] = round((total - free) / (1024**2), 2)
                ram_os["used_pct"] = round(((total - free) / total) * 100, 1)
            info["ram"]["system_memory"] = ram_os
            info["ram"].update(ram_os)
            info["ram"]["chips"] = get_wmic_all_list("memorychip")
        except: pass

        # 5. Storage details
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
            info["physical_drives"] = get_wmic_all_list("diskdrive")
        except: pass

        # 6. Network details
        try:
            net_res = subprocess.run('powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -notmatch \'127.0.0.1\' | Select-Object IPAddress, InterfaceAlias | ConvertTo-Json"', capture_output=True, text=True, shell=True)
            if net_res.stdout.strip():
                net_data = json.loads(net_res.stdout)
                if not isinstance(net_data, list): net_data = [net_data]
                info["network"]["adapters"] = net_data
            info["network"]["adapters_config"] = get_wmic_all_list("nicconfig where IPEnabled=True")
        except: pass

        # 7. Processes summary
        try:
            p_count = subprocess.run("wmic process get caption | find /c /v """, capture_output=True, text=True, shell=True)
            info["processes"]["count"] = int(p_count.stdout.strip()) if p_count.stdout.strip().isdigit() else "Unknown"
        except: pass

    else:
        info["cpu"]["logical_processors"] = os.cpu_count()
        info["ram"]["total_gb"] = "N/A (Linux/macOS fallback)"
        
    return info

def main():
    full_mode = "--full" in sys.argv
    if full_mode:
        print(json.dumps(collect_full(), indent=2, ensure_ascii=False))
    else:
        print(json.dumps(collect_standard(), indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
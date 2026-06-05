import os
import sys
import platform
import subprocess
import json
import datetime

def get_cim_all_list(class_name):
    """Utility to run Get-CimInstance and parse all properties as dictionary list"""
    try:
        # Use PowerShell to run CIM cmdlet and output JSON
        # Filter is needed if class_name has 'where', but let's handle simple classes and WQL paths
        cmd = class_name
        if " path " in class_name.lower():
            cmd = class_name.split("path ", 1)[1]
        
        # If there's a where clause, convert to CIM Filter
        # simple translation: nicconfig where IPEnabled=True -> Win32_NetworkAdapterConfiguration -Filter "IPEnabled=True"
        if " where " in cmd.lower():
            parts = cmd.lower().split(" where ", 1)
            cls = parts[0].strip()
            filter_str = parts[1].strip()
            ps_cmd = f"Get-CimInstance {cls} -Filter \\\"{filter_str}\\\" | ConvertTo-Json -Compress"
        else:
            cls = cmd.strip()
            # If not starting with Win32_, append it
            if not cls.lower().startswith("win32_") and not cls.lower().startswith("cim_"):
                cls = "Win32_" + cls
            ps_cmd = f"Get-CimInstance {cls} | ConvertTo-Json -Compress"
            
        res = subprocess.run(f"powershell -NoProfile -Command \"{ps_cmd}\"", capture_output=True, text=True, shell=True)
        if not res.stdout.strip():
            return []
            
        data = json.loads(res.stdout)
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return data
        return []
    except Exception:
        return []

def get_uptime():
    try:
        res = subprocess.run("powershell -NoProfile -Command \"(Get-CimInstance Win32_OperatingSystem).LastBootUpTime | ConvertTo-Json\"", capture_output=True, text=True, shell=True)
        if res.stdout.strip():
            data = json.loads(res.stdout)
            # PowerShell might return a date string like "/Date(1682390192000)/" or just a formatted string
            # Better to get milliseconds directly
            res2 = subprocess.run("powershell -NoProfile -Command \"[int64]((Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime).TotalSeconds\"", capture_output=True, text=True, shell=True)
            if res2.stdout.strip() and res2.stdout.strip().isdigit():
                seconds = int(res2.stdout.strip())
                days = seconds // 86400
                hours = (seconds % 86400) // 3600
                minutes = (seconds % 3600) // 60
                return f"{days} days, {hours} hours, {minutes} minutes"
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
            "manufacturer": board.get("Manufacturer"),
            "product": board.get("Product"),
            "bios_name": board.get("bios_name")
        },
        "cpu": {
            "name": cpu.get("Name"),
            "physical_cores": cpu.get("NumberOfCores"),
            "logical_processors": cpu.get("NumberOfLogicalProcessors")
        },
        "gpu": {
            "name": gpu.get("Name"),
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
            mb_data = get_cim_all_list("Win32_BaseBoard")
            if mb_data:
                info["motherboard"] = mb_data[0]
            info["motherboard"]["bios_name"] = info["motherboard"].get("Product", "")
            bios_data = get_cim_all_list("Win32_BIOS")
            if bios_data:
                for k, v in bios_data[0].items():
                    info["motherboard"][f"bios_{k}"] = v
        except: pass

        # 2. CPU Full Details
        info["cpu"] = get_cim_all_list("Win32_Processor")
        
        # 3. GPU Full Details
        gpus = get_cim_all_list("Win32_VideoController")
        for g in gpus:
            if "AdapterRAM" in g and isinstance(g["AdapterRAM"], (int, float)):
                g["vram_mb"] = round(abs(g["AdapterRAM"]) / (1024**2), 1)
        info["gpu"] = gpus

        # 4. RAM Full Details
        try:
            ram_os = {}
            res = subprocess.run("powershell -NoProfile -Command \"Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize, FreePhysicalMemory, TotalVirtualMemorySize, FreeVirtualMemory | ConvertTo-Json -Compress\"", capture_output=True, text=True, shell=True)
            if res.stdout.strip():
                ram_os = json.loads(res.stdout)
                
            if "TotalVisibleMemorySize" in ram_os:
                total = int(ram_os["TotalVisibleMemorySize"])
                free = int(ram_os.get("FreePhysicalMemory", 0))
                ram_os["total_gb"] = round(total / (1024**2), 2)
                ram_os["free_gb"] = round(free / (1024**2), 2)
                ram_os["used_gb"] = round((total - free) / (1024**2), 2)
                ram_os["used_pct"] = round(((total - free) / total) * 100, 1)
            info["ram"]["system_memory"] = ram_os
            info["ram"].update(ram_os)
            info["ram"]["chips"] = get_cim_all_list("Win32_PhysicalMemory")
        except: pass

        # 5. Storage details
        try:
            disks = get_cim_all_list("Win32_LogicalDisk")
            cleaned_disks = {}
            for d in disks:
                if d.get("DeviceID") and d.get("Size"):
                    cap = d["DeviceID"]
                    size = int(d["Size"])
                    free = int(d.get("FreeSpace", 0))
                    fs = d.get("FileSystem", "NTFS")
                    cleaned_disks[cap] = {
                        "filesystem": fs,
                        "total_gb": round(size / (1024**3), 2),
                        "free_gb": round(free / (1024**3), 2),
                        "used_gb": round((size - free) / (1024**3), 2),
                        "used_pct": round(((size - free) / size) * 100, 1) if size else 0
                    }
            info["storage"] = cleaned_disks
            info["physical_drives"] = get_cim_all_list("Win32_DiskDrive")
        except: pass

        # 6. Network details
        try:
            net_res = subprocess.run('powershell -NoProfile -Command "Get-NetIPAddress -AddressFamily IPv4 | Where-Object IPAddress -notmatch \'127.0.0.1\' | Select-Object IPAddress, InterfaceAlias | ConvertTo-Json"', capture_output=True, text=True, shell=True)
            if net_res.stdout.strip():
                net_data = json.loads(net_res.stdout)
                if not isinstance(net_data, list): net_data = [net_data]
                info["network"]["adapters"] = net_data
            info["network"]["adapters_config"] = get_cim_all_list("Win32_NetworkAdapterConfiguration where IPEnabled=True")
        except: pass

        # 7. Processes summary
        try:
            p_count = subprocess.run("powershell -NoProfile -Command \"(Get-CimInstance Win32_Process).Count\"", capture_output=True, text=True, shell=True)
            if p_count.stdout.strip().isdigit():
                info["processes"]["count"] = int(p_count.stdout.strip())
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

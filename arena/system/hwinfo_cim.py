"""Windows-style hwinfo collector implementation."""
from __future__ import annotations

import datetime
import json
import os
import platform
import subprocess
import sys

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

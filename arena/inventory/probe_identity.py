"""Inventory probe group extracted from scripts/inventory.py."""
from __future__ import annotations

from arena.inventory.probe_common import *  # noqa: F401,F403

def get_identity() -> dict:
    return {
        "user": getpass.getuser(),
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "cwd": str(Path.cwd()),
        "home": str(Path.home()),
        "uid": os.getuid() if hasattr(os, "getuid") else None,
        "gid": os.getgid() if hasattr(os, "getgid") else None,
        "tty": os.environ.get("TERM_PROGRAM") or os.environ.get("TERM") or "",
        "shell": os.environ.get("SHELL") or os.environ.get("COMSPEC") or "",
    }

def get_os() -> dict:
    sys_name = platform.system()
    info: dict[str, Any] = {
        "system": sys_name,
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform_string": platform.platform(),
    }
    if sys_name == "Linux":
        # /etc/os-release
        try:
            os_rel = {}
            with open("/etc/os-release") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        os_rel[k] = v.strip('"')
            info["distro"] = {
                "name": os_rel.get("NAME") or os_rel.get("ID"),
                "id": os_rel.get("ID"),
                "version": os_rel.get("VERSION") or os_rel.get("VERSION_ID"),
                "pretty": os_rel.get("PRETTY_NAME"),
                "codename": os_rel.get("VERSION_CODENAME"),
            }
        except Exception:
            pass
        # Kernel build
        info["kernel"] = _run(["uname", "-srvmo"]).strip()
        # Uptime
        try:
            with open("/proc/uptime") as f:
                up = float(f.read().split()[0])
            info["uptime_seconds"] = int(up)
        except Exception:
            pass
    elif sys_name == "Darwin":
        info["product_name"] = _run(["sw_vers", "-productName"]).strip()
        info["product_version"] = _run(["sw_vers", "-productVersion"]).strip()
        info["build_version"] = _run(["sw_vers", "-buildVersion"]).strip()
    elif sys_name == "Windows":
        # win32_operatingsystem for build/caption
        blocks = _get_cim_json("Win32_OperatingSystem", "Caption,Version,BuildNumber,OSArchitecture,InstallDate,LastBootUpTime")
        if blocks:
            d = blocks[0]
            info["caption"] = str(d.get("Caption", ""))
            info["build_number"] = str(d.get("BuildNumber", ""))
            info["architecture"] = str(d.get("OSArchitecture", ""))
            for key, src in [("install_date", "InstallDate"), ("last_boot", "LastBootUpTime")]:
                info[key] = _cim_dt(d.get(src, ""))
    return info

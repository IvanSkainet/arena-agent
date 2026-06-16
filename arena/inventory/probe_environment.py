"""Inventory probe group."""
from __future__ import annotations

from arena.inventory.probe_common import *  # noqa: F401,F403

def get_thermal() -> dict:
    """Temperatures/fans where available without privileges."""
    sys_name = platform.system()
    info: dict[str, Any] = {"temperatures": []}
    if sys_name == "Linux":
        base = Path("/sys/class/thermal")
        if base.exists():
            for zone in sorted(base.glob("thermal_zone*"))[:32]:
                try:
                    typ = (zone / "type").read_text().strip()
                    raw = int((zone / "temp").read_text().strip())
                    info["temperatures"].append({"source": zone.name, "type": typ, "celsius": round(raw / 1000.0, 1)})
                except Exception:
                    pass
        if _which("sensors"):
            out = _run(["sensors", "-j"], timeout=5)
            if out:
                try:
                    info["lm_sensors"] = json.loads(out)
                except Exception:
                    text = _run(["sensors"], timeout=5)
                    if text:
                        info["sensors_text"] = text[:4000]
    elif sys_name == "Darwin":
        if _which("powermetrics"):
            info["note"] = "powermetrics is available but requires elevated privileges; skipped"
    elif sys_name == "Windows":
        # MSAcpi_ThermalZoneTemperature is not present on many desktops, but it
        # is safe and locale-independent when available.
        ps = (
            "Get-CimInstance MSAcpi_ThermalZoneTemperature -Namespace root/wmi -ErrorAction SilentlyContinue | "
            "Select-Object InstanceName,CurrentTemperature | ConvertTo-Json -Compress"
        )
        out = _run(_powershell_utf8_command(ps), timeout=10)
        try:
            data = json.loads(out) if out else []
            if isinstance(data, dict):
                data = [data]
            for d in data:
                k = d.get("CurrentTemperature")
                c = round((int(k) / 10.0) - 273.15, 1) if k else None
                info["temperatures"].append({"source": d.get("InstanceName"), "celsius": c})
        except Exception:
            pass
    return info

def get_network() -> dict:
    sys_name = platform.system()
    info: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "fqdn": socket.getfqdn(),
        "interfaces": [],
    }
    # local hostname-resolved IP
    try:
        info["primary_ip"] = socket.gethostbyname(socket.gethostname())
    except Exception:
        info["primary_ip"] = None

    if sys_name == "Linux":
        out = _run(["ip", "-o", "-4", "addr"], timeout=3)
        for line in out.splitlines():
            m = re.search(r"\d+:\s+(\S+)\s+inet\s+([\d.]+/\d+)", line)
            if m:
                info["interfaces"].append({
                    "name": m.group(1),
                    "ipv4": m.group(2),
                })
    elif sys_name == "Darwin":
        out = _run(["ifconfig"], timeout=3)
        cur = None
        for line in out.splitlines():
            m = re.match(r"^(\S+):\s+flags=", line)
            if m:
                cur = m.group(1)
            elif cur:
                mi = re.search(r"inet\s+([\d.]+)", line)
                if mi:
                    info["interfaces"].append({"name": cur, "ipv4": mi.group(1)})
    elif sys_name == "Windows":
        # PowerShell Get-NetIPAddress is locale-independent and structured
        out = _run(_powershell_utf8_command(
            "Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
            "Where-Object {$_.IPAddress -ne '127.0.0.1'} | "
            "Select-Object InterfaceAlias, IPAddress, PrefixLength | "
            "ConvertTo-Json -Compress -Depth 4"
        ), timeout=10)
        try:
            j = json.loads(out) if out else []
            if isinstance(j, dict):
                j = [j]
            for item in j:
                info["interfaces"].append({
                    "name": item.get("InterfaceAlias", ""),
                    "ipv4": f"{item.get('IPAddress', '')}/{item.get('PrefixLength', '')}",
                })
        except Exception:
            # Fallback to ipconfig
            out = _run(["ipconfig"], timeout=5)
            cur_name = None
            for raw in out.splitlines():
                line = raw.rstrip()
                if not line:
                    continue
                if not line.startswith(" "):
                    m = re.match(r"^.+?:\s*$", line)
                    if m:
                        cur_name = line.rstrip(":").strip()
                    continue
                if cur_name:
                    mi = re.search(r":\s*(\d+\.\d+\.\d+\.\d+)", line)
                    if mi:
                        info["interfaces"].append({"name": cur_name, "ipv4": mi.group(1).strip()})

    return info

def get_displays() -> dict:
    sys_name = platform.system()
    info: dict[str, Any] = {}
    if sys_name == "Linux":
        for v in ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "WAYLAND_DISPLAY",
                  "DISPLAY", "DESKTOP_SESSION", "GDMSESSION"):
            val = os.environ.get(v)
            if val:
                info[v] = val
        # xrandr if available
        if _which("xrandr"):
            out = _run(["xrandr", "--current"], timeout=3)
            screens = []
            for line in out.splitlines():
                m = re.match(r"^(\S+)\s+connected\s+(?:primary\s+)?(\d+x\d+\+\d+\+\d+)", line)
                if m:
                    screens.append({"output": m.group(1), "geometry": m.group(2)})
            if screens:
                info["screens"] = screens
    elif sys_name == "Darwin":
        out = _run(["system_profiler", "SPDisplaysDataType"], timeout=10)
        # Extract resolutions
        resolutions = re.findall(r"Resolution:\s*(\d+\s*x\s*\d+)", out)
        if resolutions:
            info["resolutions"] = resolutions
    elif sys_name == "Windows":
        screens: list[dict[str, Any]] = []
        # Win32_VideoController is more reliable than Win32_DesktopMonitor for
        # current resolution on modern Windows.
        for d in _get_cim_json("Win32_VideoController", "Name,CurrentHorizontalResolution,CurrentVerticalResolution"):
            w = d.get("CurrentHorizontalResolution")
            h = d.get("CurrentVerticalResolution")
            if w and h:
                screens.append({"name": str(d.get("Name", "")), "resolution": f"{w}x{h}"})
        if not screens:
            for d in _get_cim_json("Win32_DesktopMonitor", "Name,ScreenWidth,ScreenHeight"):
                w = d.get("ScreenWidth")
                h = d.get("ScreenHeight")
                if w and h:
                    screens.append({"name": str(d.get("Name", "")), "resolution": f"{w}x{h}"})
        if screens:
            info["screens"] = screens
    return info

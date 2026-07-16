"""Sensor probes: fans, battery, audio, SMART, cpu/gpu thermal detail.

Every probe returns a dict shaped like ``{"available": bool, ...}``
so downstream (Dashboard + agents) can distinguish "no sensor
present on this host" from "our probe failed". Probes are pure
best-effort and never raise -- upstream ``report.collect()``
catches any exception, but we prefer to catch it here so we can
still emit a useful ``{"available": False, "error": "..."}``.

Cross-platform expectations:
    * Linux    - primary target; /sys is authoritative, psutil is
                 the fallback, external CLIs (smartctl, pactl) are
                 used only when installed.
    * macOS    - system_profiler for hardware, psutil for battery.
                 Fans/SMART typically need privileges or third-party
                 daemons; probes degrade to available=False.
    * Windows  - PowerShell + CIM (Win32_Battery, Win32_Fan,
                 Win32_SoundDevice, Win32_DiskDrive via WMI SMART).
"""
from __future__ import annotations

from arena.inventory.probe_common import *  # noqa: F401,F403

# ------------------------------------------------------------------ battery

def get_battery() -> dict:
    """Battery state for laptops. available=False on most desktops."""
    try:
        import psutil  # type: ignore
    except Exception:
        psutil = None  # type: ignore
    info: dict[str, Any] = {"available": False}

    if psutil is not None:
        try:
            b = psutil.sensors_battery()
        except Exception:
            b = None
        if b is not None:
            info = {
                "available": True,
                "percent": round(float(b.percent), 1),
                "plugged": bool(b.power_plugged),
                "seconds_left": (
                    int(b.secsleft)
                    if b.secsleft not in (
                        getattr(psutil, "POWER_TIME_UNLIMITED", -1),
                        getattr(psutil, "POWER_TIME_UNKNOWN", -2),
                        -1, -2,
                    )
                    else None
                ),
            }

    # Linux: enrich with /sys/class/power_supply for design capacity,
    # cycle count, technology, manufacturer -- psutil does not expose
    # those.
    sys_name = platform.system()
    if sys_name == "Linux":
        base = Path("/sys/class/power_supply")
        if base.exists():
            batteries: list[dict[str, Any]] = []
            for ps in sorted(base.glob("BAT*")):
                bat: dict[str, Any] = {"name": ps.name}
                for field, cast in (
                    ("manufacturer", str),
                    ("model_name", str),
                    ("serial_number", str),
                    ("technology", str),
                    ("status", str),
                    ("capacity", int),
                    ("cycle_count", int),
                    ("energy_full", int),
                    ("energy_full_design", int),
                    ("voltage_now", int),
                    ("current_now", int),
                ):
                    try:
                        raw = (ps / field).read_text().strip()
                        bat[field] = cast(raw)
                    except Exception:
                        pass
                # Health = full / full_design
                try:
                    ef = bat.get("energy_full")
                    efd = bat.get("energy_full_design")
                    if ef and efd:
                        bat["health_pct"] = round(100.0 * ef / efd, 1)
                except Exception:
                    pass
                batteries.append(bat)
            if batteries:
                info["available"] = True
                info["batteries"] = batteries

    return info


# ------------------------------------------------------------------ fans

def get_fans() -> dict:
    """RPM per fan sensor. Uses psutil then lm-sensors fallback on Linux,
    WMI on Windows. macOS commonly needs SMC third-party helpers, so
    returns available=False.
    """
    info: dict[str, Any] = {"available": False, "fans": []}
    try:
        import psutil  # type: ignore
    except Exception:
        psutil = None  # type: ignore

    if psutil is not None and hasattr(psutil, "sensors_fans"):
        try:
            fans = psutil.sensors_fans()  # dict[chip -> list[shwtemp/fan]]
        except Exception:
            fans = {}
        if fans:
            for chip, entries in fans.items():
                for entry in entries:
                    info["fans"].append({
                        "chip": str(chip),
                        "label": getattr(entry, "label", "") or str(chip),
                        "rpm": int(getattr(entry, "current", 0) or 0),
                    })
            info["available"] = True

    if platform.system() == "Windows" and not info["fans"]:
        ps = (
            "Get-CimInstance Win32_Fan -ErrorAction SilentlyContinue | "
            "Select-Object Name,DesiredSpeed,Status,ActiveCooling | "
            "ConvertTo-Json -Compress -Depth 3"
        )
        out = _run(_powershell_utf8_command(ps), timeout=8)
        try:
            data = json.loads(out) if out else []
            if isinstance(data, dict):
                data = [data]
            for d in data:
                info["fans"].append({
                    "chip": "wmi",
                    "label": str(d.get("Name", "")),
                    "rpm": int(d.get("DesiredSpeed") or 0),
                    "status": d.get("Status"),
                    "active_cooling": d.get("ActiveCooling"),
                })
            if data:
                info["available"] = True
        except Exception:
            pass

    return info


# ------------------------------------------------------------------ audio

def get_audio() -> dict:
    """Audio sinks / sources. PulseAudio (pactl) on Linux, WMI on
    Windows, system_profiler on macOS."""
    info: dict[str, Any] = {"available": False, "sinks": [], "sources": []}
    sys_name = platform.system()

    if sys_name == "Linux":
        if _which("pactl"):
            for kind in ("sinks", "sources"):
                out = _run(["pactl", "list", "short", kind], timeout=3)
                for line in out.splitlines():
                    parts = line.split("\t")
                    if len(parts) >= 2:
                        info[kind].append({
                            "id": parts[0],
                            "name": parts[1],
                            "driver": parts[2] if len(parts) > 2 else None,
                            "state": parts[-1] if len(parts) > 3 else None,
                        })
            if info["sinks"] or info["sources"]:
                info["available"] = True
        elif _which("aplay"):
            out = _run(["aplay", "-l"], timeout=3)
            for line in out.splitlines():
                m = re.match(r"card\s+(\d+):\s+([^\[]+)\[(.+?)\]", line)
                if m:
                    info["sinks"].append({
                        "id": m.group(1),
                        "name": m.group(3).strip(),
                        "driver": m.group(2).strip(),
                    })
            if info["sinks"]:
                info["available"] = True

    elif sys_name == "Windows":
        ps = (
            "Get-CimInstance Win32_SoundDevice -ErrorAction SilentlyContinue | "
            "Select-Object Name,Manufacturer,Status,StatusInfo | "
            "ConvertTo-Json -Compress -Depth 3"
        )
        out = _run(_powershell_utf8_command(ps), timeout=8)
        try:
            data = json.loads(out) if out else []
            if isinstance(data, dict):
                data = [data]
            for d in data:
                info["sinks"].append({
                    "name": str(d.get("Name", "")),
                    "manufacturer": str(d.get("Manufacturer", "")),
                    "status": d.get("Status"),
                })
            if data:
                info["available"] = True
        except Exception:
            pass

    elif sys_name == "Darwin":
        out = _run(["system_profiler", "SPAudioDataType"], timeout=8)
        current: dict[str, Any] | None = None
        for line in out.splitlines():
            if line.strip().endswith(":") and not line.startswith(" "):
                if current:
                    info["sinks"].append(current)
                current = {"name": line.strip().rstrip(":")}
            elif current and ":" in line:
                k, _, v = line.strip().partition(":")
                if k and v:
                    current[k.strip().lower().replace(" ", "_")] = v.strip()
        if current:
            info["sinks"].append(current)
        if info["sinks"]:
            info["available"] = True

    return info


# ------------------------------------------------------------------ SMART

def _smartctl_permission_hint() -> str:
    """Platform-appropriate hint for granting smartctl the privileges
    it needs. v4.0.1: resolves the real smartctl path server-side so
    the hint is a runnable command the operator (or an agent via
    /v1/exec with NOPASSWD sudoers) can paste verbatim. The old
    ``$(command -v smartctl)`` form only works in an interactive bash
    session and returns an empty string when smartctl is not on PATH,
    silently producing an unusable ``sudo setcap ... ""`` command.
    """
    sys_name = platform.system()
    smartctl_path = _which("smartctl")

    if sys_name == "Linux":
        if smartctl_path:
            return (
                f"Grant smartctl the raw-IO capability so it can be run "
                f"as a regular user:  sudo setcap cap_sys_rawio+ep "
                f"{smartctl_path}  (persists until smartmontools is "
                f"reinstalled). Alternative: run the bridge as root, "
                f"or add ``ALL ALL=(ALL) NOPASSWD: {smartctl_path}`` "
                f"to a sudoers.d file so agents can invoke "
                f"``sudo -n {smartctl_path} ...`` on demand."
            )
        return (
            "smartctl is not on PATH. Install the smartmontools package "
            "first (Debian/Ubuntu: apt install smartmontools; "
            "Arch: pacman -S smartmontools; RHEL/Fedora: dnf install "
            "smartmontools), then grant it the raw-IO capability with "
            "sudo setcap cap_sys_rawio+ep /usr/sbin/smartctl "
            "(adjust path if your distro installs elsewhere)."
        )
    if sys_name == "Darwin":
        binhint = smartctl_path or "/opt/homebrew/bin/smartctl (Homebrew) or /usr/local/bin/smartctl"
        return (
            f"smartctl needs elevated privileges on macOS. Add a "
            f"passwordless sudoers rule for {binhint} so agents can "
            f"call ``sudo -n smartctl ...``, or run the bridge under "
            f"sudo. (There is no Linux-style file capability API on "
            f"Darwin.)"
        )
    if sys_name == "Windows":
        return (
            "smartctl needs Administrator privileges on Windows. Restart "
            "the bridge from an elevated PowerShell / cmd session, or "
            "wrap the service in NSSM with LocalSystem."
        )
    return (
        "smartctl needs elevated privileges. Run the bridge under an "
        "account that can open raw block devices."
    )


def get_disk_smart() -> dict:
    """SMART health per block device. Requires smartctl (smartmontools).
    Returns available=False when smartctl is not on PATH.
    """
    info: dict[str, Any] = {"available": False, "devices": []}
    if not _which("smartctl"):
        info["error"] = "smartctl not on PATH (install smartmontools)"
        return info

    sys_name = platform.system()
    scan_args = ["smartctl", "--scan", "--json=c"]
    if sys_name == "Windows":
        scan_args = ["smartctl", "--scan"]
    scan_out = _run(scan_args, timeout=6)
    if not scan_out:
        return info

    devices: list[str] = []
    try:
        scan = json.loads(scan_out)
        for d in scan.get("devices", []) or []:
            devices.append(d.get("name") or d.get("info_name") or "")
    except Exception:
        for line in scan_out.splitlines():
            m = re.match(r"^(\S+)\s+-d\s+(\S+)", line)
            if m:
                devices.append(m.group(1))
    devices = [d for d in devices if d][:12]

    for dev in devices:
        entry: dict[str, Any] = {"device": dev}
        out = _run(["smartctl", "-H", "-i", "-A", "--json=c", dev], timeout=8)
        try:
            j = json.loads(out) if out else {}
            # smartctl embeds permission / open errors in the
            # messages[] array even when it also returns a partial
            # JSON payload -- surface that hint so the operator
            # knows to run the bridge under root / add a udev rule /
            # give /usr/bin/smartctl a capability, rather than
            # thinking the drive is broken.
            for msg in j.get("smartctl", {}).get("messages", []) or []:
                if msg.get("severity") == "error":
                    text = str(msg.get("string", ""))
                    entry["error"] = text
                    if "permission" in text.lower():
                        entry["hint"] = _smartctl_permission_hint()
                    break
            entry["model"] = j.get("model_name") or j.get("device", {}).get("name")
            entry["serial"] = j.get("serial_number")
            entry["firmware"] = j.get("firmware_version")
            entry["capacity_gb"] = (
                round(j.get("user_capacity", {}).get("bytes", 0) / 1e9, 1) or None
            )
            entry["passed"] = j.get("smart_status", {}).get("passed")
            # NVMe health block
            nvme = j.get("nvme_smart_health_information_log") or {}
            if nvme:
                entry["temperature_c"] = nvme.get("temperature")
                entry["percent_used"] = nvme.get("percentage_used")
                entry["power_on_hours"] = nvme.get("power_on_hours")
                entry["available_spare_pct"] = nvme.get("available_spare")
                entry["media_errors"] = nvme.get("media_errors")
            # SATA attributes
            ata = j.get("ata_smart_attributes", {}).get("table", []) or []
            for attr in ata:
                name = str(attr.get("name", "")).lower()
                raw = attr.get("raw", {}).get("value")
                if name == "temperature_celsius":
                    entry["temperature_c"] = raw
                elif name == "power_on_hours":
                    entry["power_on_hours"] = raw
                elif name == "reallocated_sector_ct":
                    entry["reallocated_sectors"] = raw
        except Exception as e:
            entry["error"] = str(e)
        info["devices"].append(entry)

    info["available"] = bool(info["devices"])
    return info


# ------------------------------------------------------------------ thermal detail

def get_thermal_detail() -> dict:
    """Structured per-source temperatures with cpu/gpu/nvme classification.
    Complements the existing get_thermal() (which returns raw arrays).
    """
    info: dict[str, Any] = {"available": False, "sensors": []}
    try:
        import psutil  # type: ignore
    except Exception:
        psutil = None  # type: ignore

    if psutil is not None and hasattr(psutil, "sensors_temperatures"):
        try:
            temps = psutil.sensors_temperatures()
        except Exception:
            temps = {}
        for chip, entries in (temps or {}).items():
            for entry in entries:
                label = getattr(entry, "label", "") or chip
                low = (chip + " " + label).lower()
                cls = "other"
                if "coretemp" in low or "cpu" in low or "package" in low or "k10temp" in low:
                    cls = "cpu"
                elif "nvme" in low:
                    cls = "nvme"
                elif "gpu" in low or "amdgpu" in low or "nouveau" in low:
                    cls = "gpu"
                elif "acpi" in low or "wmi" in low:
                    cls = "board"
                info["sensors"].append({
                    "chip": str(chip),
                    "label": label,
                    "class": cls,
                    "celsius": round(float(getattr(entry, "current", 0) or 0), 1),
                    "high_c": (
                        round(float(entry.high), 1)
                        if getattr(entry, "high", None) not in (None, 0)
                        else None
                    ),
                    "critical_c": (
                        round(float(entry.critical), 1)
                        if getattr(entry, "critical", None) not in (None, 0)
                        else None
                    ),
                })
        if info["sensors"]:
            info["available"] = True

    # Fallback for Linux without psutil sensors: read /sys/class/thermal
    if not info["sensors"] and platform.system() == "Linux":
        base = Path("/sys/class/thermal")
        if base.exists():
            for zone in sorted(base.glob("thermal_zone*"))[:32]:
                try:
                    typ = (zone / "type").read_text().strip()
                    raw = int((zone / "temp").read_text().strip())
                    info["sensors"].append({
                        "chip": zone.name,
                        "label": typ,
                        "class": "other",
                        "celsius": round(raw / 1000.0, 1),
                        "high_c": None,
                        "critical_c": None,
                    })
                except Exception:
                    pass
            if info["sensors"]:
                info["available"] = True

    return info

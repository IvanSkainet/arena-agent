"""Device discovery and capability probe for the Arena mobile domain.

Wraps `adb devices -l` and a handful of `adb shell` lookups so callers
get a stable, JSON-shaped snapshot of every connected phone without
touching the raw ADB output format themselves.

v3.83.0 expanded `device_info()` — now reports Wi-Fi (SSID, IP,
gateway), storage (data / sdcard free vs total), RAM total/available,
uptime, locale, timezone, security patch level, boot completed state,
and the current foreground activity. All queries are read-only.
"""
from __future__ import annotations

from typing import Any

from arena.mobile.adb import AdbNotFoundError, adb_version, find_adb, run


def list_devices() -> dict[str, Any]:
    """Return every ADB-visible device with connection metadata."""
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {
            "ok": False,
            "adb_installed": False,
            "adb_path": None,
            "adb_version": None,
            "devices": [],
            "hint": install_hint(),
        }

    try:
        r = run(["devices", "-l"], timeout=10)
    except (AdbNotFoundError, Exception) as e:
        return {
            "ok": False,
            "adb_installed": True,
            "adb_path": find_adb(),
            "adb_version": adb_version(),
            "devices": [],
            "hint": f"adb devices failed: {e}",
        }

    devices = _parse_devices(r.stdout or "")

    result: dict[str, Any] = {
        "ok": True,
        "adb_installed": True,
        "adb_path": find_adb(),
        "adb_version": adb_version(),
        "devices": devices,
        "hint": None,
    }
    if not devices:
        result["hint"] = (
            "adb is installed but no devices are connected. Plug your phone in via USB, "
            "enable USB debugging in Developer Options, then tap 'Allow' on the phone's "
            "authorization prompt. For wireless ADB (Android 11+) run `adb pair` first."
        )
    elif all(d["state"] == "unauthorized" for d in devices):
        result["hint"] = (
            "Device connected but shows as 'unauthorized'. Unlock the phone and tap "
            "'Allow USB debugging' on the confirmation dialog. If the dialog does not "
            "appear, toggle USB debugging off/on in Developer Options."
        )
    return result


def _parse_devices(out: str) -> list[dict[str, Any]]:
    """Parse the multi-line output of `adb devices -l`.

    Example line (real):
      SERIAL_HERE            device usb:1-2 product:volla model:VOLLA_X device:volla transport_id:5
    Or when the device is unauthorised:
      SERIAL_HERE            unauthorized usb:1-2 transport_id:3
    Or for a WiFi/network device:
      192.168.1.5:5555       device product:volla model:VOLLA_X device:volla transport_id:7
    """
    devices: list[dict[str, Any]] = []
    for line in (out or "").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("List of devices") or line.startswith("*"):
            continue

        parts = line.split()
        if len(parts) < 2:
            continue
        serial = parts[0]
        state = parts[1]
        kv: dict[str, str] = {}
        for tok in parts[2:]:
            if ":" in tok:
                key, val = tok.split(":", 1)
                if key and val:
                    kv[key] = val

        ip = None
        if ":" in serial and serial.count(".") == 3:
            ip = serial.split(":", 1)[0]

        devices.append({
            "serial": serial,
            "state": state,
            "product": kv.get("product", ""),
            "model": kv.get("model", ""),
            "device": kv.get("device", ""),
            "transport_id": kv.get("transport_id", ""),
            "usb": kv.get("usb"),
            "ip": ip,
        })
    return devices


# ---------------------------------------------------------------------------
# Full device probe — split into small helpers so each `dumpsys` failure
# is contained and the caller still gets partial info.
# ---------------------------------------------------------------------------

_PROPS_OF_INTEREST: dict[str, str] = {
    "manufacturer": "ro.product.manufacturer",
    "model": "ro.product.model",
    "device": "ro.product.device",
    "brand": "ro.product.brand",
    "android_version": "ro.build.version.release",
    "android_sdk": "ro.build.version.sdk",
    "android_codename": "ro.build.version.codename",
    "android_security_patch": "ro.build.version.security_patch",
    "build_id": "ro.build.id",
    "build_type": "ro.build.type",
    "build_tags": "ro.build.tags",
    "build_date": "ro.build.date",
    "fingerprint": "ro.build.fingerprint",
    "bootloader": "ro.bootloader",
    "cpu_abi": "ro.product.cpu.abi",
    "cpu_abi_list": "ro.product.cpu.abilist",
    "hardware": "ro.hardware",
    "board": "ro.product.board",
    "locale": "ro.product.locale",
    "hyperos_version": "ro.mi.os.version.incremental",
    "miui_version": "ro.miui.ui.version.name",
    "serialno": "ro.serialno",
}


def device_info(serial: str) -> dict[str, Any]:
    """Deeper per-device probe. Read-only; never installs or reboots.

    Layered probes so an outage in one dumpsys call (e.g. HyperOS
    ROM removing a service) never blanks the whole response.
    Extended in v3.83.1 with display refresh rates, power/screen state,
    UI mode (airplane/dark/ringer/timeout/brightness), mobile operator
    (no PII), package counts, kernel, SELinux/verified boot, current IME,
    developer toggles, FS encryption, and sensor count.
    """
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}

    info: dict[str, Any] = {"ok": True, "serial": serial}

    # Batch all getprop calls into one shell — dramatically faster than
    # 20 round-trips.
    info.update(_probe_props(serial))
    info.update(_probe_screen(serial))
    info.update(_probe_battery(serial))
    info.update(_probe_wifi(serial))
    info.update(_probe_storage(serial))
    info.update(_probe_memory(serial))
    info.update(_probe_uptime(serial))
    info.update(_probe_locale(serial))
    info.update(_probe_foreground(serial))

    # v3.83.1: extended probes live in their own module to keep this
    # file focused. Each probe is fail-soft (returns {} on any error).
    from arena.mobile import devices_probes as _p
    info.update(_p.probe_display_modes(serial))
    info.update(_p.probe_power_state(serial))
    info.update(_p.probe_ui_mode(serial))
    info.update(_p.probe_network(serial))
    info.update(_p.probe_packages_count(serial))
    info.update(_p.probe_kernel(serial))
    info.update(_p.probe_selinux(serial))
    info.update(_p.probe_ime(serial))
    info.update(_p.probe_developer_options(serial))
    info.update(_p.probe_encryption(serial))
    info.update(_p.probe_sensor_summary(serial))

    return info


def _sh(serial: str, args: list[str], timeout: int = 5) -> str:
    """Shorthand: run adb shell command, return stripped stdout or ''."""
    try:
        r = run(["shell", *args], serial=serial, timeout=timeout)
    except Exception:
        return ""
    if r.returncode != 0:
        return ""
    return (r.stdout or "").strip()


def _probe_props(serial: str) -> dict[str, Any]:
    """Batch every `getprop` into a single shell call."""
    # `getprop` with no args dumps every property in [key]: [value] form,
    # then we cherry-pick. One round-trip instead of ~20 saves ~500ms
    # over Tailnet.
    out = _sh(serial, ["getprop"], timeout=8)
    if not out:
        return {}
    props: dict[str, str] = {}
    for line in out.splitlines():
        # Format: [ro.product.model]: [24117RK2CG]
        if not line.startswith("["):
            continue
        try:
            key_part, _, val_part = line.partition("]: [")
            key = key_part.lstrip("[")
            val = val_part.rstrip("]")
        except Exception:
            continue
        if key:
            props[key] = val

    got: dict[str, Any] = {}
    for label, key in _PROPS_OF_INTEREST.items():
        val = props.get(key)
        if val:
            got[label] = val
    return got


def _probe_screen(serial: str) -> dict[str, Any]:
    """Screen size (physical + override) and density."""
    out: dict[str, Any] = {}
    size_txt = _sh(serial, ["wm", "size"])
    for line in size_txt.splitlines():
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        value = value.strip()
        if "Physical size" in label:
            out["screen_size_physical"] = value
        elif "Override size" in label:
            out["screen_size_override"] = value

    density_txt = _sh(serial, ["wm", "density"])
    for line in density_txt.splitlines():
        if ":" not in line:
            continue
        label, _, value = line.partition(":")
        value = value.strip()
        if "Physical density" in label:
            out["density_physical"] = value
        elif "Override density" in label:
            out["density_override"] = value
    return out


def _probe_battery(serial: str) -> dict[str, Any]:
    """Battery snapshot from `dumpsys battery`."""
    text = _sh(serial, ["dumpsys", "battery"])
    if not text:
        return {}
    battery: dict[str, str] = {}
    wanted = (
        "level:", "scale:", "status:", "health:", "temperature:", "voltage:",
        "technology:", "AC powered:", "USB powered:", "Wireless powered:",
        "Max charging current:", "Max charging voltage:",
    )
    for line in text.splitlines():
        line = line.strip()
        for tag in wanted:
            if line.startswith(tag):
                k, _, v = line.partition(":")
                battery[k.strip().lower().replace(" ", "_")] = v.strip()
                break
    return {"battery": battery} if battery else {}


def _probe_wifi(serial: str) -> dict[str, Any]:
    """Wi-Fi state via `dumpsys wifi` — best-effort, guarded for HyperOS quirks."""
    text = _sh(serial, ["dumpsys", "wifi"], timeout=6)
    if not text:
        return {}
    wifi: dict[str, Any] = {}
    for line in text.splitlines():
        line = line.strip()
        # `mWifiInfo`: SSID: "...", BSSID: aa:bb:..., RSSI: -47, Link speed: ...
        if line.startswith("mWifiInfo"):
            # Truncate to a single line for the dashboard — do not paste
            # thousands of chars of dumpsys.
            wifi["info_line"] = line[:400]
        elif line.startswith("Wi-Fi is"):
            wifi["state"] = line
    # ip address: pick from `ip -f inet addr show` — much cleaner.
    ip_txt = _sh(serial, ["ip", "-f", "inet", "addr", "show", "wlan0"])
    for line in ip_txt.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            wifi["ipv4"] = line.split()[1]
            break
    return {"wifi": wifi} if wifi else {}


def _probe_storage(serial: str) -> dict[str, Any]:
    """`/data` and `/sdcard` free / total in MB via `df -h`."""
    text = _sh(serial, ["df", "-h", "/data", "/sdcard"])
    if not text:
        return {}
    entries: list[dict[str, str]] = []
    lines = text.splitlines()
    header_seen = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if not header_seen and line.lower().startswith("filesystem"):
            header_seen = True
            continue
        cols = line.split()
        if len(cols) < 6:
            continue
        entries.append({
            "filesystem": cols[0],
            "size": cols[1],
            "used": cols[2],
            "avail": cols[3],
            "use_pct": cols[4],
            "mount": cols[5],
        })
    return {"storage": entries} if entries else {}


def _probe_memory(serial: str) -> dict[str, Any]:
    """Total / available / free memory in KB from `/proc/meminfo`."""
    text = _sh(serial, ["cat", "/proc/meminfo"])
    if not text:
        return {}
    mem: dict[str, str] = {}
    wanted = ("MemTotal:", "MemAvailable:", "MemFree:", "SwapTotal:", "SwapFree:")
    for line in text.splitlines():
        for tag in wanted:
            if line.startswith(tag):
                mem[tag.rstrip(":").lower()] = line.split(":", 1)[1].strip()
                break
    return {"memory": mem} if mem else {}


def _probe_uptime(serial: str) -> dict[str, Any]:
    """Uptime as returned by `uptime`."""
    text = _sh(serial, ["uptime"])
    if text:
        return {"uptime": text.splitlines()[0]}
    return {}


def _probe_locale(serial: str) -> dict[str, Any]:
    """Locale + timezone from the persist.* namespace."""
    out: dict[str, Any] = {}
    tz = _sh(serial, ["getprop", "persist.sys.timezone"])
    if tz:
        out["timezone"] = tz
    lang = _sh(serial, ["getprop", "persist.sys.locale"])
    if lang:
        out["locale_current"] = lang
    return out


def _probe_foreground(serial: str) -> dict[str, Any]:
    """Currently focused app / activity — useful for `agent, what am I looking at?`."""
    # `dumpsys activity activities | grep -i topResumedActivity` is the
    # canonical way, but the shell allowlist forbids `|`. We fetch the
    # full dump and parse in Python instead.
    text = _sh(serial, ["dumpsys", "activity", "activities"], timeout=8)
    if not text:
        return {}
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("topResumedActivity="):
            return {"foreground_activity": s.split("=", 1)[1].strip().rstrip("}")}
        if s.startswith("mResumedActivity"):
            # Older Android: "mResumedActivity: ActivityRecord{... u0 com.pkg/.Main ...}"
            return {"foreground_activity": s[:200]}
    return {}

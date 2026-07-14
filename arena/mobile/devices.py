"""Device discovery and capability probe for the Arena mobile domain.

Wraps `adb devices -l` and a handful of `adb shell getprop` lookups so
callers get a stable, JSON-shaped snapshot of every connected phone
without touching the raw ADB output format themselves.
"""
from __future__ import annotations

from typing import Any

from arena.mobile.adb import AdbNotFoundError, adb_version, find_adb, run


def list_devices() -> dict[str, Any]:
    """Return every ADB-visible device with connection metadata.

    Response shape:
      {
        "ok": bool,
        "adb_installed": bool,
        "adb_path": str | None,
        "adb_version": str | None,
        "devices": [
          {"serial": str, "state": "device" | "unauthorized" | "offline" | ...,
           "product": str, "model": str, "device": str, "transport_id": str,
           "usb": str | None, "ip": str | None}
        ],
        "hint": str | None,   # populated when nothing is connected/authorised
      }
    """
    if find_adb() is None:
        # Import lazily so this stays importable in test envs without adb.
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
        # Skip the "List of devices attached" header and any adb daemon
        # noise ("* daemon started successfully *").
        if line.startswith("List of devices"):
            continue
        if line.startswith("*"):
            continue

        parts = line.split()
        if len(parts) < 2:
            continue
        serial = parts[0]
        state = parts[1]
        # Everything after state is key:value pairs. Ignore stray tokens.
        kv: dict[str, str] = {}
        for tok in parts[2:]:
            if ":" in tok:
                key, val = tok.split(":", 1)
                if key and val:
                    kv[key] = val

        ip = None
        # Network-attached devices identify themselves as "host:port".
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


def device_info(serial: str) -> dict[str, Any]:
    """Deeper per-device probe via `getprop` and a few small shell calls.

    Only touches read-only queries; never installs, reboots, or reconfigures.
    """
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}

    info: dict[str, Any] = {"ok": True, "serial": serial}

    props_of_interest = {
        "manufacturer": "ro.product.manufacturer",
        "model": "ro.product.model",
        "device": "ro.product.device",
        "brand": "ro.product.brand",
        "android_version": "ro.build.version.release",
        "android_sdk": "ro.build.version.sdk",
        "build_id": "ro.build.id",
        "fingerprint": "ro.build.fingerprint",
        "cpu_abi": "ro.product.cpu.abi",
        "hyperos_version": "ro.mi.os.version.incremental",
        "miui_version": "ro.miui.ui.version.name",
    }
    got: dict[str, str] = {}
    for label, key in props_of_interest.items():
        try:
            r = run(["shell", "getprop", key], serial=serial, timeout=5)
            val = (r.stdout or "").strip()
            if val:
                got[label] = val
        except Exception:
            continue
    info.update(got)

    # Screen size (works on nearly every Android, may be split by orientation).
    try:
        r = run(["shell", "wm", "size"], serial=serial, timeout=5)
        # "Physical size: 1440x3200" (+ "Override size: ..." on some phones)
        for line in (r.stdout or "").splitlines():
            if "Physical size" in line and ":" in line:
                info["screen_size_physical"] = line.split(":", 1)[1].strip()
            elif "Override size" in line and ":" in line:
                info["screen_size_override"] = line.split(":", 1)[1].strip()
    except Exception:
        pass

    # Screen density.
    try:
        r = run(["shell", "wm", "density"], serial=serial, timeout=5)
        for line in (r.stdout or "").splitlines():
            if "Physical density" in line and ":" in line:
                info["density_physical"] = line.split(":", 1)[1].strip()
            elif "Override density" in line and ":" in line:
                info["density_override"] = line.split(":", 1)[1].strip()
    except Exception:
        pass

    # Battery snapshot.
    try:
        r = run(["shell", "dumpsys", "battery"], serial=serial, timeout=5)
        battery: dict[str, str] = {}
        for line in (r.stdout or "").splitlines():
            line = line.strip()
            for key_looking_for in ("level:", "status:", "temperature:", "AC powered:", "USB powered:", "Wireless powered:"):
                if line.startswith(key_looking_for):
                    k, _, v = line.partition(":")
                    battery[k.strip().lower().replace(" ", "_")] = v.strip()
        if battery:
            info["battery"] = battery
    except Exception:
        pass

    return info

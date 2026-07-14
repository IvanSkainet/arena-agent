"""Extended device probes for `device_info()` — v3.83.1 expansion.

Split out of `devices.py` so the core module stays readable. Each
probe is deliberately defensive: any failure is swallowed and returns
an empty dict, so a broken `dumpsys` on one exotic ROM never breaks
the whole /info response.

Naming rule: everything private (`_sh`, `_probe_*`) mirrors
`devices.py::_sh` so callers can add new probes without a new import.
"""
from __future__ import annotations

import re
from typing import Any

from arena.mobile.adb import run


def _sh(serial: str, args: list[str], timeout: int = 5) -> str:
    """Shorthand: run adb shell command, return stripped stdout or ''."""
    try:
        r = run(["shell", *args], serial=serial, timeout=timeout)
    except Exception:
        return ""
    if r.returncode != 0:
        return ""
    return (r.stdout or "").strip()


def probe_display_modes(serial: str) -> dict[str, Any]:
    """Refresh rates + active mode from `dumpsys display`.

    Reports (when detectable):
      display.active_refresh_rate  — currently rendering at this Hz
      display.supported_refresh_rates  — list of Hz values
      display.hdr_types  — list of supported HDR type ints (1=Dolby, 2=HDR10, 3=HLG, 4=HDR10+)
      display.rounded_corner_radius_px
    """
    text = _sh(serial, ["dumpsys", "display"], timeout=8)
    if not text:
        return {}
    out: dict[str, Any] = {}

    # renderFrameRate 120.00001
    m = re.search(r"renderFrameRate\s+([\d.]+)", text)
    if m:
        out["active_refresh_rate"] = round(float(m.group(1)), 1)

    # supportedRefreshRates [120.00001, 90.0, 60.000004]
    m = re.search(r"supportedRefreshRates\s+\[([\d.,\s]+)\]", text)
    if m:
        try:
            rates = sorted({round(float(x.strip()), 1)
                            for x in m.group(1).split(",") if x.strip()},
                           reverse=True)
            out["supported_refresh_rates"] = rates
        except ValueError:
            pass

    # mSupportedHdrTypes=[1, 2, 3, 4]
    m = re.search(r"mSupportedHdrTypes=\[([\d,\s]+)\]", text)
    if m:
        try:
            out["hdr_types"] = [int(x.strip()) for x in m.group(1).split(",") if x.strip()]
        except ValueError:
            pass

    # RoundedCorner{position=TopLeft, radius=120, ...}
    m = re.search(r"RoundedCorner\{position=\w+,\s*radius=(\d+)", text)
    if m:
        out["rounded_corner_radius_px"] = int(m.group(1))

    return {"display": out} if out else {}


def probe_power_state(serial: str) -> dict[str, Any]:
    """Screen on/off, wakefulness, thermal, low-power mode.

    Reports:
      power.wakefulness  — Awake / Dozing / Asleep / Dreaming
      power.screen_on  — bool
      power.low_power_mode  — bool
      power.charging  — bool (from mPlugType != 0 or dumpsys)
    """
    text = _sh(serial, ["dumpsys", "power"], timeout=6)
    if not text:
        return {}
    out: dict[str, Any] = {}

    m = re.search(r"mWakefulness=(\w+)", text)
    if m:
        val = m.group(1)
        out["wakefulness"] = val
        out["screen_on"] = val == "Awake"
    m = re.search(r"mSettingBatterySaverEnabled=(true|false)", text)
    if m:
        out["low_power_mode"] = m.group(1) == "true"
    m = re.search(r"mPlugType=(\d+)", text)
    if m:
        out["charging"] = int(m.group(1)) != 0

    return {"power": out} if out else {}


def probe_ui_mode(serial: str) -> dict[str, Any]:
    """Airplane mode, dark theme, ringer mode, screen timeout, brightness.

    These are read via `settings get` (allowlisted read-only sub-verb),
    not the `settings put` writer, so we can never accidentally toggle
    them.
    """
    out: dict[str, Any] = {}
    airplane = _sh(serial, ["settings", "get", "global", "airplane_mode_on"])
    if airplane in ("0", "1"):
        out["airplane_mode"] = airplane == "1"

    # ui_night_mode: 0=undefined, 1=off, 2=on, 3=custom(auto)
    night = _sh(serial, ["settings", "get", "secure", "ui_night_mode"])
    night_map = {"0": "auto/unset", "1": "light", "2": "dark", "3": "custom"}
    if night in night_map:
        out["night_mode"] = night_map[night]

    # dumpsys audio ringer:  ringer mode(internal) = 2  (0=silent, 1=vibrate, 2=normal)
    audio = _sh(serial, ["dumpsys", "audio"], timeout=6)
    m = re.search(r"ringer mode\(internal\)\s*=\s*(\d)", audio)
    ringer_map = {"0": "silent", "1": "vibrate", "2": "normal"}
    if m and m.group(1) in ringer_map:
        out["ringer_mode"] = ringer_map[m.group(1)]

    timeout_ms = _sh(serial, ["settings", "get", "system", "screen_off_timeout"])
    try:
        if timeout_ms:
            out["screen_off_timeout_sec"] = int(timeout_ms) // 1000
    except ValueError:
        pass

    brightness = _sh(serial, ["settings", "get", "system", "screen_brightness"])
    try:
        if brightness:
            out["screen_brightness_raw"] = int(brightness)
    except ValueError:
        pass

    auto_rot = _sh(serial, ["settings", "get", "system", "accelerometer_rotation"])
    if auto_rot in ("0", "1"):
        out["auto_rotate"] = auto_rot == "1"

    return {"ui_mode": out} if out else {}


def probe_network(serial: str) -> dict[str, Any]:
    """Mobile network operator + type. SIM ICCID / IMSI are NOT read.

    Reports:
      network.operator_alpha  — human-readable operator name (e.g. "beeline")
      network.operator_iso  — 2-letter country code
      network.mobile_type  — LTE / IWLAN / 5G / NR / Unknown
      network.sim_state  — LOADED / ABSENT / etc
      network.data_enabled  — bool
    """
    # ONLY read the "alpha" (operator display name) and iso country —
    # never the ICCID (SIM serial) or IMSI (subscriber id).
    props_text = _sh(serial, ["getprop"], timeout=6)
    out: dict[str, Any] = {}
    for line in props_text.splitlines():
        if not line.startswith("["):
            continue
        try:
            key_part, _, val_part = line.partition("]: [")
            k = key_part.lstrip("[")
            v = val_part.rstrip("]")
        except Exception:
            continue
        # Multi-sim reports comma-separated values — take the first.
        first = v.split(",", 1)[0] if v else ""
        if k == "gsm.operator.alpha" and first:
            out["operator_alpha"] = first
        elif k == "gsm.operator.iso-country" and first:
            out["operator_iso"] = first
        elif k == "gsm.network.type" and first:
            out["mobile_type"] = first
        elif k == "gsm.sim.state" and first:
            out["sim_state"] = first
        elif k == "gsm.operator.isroaming" and first in ("true", "false"):
            out["roaming"] = first == "true"

    data_enabled = _sh(serial, ["settings", "get", "global", "mobile_data"])
    if data_enabled in ("0", "1"):
        out["data_enabled"] = data_enabled == "1"

    return {"network": out} if out else {}


def probe_packages_count(serial: str) -> dict[str, Any]:
    """Number of user vs system packages (no PII, just totals)."""
    user_out = _sh(serial, ["pm", "list", "packages", "-3"], timeout=6)
    sys_out = _sh(serial, ["pm", "list", "packages", "-s"], timeout=6)
    disabled_out = _sh(serial, ["pm", "list", "packages", "-d"], timeout=6)
    out: dict[str, Any] = {}
    if user_out:
        out["user_installed"] = sum(1 for L in user_out.splitlines() if L.strip())
    if sys_out:
        out["system"] = sum(1 for L in sys_out.splitlines() if L.strip())
    if disabled_out:
        out["disabled"] = sum(1 for L in disabled_out.splitlines() if L.strip())
    return {"packages_count": out} if out else {}


def probe_kernel(serial: str) -> dict[str, Any]:
    """Kernel version from /proc/version."""
    text = _sh(serial, ["cat", "/proc/version"])
    if text:
        return {"kernel": text.strip().splitlines()[0][:200]}
    return {}


def probe_selinux(serial: str) -> dict[str, Any]:
    """SELinux enforcement + Verified Boot state."""
    out: dict[str, Any] = {}
    se = _sh(serial, ["getprop", "ro.boot.selinux"])
    if se:
        out["selinux"] = se
    vb = _sh(serial, ["getprop", "ro.boot.verifiedbootstate"])
    if vb:
        out["verified_boot"] = vb  # green / yellow / orange / red
    return out


def probe_ime(serial: str) -> dict[str, Any]:
    """Current default IME and count of enabled/available IMEs.

    Reports:
      ime.current  — package/service name of the current IME (e.g. LatinIME)
      ime.enabled_count  — number of enabled IMEs
      ime.available_count  — number of installed IMEs
    """
    out: dict[str, Any] = {}
    cur = _sh(serial, ["settings", "get", "secure", "default_input_method"])
    if cur and cur != "null":
        out["current"] = cur

    enabled = _sh(serial, ["ime", "list", "-s"], timeout=6)
    if enabled:
        out["enabled_count"] = sum(1 for L in enabled.splitlines() if L.strip())
    avail = _sh(serial, ["ime", "list", "-s", "-a"], timeout=6)
    if avail:
        out["available_count"] = sum(1 for L in avail.splitlines() if L.strip())
    return {"ime": out} if out else {}


def probe_developer_options(serial: str) -> dict[str, Any]:
    """Developer-facing toggles — useful for the agent to know what
    it can/can't do."""
    out: dict[str, Any] = {}
    for scope, key, label in [
        ("global", "adb_enabled", "adb_enabled"),
        ("global", "development_settings_enabled", "developer_options_enabled"),
        ("global", "stay_on_while_plugged_in", "stay_awake_while_charging"),
        ("global", "install_non_market_apps", "install_from_unknown_sources"),
        ("secure", "adb_wifi_enabled", "adb_wifi_enabled"),
        ("global", "usb_debugging_secure_settings", "usb_debug_security_settings"),
    ]:
        val = _sh(serial, ["settings", "get", scope, key])
        if val and val != "null":
            # Booleans in Android settings are typically "0" / "1" / "0"
            # or integer bitmasks (stay_on_while_plugged_in). Report the
            # raw value and a bool interpretation when unambiguous.
            entry: Any = val
            if val in ("0", "1"):
                entry = val == "1"
            out[label] = entry
    return {"developer": out} if out else {}


def probe_encryption(serial: str) -> dict[str, Any]:
    """Filesystem encryption state (file-based encryption / FBE is the
    modern default; we report whichever `getprop` exposes)."""
    out: dict[str, Any] = {}
    state = _sh(serial, ["getprop", "ro.crypto.state"])
    if state:
        out["state"] = state
    typ = _sh(serial, ["getprop", "ro.crypto.type"])
    if typ:
        out["type"] = typ  # file / block / none
    return {"encryption": out} if out else {}


def probe_sensor_summary(serial: str) -> dict[str, Any]:
    """Count of sensors reported by `dumpsys sensorservice`.

    We only take counts + a compact summary because the full sensorservice
    dump can be 20+ KB and expose accelerometer sample buffers that agents
    don't need.
    """
    text = _sh(serial, ["dumpsys", "sensorservice"], timeout=8)
    if not text:
        return {}
    # Sensor list section starts with "Sensor List:" — count the lines
    # that look like a sensor entry (start with a number and a space, or
    # start with "0x" hex handle).
    count = 0
    in_list = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("Sensor List:") or s.startswith("Sensors:"):
            in_list = True
            continue
        if in_list:
            if not s:
                break
            # Sensor entry lines look like: "0x00000001) accelerometer | ..."
            if re.match(r"^(0x[0-9a-fA-F]+\)|\d+\))\s", s):
                count += 1
    if count:
        return {"sensors": {"count": count}}
    return {}


def probe_others(serial: str) -> dict[str, Any]:
    """Grab the top-level system state that doesn't fit any of the
    named categories — GPU driver, camera count, radio versions,
    persist.* toggles, feature flags, and so on. Everything is
    ro./persist. so it's read-only and safe.

    Populates `others.{key: value}` where every key survived a
    lightweight PII filter (ICCID/IMSI/MAC/serial not included).
    """
    out: dict[str, str] = {}
    text = _sh(serial, ["getprop"], timeout=8)
    if not text:
        return {}

    # These prop prefixes tend to be useful but are excluded from the
    # dedicated probes above. We deliberately DON'T include gsm.sim.imsi,
    # gsm.sim.iccid, ro.serialno.original, ril.serialno (already covered
    # in probe_network's exclusion list).
    interesting_prefixes = (
        "ro.opengles.",       # GPU / GL driver
        "ro.hardware.",       # subsystems (camera vendor, wifi chip)
        "ro.vendor.",         # vendor-specific niceties
        "ro.config.",         # UX config
        "ro.telephony.",      # radio version bits (no numeric ids)
        "ro.baseband",
        "ro.miui.",           # MIUI feature flags
        "ro.mi.",             # POCO / Xiaomi extras
        "persist.sys.usb.",   # USB mode flags
        "persist.vendor.usb.",
        "persist.debug.",     # non-PII debug flags
        "dalvik.vm.",         # ART/VM heap sizes
        "ro.build.version.",  # patch level etc
        "ro.crypto.",
        "sys.usb.state",
        "vendor.debug.",
    )
    # Values that are PII-ish or already covered elsewhere.
    exclude_exact = {
        "ro.serialno", "ro.boot.serialno", "gsm.sim.iccid", "gsm.sim.imsi",
        "ril.serialnumber", "ro.ril.oem.imei", "ro.ril.oem.meid",
    }

    for line in text.splitlines():
        if not line.startswith("["):
            continue
        try:
            key_part, _, val_part = line.partition("]: [")
            k = key_part.lstrip("[")
            v = val_part.rstrip("]")
        except Exception:
            continue
        if not k or not v:
            continue
        if k in exclude_exact:
            continue
        # imei / iccid / mac hint filter: skip 10+ digit runs and MAC-shaped values
        if len(v) >= 10 and v.isdigit():
            continue
        if _looks_like_mac(v):
            continue
        # Match against prefix whitelist.
        for p in interesting_prefixes:
            if k.startswith(p):
                # Truncate to keep the response manageable.
                out[k] = v if len(v) <= 200 else v[:197] + "..."
                break
    if not out:
        return {}
    # Sort so the response is stable across probes (helps tests).
    out_sorted = {k: out[k] for k in sorted(out)}
    return {"others": out_sorted}


def _looks_like_mac(v: str) -> bool:
    """Detect strings that look like MAC addresses so we don't leak them."""
    stripped = v.replace(":", "").replace("-", "")
    if len(stripped) == 12 and all(c in "0123456789abcdefABCDEF" for c in stripped):
        return True
    return False

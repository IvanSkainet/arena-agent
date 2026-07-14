"""Sensor listing + last-value readout via `dumpsys sensorservice`.

Returns two things:
  * `sensors` — one entry per hardware sensor on the device (name,
    vendor, version, type integer + friendly type name, min/max rate,
    power draw, wake-up bit, resolution, flags).
  * `recent_events` — the most recent event (up to a caller-picked
    limit) for each sensor that has published anything since boot,
    parsed out of the "Recent Sensor events" section of the dumpsys
    dump. Values are the raw floats the sensor emitted, so an agent
    can read accelerometer XYZ, ambient light lux, proximity distance,
    magnetometer, etc. without having to install anything on the phone.

No sensor is *activated* by this call — we only read what other clients
have already subscribed to. That keeps the operation battery-neutral
and matches the read-only posture of the rest of the mobile domain.
"""
from __future__ import annotations

import re
from typing import Any

from arena.mobile.adb import AdbNotFoundError, find_adb, run

# Android SensorType constants — see hardware/libhardware/include/hardware/sensors.h
# and android.hardware.Sensor.TYPE_*. We only translate the common types;
# unknown handles fall back to "type_N" so the caller still sees the id.
_SENSOR_TYPE_NAMES: dict[int, str] = {
    1: "accelerometer",
    2: "magnetic_field",
    3: "orientation",
    4: "gyroscope",
    5: "light",
    6: "pressure",
    7: "temperature",              # deprecated, superseded by ambient_temperature
    8: "proximity",
    9: "gravity",
    10: "linear_acceleration",
    11: "rotation_vector",
    12: "relative_humidity",
    13: "ambient_temperature",
    14: "magnetic_field_uncalibrated",
    15: "game_rotation_vector",
    16: "gyroscope_uncalibrated",
    17: "significant_motion",
    18: "step_detector",
    19: "step_counter",
    20: "geomagnetic_rotation_vector",
    21: "heart_rate",
    22: "tilt_detector",
    23: "wake_gesture",
    24: "glance_gesture",
    25: "pick_up_gesture",
    26: "wrist_tilt_gesture",
    27: "device_orientation",
    28: "pose_6dof",
    29: "stationary_detect",
    30: "motion_detect",
    31: "heart_beat",
    32: "dynamic_sensor_meta",
    33: "additional_info",
    34: "low_latency_offbody_detect",
    35: "accelerometer_uncalibrated",
    36: "hinge_angle",
    37: "head_tracker",
    38: "accelerometer_limited_axes",
    39: "gyroscope_limited_axes",
    40: "accelerometer_limited_axes_uncalibrated",
    41: "gyroscope_limited_axes_uncalibrated",
    42: "heading",
}

# Human-friendly names for the value channels each sensor type reports.
# Matches Android's SensorEvent.values convention. For sensor types we
# don't recognise, values are returned as an anonymous list.
_SENSOR_CHANNELS: dict[int, list[str]] = {
    1: ["x", "y", "z"],                            # accelerometer m/s^2
    2: ["x", "y", "z"],                            # magnetic uT
    3: ["azimuth", "pitch", "roll"],               # orientation deg (deprecated)
    4: ["x", "y", "z"],                            # gyroscope rad/s
    5: ["lux"],                                    # light
    6: ["hPa"],                                    # pressure
    8: ["cm"],                                     # proximity
    9: ["x", "y", "z"],                            # gravity m/s^2
    10: ["x", "y", "z"],                           # linear acceleration
    11: ["x", "y", "z", "cos", "acc"],             # rotation vector
    12: ["percent"],                               # humidity
    13: ["celsius"],                               # ambient temperature
    14: ["x", "y", "z", "bias_x", "bias_y", "bias_z"],  # mag uncalibrated
    15: ["x", "y", "z", "cos", "acc"],             # game rotation vector
    16: ["x", "y", "z", "bias_x", "bias_y", "bias_z"],  # gyro uncalibrated
    19: ["count"],                                 # step counter
    21: ["bpm"],                                   # heart rate
    36: ["angle_deg"],                             # hinge angle
    42: ["heading_deg", "acc_deg"],                # heading
}


def _err(msg: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": msg}
    payload.update(extra)
    return payload


def _ensure_adb() -> dict[str, Any] | None:
    if find_adb() is None:
        from arena.mobile.adb import install_hint
        return {"ok": False, "error": "adb not installed", "hint": install_hint()}
    return None


def list_sensors(
    serial: str,
    *,
    include_recent_events: bool = True,
    events_per_sensor: int = 1,
) -> dict[str, Any]:
    """Return every hardware sensor + optional recent-values readout.

    Args:
      include_recent_events: also parse the "Recent Sensor events"
        section for last-N values per sensor.
      events_per_sensor: how many events to keep per sensor (1..10).
        Defaults to 1 so the response stays JSON-small; agents that
        want a short time series can bump this.
    """
    if not isinstance(serial, str) or not serial.strip():
        return _err("serial required")
    guard = _ensure_adb()
    if guard:
        return guard

    try:
        r = run(["shell", "dumpsys", "sensorservice"], serial=serial, timeout=15)
    except AdbNotFoundError as e:
        return _err(str(e))
    except Exception as e:
        return _err(f"dumpsys sensorservice failed: {e}")
    if r.returncode != 0:
        return _err(
            (r.stderr or "").strip() or f"dumpsys exit {r.returncode}",
            exit_code=r.returncode,
        )

    text = r.stdout or ""
    sensors = _parse_sensor_list(text)
    result: dict[str, Any] = {
        "ok": True,
        "serial": serial,
        "sensor_count": len(sensors),
        "sensors": sensors,
    }
    if include_recent_events:
        limit = max(1, min(10, int(events_per_sensor or 1)))
        result["recent_events"] = _parse_recent_events(text, sensors, limit=limit)
    return result


# ---------------------------------------------------------------------------
# Parser helpers
# ---------------------------------------------------------------------------

# Sensor list entry example:
#   0x0100000b) lsm6dsv Accelerometer Non-wakeup | STMicro         | ver: 18176 | type: android.sensor.accelerometer(1) | perm: n/a | flags: 0x00000980
#       continuous | minRate=1.00Hz | maxRate=479.85Hz | FIFO (max,reserved) = (10000, 3000) events
_HANDLE_RE = re.compile(
    r"^(0x[0-9a-fA-F]+)\)\s+(.+?)\s+\|\s+(.+?)\s+\|\s+ver:\s+(\S+)\s+\|\s+type:\s+([^\s|]+)"
    r"(?:\s+\|\s+perm:\s+(\S+))?"
    r"(?:\s+\|\s+flags:\s+(0x[0-9a-fA-F]+))?"
)
_TYPE_RE = re.compile(r"^([\w\.]+?)\((\d+)\)$")
_MIN_MAX_RE = re.compile(r"minRate=([\d\.]+)Hz.*?maxRate=([\d\.]+)Hz")
_RESOLUTION_RE = re.compile(r"resolution=([\d\.eE+-]+)")
_POWER_RE = re.compile(r"power=([\d\.eE+-]+)mA")
_FIFO_RE = re.compile(r"FIFO\s+\(max,reserved\)\s+=\s+\((\d+),\s*(\d+)\)")


def _parse_sensor_list(text: str) -> list[dict[str, Any]]:
    """Walk the "Sensor List:" section into a list of sensor dicts."""
    lines = text.splitlines()
    # Locate the header line "Sensor List:" and iterate until we hit a
    # blank line or a new dumpsys section (any non-indented line that
    # doesn't start with a hex handle).
    sensors: list[dict[str, Any]] = []
    in_list = False
    cur: dict[str, Any] | None = None
    for raw in lines:
        line = raw.rstrip()
        if line.startswith("Sensor List:") or line.startswith("Sensors:"):
            in_list = True
            continue
        if not in_list:
            continue
        if not line.strip():
            if cur is not None:
                sensors.append(cur)
                cur = None
            # Blank line usually terminates the section on modern Android.
            break
        m = _HANDLE_RE.match(line)
        if m:
            if cur is not None:
                sensors.append(cur)
            handle_hex, name, vendor, version, type_str, perm, flags = m.groups()
            type_int, type_name = _split_type(type_str)
            cur = {
                "handle": handle_hex,
                "handle_int": int(handle_hex, 16),
                "name": name.strip(),
                "vendor": vendor.strip(),
                "version": _to_int_or_str(version),
                "type_int": type_int,
                "type": type_name,
                "wake_up": "wakeUp" in name or "Wakeup" in name,
                "perm": (perm or "").strip() or None,
                "flags": flags,
            }
            continue
        if cur is None:
            continue
        # Continuation lines carry the rate / FIFO / power / resolution
        # bits — merge them into the current sensor.
        stripped = line.strip()
        m = _MIN_MAX_RE.search(stripped)
        if m:
            cur["min_rate_hz"] = float(m.group(1))
            cur["max_rate_hz"] = float(m.group(2))
        m = _RESOLUTION_RE.search(stripped)
        if m:
            try:
                cur["resolution"] = float(m.group(1))
            except ValueError:
                pass
        m = _POWER_RE.search(stripped)
        if m:
            try:
                cur["power_ma"] = float(m.group(1))
            except ValueError:
                pass
        m = _FIFO_RE.search(stripped)
        if m:
            cur["fifo_max_events"] = int(m.group(1))
            cur["fifo_reserved_events"] = int(m.group(2))
        # Descriptor tokens like "continuous", "special-trigger", "wakeUp".
        for tok in ("continuous", "on-change", "one-shot", "special-trigger"):
            if tok in stripped and "trigger_mode" not in cur:
                cur["trigger_mode"] = tok
                break
    if cur is not None:
        sensors.append(cur)
    return sensors


def _split_type(type_str: str) -> tuple[int, str]:
    """Turn "android.sensor.accelerometer(1)" into (1, "accelerometer")."""
    m = _TYPE_RE.match(type_str)
    if not m:
        return (0, type_str)
    name, num = m.group(1), m.group(2)
    try:
        type_int = int(num)
    except ValueError:
        return (0, type_str)
    friendly = _SENSOR_TYPE_NAMES.get(type_int)
    if friendly:
        return (type_int, friendly)
    # Fall back to the tail of the android.sensor.X namespace.
    if name.startswith("android.sensor."):
        return (type_int, name.rsplit(".", 1)[-1])
    return (type_int, name)


def _to_int_or_str(v: str) -> Any:
    try:
        return int(v)
    except ValueError:
        return v


# Recent events section:
#   <name> [Non-]?wakeup: last N events
#       1 (ts=..., wall=HH:MM:SS.mmm) v1, v2, v3, ...
_RECENT_HEADER_RE = re.compile(r"^(.+?)\s+(Non-wakeup|Wakeup):\s+last\s+\d+\s+events$")
_RECENT_ROW_RE = re.compile(
    r"^\s*\d+\s+\(ts=([\d\.]+),\s+wall=([\d:\.]+)\)\s+(.+?)\s*$"
)


def _parse_recent_events(
    text: str,
    sensors: list[dict[str, Any]],
    *,
    limit: int,
) -> dict[str, dict[str, Any]]:
    """Group "Recent Sensor events" rows by sensor name.

    Returns a dict keyed by sensor display name. Each entry contains
    `type_int`, `channels` (if we know them), and `events` (up to
    `limit` items, newest last). Values that look like all-zero tails
    are trimmed so proximity/light aren't hidden behind 12 zero
    padding floats.
    """
    lines = text.splitlines()
    # Find the section header.
    try:
        start = next(i for i, L in enumerate(lines) if L.startswith("Recent Sensor events"))
    except StopIteration:
        return {}
    by_name: dict[str, dict[str, Any]] = {}
    cur_name: str | None = None
    cur_events: list[dict[str, Any]] = []
    for raw in lines[start + 1:]:
        line = raw.rstrip()
        if not line.strip():
            continue
        header = _RECENT_HEADER_RE.match(line)
        if header:
            if cur_name and cur_events:
                by_name[cur_name] = _finalise_recent(cur_name, cur_events, sensors, limit)
            cur_name = header.group(1).strip()
            cur_events = []
            continue
        row = _RECENT_ROW_RE.match(line)
        if row and cur_name is not None:
            ts, wall, values_str = row.groups()
            values = _parse_values(values_str)
            cur_events.append({
                "ts": float(ts),
                "wall": wall,
                "values": values,
            })
            continue
        # A non-empty, non-matching line signals a new dumpsys section
        # (e.g. "Active sensor list:" further down). Stop parsing.
        if cur_name is None:
            continue
        # Otherwise it's noise — skip.
    if cur_name and cur_events:
        by_name[cur_name] = _finalise_recent(cur_name, cur_events, sensors, limit)
    return by_name


def _parse_values(values_str: str) -> list[float]:
    """Parse "v1, v2, ..." into floats, trimming trailing zeros.

    dumpsys always emits 16 float columns even for a 1-axis sensor,
    so light-lux ends up looking like "6308.0, 896.0, 618.0, 566.0, 0, 0, ..."
    and proximity like "5.0, 0.0, ...". Trimming trailing exact zeros
    keeps the response readable without losing information — a true
    zero reading on channel N still shows if a later channel is non-zero.
    """
    tokens = [t.strip() for t in values_str.split(",") if t.strip()]
    floats: list[float] = []
    for t in tokens:
        try:
            floats.append(float(t))
        except ValueError:
            continue
    while len(floats) > 1 and floats[-1] == 0.0:
        floats.pop()
    return floats


def _finalise_recent(
    name: str,
    events: list[dict[str, Any]],
    sensors: list[dict[str, Any]],
    limit: int,
) -> dict[str, Any]:
    """Attach type + channel labels to the tail of the events list."""
    match = _match_sensor(name, sensors)
    type_int = match.get("type_int") if match else None
    channels = _SENSOR_CHANNELS.get(int(type_int)) if type_int else None
    trimmed = events[-limit:]
    # Attach channel-named readings so callers don't need to know the
    # Android sensor value convention.
    if channels:
        for ev in trimmed:
            named: dict[str, float] = {}
            for idx, ch in enumerate(channels):
                if idx < len(ev["values"]):
                    named[ch] = ev["values"][idx]
            ev["named"] = named
    return {
        "type_int": type_int,
        "type": (match or {}).get("type"),
        "channels": channels,
        "events": trimmed,
    }


def _match_sensor(name: str, sensors: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Recent-events section uses friendly names ("stk3bfx Ambient Light
    Sensor Raw Data"), sensor-list section uses variations of the same.
    A prefix / substring match is enough in practice."""
    lname = name.lower()
    for s in sensors:
        if s["name"].lower() == lname:
            return s
    for s in sensors:
        if s["name"].lower().startswith(lname) or lname.startswith(s["name"].lower()):
            return s
    # Fall back to a loose word-overlap match — the recent-events name
    # sometimes drops the "Non-wakeup" trailer or reorders words.
    tokens = set(lname.split())
    best: tuple[int, dict[str, Any]] | None = None
    for s in sensors:
        overlap = len(tokens & set(s["name"].lower().split()))
        if overlap and (best is None or overlap > best[0]):
            best = (overlap, s)
    return best[1] if best else None

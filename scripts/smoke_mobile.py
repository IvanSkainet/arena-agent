#!/usr/bin/env python3
"""Live smoke test for /v1/mobile/*.

Unlike tests/test_mobile*.py which run monkeypatched, this script hits
a REAL bridge with a REAL device attached and checks each endpoint
end-to-end. Use it before releasing anything mobile-touching.

    export ARENA_BRIDGE_URL="https://your-host.tail328f18.ts.net"
    export ARENA_BRIDGE_TOKEN="..."
    export ARENA_SMOKE_SERIAL="2200ad3b"     # first `adb devices` serial
    python scripts/smoke_mobile.py

Options:
    --skip-camera       don't launch the camera app (default: run)
    --skip-write        skip actions that touch device state
                        (tap/swipe/gesture/key)
    --json              dump the aggregated report as JSON to stdout
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


def _env(key: str) -> str:
    v = os.environ.get(key, "").strip()
    if not v:
        sys.exit(f"error: env var {key} is required for smoke tests")
    return v


BASE = os.environ.get("ARENA_BRIDGE_URL", "").rstrip("/")
TOKEN = os.environ.get("ARENA_BRIDGE_TOKEN", "")
SERIAL = os.environ.get("ARENA_SMOKE_SERIAL", "")


def _http(method: str, path: str,
          body: dict | None = None,
          timeout: int = 60) -> tuple[int, dict | bytes, dict]:
    """Return (status, json-or-bytes, headers). Never raises."""
    url = BASE + path
    data = None
    headers = {"Accept": "application/json"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            ctype = resp.headers.get("Content-Type", "").lower()
            hdrs = {k: v for k, v in resp.headers.items()}
            if "application/json" in ctype:
                return (resp.status, json.loads(raw) if raw else {}, hdrs)
            return (resp.status, raw, hdrs)
    except urllib.error.HTTPError as e:
        try:
            body_err = json.loads(e.read())
        except Exception:
            body_err = {"error": e.reason}
        return (e.code, body_err, dict(e.headers or {}))
    except urllib.error.URLError as e:
        return (0, {"error": f"connection: {e.reason}"}, {})


CHECKS: list[tuple[str, bool, str]] = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    marker = "✓" if cond else "✗"
    print(f"  {marker} {name}" + (f"  — {detail}" if detail else ""))
    CHECKS.append((name, cond, detail))


def section(title: str) -> None:
    print()
    print(f"── {title} " + "─" * (60 - len(title)))


# ---------------------------------------------------------------------------
# Individual endpoint smokes
# ---------------------------------------------------------------------------

def smoke_capabilities() -> None:
    section("capabilities.mobile")
    s, r, _ = _http("GET", "/v1/capabilities")
    _check("HTTP 200", s == 200)
    m = (r or {}).get("mobile") or {}
    _check("available=True", bool(m.get("available")))
    endpoints = set(m.get("endpoints") or [])
    for required in ("devices", "info", "screenshot", "tap", "swipe",
                     "gesture", "batch",
                     "camera/launch", "camera/shutter", "camera/capture"):
        _check(f"endpoint '{required}' advertised", required in endpoints)


def smoke_devices() -> None:
    section("/v1/mobile/devices")
    s, r, _ = _http("GET", "/v1/mobile/devices")
    _check("HTTP 200", s == 200)
    _check("ok=True", bool((r or {}).get("ok")))
    ds = (r or {}).get("devices") or []
    _check(f"{len(ds)} device(s) attached", len(ds) > 0)
    found = any((d.get("serial") == SERIAL and d.get("state") == "device") for d in ds)
    _check(f"target serial {SERIAL} in state=device", found)


def smoke_info() -> None:
    section(f"/v1/mobile/{SERIAL}/info")
    s, r, _ = _http("GET", f"/v1/mobile/{SERIAL}/info")
    _check("HTTP 200", s == 200)
    _check("ok=True", bool((r or {}).get("ok")))
    for key in ("manufacturer", "model", "android_version", "screen_size_physical",
                "rotation", "orientation", "display", "power", "network",
                "storage", "packages_count", "ime", "others"):
        _check(f"field '{key}' present", key in r,
               detail=str(r.get(key))[:60] if key in r else "")


def smoke_screenshot() -> None:
    section(f"/v1/mobile/{SERIAL}/screenshot")
    for source in ("raw", "png"):
        force_png = "&force_png_source=1" if source == "png" else ""
        started = time.monotonic()
        s, body, hdrs = _http(
            "GET",
            f"/v1/mobile/{SERIAL}/screenshot?max_size=480&format=webp&quality=75{force_png}",
            timeout=30)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        _check(f"[{source}] HTTP 200", s == 200)
        _check(f"[{source}] body is binary WebP",
               isinstance(body, bytes) and body[:4] == b"RIFF"
               and body[8:12] == b"WEBP",
               detail=f"{len(body):,} bytes")
        mode = hdrs.get("X-Arena-Mobile-Capture-Mode", "").lower()
        _check(f"[{source}] X-Arena-Mobile-Capture-Mode == '{source}'",
               mode == source, detail=f"got {mode!r}")
        cap_ms = int(hdrs.get("X-Arena-Mobile-Capture-Ms") or "0")
        enc_ms = int(hdrs.get("X-Arena-Mobile-Encode-Ms") or "0")
        _check(f"[{source}] total {elapsed_ms} ms (cap={cap_ms} enc={enc_ms})",
               elapsed_ms < 15000,
               detail=f"round-trip {elapsed_ms}ms")


def smoke_sensors() -> None:
    section(f"/v1/mobile/{SERIAL}/sensors")
    s, r, _ = _http("GET", f"/v1/mobile/{SERIAL}/sensors?events_per_sensor=1")
    _check("HTTP 200", s == 200)
    _check("sensor_count > 0", (r or {}).get("sensor_count", 0) > 0)
    ev = (r or {}).get("recent_events") or {}
    _check(f"{len(ev)} sensor(s) with live values", len(ev) > 0)


def smoke_gestures_shade() -> None:
    """Regression from user report: shade must open in ONE click, on
    the statusbar_cmd fast path."""
    section(f"/v1/mobile/{SERIAL}/gesture (shade fast path)")
    # Wake + home + explicit collapse first, so subsequent expand-*
    # calls hit a clean state (SystemUI returns non-zero on some ROMs
    # if you try to expand-settings while notifications is already open).
    _http("POST", f"/v1/mobile/{SERIAL}/key", body={"key": "WAKEUP"})
    _http("POST", f"/v1/mobile/{SERIAL}/key", body={"key": "HOME"})
    time.sleep(0.8)
    for g in ("notifications", "quick_settings", "shade_center", "shade_full"):
        # Force-close before every expand so the transitions are clean.
        _http("POST", f"/v1/mobile/{SERIAL}/gesture",
              body={"gesture": "close_shade"})
        time.sleep(0.6)
        s, r, _ = _http("POST", f"/v1/mobile/{SERIAL}/gesture",
                        body={"gesture": g})
        backend = (r or {}).get("backend", "?")
        _check(f"gesture {g!r} used statusbar_cmd fast path",
               s == 200 and (r or {}).get("ok") and backend == "statusbar_cmd",
               detail=f"backend={backend}")
        time.sleep(0.6)
    # Leave the phone clean.
    _http("POST", f"/v1/mobile/{SERIAL}/gesture",
          body={"gesture": "close_shade"})


def smoke_batch() -> None:
    section(f"/v1/mobile/{SERIAL}/batch")
    started = time.monotonic()
    s, r, _ = _http("POST", f"/v1/mobile/{SERIAL}/batch",
                    body={"steps": [
                        {"type": "key", "key": "WAKEUP"},
                        {"type": "sleep", "duration_ms": 200},
                        {"type": "key", "key": "HOME"},
                        {"type": "gesture", "gesture": "notifications"},
                        {"type": "sleep", "duration_ms": 500},
                        {"type": "gesture", "gesture": "close_shade"},
                    ]})
    round_trip_ms = int((time.monotonic() - started) * 1000)
    _check("HTTP 200 + ok", s == 200 and (r or {}).get("ok"))
    executed = (r or {}).get("executed", 0)
    _check(f"executed 6 steps", executed == 6)
    _check(f"total round-trip {round_trip_ms} ms",
           round_trip_ms < 10000,
           detail=f"batch = {(r or {}).get('total_duration_ms')}ms")


def smoke_apk_prepare() -> None:
    section("/v1/mobile/apk/prepare (ADBKeyboard bundle)")
    # Copy bundled APK into staging.
    import shutil
    from pathlib import Path
    src = Path("/home/ivan/arena-bridge/assets/apks/adbkeyboard-v2.5-dev.apk")
    if not src.exists():
        _check("bundled APK exists (SKIP)", False,
               detail="run from bridge host with /assets/apks present")
        return
    staging = Path("/tmp/arena-apk-staging")
    staging.mkdir(exist_ok=True)
    dst = staging / "smoke-adbkeyboard.apk"
    shutil.copy(src, dst)
    s, r, _ = _http("POST", "/v1/mobile/apk/prepare",
                    body={"apk_path": "smoke-adbkeyboard.apk"})
    _check("HTTP 200 + ok", s == 200 and (r or {}).get("ok"))
    _check("sha256 present", bool((r or {}).get("sha256")))
    _check("package extracted (v3.84.0 fix)",
           (r or {}).get("package") == "com.android.adbkeyboard",
           detail=str((r or {}).get("package")))


def smoke_camera(skip: bool) -> None:
    section(f"/v1/mobile/{SERIAL}/camera/launch + list_photos")
    if skip:
        _check("SKIP (--skip-camera)", True)
        return
    _http("POST", f"/v1/mobile/{SERIAL}/key", body={"key": "HOME"})
    time.sleep(0.5)
    s, r, _ = _http("POST", f"/v1/mobile/{SERIAL}/camera/launch",
                    body={"intent": "still"})
    _check("launch HTTP 200 + ok", s == 200 and (r or {}).get("ok"))
    time.sleep(2.0)
    # List DCIM to ensure the endpoint returns something coherent.
    s2, r2, _ = _http("GET", f"/v1/mobile/{SERIAL}/camera/photos?limit=3")
    _check("photos HTTP 200 + ok", s2 == 200 and (r2 or {}).get("ok"))
    _check("at least 1 photo listed", (r2 or {}).get("count", 0) > 0)
    _http("POST", f"/v1/mobile/{SERIAL}/key", body={"key": "HOME"})


def smoke_apk_upload() -> None:
    """v3.84.2: POST an APK to /v1/mobile/apk/upload — the bytes end
    up in staging + we get sha + consent token in one call."""
    section("/v1/mobile/apk/upload")
    from pathlib import Path
    src = Path("/home/ivan/arena-bridge/assets/apks/adbkeyboard-v2.5-dev.apk")
    if not src.exists():
        _check("bundled APK exists (SKIP)", False,
               detail="run from bridge host with assets/apks/ present")
        return
    data = src.read_bytes()
    url = "/v1/mobile/apk/upload?filename=smoke-upload.apk"
    # Custom-body upload isn't the JSON convenience of _http, so we
    # hand-roll a raw request.
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        BASE + url, data=data, method="POST",
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Content-Type": "application/octet-stream"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            r = json.loads(resp.read())
            status = resp.status
    except urllib.error.HTTPError as e:
        r = {"error": e.reason}
        status = e.code
    _check("HTTP 200 + ok", status == 200 and (r or {}).get("ok"))
    _check("sha256 present", bool((r or {}).get("sha256")))
    _check("required_consent starts with 'yes-install-'",
           str((r or {}).get("required_consent", "")).startswith("yes-install-"))


def smoke_recording() -> None:
    """v3.84.2: 3s sync recording, verify MP4 comes back."""
    section(f"/v1/mobile/{SERIAL}/recording/sync")
    # Make sure the shade / any modal is closed — screenrecord occasionally
    # gets zero bytes if SurfaceFlinger has a system dialog on top.
    _http("POST", f"/v1/mobile/{SERIAL}/gesture", body={"gesture": "close_shade"})
    _http("POST", f"/v1/mobile/{SERIAL}/key", body={"key": "HOME"})
    time.sleep(1.0)
    started = time.monotonic()
    s, r, _ = _http("POST", f"/v1/mobile/{SERIAL}/recording/sync",
                    body={"duration_ms": 3000, "size": "540x1200",
                          "bit_rate": 2_000_000, "include_bytes": True},
                    timeout=60)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    _check("HTTP 200 + ok", s == 200 and (r or {}).get("ok"),
           detail=f"round-trip {elapsed_ms}ms")
    _check("size_bytes > 1KB",
           (r or {}).get("size_bytes", 0) > 1024,
           detail=f"{(r or {}).get('size_bytes', 0):,} bytes MP4")
    b64 = (r or {}).get("bytes_b64", "")
    import base64
    if b64:
        raw = base64.b64decode(b64)
        # MP4 files start with a size + 'ftyp' box in the first 12 bytes.
        _check("payload is a valid MP4 (contains 'ftyp')",
               b"ftyp" in raw[:20],
               detail=f"prefix={raw[:12].hex()}")
    _check("record_ms field present",
           isinstance((r or {}).get("record_ms"), int))


def summary(json_out: bool) -> int:
    section("summary")
    passed = sum(1 for _, ok, _ in CHECKS if ok)
    total = len(CHECKS)
    print(f"  {passed}/{total} checks passed")
    if json_out:
        print(json.dumps({
            "passed": passed, "total": total,
            "checks": [{"name": n, "ok": ok, "detail": d}
                       for n, ok, d in CHECKS],
        }, indent=2, ensure_ascii=False))
    return 0 if passed == total else 1


def main() -> int:
    if not BASE or not TOKEN or not SERIAL:
        sys.exit("error: set ARENA_BRIDGE_URL, ARENA_BRIDGE_TOKEN, "
                 "ARENA_SMOKE_SERIAL")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--skip-camera", action="store_true")
    p.add_argument("--skip-write", action="store_true",
                   help="skip actions that mutate device state")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()
    smoke_capabilities()
    smoke_devices()
    smoke_info()
    smoke_screenshot()
    smoke_sensors()
    smoke_apk_prepare()
    smoke_apk_upload()
    if not args.skip_write:
        smoke_gestures_shade()
        smoke_batch()
        smoke_recording()
    smoke_camera(skip=args.skip_camera or args.skip_write)
    return summary(args.json)


if __name__ == "__main__":
    sys.exit(main())

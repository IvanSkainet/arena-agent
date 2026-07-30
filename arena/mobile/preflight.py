"""Android/mobile preflight, reconnect and observe helpers."""
from __future__ import annotations

from typing import Any

from arena.mobile import transport as _transport
from arena.mobile import ui as _ui
from arena.mobile import wireless as _wireless
from arena.mobile.adb import adb_version, find_adb
from arena.mobile.devices import device_info, list_devices


def _pick_serial(devices: list[dict[str, Any]], serial: str | None = None) -> str | None:
    if serial:
        return serial
    for d in devices:
        if d.get("state") == "device":
            return str(d.get("serial") or "") or None
    return str(devices[0].get("serial") or "") if devices else None


def preflight(serial: str | None = None) -> dict[str, Any]:
    adb = find_adb()
    devices = list_devices()
    rows = devices.get("devices") or [] if isinstance(devices, dict) else []
    selected = _pick_serial(rows, serial)
    checks = [
        {"name": "adb.installed", "ok": bool(adb), "severity": "fail", "detail": adb or "missing"},
        {"name": "device.visible", "ok": bool(rows), "severity": "warn", "detail": f"count={len(rows)}"},
        {"name": "device.authorized", "ok": any(d.get("state") == "device" for d in rows), "severity": "warn", "detail": ",".join(str(d.get("state")) for d in rows) or "none"},
    ]
    info = None
    transport = None
    if selected and any(d.get("serial") == selected and d.get("state") == "device" for d in rows):
        try:
            info = device_info(selected)
            checks.append({"name": "device.info", "ok": bool(info.get("ok")), "severity": "warn", "detail": str(info.get("model") or info.get("error") or "")})
        except Exception as e:
            info = {"ok": False, "error": str(e)}
            checks.append({"name": "device.info", "ok": False, "severity": "warn", "detail": str(e)[:200]})
        try:
            transport = _transport.describe(selected)
        except Exception as e:
            transport = {"ok": False, "error": str(e)}
    warnings = [c for c in checks if not c["ok"] and c["severity"] == "warn"]
    failed = [c for c in checks if not c["ok"] and c["severity"] == "fail"]
    next_actions = []
    if not adb:
        next_actions.append("Install Android Platform Tools / adb on the bridge host.")
    if not rows:
        next_actions.append("Connect POCO via USB or wireless ADB and authorize the debugging prompt on the phone.")
    if rows and not any(d.get("state") == "device" for d in rows):
        next_actions.append("Unlock the phone and accept USB/wireless debugging authorization; do not bypass PIN/lock automatically.")
    if selected:
        next_actions.append("Use mobile.observe for read-only foreground/device context before any input action.")
    return {"ok": not failed, "ready": bool(rows) and any(d.get("state") == "device" for d in rows) and not failed,
            "mode": "blocked" if failed else ("degraded" if warnings else "nominal"),
            "adb_path": adb, "adb_version": adb_version(), "selected_serial": selected,
            "devices": devices, "info": info, "transport": transport,
            "checks": checks, "warnings": warnings, "failed": failed,
            "next_actions": next_actions,
            "lock_boundary": "Do not unlock or bypass PIN/biometric boundaries automatically; observer confirmation is required."}


def reconnect(serial: str | None = None, host: str | None = None, port: int | None = None,
              alias: str | None = None) -> dict[str, Any]:
    if alias and not host:
        parsed = _transport.parse_hostport(alias)
        if parsed:
            host, port = parsed
    if host:
        ok = _wireless.connect(host, int(port or 5555))
        if ok.get("ok") and serial:
            from arena.mobile import adb_fallback as _fb
            _fb.add_alias(serial, f"{host}:{int(port or 5555)}", kind="tcp")
        return {"ok": bool(ok.get("ok")), "action": "mobile.reconnect", "serial": serial, "host": host, "port": int(port or 5555), "connect": ok}
    if serial:
        desc = _transport.describe(serial)
        attempts = []
        for dev in desc.get("devices") or []:
            for tr in dev.get("transports") or []:
                addr = tr.get("address")
                if tr.get("kind") == "tcp" and addr:
                    parsed = _transport.parse_hostport(addr)
                    if parsed:
                        h, p = parsed
                        attempts.append(reconnect(serial=serial, host=h, port=p))
        return {"ok": any(a.get("ok") for a in attempts), "serial": serial, "attempts": attempts, "transport": desc}
    return {"ok": False, "error": "provide serial with known transport alias, or host/port"}


def observe(serial: str | None = None, *, include_ui: bool = True, max_nodes: int = 80) -> dict[str, Any]:
    pf = preflight(serial)
    selected = pf.get("selected_serial")
    out: dict[str, Any] = {"ok": bool(selected), "preflight": pf, "serial": selected}
    if not selected or not pf.get("ready"):
        out["error"] = "no authorized device available"
        return out
    if include_ui:
        try:
            out["ui"] = _ui.dump_ui(str(selected), interactive_only=True, include_full_tree=False, max_nodes=max_nodes)
        except Exception as e:
            out["ui"] = {"ok": False, "error": str(e)}
    info = pf.get("info") or {}
    out["summary"] = {"model": info.get("model"), "android_version": info.get("android_version"), "foreground": info.get("foreground_activity") or info.get("current_activity"), "screen": info.get("screen") or info.get("display")}
    return out

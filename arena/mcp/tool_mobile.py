"""MCP mobile-device tools via local bridge endpoints.

Wraps the existing /v1/mobile/* HTTP handlers so scenarios and the browser
chat extension can drive Android devices through the same typed tool
surface as fs.*, desktop.*, and scenario.*. All calls go through the
loopback bridge URL so they inherit auth, audit, and CORS handling from
the aiohttp app.

Introduced in v4.56.0. The 30 tools here cover the full breadth of the
existing arena/mobile/* handlers: device discovery, screenshot capture,
input (tap/swipe/type/key), shell, packages, camera + screen recording,
transport (USB <-> wireless ADB) and devops (pair/connect/apk).
"""
from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from typing import Any

from arena.mcp.tool_utils import text_content


def _bridge_get_json(ctx, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = ctx.app_config() or {}
    port = int(cfg.get("port", 8765) or 8765)
    token = cfg.get("token", "")
    query = ""
    if params:
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        if clean:
            query = "?" + urllib.parse.urlencode(clean)
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}{query}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:  # nosec B310 -- loopback bridge URL for local MCP tool  # nosemgrep: dynamic-urllib-use-detected -- loopback-only fixed prefix, same rationale as tool_desktop._bridge_get
        return json.loads(resp.read().decode("utf-8", "replace"))


def _bridge_get_bytes(ctx, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """GET a binary endpoint (screenshot, recording) and wrap as
    ``{"ok": True, "mime": ..., "base64": ..., "size_bytes": ...}``.

    Response headers that begin with ``X-Arena-Mobile-`` are surfaced
    into ``headers`` so callers can still read width/height/latency
    without a second round-trip.
    """
    cfg = ctx.app_config() or {}
    port = int(cfg.get("port", 8765) or 8765)
    token = cfg.get("token", "")
    query = ""
    if params:
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        if clean:
            query = "?" + urllib.parse.urlencode(clean)
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}{query}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:  # nosec B310 -- loopback  # nosemgrep: dynamic-urllib-use-detected -- loopback-only fixed prefix
        blob = resp.read()
        mime = resp.headers.get("Content-Type", "application/octet-stream")
        headers = {k: v for k, v in resp.headers.items() if k.lower().startswith("x-arena-mobile")}
    return {
        "ok": True,
        "mime": mime,
        "size_bytes": len(blob),
        "base64": base64.b64encode(blob).decode("ascii"),
        "headers": headers,
    }


def _bridge_post(ctx, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = ctx.app_config() or {}
    port = int(cfg.get("port", 8765) or 8765)
    token = cfg.get("token", "")
    body = json.dumps(payload or {}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:  # nosec B310 -- loopback  # nosemgrep: dynamic-urllib-use-detected -- loopback-only fixed prefix
        return json.loads(resp.read().decode("utf-8", "replace"))


def _require_serial(args: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    serial = str(args.get("serial", "") or "").strip()
    if not serial:
        return None, {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'serial' argument"}]}
    return serial, None


# Small routing table so handle_mobile_tool stays flat and greppable.
# Each entry is (method, path_template, arg_names, is_binary).
#   method: "GET" or "POST"
#   path_template: "/v1/mobile/{serial}/..." with {serial} or {rec_id} substitution
#   arg_names: query params (GET) or body keys (POST); values pulled from args
#   is_binary: True for endpoints that return raw bytes (screenshot, record pull)
_ROUTES: dict[str, tuple[str, str, tuple[str, ...], bool]] = {
    # Device discovery + info
    "mobile.devices":            ("GET",  "/v1/mobile/devices",                                (),                        False),
    "mobile.info":               ("GET",  "/v1/mobile/{serial}/info",                          (),                        False),
    "mobile.transport_status":   ("GET",  "/v1/mobile/{serial}/transport",                     (),                        False),
    # Screenshot / UI dump
    "mobile.screenshot":         ("GET",  "/v1/mobile/{serial}/screenshot",                    ("max_size", "quality", "format", "wire", "force_png_source"), True),
    "mobile.ui":                 ("GET",  "/v1/mobile/{serial}/ui",                            (),                        False),
    "mobile.sensors":            ("GET",  "/v1/mobile/{serial}/sensors",                       (),                        False),
    "mobile.packages":           ("GET",  "/v1/mobile/{serial}/packages",                      ("include_system",),       False),
    # Input
    "mobile.tap":                ("POST", "/v1/mobile/{serial}/tap",                           ("x", "y", "duration_ms"), False),
    "mobile.swipe":              ("POST", "/v1/mobile/{serial}/swipe",                         ("x1", "y1", "x2", "y2", "duration_ms"), False),
    "mobile.type":               ("POST", "/v1/mobile/{serial}/type",                          ("text",),                 False),
    "mobile.key":                ("POST", "/v1/mobile/{serial}/key",                           ("keycode",),              False),
    "mobile.key_combo":          ("POST", "/v1/mobile/{serial}/key_combo",                     ("keys",),                 False),
    "mobile.scroll":             ("POST", "/v1/mobile/{serial}/scroll",                        ("direction", "distance", "duration_ms"), False),
    "mobile.gesture":            ("POST", "/v1/mobile/{serial}/gesture",                       ("points", "duration_ms"), False),
    "mobile.tap_by":             ("POST", "/v1/mobile/{serial}/tap_by",                        ("selector", "text", "resource_id", "class_name", "clickable", "index"), False),
    "mobile.paste":              ("POST", "/v1/mobile/{serial}/paste",                         ("text",),                 False),
    "mobile.shell":              ("POST", "/v1/mobile/{serial}/shell",                         ("cmd", "timeout"),        False),
    # IME helpers
    "mobile.ime_status":         ("GET",  "/v1/mobile/{serial}/ime",                           (),                        False),
    "mobile.ime_set":            ("POST", "/v1/mobile/{serial}/ime/set",                       ("ime",),                  False),
    "mobile.ime_reset":          ("POST", "/v1/mobile/{serial}/ime/reset",                    (),                        False),
    # Camera (photo)
    "mobile.camera_launch":      ("POST", "/v1/mobile/{serial}/camera/launch",                 (),                        False),
    "mobile.camera_shutter":     ("POST", "/v1/mobile/{serial}/camera/shutter",                (),                        False),
    "mobile.camera_photos":      ("GET",  "/v1/mobile/{serial}/camera/photos",                 ("limit",),                False),
    "mobile.camera_capture":     ("POST", "/v1/mobile/{serial}/camera/capture",                ("timeout", "pull"),       False),
    "mobile.camera_pull":        ("POST", "/v1/mobile/{serial}/camera/pull",                   ("remote_path", "local_name"), False),
    # Camera (video) — recording via camera app UI
    "mobile.camera_record_start":("POST", "/v1/mobile/{serial}/camera/record/start",           (),                        False),
    "mobile.camera_record_stop": ("POST", "/v1/mobile/{serial}/camera/record/stop",            (),                        False),
    # Screen recording (screencap style, records the screen; captures device audio+mic on API 31+)
    "mobile.record_start":       ("POST", "/v1/mobile/{serial}/recording/start",               ("bit_rate", "time_limit", "size", "audio"), False),
    "mobile.record_list":        ("GET",  "/v1/mobile/{serial}/recordings",                    (),                        False),
    # Devops
    "mobile.helpers_status":     ("GET",  "/v1/mobile/helpers/status",                         (),                        False),
}


def handle_mobile_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    """Dispatch mobile.* tools. Returns MCP content wrapper or None if
    the name is not a mobile tool (so downstream dispatchers get a
    chance)."""
    # Special cases first: rec_id-scoped stop/pull/purge live under
    # /v1/mobile/recording/{rec_id}/... rather than /v1/mobile/{serial}/...
    if name == "mobile.record_stop":
        rec_id = str(args.get("rec_id", "") or "").strip()
        if not rec_id:
            return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'rec_id' argument"}]}
        return text_content(json.dumps(_bridge_post(ctx, f"/v1/mobile/recording/{urllib.parse.quote(rec_id, safe='')}/stop"), ensure_ascii=False))
    if name == "mobile.record_pull":
        rec_id = str(args.get("rec_id", "") or "").strip()
        if not rec_id:
            return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'rec_id' argument"}]}
        return text_content(json.dumps(_bridge_get_bytes(ctx, f"/v1/mobile/recording/{urllib.parse.quote(rec_id, safe='')}"), ensure_ascii=False))

    entry = _ROUTES.get(name)
    if entry is None:
        return None
    method, path_tpl, arg_names, is_binary = entry

    # Extract serial only if the path template needs it.
    if "{serial}" in path_tpl:
        serial, err = _require_serial(args)
        if err is not None:
            return err
        path = path_tpl.format(serial=urllib.parse.quote(serial, safe=""))
    else:
        path = path_tpl

    payload: dict[str, Any] = {}
    for a in arg_names:
        if a in args and args[a] not in (None, ""):
            payload[a] = args[a]

    if method == "GET":
        if is_binary:
            # For screenshot: wire=json auto-forces JSON b64 already server-side.
            # We always fetch bytes locally and wrap them ourselves so MCP
            # callers get a consistent shape.
            data = _bridge_get_bytes(ctx, path, payload)
        else:
            data = _bridge_get_json(ctx, path, payload)
    else:
        data = _bridge_post(ctx, path, payload)
    return text_content(json.dumps(data, ensure_ascii=False))


__all__ = ["handle_mobile_tool"]

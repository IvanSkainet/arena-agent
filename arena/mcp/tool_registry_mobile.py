"""MCP tool registry entries for /v1/mobile/* handlers.

Introduced in v4.56.0. These wrap the existing HTTP endpoints from
arena/mobile/handlers*.py — no new device logic here, just a typed
MCP surface so scenarios and the chat extension can call them the
same way they call fs.*, desktop.*, and scenario.*.

Risk-tiering rationale for policy.py:
  safe:      pure reads (devices, info, screenshot, ui, sensors,
             packages, ime_status, transport_status, helpers_status,
             camera_photos, record_list).
  medium:    on-device input & camera actions that alter state but
             are locally reversible (tap/swipe/type/key/scroll/paste,
             camera_*, record_start/stop, record_pull).
  dangerous: shell, IME switch, apk install, transport toggles,
             record_purge. Handled via _DANGEROUS_PREFIXES = ("mobile.shell",)
             plus an explicit set in policy.py.
"""
from __future__ import annotations


def _serial_prop() -> dict:
    return {"type": "string", "description": "ADB serial (e.g. '2200ad3b' or '192.168.1.10:5555')"}


MOBILE_MCP_TOOLS = [
    {"name": "mobile.devices",
     "description": "List connected Android devices (adb devices, with product/model/ip metadata).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "mobile.info",
     "description": "Device info: model, build, screen size, battery, IP, transport.",
     "inputSchema": {"type": "object", "properties": {"serial": _serial_prop()}, "required": ["serial"]}},
    {"name": "mobile.transport_status",
     "description": "Show current ADB transport (USB vs wireless) for a device.",
     "inputSchema": {"type": "object", "properties": {"serial": _serial_prop()}, "required": ["serial"]}},
    {"name": "mobile.screenshot",
     "description": "Capture device screenshot. Returns {mime, base64, size_bytes, headers} (X-Arena-Mobile-* headers surfaced for width/height).",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(),
         "max_size": {"type": "integer", "description": "Downscale so max(width,height) <= this"},
         "quality": {"type": "integer", "default": 85},
         "format": {"type": "string", "enum": ["png", "jpeg", "webp"], "default": "png"}},
         "required": ["serial"]}},
    {"name": "mobile.ui",
     "description": "Dump current UI hierarchy (uiautomator XML tree).",
     "inputSchema": {"type": "object", "properties": {"serial": _serial_prop()}, "required": ["serial"]}},
    {"name": "mobile.sensors",
     "description": "Read available sensors snapshot (battery, orientation, network) for the device.",
     "inputSchema": {"type": "object", "properties": {"serial": _serial_prop()}, "required": ["serial"]}},
    {"name": "mobile.packages",
     "description": "List installed packages (pm list packages).",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(),
         "include_system": {"type": "boolean", "default": False}},
         "required": ["serial"]}},
    # Input
    {"name": "mobile.tap",
     "description": "Tap at (x, y). Coordinates match screenshot pixels.",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(),
         "x": {"type": "integer"}, "y": {"type": "integer"},
         "duration_ms": {"type": "integer", "default": 50}},
         "required": ["serial", "x", "y"]}},
    {"name": "mobile.swipe",
     "description": "Swipe from (x1,y1) to (x2,y2).",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(),
         "x1": {"type": "integer"}, "y1": {"type": "integer"},
         "x2": {"type": "integer"}, "y2": {"type": "integer"},
         "duration_ms": {"type": "integer", "default": 300}},
         "required": ["serial", "x1", "y1", "x2", "y2"]}},
    {"name": "mobile.type",
     "description": "Type text into the focused field (requires ADBKeyboard IME on Android when text is non-ASCII).",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(), "text": {"type": "string"}},
         "required": ["serial", "text"]}},
    {"name": "mobile.key",
     "description": "Send a keycode (int) or named key (BACK, HOME, ENTER, VOLUME_UP, ...).",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(), "keycode": {"anyOf": [{"type": "integer"}, {"type": "string"}]}},
         "required": ["serial", "keycode"]}},
    {"name": "mobile.key_combo",
     "description": "Send a key combination (list of keys pressed together, e.g. ['CTRL','A']).",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(), "keys": {"type": "array", "items": {"type": "string"}}},
         "required": ["serial", "keys"]}},
    {"name": "mobile.scroll",
     "description": "Scroll the focused view by direction (up|down|left|right).",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(),
         "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
         "distance": {"type": "integer", "default": 500},
         "duration_ms": {"type": "integer", "default": 300}},
         "required": ["serial", "direction"]}},
    {"name": "mobile.gesture",
     "description": "Play back a custom multi-point gesture (list of {x,y} waypoints).",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(),
         "points": {"type": "array", "items": {"type": "object"}},
         "duration_ms": {"type": "integer", "default": 400}},
         "required": ["serial", "points"]}},
    {"name": "mobile.tap_by",
     "description": "Find a UI element by selector (text / resource_id / class_name / clickable) and tap its centre.",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(),
         "text": {"type": "string"},
         "resource_id": {"type": "string"},
         "class_name": {"type": "string"},
         "clickable": {"type": "boolean"},
         "index": {"type": "integer", "default": 0}},
         "required": ["serial"]}},
    {"name": "mobile.paste",
     "description": "Paste text via ADBKeyboard IME (preserves unicode & special chars).",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(), "text": {"type": "string"}},
         "required": ["serial", "text"]}},
    {"name": "mobile.shell",
     "description": "Run an adb shell command on the device. DANGEROUS: full shell access.",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(),
         "cmd": {"type": "string"},
         "timeout": {"type": "integer", "default": 30}},
         "required": ["serial", "cmd"]}},
    # IME
    {"name": "mobile.ime_status",
     "description": "Show current IME + list installed IMEs on the device.",
     "inputSchema": {"type": "object", "properties": {"serial": _serial_prop()}, "required": ["serial"]}},
    {"name": "mobile.ime_set",
     "description": "Switch active IME (e.g. to ADBKeyboard).",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(), "ime": {"type": "string"}},
         "required": ["serial", "ime"]}},
    {"name": "mobile.ime_reset",
     "description": "Reset IME to system default.",
     "inputSchema": {"type": "object", "properties": {"serial": _serial_prop()}, "required": ["serial"]}},
    # Camera
    {"name": "mobile.camera_launch",
     "description": "Launch the default camera app.",
     "inputSchema": {"type": "object", "properties": {"serial": _serial_prop()}, "required": ["serial"]}},
    {"name": "mobile.camera_shutter",
     "description": "Press the camera shutter (KEYCODE_CAMERA).",
     "inputSchema": {"type": "object", "properties": {"serial": _serial_prop()}, "required": ["serial"]}},
    {"name": "mobile.camera_photos",
     "description": "List recently captured photos on the device.",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(), "limit": {"type": "integer", "default": 10}},
         "required": ["serial"]}},
    {"name": "mobile.camera_capture",
     "description": "One-shot: launch camera, wait, press shutter, wait for file, optionally pull to host.",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(),
         "timeout": {"type": "integer", "default": 15},
         "pull": {"type": "boolean", "default": True}},
         "required": ["serial"]}},
    {"name": "mobile.camera_pull",
     "description": "Pull a photo from the device to the bridge host.",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(),
         "remote_path": {"type": "string"},
         "local_name": {"type": "string"}},
         "required": ["serial", "remote_path"]}},
    {"name": "mobile.camera_record_start",
     "description": "Start video recording via the camera app UI.",
     "inputSchema": {"type": "object", "properties": {"serial": _serial_prop()}, "required": ["serial"]}},
    {"name": "mobile.camera_record_stop",
     "description": "Stop the video recording that was started via camera_record_start.",
     "inputSchema": {"type": "object", "properties": {"serial": _serial_prop()}, "required": ["serial"]}},
    # Screen recording (screencap-style, direct MP4)
    {"name": "mobile.record_start",
     "description": "Start a screen recording (screenrecord). Returns rec_id.",
     "inputSchema": {"type": "object", "properties": {
         "serial": _serial_prop(),
         "bit_rate": {"type": "integer", "description": "Bit rate in bits/sec"},
         "time_limit": {"type": "integer", "description": "Max duration in seconds"},
         "size": {"type": "string", "description": "e.g. '720x1280'"},
         "audio": {"type": "boolean", "default": False, "description": "Include device audio (Android 12+)"}},
         "required": ["serial"]}},
    {"name": "mobile.record_stop",
     "description": "Stop an active screen recording by its rec_id.",
     "inputSchema": {"type": "object", "properties": {"rec_id": {"type": "string"}}, "required": ["rec_id"]}},
    {"name": "mobile.record_list",
     "description": "List active/recent recordings for a device.",
     "inputSchema": {"type": "object", "properties": {"serial": _serial_prop()}, "required": ["serial"]}},
    {"name": "mobile.record_pull",
     "description": "Fetch a recorded MP4 by rec_id. Returns {mime, base64, size_bytes}.",
     "inputSchema": {"type": "object", "properties": {"rec_id": {"type": "string"}}, "required": ["rec_id"]}},
    # Devops
    {"name": "mobile.helpers_status",
     "description": "Show ADBKeyboard helper APK status (available, version, sha256, installation hint).",
     "inputSchema": {"type": "object", "properties": {}}},
]

__all__ = ["MOBILE_MCP_TOOLS"]

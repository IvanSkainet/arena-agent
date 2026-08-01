"""v4.59.0 additions to arena/mcp/tool_mobile.py.

Four new mobile.* tools that were exec-costume in v4.56/57/58:
  - mobile.launch_app — start an app via activity intent
  - mobile.pull_file — copy a file FROM device TO host (adb pull)
  - mobile.push_file — copy a file FROM host TO device (adb push)
  - mobile.list_files — ls -la on a device path (parsed to structured rows)

Unlike v4.56.0 wrappers, adb pull/push are NOT exposed as HTTP endpoints
on the bridge yet, so these run adb via subprocess directly from the MCP
handler (same pattern as asr.transcribe in v4.58.0).

All four go into arena/mcp/tool_mobile.py's dispatch chain BEFORE the
_ROUTES table lookup, so they intercept the mobile.* namespace without
requiring a new dispatcher slot.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from arena.mcp.tool_utils import text_content
from arena.mobile import audio_capture as _audio, preflight as _preflight
from arena.mobile.adb import find_adb as _find_adb, install_hint as _adb_install_hint

_MAX_PULL_BYTES = 100 * 1024 * 1024  # 100 MiB safety cap on pulled files
_DEFAULT_ADB_TIMEOUT = 60


def _err(msg: str) -> dict[str, Any]:
    return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {msg}"}]}


def _adb_path() -> str | None:
    # Use the SAME cross-platform discovery as the rest of the mobile
    # module (explicit SDK candidate paths via find_adb), not just
    # shutil.which("adb"). adb is commonly installed under the Android
    # SDK platform-tools dir WITHOUT being on the bridge process PATH;
    # relying on PATH alone silently broke launch_app / pull_file /
    # push_file / list_files on such hosts while mobile.ui / mobile.shell
    # (which use find_adb) kept working. Found by the voice-memo scenario
    # drive; fixed in v4.83.0.
    return _find_adb()


def _run_adb(args: list[str], timeout: int = _DEFAULT_ADB_TIMEOUT) -> tuple[int, str, str]:
    adb = _adb_path()
    if not adb:
        return -1, "", f"adb not found ({_adb_install_hint()})"
    try:
        r = subprocess.run(  # nosec B603 -- fully controlled args # nosemgrep: dangerous-subprocess-use-audit
            [adb, *args], capture_output=True, timeout=timeout, text=True,
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"adb timed out after {timeout}s"


def _launch_app(serial: str, args: dict[str, Any]) -> dict[str, Any]:
    package = str(args.get("package", "") or "").strip()
    activity = str(args.get("activity", "") or "").strip()
    action = str(args.get("action", "") or "").strip()
    if not package and not action:
        return {"ok": False, "error": "provide package (with optional activity) or action"}

    cmd = ["-s", serial, "shell", "am", "start"]
    if action:
        cmd.extend(["-a", action])
    if package:
        target = f"{package}/{activity}" if activity else package
        cmd.extend(["-n", target] if activity else ["-p", package])

    # Default flags: bring to front + reset task if reopening.
    cmd.extend(["-f", "0x14000000"])  # FLAG_ACTIVITY_NEW_TASK | FLAG_ACTIVITY_CLEAR_TOP

    rc, out, err = _run_adb(cmd, timeout=15)
    ok = rc == 0 and "Error" not in out
    return {
        "ok": ok,
        "package": package or None,
        "activity": activity or None,
        "action": action or None,
        "stdout": out.strip()[-1000:],
        "stderr": err.strip()[-1000:],
        "exit": rc,
    }


def _pull_file(serial: str, args: dict[str, Any]) -> dict[str, Any]:
    remote = str(args.get("remote", "") or "").strip()
    if not remote:
        return {"ok": False, "error": "missing 'remote' path"}
    local = str(args.get("local", "") or "").strip()
    return_bytes = bool(args.get("return_bytes", False))

    if not local:
        # Default: put under ~/.arena/mobile-pulls/<basename> (not world-writable /tmp)
        target_dir = Path(os.environ.get("ARENA_MOBILE_PULLS_DIR") or (Path.home() / ".arena" / "mobile-pulls")).expanduser()
        target_dir.mkdir(parents=True, exist_ok=True)
        local = str(target_dir / Path(remote).name)

    rc, out, err = _run_adb(["-s", serial, "pull", remote, local], timeout=120)
    if rc != 0:
        return {"ok": False, "error": "adb pull failed", "stdout": out[-500:], "stderr": err[-500:]}

    try:
        st = Path(local).stat()
        size = st.st_size
    except OSError:
        size = None

    result: dict[str, Any] = {
        "ok": True,
        "remote": remote,
        "local": local,
        "size_bytes": size,
        "adb_output": (out or err).strip()[-400:],
    }
    if return_bytes and size is not None and size <= _MAX_PULL_BYTES:
        try:
            data = Path(local).read_bytes()
            result["base64"] = base64.b64encode(data).decode("ascii")
        except OSError as e:
            result["base64_error"] = str(e)
    elif return_bytes:
        result["base64_error"] = f"file too large ({size} > {_MAX_PULL_BYTES})"
    return result


def _push_file(serial: str, args: dict[str, Any]) -> dict[str, Any]:
    local = str(args.get("local", "") or "").strip()
    remote = str(args.get("remote", "") or "").strip()
    if not local or not remote:
        return {"ok": False, "error": "provide both 'local' and 'remote'"}
    if not Path(local).exists():
        return {"ok": False, "error": f"local file not found: {local}"}
    rc, out, err = _run_adb(["-s", serial, "push", local, remote], timeout=120)
    return {
        "ok": rc == 0,
        "local": local, "remote": remote,
        "stdout": out[-400:], "stderr": err[-400:], "exit": rc,
    }


_LS_ROW = re.compile(
    r"^(?P<perms>\S+)\s+\d+\s+(?P<owner>\S+)\s+(?P<group>\S+)\s+(?P<size>\d+)\s+(?P<date>\S+\s+\S+(?:\s+[+\-]\d{4})?)\s+(?P<name>.+)$"
)


def _list_files(serial: str, args: dict[str, Any]) -> dict[str, Any]:
    path = str(args.get("path", "") or "").strip() or "/sdcard/"
    # Support glob or plain dir. Use -lA (all, incl. hidden) --full-time.
    cmd_str = f"ls -lA {shlex.quote(path)}"
    rc, out, err = _run_adb(["-s", serial, "shell", cmd_str], timeout=15)
    if rc != 0 and not out.strip():
        return {"ok": False, "error": err.strip()[-500:] or "ls failed", "path": path}

    rows = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("total "):
            continue
        m = _LS_ROW.match(line)
        if m:
            rows.append({
                "name": m.group("name"),
                "size": int(m.group("size")),
                "perms": m.group("perms"),
                "modified": m.group("date"),
                "type": "dir" if m.group("perms").startswith("d") else ("link" if m.group("perms").startswith("l") else "file"),
            })
        else:
            rows.append({"raw": line})
    return {"ok": True, "path": path, "count": len(rows), "entries": rows[:1000]}


def _voice_record(serial: str, args: dict[str, Any]) -> dict[str, Any]:
    duration = args.get("duration_ms", args.get("duration"))
    try:
        duration_ms = int(duration) if duration is not None else 8000
    except (TypeError, ValueError):
        return {"ok": False, "error": f"duration_ms must be an integer, got {duration!r}"}
    pre_delay = args.get("pre_delay_ms", 0)
    try:
        pre_delay_ms = int(pre_delay) if pre_delay is not None else 0
    except (TypeError, ValueError):
        return {"ok": False, "error": f"pre_delay_ms must be an integer, got {pre_delay!r}"}
    return _audio.voice_record(
        serial,
        duration_ms=duration_ms,
        pre_delay_ms=pre_delay_ms,
        return_bytes=bool(args.get("return_bytes", False)),
        keep_on_device=bool(args.get("keep_on_device", False)),
    )


def handle_mobile_ext_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    """Dispatch v4.59.0+ mobile.* additions. Returns None if not ours so
    the main mobile dispatcher can try its _ROUTES table."""
    if name == "mobile.preflight":
        return text_content(json.dumps(_preflight.preflight(str(args.get("serial") or "") or None), ensure_ascii=False))
    if name == "mobile.reconnect":
        return text_content(json.dumps(_preflight.reconnect(
            serial=str(args.get("serial") or "") or None,
            host=str(args.get("host") or "") or None,
            port=int(args.get("port")) if args.get("port") else None,
            alias=str(args.get("alias") or "") or None,
        ), ensure_ascii=False))
    if name == "mobile.observe":
        return text_content(json.dumps(_preflight.observe(
            str(args.get("serial") or "") or None,
            include_ui=bool(args.get("include_ui", True)),
            max_nodes=int(args.get("max_nodes", 80)),
        ), ensure_ascii=False))
    serial_required = {"mobile.launch_app", "mobile.pull_file", "mobile.push_file",
                       "mobile.list_files", "mobile.voice_record"}
    if name not in serial_required:
        return None
    serial = str(args.get("serial", "") or "").strip()
    if not serial:
        return _err(f"{name}: missing 'serial' argument")

    if name == "mobile.launch_app":
        return text_content(json.dumps(_launch_app(serial, args), ensure_ascii=False))
    if name == "mobile.pull_file":
        return text_content(json.dumps(_pull_file(serial, args), ensure_ascii=False))
    if name == "mobile.push_file":
        return text_content(json.dumps(_push_file(serial, args), ensure_ascii=False))
    if name == "mobile.list_files":
        return text_content(json.dumps(_list_files(serial, args), ensure_ascii=False))
    if name == "mobile.voice_record":
        return text_content(json.dumps(_voice_record(serial, args), ensure_ascii=False))
    return None


MOBILE_EXT_MCP_TOOLS = [

    {
        "name": "mobile.preflight",
        "description": "Read-only Android/ADB preflight: adb path/version, visible devices, authorization state, selected device info, transport status, checks and next actions.",
        "inputSchema": {"type": "object", "properties": {"serial": {"type": "string"}}, "additionalProperties": False},
    },
    {
        "name": "mobile.reconnect",
        "description": "Reconnect a known/provided wireless ADB transport (host/port or alias). Does not unlock or operate the phone UI.",
        "inputSchema": {"type": "object", "properties": {"serial": {"type": "string"}, "host": {"type": "string"}, "port": {"type": "integer"}, "alias": {"type": "string"}}, "additionalProperties": False},
    },
    {
        "name": "mobile.observe",
        "description": "Read-only device observation: runs mobile.preflight and optionally a compact UI dump; does not send input or unlock.",
        "inputSchema": {"type": "object", "properties": {"serial": {"type": "string"}, "include_ui": {"type": "boolean", "default": True}, "max_nodes": {"type": "integer", "default": 80}}, "additionalProperties": False},
    },
    {
        "name": "mobile.launch_app",
        "description": (
            "Start an Android app via activity intent. Provide `package` "
            "(and optionally `activity`) or `action` (e.g. "
            "'android.intent.action.MAIN'). Uses FLAG_ACTIVITY_NEW_TASK "
            "| FLAG_ACTIVITY_CLEAR_TOP so re-launching brings the app to "
            "front from a fresh state."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "serial": {"type": "string"},
                "package": {"type": "string", "description": "e.g. com.android.soundrecorder"},
                "activity": {"type": "string", "description": "e.g. .StartActivity"},
                "action": {"type": "string", "description": "Intent action (optional; without package = generic intent)"},
            },
            "required": ["serial"], "additionalProperties": False},
    },
    {
        "name": "mobile.pull_file",
        "description": (
            "Copy a file FROM the device TO the bridge host (adb pull). "
            "`local` defaults to /tmp/arena-mobile-pulls/<basename>. "
            "If `return_bytes=true`, also embeds file as base64 (capped 100 MiB)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "serial": {"type": "string"},
                "remote": {"type": "string", "description": "e.g. /sdcard/MIUI/sound_recorder/latest.mp3"},
                "local": {"type": "string", "description": "Absolute host path (optional)"},
                "return_bytes": {"type": "boolean", "default": False},
            },
            "required": ["serial", "remote"], "additionalProperties": False},
    },
    {
        "name": "mobile.push_file",
        "description": "Copy a file FROM the bridge host TO the device (adb push).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "serial": {"type": "string"},
                "local": {"type": "string"},
                "remote": {"type": "string"},
            },
            "required": ["serial", "local", "remote"], "additionalProperties": False},
    },
    {
        "name": "mobile.list_files",
        "description": (
            "List a directory on the device (adb shell ls -lA). "
            "Returns structured entries with name/size/perms/modified/type."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "serial": {"type": "string"},
                "path": {"type": "string", "default": "/sdcard/"},
            },
            "required": ["serial"], "additionalProperties": False},
    },
    {
        "name": "mobile.voice_record",
        "description": (
            "Record MICROPHONE audio from the device into an MP4 (AAC) and "
            "pull it back to the bridge host. The bridge installs a tiny "
            "signed helper app (com.arena.voicerecorder) on first use, "
            "grants RECORD_AUDIO, records for `duration_ms`, and returns the "
            "captured file's local host path. Transcribe the result with "
            "asr.transcribe(file=<local>). This is the bridge's 'hearing' "
            "sense — capture is fully bridge-controlled (the system Recorder "
            "app is not driven)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "serial": {"type": "string"},
                "duration_ms": {"type": "integer", "default": 8000,
                                "description": "recording length in ms (500..600000)"},
                "pre_delay_ms": {"type": "integer", "default": 0,
                                 "description": "delay before starting the recording, after install/permissions (0..120000)"},
                "return_bytes": {"type": "boolean", "default": False,
                                 "description": "also embed the MP4 as base64"},
                "keep_on_device": {"type": "boolean", "default": False,
                                   "description": "do not delete the on-device file after pulling"},
            },
            "required": ["serial"], "additionalProperties": False},
    },
]

__all__ = ["handle_mobile_ext_tool", "MOBILE_EXT_MCP_TOOLS"]

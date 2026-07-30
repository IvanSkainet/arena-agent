"""MuMu Player MCP helpers.

Thin, Windows-focused wrappers around MuMu's own `mumu-cli.exe`. They keep the
syntax stable for scenarios and avoid shell quoting errors.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from arena.mcp.tool_utils import text_content


def _cli() -> Path:
    return Path(os.environ.get("ARENA_MUMU_CLI", r"C:\Program Files\Netease\MuMuPlayer\nx_main\mumu-cli.exe"))


def _adb() -> Path:
    return Path(os.environ.get("ANDROID_ADB", os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe")))


def _run(argv: list[str], timeout: int = 30) -> dict[str, Any]:
    if not argv or not Path(argv[0]).exists():
        return {"ok": False, "error": "executable_not_found", "argv": argv}
    try:
        cp = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=max(1, int(timeout)))
        return {"ok": cp.returncode == 0, "returncode": cp.returncode, "argv": argv, "stdout": cp.stdout, "stderr": cp.stderr}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "argv": argv}


def _json_or_raw(res: dict[str, Any]) -> dict[str, Any]:
    out = dict(res)
    text = str(out.get("stdout") or "").strip()
    if text.startswith("{") or text.startswith("["):
        try:
            out["json"] = json.loads(text)
        except Exception:
            pass
    return out


def _vmindex(args: dict[str, Any]) -> str:
    return str(args.get("vmindex", args.get("index", 0)))


def handle_mumu_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    cli = str(_cli())
    timeout = int(args.get("timeout", 30) or 30)
    if name == "mumu.version":
        return text_content(json.dumps(_json_or_raw(_run([cli, "version"], timeout)), ensure_ascii=False))
    if name == "mumu.info":
        return text_content(json.dumps(_json_or_raw(_run([cli, "info", "--vmindex", _vmindex(args)], timeout)), ensure_ascii=False))
    if name == "mumu.launch":
        idx = _vmindex(args)
        r1 = _json_or_raw(_run([cli, "control", "--vmindex", idx, "launch"], timeout))
        r2 = _json_or_raw(_run([cli, "control", "--vmindex", idx, "show_window"], timeout)) if args.get("show_window", True) else None
        return text_content(json.dumps({"ok": bool(r1.get("ok")), "launch": r1, "show_window": r2}, ensure_ascii=False))
    if name == "mumu.shutdown":
        return text_content(json.dumps(_json_or_raw(_run([cli, "control", "--vmindex", _vmindex(args), "shutdown"], timeout)), ensure_ascii=False))
    if name == "mumu.shell":
        cmd = str(args.get("cmd") or "").strip()
        if not cmd:
            return text_content(json.dumps({"ok": False, "error": "cmd is required"}, ensure_ascii=False))
        return text_content(json.dumps(_run([cli, "sh", "--vmindex", _vmindex(args), *cmd.split()], timeout), ensure_ascii=False))
    if name == "mumu.adb":
        cmd = str(args.get("cmd") or "devices -l").strip()
        return text_content(json.dumps(_run([cli, "adb", "--vmindex", _vmindex(args), "--cmd", cmd], timeout), ensure_ascii=False))
    if name == "mumu.devices":
        adb = str(_adb())
        return text_content(json.dumps(_run([adb, "devices", "-l"], timeout), ensure_ascii=False))
    if name == "mumu.screenshot":
        idx = _vmindex(args)
        remote = "/sdcard/arena_mumu_screenshot.png"
        dest = str(args.get("path") or r"C:\Users\Ivan\Downloads\arena-agent\arena-bridge\arena_mumu_screenshot.png")
        cap = _run([cli, "adb", "--vmindex", idx, "--cmd", f"shell screencap -p {remote}"], timeout)
        pull = _run([cli, "adb", "--vmindex", idx, "--cmd", f"pull {remote} {dest}"], timeout)
        return text_content(json.dumps({"ok": bool(cap.get("ok") and pull.get("ok")), "path": dest, "capture": cap, "pull": pull}, ensure_ascii=False))
    return None


MUMU_TOOLS = [
    {"name": "mumu.version", "description": "Return MuMu Player CLI version.", "inputSchema": {"type": "object", "properties": {"timeout": {"type": "integer", "default": 30}}, "additionalProperties": False}},
    {"name": "mumu.info", "description": "Return MuMu VM info for vmindex (default 0).", "inputSchema": {"type": "object", "properties": {"vmindex": {"type": "integer", "default": 0}, "index": {"type": "integer"}, "timeout": {"type": "integer", "default": 30}}, "additionalProperties": False}},
    {"name": "mumu.launch", "description": "Launch/show a MuMu VM by vmindex.", "inputSchema": {"type": "object", "properties": {"vmindex": {"type": "integer", "default": 0}, "index": {"type": "integer"}, "show_window": {"type": "boolean", "default": True}, "timeout": {"type": "integer", "default": 30}}, "additionalProperties": False}},
    {"name": "mumu.shutdown", "description": "Shutdown a MuMu VM by vmindex.", "inputSchema": {"type": "object", "properties": {"vmindex": {"type": "integer", "default": 0}, "index": {"type": "integer"}, "timeout": {"type": "integer", "default": 30}}, "additionalProperties": False}},
    {"name": "mumu.shell", "description": "Run a shell command in a MuMu VM via mumu-cli sh.", "inputSchema": {"type": "object", "properties": {"vmindex": {"type": "integer", "default": 0}, "index": {"type": "integer"}, "cmd": {"type": "string"}, "timeout": {"type": "integer", "default": 30}}, "required": ["cmd"], "additionalProperties": False}},
    {"name": "mumu.adb", "description": "Run a MuMu-scoped adb command through mumu-cli adb --cmd.", "inputSchema": {"type": "object", "properties": {"vmindex": {"type": "integer", "default": 0}, "index": {"type": "integer"}, "cmd": {"type": "string", "default": "devices -l"}, "timeout": {"type": "integer", "default": 30}}, "additionalProperties": False}},
    {"name": "mumu.devices", "description": "List SDK adb devices after MuMu has started.", "inputSchema": {"type": "object", "properties": {"timeout": {"type": "integer", "default": 30}}, "additionalProperties": False}},
    {"name": "mumu.screenshot", "description": "Capture a MuMu VM screenshot and pull it to the bridge filesystem.", "inputSchema": {"type": "object", "properties": {"vmindex": {"type": "integer", "default": 0}, "index": {"type": "integer"}, "path": {"type": "string"}, "timeout": {"type": "integer", "default": 30}}, "additionalProperties": False}},
]


__all__ = ["MUMU_TOOLS", "handle_mumu_tool"]

"""Interactive Input Helper: runs in the user's desktop session.

This is a standalone HTTP micro-server that accepts input commands from the
bridge (which runs in Session 0 on Windows) and executes them via SendInput
in the interactive session where real GUI windows live.

Usage:
    python helper_server.py [--port 19222] [--token SECRET]

The helper is intentionally tiny and dependency-free (stdlib + ctypes only).
It listens on 127.0.0.1 only — never exposed to the network.

Endpoints:
    GET  /health              — liveness probe
    POST /click               — {x, y, button?, double?}
    POST /move                — {x, y}
    POST /type                — {text, delay_ms?}
    POST /key                 — {name, modifiers?}
    POST /launch              — {path, args?}
    POST /send_chat_command   — {hwnd?, command, open_key?} — Minecraft/LWJGL chat
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# ---------------------------------------------------------------------------
# Windows input constants
# ---------------------------------------------------------------------------
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_ABSOLUTE = 0x8000
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102

user32 = ctypes.windll.user32 if sys.platform == "win32" else None

VK_MAP = {
    "return": 0x0D, "enter": 0x0D, "escape": 0x1B, "esc": 0x1B,
    "tab": 0x09, "space": 0x20, "backspace": 0x08, "delete": 0x2E,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
    "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
    "f11": 0x7A, "f12": 0x7B,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "insert": 0x2D, "capslock": 0x14, "numlock": 0x90,
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
    "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
    "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
    "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
    "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59, "z": 0x5A,
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    "/": 0xBF, "oem_2": 0xBF,
}


# ---------------------------------------------------------------------------
# ctypes structures for SendInput
# ---------------------------------------------------------------------------
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUTunion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("ii", _INPUTunion)]


def _send_input(*inputs):
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    user32.SendInput(n, arr, ctypes.sizeof(INPUT))


# ---------------------------------------------------------------------------
# Input actions
# ---------------------------------------------------------------------------

def do_click(x: int, y: int, button: str = "left", double: bool = False) -> dict:
    user32.SetCursorPos(x, y)
    time.sleep(0.03)
    down_flag, up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    if button == "right":
        down_flag, up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    elif button == "middle":
        down_flag, up_flag = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP

    inp_down = INPUT(type=INPUT_MOUSE)
    inp_down.ii.mi.dwFlags = down_flag
    inp_up = INPUT(type=INPUT_MOUSE)
    inp_up.ii.mi.dwFlags = up_flag
    _send_input(inp_down, inp_up)

    if double:
        time.sleep(0.05)
        _send_input(inp_down, inp_up)

    return {"ok": True, "action": "click", "x": x, "y": y, "button": button, "double": double}


def do_move(x: int, y: int) -> dict:
    user32.SetCursorPos(x, y)
    return {"ok": True, "action": "move", "x": x, "y": y}


def do_type(text: str, delay_ms: int = 5) -> dict:
    for ch in text:
        code = ord(ch)
        if code > 0xFFFF:
            continue
        inp_down = INPUT(type=INPUT_KEYBOARD)
        inp_down.ii.ki.wScan = code
        inp_down.ii.ki.dwFlags = KEYEVENTF_UNICODE
        inp_up = INPUT(type=INPUT_KEYBOARD)
        inp_up.ii.ki.wScan = code
        inp_up.ii.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        _send_input(inp_down, inp_up)
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)
    return {"ok": True, "action": "type", "length": len(text)}


def do_key(name: str, modifiers: list[str] | None = None) -> dict:
    name_l = name.lower().strip()
    vk = VK_MAP.get(name_l)
    if vk is None and len(name_l) == 1:
        vks = user32.VkKeyScanW(ctypes.c_wchar(name_l))
        if vks != -1:
            vk = vks & 0xFF
    if vk is None:
        return {"ok": False, "error": f"unknown key: {name}"}

    mods = [VK_MAP[m.lower()] for m in (modifiers or []) if m.lower() in VK_MAP]

    # Press modifiers
    for mc in mods:
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.ii.ki.wVk = mc
        _send_input(inp)

    # Press key
    inp_down = INPUT(type=INPUT_KEYBOARD)
    inp_down.ii.ki.wVk = vk
    _send_input(inp_down)
    time.sleep(0.03)

    inp_up = INPUT(type=INPUT_KEYBOARD)
    inp_up.ii.ki.wVk = vk
    inp_up.ii.ki.dwFlags = KEYEVENTF_KEYUP
    _send_input(inp_up)

    # Release modifiers
    for mc in reversed(mods):
        inp = INPUT(type=INPUT_KEYBOARD)
        inp.ii.ki.wVk = mc
        inp.ii.ki.dwFlags = KEYEVENTF_KEYUP
        _send_input(inp)

    return {"ok": True, "action": "key", "name": name, "modifiers": modifiers or []}


def do_launch(path: str, args: list[str] | None = None) -> dict:
    try:
        cmd = [path] + (args or [])
        proc = subprocess.Popen(cmd, creationflags=0x00000010)  # CREATE_NEW_CONSOLE
        return {"ok": True, "action": "launch", "path": path, "pid": proc.pid}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def do_send_chat_command(command: str, hwnd: int | None = None, open_key: str = "/") -> dict:
    """Send a command to a Minecraft/LWJGL window via the chat.

    1. Focus the window
    2. Press open_key (default /) to open command chat
    3. Type the command text via WM_CHAR
    4. Press Enter via WM_CHAR(13)
    """
    if hwnd is None:
        # Auto-find Minecraft window
        def find_mc():
            result = []
            def cb(h, _):
                if user32.IsWindowVisible(h):
                    buf = ctypes.create_unicode_buffer(256)
                    user32.GetWindowTextW(h, buf, 256)
                    if "Minecraft" in buf.value:
                        result.append(h)
                return True
            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            user32.EnumWindows(WNDENUMPROC(cb), 0)
            return result[0] if result else None
        hwnd = find_mc()

    if not hwnd:
        return {"ok": False, "error": "Minecraft window not found"}

    # Focus window
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)

    # Press / key via SendInput to open command chat
    vk = VK_MAP.get(open_key, VK_MAP.get("/", 0xBF))
    inp_down = INPUT(type=INPUT_KEYBOARD)
    inp_down.ii.ki.wVk = vk
    inp_up = INPUT(type=INPUT_KEYBOARD)
    inp_up.ii.ki.wVk = vk
    inp_up.ii.ki.dwFlags = KEYEVENTF_KEYUP
    _send_input(inp_down, inp_up)
    time.sleep(0.4)

    # Type command text via SendInput UNICODE
    for ch in command:
        code = ord(ch)
        d = INPUT(type=INPUT_KEYBOARD)
        d.ii.ki.wScan = code
        d.ii.ki.dwFlags = KEYEVENTF_UNICODE
        u = INPUT(type=INPUT_KEYBOARD)
        u.ii.ki.wScan = code
        u.ii.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        _send_input(d, u)
        time.sleep(0.02)

    time.sleep(0.2)

    # Press Enter via SendInput
    enter_down = INPUT(type=INPUT_KEYBOARD)
    enter_down.ii.ki.wVk = 0x0D
    enter_up = INPUT(type=INPUT_KEYBOARD)
    enter_up.ii.ki.wVk = 0x0D
    enter_up.ii.ki.dwFlags = KEYEVENTF_KEYUP
    _send_input(enter_down, enter_up)

    return {"ok": True, "action": "send_chat_command", "command": command, "hwnd": hwnd}


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

_TOKEN = ""


class InputHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress default logging
        pass

    def _check_auth(self) -> bool:
        if not _TOKEN:
            return True
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {_TOKEN}":
            return True
        self.send_response(401)
        self.end_headers()
        self.wfile.write(b'{"ok":false,"error":"unauthorized"}')
        return False

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        if not self._check_auth():
            return
        if self.path == "/health":
            self._json_response({
                "ok": True,
                "service": "arena-input-helper",
                "session": os.environ.get("SESSIONNAME", "unknown"),
                "pid": os.getpid(),
            })
            return
        self._json_response({"ok": False, "error": "not found"}, 404)

    def do_POST(self):
        if not self._check_auth():
            return
        try:
            body = self._read_json()
        except Exception:
            self._json_response({"ok": False, "error": "invalid JSON"}, 400)
            return

        path = self.path.rstrip("/")
        try:
            if path == "/click":
                result = do_click(
                    int(body["x"]), int(body["y"]),
                    button=body.get("button", "left"),
                    double=body.get("double", False),
                )
            elif path == "/move":
                result = do_move(int(body["x"]), int(body["y"]))
            elif path == "/type":
                result = do_type(
                    str(body.get("text", "")),
                    delay_ms=int(body.get("delay_ms", 5)),
                )
            elif path == "/key":
                result = do_key(
                    str(body.get("name", "")),
                    modifiers=body.get("modifiers"),
                )
            elif path == "/launch":
                result = do_launch(
                    str(body.get("path", "")),
                    args=body.get("args"),
                )
            elif path == "/send_chat_command":
                result = do_send_chat_command(
                    command=str(body.get("command", "")),
                    hwnd=body.get("hwnd"),
                    open_key=body.get("open_key", "/"),
                )
            else:
                self._json_response({"ok": False, "error": f"unknown endpoint: {path}"}, 404)
                return
            self._json_response(result)
        except Exception as e:
            self._json_response({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Arena Interactive Input Helper")
    parser.add_argument("--port", type=int, default=19222)
    parser.add_argument("--token", type=str, default="")
    args = parser.parse_args()

    global _TOKEN
    _TOKEN = args.token or os.environ.get("ARENA_INPUT_HELPER_TOKEN", "")

    server = HTTPServer(("127.0.0.1", args.port), InputHandler)
    print(f"Arena Input Helper listening on http://127.0.0.1:{args.port}")
    print(f"Session: {os.environ.get('SESSIONNAME', 'unknown')}, PID: {os.getpid()}")
    if _TOKEN:
        print(f"Token: {'*' * 8}...{_TOKEN[-4:]}")
    else:
        print("Token: (none — unauthenticated)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()

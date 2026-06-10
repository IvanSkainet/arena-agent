"""Desktop input command builders.

These helpers construct shell commands for existing desktop automation backends.
They do not execute commands and do not know about aiohttp/control leases.
"""
from __future__ import annotations

import os
import shlex
from typing import Any

YDOTOOL_BUTTONS = {"left": "0x110", "middle": "0x112", "right": "0x111"}
YDOTOOL_KEYS = {
    "Return": "28", "Enter": "28", "Escape": "1", "Tab": "15",
    "BackSpace": "14", "Delete": "111", "Space": "57",
    "Up": "103", "Down": "108", "Left": "105", "Right": "106",
    "ctrl": "29", "shift": "42", "alt": "56", "super": "125",
}


def display_env() -> str:
    return f'DISPLAY={os.environ.get("DISPLAY", ":0")}'


def build_click_command(*, env: dict[str, Any], x: int, y: int, button: str = "left", double: bool = False, activate: bool = True, has_kdotool: bool = False) -> tuple[str | None, str, str | None]:
    """Return (command, tool, error)."""
    btn_code = YDOTOOL_BUTTONS.get(button, "0x110")
    disp = display_env()
    parts: list[str] = []
    if env.get("has_ydotool"):
        parts.append(f'ydotool mousemove --absolute {int(x)} {int(y)}')
        if activate and has_kdotool:
            parts.append(
                f'kdotool search --position {int(x)} {int(y)} 2>/dev/null && '
                f'kdotool activate $(kdotool search --position {int(x)} {int(y)} 2>/dev/null | head -1) 2>/dev/null || true'
            )
        parts.append(f'ydotool click {btn_code}')
        if double:
            parts.append(f'sleep 0.05 && ydotool click {btn_code}')
        return " && ".join(parts), "ydotool", None
    if env.get("has_xdotool"):
        if activate:
            parts.append(
                f'{disp} xdotool mousemove {int(x)} {int(y)} && '
                f'{disp} xdotool getmouselocation --shell 2>/dev/null | grep WINDOW | cut -d= -f2 | '
                f'xargs -I{{}} {disp} xdotool windowactivate {{}} 2>/dev/null || true'
            )
        else:
            parts.append(f'{disp} xdotool mousemove {int(x)} {int(y)}')
        click_type = "1" if button == "left" else ("2" if button == "middle" else "3")
        click_opt = "--repeat 2" if double else ""
        parts.append(f'{disp} xdotool click {click_opt} {click_type}')
        return " && ".join(parts), "xdotool", None
    return None, "none", "No click tool available (need ydotool or xdotool)"


def build_type_command(*, env: dict[str, Any], text: str, delay: int | float = 50, clear: bool = False) -> tuple[str | None, str, str | None]:
    escaped_text = shlex.quote(text)
    disp = display_env()
    if env.get("has_ydotool"):
        cmd = f'ydotool type --key-delay {delay} {escaped_text}'
        tool = "ydotool"
    elif env.get("has_wtype"):
        cmd = f'wtype {escaped_text}'
        tool = "wtype"
    elif env.get("has_xdotool"):
        cmd = f'{disp} xdotool type --delay {delay} {escaped_text}'
        tool = "xdotool"
    else:
        return None, "none", "No type tool available (need ydotool, wtype, or xdotool)"

    if clear:
        if env.get("has_ydotool"):
            cmd = "ydotool key 29:1 30:1 30:0 29:0 && sleep 0.1 && " + cmd
        elif env.get("has_xdotool"):
            cmd = f"{disp} xdotool key ctrl+a && sleep 0.1 && " + cmd
    return cmd, tool, None


def _ydotool_code_for_key(part: str) -> str | None:
    code = YDOTOOL_KEYS.get(part)
    if code is None and len(part) == 1:
        code = str(ord(part.upper()) - 36)  # historical approximation
    if code is None:
        code = YDOTOOL_KEYS.get(part.lower())
    return code


def build_key_command(*, env: dict[str, Any], key: str | None = None, keys: list[str] | None = None) -> tuple[str | None, str, str | None, str]:
    disp = display_env()
    key_label = key or ("+".join(keys or []))
    if env.get("has_ydotool"):
        if key:
            if "+" in key:
                parts = key.split("+")
                codes = [c for c in (_ydotool_code_for_key(p) for p in parts) if c]
                cmd_parts = [f"{c}:1" for c in codes] + [f"{c}:0" for c in reversed(codes)]
                return f'ydotool key {" ".join(cmd_parts)}', "ydotool", None, key_label
            code = YDOTOOL_KEYS.get(key)
            if code:
                return f'ydotool key {code}:1 {code}:0', "ydotool", None, key_label
            return f'ydotool key {key}', "ydotool", None, key_label
        if keys:
            press = [f"{YDOTOOL_KEYS[k]}:1" for k in keys if k in YDOTOOL_KEYS]
            release = [f"{YDOTOOL_KEYS[k]}:0" for k in reversed(keys) if k in YDOTOOL_KEYS]
            return f'ydotool key {" ".join(press + release)}', "ydotool", None, key_label
    if env.get("has_xdotool"):
        return f'{disp} xdotool key {shlex.quote(key_label)}', "xdotool", None, key_label
    return None, "none", "No key tool available (need ydotool or xdotool)", key_label


def build_mouse_command(*, env: dict[str, Any], x: int, y: int, absolute: bool = True) -> tuple[str | None, str, str | None]:
    disp = display_env()
    if env.get("has_ydotool"):
        abs_flag = "--absolute" if absolute else ""
        return f'ydotool mousemove {abs_flag} {int(x)} {int(y)}', "ydotool", None
    if env.get("has_xdotool"):
        return f'{disp} xdotool mousemove {int(x)} {int(y)}', "xdotool", None
    return None, "none", "No mouse tool available (need ydotool or xdotool)"

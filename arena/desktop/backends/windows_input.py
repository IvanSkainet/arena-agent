"""Windows input primitives over SendInput, for input sequences (#616)."""
# `windows.py` presses with `keybd_event(vk, 0, ...)` and moves with
# `SetCursorPos`. Both are fine for a dialog and neither is enough for an
# application that reads the keyboard by scan code or the mouse as raw motion:
# a virtual key with no scan code is not a key such a program knows, and
# `SetCursorPos` produces no motion at all. `SendInput` with the scan code
# filled in, and `MOUSEEVENTF_MOVE` for deltas, are what a physical device
# would have produced.
#
# The `user32` handle is passed in, so everything here can be exercised on any
# platform with a stand-in that records what it was sent.

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from typing import Any

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120
_MAPVK_VK_TO_VSC = 0
_BUTTON_FLAGS = {"left": (0x0002, 0x0004), "right": (0x0008, 0x0010), "middle": (0x0020, 0x0040)}

_ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", _ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", _ULONG_PTR)]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _InputUnion)]


def _virtual_keys() -> dict[str, int]:
    keys = {
        "space": 0x20, "shift": 0xA0, "lshift": 0xA0, "rshift": 0xA1, "ctrl": 0xA2, "lctrl": 0xA2,
        "rctrl": 0xA3, "alt": 0xA4, "lalt": 0xA4, "ralt": 0xA5, "esc": 0x1B, "escape": 0x1B,
        "enter": 0x0D, "return": 0x0D, "tab": 0x09, "backspace": 0x08, "delete": 0x2E, "insert": 0x2D,
        "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22, "left": 0x25, "up": 0x26,
        "right": 0x27, "down": 0x28, "capslock": 0x14, "slash": 0xBF, "/": 0xBF, "minus": 0xBD,
        "equals": 0xBB, "comma": 0xBC, "period": 0xBE, "semicolon": 0xBA, "quote": 0xDE,
        "backquote": 0xC0, "lbracket": 0xDB, "rbracket": 0xDD, "backslash": 0xDC,
    }
    keys.update({f"f{number}": 0x6F + number for number in range(1, 13)})
    keys.update({char: ord(char.upper()) for char in "abcdefghijklmnopqrstuvwxyz0123456789"})
    return keys


VIRTUAL_KEYS = _virtual_keys()
#: Keys whose scan code is shared with the numeric pad and needs the extended bit.
_EXTENDED = frozenset({0xA3, 0xA5, 0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28})


class WindowsInputDriver:
    """The `InputDriver` of `arena.desktop.input_sequence`, on user32."""

    def __init__(self, user32: Any) -> None:
        """Bind to a user32 handle; tests pass a stand-in that records what it is sent."""
        self._user32 = user32

    def _send(self, event: INPUT) -> None:
        sent = self._user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT))
        if sent != 1:
            raise OSError(f"SendInput delivered {sent} of 1 events (blocked by UIPI or another input)")

    def _key(self, name: str, flags: int) -> None:
        vk = VIRTUAL_KEYS[name]
        if vk in _EXTENDED:
            flags |= KEYEVENTF_EXTENDEDKEY
        event = INPUT(type=INPUT_KEYBOARD)
        event.u.ki = KEYBDINPUT(vk, self._user32.MapVirtualKeyW(vk, _MAPVK_VK_TO_VSC), flags, 0, 0)
        self._send(event)

    def _mouse(self, flags: int, delta: tuple[int, int] = (0, 0), data: int = 0) -> None:
        event = INPUT(type=INPUT_MOUSE)
        event.u.mi = MOUSEINPUT(delta[0], delta[1], data & 0xFFFFFFFF, flags, 0, 0)
        self._send(event)

    def knows_key(self, name: str) -> bool:
        return name in VIRTUAL_KEYS

    def key_down(self, name: str) -> None:
        self._key(name, 0)

    def key_up(self, name: str) -> None:
        self._key(name, KEYEVENTF_KEYUP)

    def button_down(self, name: str) -> None:
        self._mouse(_BUTTON_FLAGS[name][0])

    def button_up(self, name: str) -> None:
        self._mouse(_BUTTON_FLAGS[name][1])

    def move_rel(self, dx: int, dy: int) -> None:
        self._mouse(MOUSEEVENTF_MOVE, (dx, dy))

    def move_to(self, x: int, y: int) -> None:
        # SetCursorPos reports a refusal by returning zero, not by raising.
        if not self._user32.SetCursorPos(x, y):
            raise OSError("SetCursorPos failed: the system refused to move the cursor")

    def shift_cursor(self, dx: int, dy: int) -> None:
        """Move the cursor by exactly (dx, dy) pixels from where it is."""
        # Not `move_rel`: that is device motion, and the system scales it by the
        # pointer speed before it reaches the cursor. On a machine with the
        # speed at its lowest, 640 counts moved the cursor 20 pixels.
        here = wt.POINT()
        if not self._user32.GetCursorPos(ctypes.byref(here)):
            raise OSError("GetCursorPos failed: the cursor position is not available to this process")
        self.move_to(here.x + dx, here.y + dy)

    def scroll(self, clicks: int) -> None:
        self._mouse(MOUSEEVENTF_WHEEL, data=clicks * WHEEL_DELTA)

    def foreground_title(self) -> str:
        buffer = ctypes.create_unicode_buffer(512)
        self._user32.GetWindowTextW(self._user32.GetForegroundWindow(), buffer, 512)
        return buffer.value


def system_driver() -> WindowsInputDriver:  # pragma: no cover -- needs a real user32
    """The driver bound to this machine's user32, with the prototypes SendInput needs."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
    user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wt.UINT
    user32.MapVirtualKeyW.argtypes = [wt.UINT, wt.UINT]
    user32.MapVirtualKeyW.restype = wt.UINT
    user32.GetForegroundWindow.restype = wt.HWND
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
    user32.GetCursorPos.restype = wt.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wt.BOOL
    return WindowsInputDriver(user32)


def mouse_move(x: int, y: int, absolute: bool = True) -> None:
    """Move the cursor to (x, y), or by (x, y) pixels when `absolute` is false (#617)."""
    if absolute:  # pragma: no cover -- Windows only
        from arena.desktop.backends import windows

        windows.mouse_move(x, y)
        return
    system_driver().shift_cursor(x, y)


__all__ = ["VIRTUAL_KEYS", "WindowsInputDriver", "mouse_move", "system_driver"]

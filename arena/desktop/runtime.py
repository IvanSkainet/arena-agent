"""Desktop runtime helpers.

Compatibility facade over focused desktop runtime modules.
"""
from __future__ import annotations

from arena.desktop.active_window import _get_active_window
from arena.desktop.env import _detect_desktop_env
from arena.desktop.exec import _desktop_exec
from arena.desktop.kwin import _kwin_windows_via_script
from arena.desktop.ocr import ocr_desktop

__all__ = [
    "_desktop_exec",
    "_detect_desktop_env",
    "_kwin_windows_via_script",
    "_get_active_window",
    "ocr_desktop",
]

"""Handlers for desktop automation endpoints."""
from __future__ import annotations

from dataclasses import dataclass

from arena.desktop.input_handlers import make_desktop_input_handlers
from arena.desktop.ocr_handler import make_desktop_ocr_handlers
from arena.desktop.screenshot_handler import make_desktop_screenshot_handler
from arena.desktop.window_handlers import make_desktop_window_handlers
from arena.handler_context import DesktopHandlerContext


@dataclass(frozen=True)
class DesktopHandlers:
    screenshot: object
    click: object
    type: object
    key: object
    mouse: object
    windows: object
    active_window: object
    focus: object
    ocr: object
    find_text: object


def make_desktop_handlers(ctx: DesktopHandlerContext) -> DesktopHandlers:
    click, type_handler, key, mouse = make_desktop_input_handlers(ctx)
    windows, active_window, focus = make_desktop_window_handlers(ctx)
    ocr_handlers = make_desktop_ocr_handlers(ctx)
    return DesktopHandlers(
        screenshot=make_desktop_screenshot_handler(ctx),
        click=click,
        type=type_handler,
        key=key,
        mouse=mouse,
        windows=windows,
        active_window=active_window,
        focus=focus,
        ocr=ocr_handlers.ocr,
        find_text=ocr_handlers.find_text,
    )

"""Handlers for desktop automation endpoints."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from arena.desktop.display_handler import make_desktop_display_handler
from arena.desktop.input_handlers import make_desktop_input_handlers
from arena.desktop.ocr_handler import make_desktop_ocr_handlers
from arena.desktop.screenshot_handler import make_desktop_screenshot_handler
from arena.desktop.text_action_handler import make_desktop_text_action_handler
from arena.desktop.text_window_handler import make_desktop_text_window_handler
from arena.desktop.window_action_handler import make_desktop_window_action_handler
from arena.desktop.window_handlers import make_desktop_window_handlers
from arena.handler_context import DesktopHandlerContext


@dataclass(frozen=True)
class DesktopHandlers:
    screenshot: Callable[..., Any]
    displays: Callable[..., Any]
    click: Callable[..., Any]
    type: Callable[..., Any]
    key: Callable[..., Any]
    mouse: Callable[..., Any]
    windows: Callable[..., Any]
    active_window: Callable[..., Any]
    focus: Callable[..., Any]
    window_action: Callable[..., Any]
    resolve_text_target: Callable[..., Any]
    text_action: Callable[..., Any]
    ocr: Callable[..., Any]
    find_text: Callable[..., Any]
    click_text: Callable[..., Any]



def make_desktop_handlers(ctx: DesktopHandlerContext) -> DesktopHandlers:
    click, type_handler, key, mouse = make_desktop_input_handlers(ctx)
    windows, active_window, focus = make_desktop_window_handlers(ctx)
    ocr_handlers = make_desktop_ocr_handlers(ctx)
    return DesktopHandlers(
        screenshot=make_desktop_screenshot_handler(ctx),
        displays=make_desktop_display_handler(ctx),
        click=click,
        type=type_handler,
        key=key,
        mouse=mouse,
        windows=windows,
        active_window=active_window,
        focus=focus,
        window_action=make_desktop_window_action_handler(ctx),
        resolve_text_target=make_desktop_text_window_handler(ctx),
        text_action=make_desktop_text_action_handler(ctx),
        ocr=ocr_handlers.ocr,
        find_text=ocr_handlers.find_text,
        click_text=ocr_handlers.click_text,
    )

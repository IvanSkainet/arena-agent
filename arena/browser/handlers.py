"""Facade for non-CDP browser endpoint handler factories."""
from __future__ import annotations

from arena.browser.browse_handlers import BrowserBrowseHandlers, make_browser_browse_handlers
from arena.browser.fetch_handlers import BrowserFetchHandlers, make_browser_fetch_handlers

__all__ = [
    "BrowserBrowseHandlers",
    "BrowserFetchHandlers",
    "make_browser_browse_handlers",
    "make_browser_fetch_handlers",
]

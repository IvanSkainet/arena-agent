"""Browser fetch/search runtime compatibility wrappers."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from arena.browser.fetch import browser_dump, browser_fetch, browser_head, browser_read, browser_search


@dataclass(frozen=True)
class BrowserRuntimeContext:
    version: str
    validate_url: Callable[[str], str | None]


@dataclass(frozen=True)
class BrowserRuntime:
    browser_search_sync: Callable[[str, int], dict[str, Any]]
    browser_read_sync: Callable[[str], dict[str, Any]]
    browser_dump_sync: Callable[[str], dict[str, Any]]
    browser_fetch_sync: Callable[[str], dict[str, Any]]
    browser_head_sync: Callable[[str], dict[str, Any]]


def make_browser_runtime(ctx: BrowserRuntimeContext) -> BrowserRuntime:
    def _browser_search_sync(query: str, n: int) -> dict[str, Any]:
        return browser_search(query, n, version=ctx.version)

    def _browser_read_sync(url: str) -> dict[str, Any]:
        return browser_read(url, version=ctx.version, validate_url=ctx.validate_url)

    def _browser_dump_sync(url: str) -> dict[str, Any]:
        return browser_dump(url, version=ctx.version, validate_url=ctx.validate_url)

    def _browser_fetch_sync(url: str) -> dict[str, Any]:
        return browser_fetch(url, version=ctx.version, validate_url=ctx.validate_url)

    def _browser_head_sync(url: str) -> dict[str, Any]:
        return browser_head(url, version=ctx.version, validate_url=ctx.validate_url)

    return BrowserRuntime(
        browser_search_sync=_browser_search_sync,
        browser_read_sync=_browser_read_sync,
        browser_dump_sync=_browser_dump_sync,
        browser_fetch_sync=_browser_fetch_sync,
        browser_head_sync=_browser_head_sync,
    )

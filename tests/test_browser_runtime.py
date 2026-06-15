"""Browser runtime wrapper extraction tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.browser.runtime import BrowserRuntimeContext, make_browser_runtime  # noqa: E402


def test_browser_runtime_factory_outputs():
    runtime = make_browser_runtime(BrowserRuntimeContext(version="test", validate_url=lambda url: None))
    assert callable(runtime.browser_search_sync)
    assert callable(runtime.browser_read_sync)
    assert callable(runtime.browser_dump_sync)
    assert callable(runtime.browser_fetch_sync)
    assert callable(runtime.browser_head_sync)


def test_unified_browser_runtime_bindings():
    assert ub._browser_search_sync.__module__ == "arena.browser.runtime"
    assert ub._browser_read_sync.__module__ == "arena.browser.runtime"
    assert ub._browser_dump_sync.__module__ == "arena.browser.runtime"
    assert ub._browser_fetch_sync.__module__ == "arena.browser.runtime"
    assert ub._browser_head_sync.__module__ == "arena.browser.runtime"


def test_browser_runtime_validation_propagates():
    runtime = make_browser_runtime(BrowserRuntimeContext(version="test", validate_url=lambda url: "blocked"))
    result = runtime.browser_read_sync("https://example.com")
    assert result["ok"] is False
    assert "blocked" in result["error"]

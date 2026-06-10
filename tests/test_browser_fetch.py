"""Non-CDP browser fetch helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.browser.fetch import browser_fetch, browser_head, browser_read  # noqa: E402
import unified_bridge as ub  # noqa: E402


def _block_local(url: str):
    return "blocked" if "localhost" in url else None


def test_browser_helpers_validate_url():
    assert browser_read("http://localhost/", version="x", validate_url=_block_local)["error"] == "blocked"
    assert browser_fetch("http://localhost/", version="x", validate_url=_block_local)["error"] == "blocked"
    assert browser_head("http://localhost/", version="x", validate_url=_block_local)["error"] == "blocked"


def test_unified_bridge_browser_wrappers_validate_localhost():
    assert ub._browser_read_sync("http://localhost/")["ok"] is False
    assert ub._browser_head_sync("http://localhost/")["ok"] is False

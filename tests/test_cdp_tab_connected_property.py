"""`CDPTab.connected` must be a value, not a bound method.

It was declared as a plain method:

    def connected(self) -> bool:
        return self._connected and self._browser is not None

but six call sites read it as a value -- `if tab.connected:`,
`return active_tab.connected`, `"●" if tab.connected else "○"`. A bound method
object is always truthy, so **a disconnected tab reported itself as connected
everywhere**: the auto-connect path returned success without a connection, the
lifecycle cleanup thought every tab was live, and the CLI drew every tab with a
filled dot.

Nothing in the tree ever called `connected()`, which is why the mistake was
invisible: there was no TypeError to notice, just a boolean that was never
False.

Found by sorting type findings by "this call cannot succeed" -- pyrefly flagged
`return active_tab.connected` as returning `(self: CDPTab) -> bool` where
`bool` was declared.

The tests below read the attribute, because reading it *is* the contract.
"""
from __future__ import annotations

import ast
import inspect
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from arena.browser.cdp_client.tab import CDPTab  # noqa: E402

CDP_DIR = REPO / "arena" / "browser" / "cdp_client"


def _tab(*, connected: bool) -> CDPTab:
    tab = CDPTab.__new__(CDPTab)
    object.__setattr__(tab, "_connected", connected)
    object.__setattr__(tab, "_browser", object() if connected else None)
    return tab


def test_disconnected_tab_is_falsy():
    """The regression: a bound method object would make this True."""
    assert _tab(connected=False).connected is False


def test_connected_tab_is_true():
    assert _tab(connected=True).connected is True


def test_a_tab_with_no_browser_is_not_connected():
    """Both halves of the original expression still matter."""
    tab = CDPTab.__new__(CDPTab)
    object.__setattr__(tab, "_connected", True)
    object.__setattr__(tab, "_browser", None)
    assert tab.connected is False


def test_it_is_declared_as_a_property():
    attr = inspect.getattr_static(CDPTab, "connected")
    assert isinstance(attr, property), (
        "connected is a plain method again; every `if tab.connected:` in the "
        "tree would silently become always-true"
    )


def test_no_call_site_invokes_it_as_a_method():
    """`tab.connected()` would now raise 'bool is not callable'."""
    offenders = []
    for path in sorted(CDP_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "connected"):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], f"connected() called as a method at: {offenders}"


def test_the_value_readers_are_still_there():
    """If these disappear the property may no longer be load bearing."""
    readers = 0
    for path in sorted(CDP_DIR.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if (isinstance(node, ast.Attribute) and node.attr == "connected"
                    and not isinstance(getattr(node, "ctx", None), ast.Store)):
                readers += 1
    assert readers >= 5, f"only {readers} readers found; expected the original six"

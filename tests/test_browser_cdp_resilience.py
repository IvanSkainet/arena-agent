"""v4.106.0 -- CDP browse/status resilience after failed launches."""
from __future__ import annotations

from arena.browser.browse_cdp import _reset_cdp_state, _valid_active_tab


class _BadMgr:
    def active_tab(self):  # callable attribute shape caused stale connected state
        return None


class _GoodTab:
    connected = True


class _GoodMgr:
    active_tab = _GoodTab()


def test_valid_active_tab_rejects_callable_active_tab():
    assert _valid_active_tab(_BadMgr()) is False
    assert _valid_active_tab(_GoodMgr()) is True


def test_reset_cdp_state_clears_connected_and_manager():
    st = {"manager": _BadMgr(), "connected": True}
    _reset_cdp_state(st, "boom")
    assert st["manager"] is None
    assert st["connected"] is False
    assert st["last_disconnect_reason"] == "boom"

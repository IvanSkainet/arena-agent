"""CDP active-tab helper extraction tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.browser.cdp.active_tab import cdp_active_tab  # noqa: E402


class _Tab:
    def __init__(self, target_id="tab-1", connected=True):
        self.target_id = target_id
        self.connected = connected
        self.connect_called = False

    async def connect(self):
        self.connect_called = True
        self.connected = True


class _Manager:
    def __init__(self, active_tab=None, tabs=None):
        self.active_tab = active_tab
        self.tabs = tabs or {}

    def get_tab(self, tab_id):
        return self.tabs.get(tab_id)


def _json(response):
    return ub.json.loads(response.text)


def _kwargs(state, module=object()):
    return {
        "cdp_state": state,
        "get_cdp_module": lambda: module,
        "cors_json_response": ub._cors_json_response,
        "log_warning": lambda *args, **kwargs: None,
    }


def test_cdp_active_tab_missing_module():
    tab, response = asyncio.run(cdp_active_tab(**_kwargs({"connected": False}, module=None)))
    assert tab is None
    assert response.status == 500
    assert _json(response) == {"ok": False, "error": "cdp_browser module not found. Install to scripts/ directory."}


def test_cdp_active_tab_not_connected():
    tab, response = asyncio.run(cdp_active_tab(**_kwargs({"connected": False, "manager": None})))
    assert tab is None
    assert response.status == 400
    assert _json(response) == {"ok": False, "error": "CDP not connected. POST /v1/browser/cdp/connect first."}


def test_cdp_active_tab_specific_tab_not_found_or_disconnected():
    manager = _Manager(tabs={"tab-1": _Tab("tab-1", connected=False)})
    state = {"connected": True, "manager": manager}

    tab, response = asyncio.run(cdp_active_tab("missing", **_kwargs(state)))
    assert tab is None
    assert response.status == 404
    assert _json(response) == {"ok": False, "error": "Tab missing not found"}

    tab, response = asyncio.run(cdp_active_tab("tab-1", **_kwargs(state)))
    assert tab is None
    assert response.status == 400
    assert _json(response) == {"ok": False, "error": "Tab tab-1 is not connected"}


def test_cdp_active_tab_active_success_and_reconnect():
    tab_obj = _Tab(connected=False)
    manager = _Manager(active_tab=tab_obj)
    state = {"connected": True, "manager": manager}
    tab, response = asyncio.run(cdp_active_tab(**_kwargs(state)))
    assert response is None
    assert tab is tab_obj
    assert tab.connected is True
    assert tab.connect_called is True


def test_unified_cdp_active_tab_compat_wrapper_uses_extracted_helper():
    assert ub._cdp_active_tab_impl is cdp_active_tab

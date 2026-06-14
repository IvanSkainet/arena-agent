"""CDP runtime module extraction smoke tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.browser.cdp import runtime  # noqa: E402


def test_unified_cdp_runtime_reexports_runtime_singletons():
    assert ub._cdp_state is runtime._cdp_state
    assert ub._cdp_connect_lock is runtime._cdp_connect_lock
    assert ub._get_cdp_module is runtime._get_cdp_module
    assert ub._start_cdp_watcher is runtime._start_cdp_watcher
    assert ub._stop_cdp_watcher is runtime._stop_cdp_watcher
    assert ub._cdp_watcher_active is runtime.cdp_watcher_active


def test_cdp_runtime_initial_state_shape():
    state = runtime._cdp_state
    assert "manager" in state
    assert "connected" in state
    assert "port" in state
    assert "headless" in state
    assert "reconnect_count" in state


def test_cdp_watcher_active_false_when_not_started():
    runtime._stop_cdp_watcher()
    assert runtime.cdp_watcher_active() is False

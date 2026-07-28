"""v4.106.1 -- structured BrowserAct JSON error diagnostics."""
from __future__ import annotations

from arena.browser.browse_browseract import _browseract_likely_cause


def test_browseract_auth_required_has_actionable_cause():
    cause, action = _browseract_likely_cause("CLI_AUTH_REQUIRED", "API key required", None)
    assert cause == "browseract_api_key_missing"
    assert "auth set" in action


def test_browseract_cdp_proxy_failure_has_actionable_cause():
    cause, action = _browseract_likely_cause(
        "CONNECTION_FAILED",
        "Could not resolve WebSocket URL from http://127.0.0.1:61497/json/version.",
        {"cdp_url": "http://127.0.0.1:61497"},
    )
    assert cause == "browseract_local_cdp_proxy_failed"
    assert "cdp_url=http://127.0.0.1:61497" in action
    assert "report-log" in action

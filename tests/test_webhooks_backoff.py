"""Circuit-breaker behaviour for webhook delivery."""
from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.observability.webhooks as wh


def cfg(url="http://127.0.0.1:9999/webhook", events=None):
    return {"urls": [url], "events": events or ["*"]}


def test_webhook_backoff_logs_once_after_threshold(monkeypatch):
    wh.reset_webhook_breakers()
    calls = []
    logs = []

    def boom(url, payload):
        calls.append(url)
        raise ConnectionRefusedError("closed")

    monkeypatch.setattr(wh, "_send_one", boom)
    monkeypatch.setattr(wh, "_now", lambda: 100.0)

    for _ in range(6):
        wh.fire_webhooks({"type": "x"}, load_fn=cfg, log_debug=lambda *a: logs.append(a))

    assert len(calls) == 3
    assert len(logs) == 1
    assert "backing off" in logs[0][0]
    state = wh._BREAKERS["http://127.0.0.1:9999/webhook"]
    assert state["down"] is True
    assert state["open_until"] > 100.0


def test_webhook_backoff_retries_after_cooldown_and_exponentiates(monkeypatch):
    wh.reset_webhook_breakers()
    now = {"value": 100.0}
    calls = []

    def boom(url, payload):
        calls.append((url, now["value"]))
        raise TimeoutError("dead")

    monkeypatch.setattr(wh, "_send_one", boom)
    monkeypatch.setattr(wh, "_now", lambda: now["value"])

    for _ in range(3):
        wh.fire_webhooks({"type": "x"}, load_fn=cfg)
    first_open = wh._BREAKERS["http://127.0.0.1:9999/webhook"]["open_until"]
    assert first_open == 130.0

    now["value"] = 129.0
    wh.fire_webhooks({"type": "x"}, load_fn=cfg)
    assert len(calls) == 3

    now["value"] = 131.0
    for _ in range(3):
        wh.fire_webhooks({"type": "x"}, load_fn=cfg)
    second_open = wh._BREAKERS["http://127.0.0.1:9999/webhook"]["open_until"]
    assert second_open == 191.0


def test_webhook_success_recovers_after_open_state(monkeypatch):
    wh.reset_webhook_breakers()
    logs = []
    url = "http://example.test/webhook"
    wh._BREAKERS[url] = {"fails": 0, "open_until": 0.0, "trips": 2, "down": True}

    monkeypatch.setattr(wh, "_send_one", lambda u, payload: None)
    monkeypatch.setattr(wh, "_now", lambda: 999.0)

    wh.fire_webhooks({"type": "x"}, load_fn=lambda: cfg(url), log_debug=lambda *a: logs.append(a))

    assert logs == [("[Webhooks] %s recovered", url)]
    assert wh._BREAKERS[url] == {"fails": 0, "open_until": 0.0, "trips": 0, "down": False}


def test_webhook_filters_events_before_delivery(monkeypatch):
    wh.reset_webhook_breakers()
    calls = []
    monkeypatch.setattr(wh, "_send_one", lambda url, payload: calls.append(url))
    wh.fire_webhooks({"type": "ignored"}, load_fn=lambda: cfg(events=["wanted"]))
    assert calls == []


def test_webhook_internal_errors_are_logged(monkeypatch):
    logs = []

    def bad_load():
        raise urllib.error.URLError("broken config")

    wh.fire_webhooks({"type": "x"}, load_fn=bad_load, log_debug=lambda *a: logs.append(a))

    assert logs
    assert "Internal error" in logs[0][0]

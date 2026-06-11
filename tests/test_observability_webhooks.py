"""Webhook helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.observability.webhooks import load_webhooks, normalize_webhooks_config, save_webhooks  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_normalize_webhooks_config():
    cfg, err = normalize_webhooks_config({"urls": ["http://example.test", "file:///x"], "events": ["exec"]})
    assert err is None
    assert cfg == {"urls": ["http://example.test"], "events": ["exec"]}
    cfg, err = normalize_webhooks_config({"urls": "bad", "events": []})
    assert cfg is None and err


def test_load_save_webhooks(tmp_path):
    path = tmp_path / "webhooks.json"
    save_webhooks(path, {"urls": ["http://example.test"], "events": ["*"]})
    data = load_webhooks(path)
    assert data["urls"] == ["http://example.test"]


def test_unified_bridge_webhook_wrappers():
    assert callable(ub._load_webhooks)
    assert callable(ub._save_webhooks)
    assert callable(ub._fire_webhooks)

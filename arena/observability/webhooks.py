"""Webhook notification config and sender helpers."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any, Callable

_DEFAULT_WEBHOOKS = {"urls": [], "events": ["*"]}
_WEBHOOKS_CACHE: dict[str, Any] | None = None


def load_webhooks(path: Path) -> dict[str, Any]:
    global _WEBHOOKS_CACHE
    if _WEBHOOKS_CACHE is not None:
        return _WEBHOOKS_CACHE
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            _WEBHOOKS_CACHE = data
            return data
        except Exception:
            pass
    _WEBHOOKS_CACHE = dict(_DEFAULT_WEBHOOKS)
    return _WEBHOOKS_CACHE


def save_webhooks(path: Path, data: dict[str, Any]) -> None:
    global _WEBHOOKS_CACHE
    _WEBHOOKS_CACHE = data
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def normalize_webhooks_config(data: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    urls = data.get("urls", [])
    events = data.get("events", ["*"])
    if not isinstance(urls, list) or not isinstance(events, list):
        return None, "urls and events must be lists"
    cfg = {"urls": [str(u) for u in urls if str(u).startswith("http")], "events": [str(e) for e in events]}
    return cfg, None


def fire_webhooks(event: dict[str, Any], *, load_fn: Callable[[], dict[str, Any]], log_debug: Callable[..., None] | None = None) -> None:
    try:
        config = load_fn()
        if not config.get("urls"):
            return
        event_type = event.get("type", event.get("event", "unknown"))
        filters = set(config.get("events", ["*"]))
        if "*" not in filters and event_type not in filters:
            return
        payload = json.dumps(event, ensure_ascii=False).encode("utf-8")
        for url in config["urls"]:
            try:
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=5):
                    pass
            except Exception as e:
                if log_debug:
                    log_debug("[Webhooks] Failed to send to %s: %s", url, e)
    except Exception as e:
        if log_debug:
            log_debug("[Webhooks] Internal error: %s", e)

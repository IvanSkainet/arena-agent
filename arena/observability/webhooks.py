"""Webhook notification config and sender helpers."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

_DEFAULT_WEBHOOKS = {"urls": [], "events": ["*"]}
_WEBHOOKS_CACHE: dict[str, Any] | None = None
_WEBHOOK_FAIL_THRESHOLD = 3
_WEBHOOK_BASE_COOLDOWN = 30.0
_WEBHOOK_MAX_COOLDOWN = 3600.0
_BREAKERS: dict[str, dict[str, Any]] = {}


def _now() -> float:
    return time.monotonic()


def reset_webhook_breakers() -> None:
    """Clear per-URL circuit breaker state after config changes or in tests."""
    _BREAKERS.clear()


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
    reset_webhook_breakers()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def normalize_webhooks_config(data: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    urls = data.get("urls", [])
    events = data.get("events", ["*"])
    if not isinstance(urls, list) or not isinstance(events, list):
        return None, "urls and events must be lists"
    cfg = {"urls": [str(u) for u in urls if str(u).startswith("http")], "events": [str(e) for e in events]}
    return cfg, None


def _send_one(url: str, payload: bytes) -> None:
    # v4.43.0: opt-in outbound-SSRF hardening. Webhook URLs are
    # operator-configured and legitimately can point at private
    # addresses (local dev harness, home-network Discord relay,
    # etc.), so we do NOT block RFC1918 by default. Operators
    # who want strict outbound filtering set
    # ARENA_WEBHOOK_STRICT=1 and get the browser-fetch SSRF-guard
    # behaviour: metadata IMDS, ``.internal``, ``.local``,
    # RFC1918 all rejected.
    import os as _os
    if _os.environ.get("ARENA_WEBHOOK_STRICT", "").strip().lower() in (
            "1", "true", "yes", "on"):
        from arena.security_ssrf import _validate_url
        err = _validate_url(url)
        if err:
            raise ValueError(
                f"webhook URL rejected by strict SSRF check: {err}")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5):  # nosec B310 -- operator-configured webhook URL; ARENA_WEBHOOK_STRICT=1 enables SSRF filtering
        pass


def _breaker_for(url: str) -> dict[str, Any]:
    return _BREAKERS.setdefault(url, {"fails": 0, "open_until": 0.0, "trips": 0, "down": False})


def _mark_webhook_failure(url: str, exc: Exception, *, now: float, log_debug: Callable[..., None] | None) -> None:
    state = _breaker_for(url)
    state["fails"] += 1
    if state["fails"] < _WEBHOOK_FAIL_THRESHOLD:
        return
    state["trips"] += 1
    cooldown = min(_WEBHOOK_BASE_COOLDOWN * (2 ** (state["trips"] - 1)), _WEBHOOK_MAX_COOLDOWN)
    state["fails"] = 0
    state["open_until"] = now + cooldown
    if not state["down"] and log_debug:
        log_debug("[Webhooks] %s unreachable (%s); backing off %.0fs", url, exc, cooldown)
    state["down"] = True


def _mark_webhook_success(url: str, *, log_debug: Callable[..., None] | None) -> None:
    state = _breaker_for(url)
    if state["down"] and log_debug:
        log_debug("[Webhooks] %s recovered", url)
    state.update({"fails": 0, "open_until": 0.0, "trips": 0, "down": False})


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
        now = _now()
        for url in config["urls"]:
            if now < _breaker_for(url)["open_until"]:
                continue
            try:
                _send_one(url, payload)
            except Exception as e:
                _mark_webhook_failure(url, e, now=now, log_debug=log_debug)
            else:
                _mark_webhook_success(url, log_debug=log_debug)
    except Exception as e:
        if log_debug:
            log_debug("[Webhooks] Internal error: %s", e)

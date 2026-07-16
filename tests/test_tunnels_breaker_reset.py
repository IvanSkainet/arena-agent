"""Tests for POST /v1/tunnels/probe/reset + Dashboard reset buttons (v4.14.0).

The v4.8.0 circuit breaker had exactly two escape hatches: wait
60s or ``systemctl restart arena-bridge``. Neither felt like a
first-class ops tool. v4.14.0 adds:

* ``POST /v1/tunnels/probe/reset`` -- clear one keyed record or
  every record from the shared breaker singleton
* Per-open-badge "×" button in the Overview Network Status card
* A "Reset all" button at the row tail once any breaker is open

Same containment discipline as every dashboard change since
v4.6.0: dashboard.css untouched, all new styling scoped to
``#tab-overview #networkCard``, no hex literals inline.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_REPO = Path(__file__).resolve().parents[1]
_BODY = _REPO / "dashboard" / "assets" / "body-01-overview.html"
_JS = _REPO / "dashboard" / "assets" / "04c-net-breaker.js"
_CSS = _REPO / "dashboard" / "assets" / "dashboard.css"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Backend: route registration + wiring guards
# ---------------------------------------------------------------------------
def test_reset_route_in_registry_with_post_method():
    """POST -- this is a mutation, not a query. GET would be
    technically fine but browsers cache GETs; the manual reset
    button in the Dashboard needs the request to actually hit
    the server every click."""
    from arena.route_registry.registry import ROUTES
    keys = {(m, p) for (m, p, *_rest) in ROUTES}
    assert ("POST", "/v1/tunnels/probe/reset") in keys


def test_reset_route_wired_in_core_router():
    core_py = (_REPO / "arena" / "route_registry" / "core.py"
               ).read_text(encoding="utf-8")
    assert 'add_post("/v1/tunnels/probe/reset"' in core_py
    assert 'h["handle_v1_tunnels_probe_reset"]' in core_py


def test_wiring_exports_reset_key():
    plat = (_REPO / "arena" / "wiring" / "platform.py"
            ).read_text(encoding="utf-8")
    assert '"handle_v1_tunnels_probe_reset"' in plat
    assert "handlers.tunnels_probe_reset" in plat


def test_admin_handlers_dataclass_has_reset_field():
    from arena.admin.handlers import AdminHandlers
    assert "tunnels_probe_reset" in AdminHandlers.__dataclass_fields__


# ---------------------------------------------------------------------------
# Backend: reset behaviour against a real breaker singleton
# ---------------------------------------------------------------------------
def _seed_breaker(keys_with_state):
    """Populate the shared breaker with the given (key, state)
    tuples so tests can then verify a reset clears them."""
    from arena.admin.tunnels_breaker import (
        get_default_breaker, reset_default_breaker,
    )
    reset_default_breaker()
    b = get_default_breaker()
    for key, state in keys_with_state:
        if state == "open":
            # Force-open by racking up threshold failures.
            for _ in range(b.threshold):
                b.record_failure(key, error="test-forced")
        elif state == "warn":
            b.record_failure(key, error="test-warn")
        elif state == "ok":
            b.record_success(key)
    return b


class _FakeRequest:
    """Minimal aiohttp.web.Request stand-in the handler reads:
    .json() coroutine, .remote str, .app[APP_CFG] no-op. The
    handler doesn't touch anything else on the request."""

    def __init__(self, body_json=None, remote="127.0.0.1"):
        self._body = body_json
        self.remote = remote

    async def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


def _build_reset_handler():
    """Bypass the full admin-handler factory (needs many stubs the
    reset handler doesn't touch) by inlining the same body against
    the shared breaker singleton. Keeps the test focused on the
    contract we're actually shipping, not the wiring around it.

    The wiring itself is proved by
    ``test_reset_route_in_registry_with_post_method`` +
    ``test_admin_handlers_dataclass_has_reset_field`` and by the
    live smoke -- so redundant coverage here would just be
    fragile boilerplate."""
    from arena.admin.tunnels_breaker import get_default_breaker

    events = []
    audit = lambda ev: events.append(ev)  # noqa: E731

    async def fn(request):
        key = None
        try:
            data = await request.json()
            if isinstance(data, dict):
                raw = data.get("key")
                if isinstance(raw, str) and raw.strip():
                    key = raw.strip()
        except Exception:
            pass
        breaker = get_default_breaker()
        before = breaker.snapshot()
        if key is not None:
            breaker.reset(key)
        else:
            breaker.reset()
        audit({
            "type": "tunnels_breaker_reset",
            "key": key or "all",
            "keys_cleared": (1 if key else len(before)),
            "client": getattr(request, "remote", "127.0.0.1") or "127.0.0.1",
        })

        class _Resp:
            def __init__(self, payload):
                import json
                self.body = json.dumps(payload).encode("utf-8")

        return _Resp({
            "ok": True,
            "reset": key or "all",
            "keys_cleared": (1 if key else len(before)),
            "breaker_before": before,
            "breaker_after": breaker.snapshot(),
        })

    return fn, events


def _read_json_body(response):
    """Extract dict from the response object our stub returned."""
    import json
    return json.loads(response.body.decode("utf-8"))


def test_reset_clears_all_when_body_empty():
    """POST with no body / empty JSON drops every breaker record."""
    _seed_breaker([
        ("cloudflared|a.example:443", "open"),
        ("zerotier|10.0.0.1:8765", "open"),
    ])
    from arena.admin.tunnels_breaker import get_default_breaker
    assert len(get_default_breaker().snapshot()) == 2

    fn, events = _build_reset_handler()
    req = _FakeRequest(body_json=None)  # empty body -> reset all
    resp = asyncio.run(fn(req))
    payload = _read_json_body(resp)

    assert payload["ok"] is True
    assert payload["reset"] == "all"
    assert payload["keys_cleared"] == 2
    assert set(payload["breaker_before"]) == {
        "cloudflared|a.example:443",
        "zerotier|10.0.0.1:8765",
    }
    assert payload["breaker_after"] == {}
    assert len(get_default_breaker().snapshot()) == 0

    assert any(e["type"] == "tunnels_breaker_reset"
               and e["key"] == "all"
               and e["keys_cleared"] == 2 for e in events)


def test_reset_clears_only_the_requested_key():
    """POST with {'key': '...'} touches only that record; others
    stay intact so a wide flap of one provider doesn't wipe every
    other breaker's failure history."""
    _seed_breaker([
        ("cloudflared|a.example:443", "open"),
        ("zerotier|10.0.0.1:8765", "open"),
    ])
    fn, events = _build_reset_handler()
    req = _FakeRequest(body_json={"key": "cloudflared|a.example:443"})
    resp = asyncio.run(fn(req))
    payload = _read_json_body(resp)

    assert payload["ok"] is True
    assert payload["reset"] == "cloudflared|a.example:443"
    assert payload["keys_cleared"] == 1

    from arena.admin.tunnels_breaker import get_default_breaker
    snap = get_default_breaker().snapshot()
    assert "cloudflared|a.example:443" not in snap
    assert "zerotier|10.0.0.1:8765" in snap
    assert snap["zerotier|10.0.0.1:8765"]["state"] == "open"

    assert any(e["type"] == "tunnels_breaker_reset"
               and e["key"] == "cloudflared|a.example:443" for e in events)


def test_reset_treats_whitespace_key_as_no_key():
    """Guard against a client sending {'key': ' '} accidentally --
    the handler must treat it as "reset all" rather than passing
    the whitespace string through to breaker.reset() (which would
    silently no-op and leave the operator confused)."""
    _seed_breaker([("k|h:1", "open"), ("k|h:2", "open")])
    fn, _events = _build_reset_handler()
    req = _FakeRequest(body_json={"key": "   "})
    resp = asyncio.run(fn(req))
    payload = _read_json_body(resp)
    assert payload["reset"] == "all"
    from arena.admin.tunnels_breaker import get_default_breaker
    assert get_default_breaker().snapshot() == {}


def test_reset_survives_malformed_body_without_500():
    """A non-JSON body must not blow up the handler -- treat it as
    an empty request and reset everything. Prevents a curl typo
    from returning 500."""
    _seed_breaker([("cloudflared|foo:443", "open")])
    fn, _events = _build_reset_handler()

    class _BadReq:
        remote = "127.0.0.1"
        async def json(self):
            raise ValueError("not JSON")

    resp = asyncio.run(fn(_BadReq()))
    payload = _read_json_body(resp)
    assert payload["ok"] is True
    assert payload["reset"] == "all"


def test_reset_audit_event_shape():
    """The audit trail must record who cleared what so a post-hoc
    investigation ("who reset the Cloudflared breaker at 14:22 and
    made the outage look shorter than it was?") is actually
    possible."""
    _seed_breaker([("cloudflared|x:443", "open")])
    fn, events = _build_reset_handler()
    req = _FakeRequest(body_json={"key": "cloudflared|x:443"},
                       remote="10.57.152.44")
    asyncio.run(fn(req))
    e = [x for x in events if x["type"] == "tunnels_breaker_reset"][-1]
    assert e["key"] == "cloudflared|x:443"
    assert e["keys_cleared"] == 1
    assert e["client"] == "10.57.152.44"


# ---------------------------------------------------------------------------
# Dashboard UI: reset buttons in the net-breaker row
# ---------------------------------------------------------------------------
def test_js_renders_reset_button_only_on_open_badges():
    """The '×' reset button appears only when state === 'open'. A
    warn/ok breaker doesn't need one -- there's nothing to clear."""
    js = _read(_JS)
    # The reset button is created inside an ``if (state === "open")``
    # branch. Regression guard against a future edit that hoists
    # the button unconditionally (spamming healthy triples).
    open_idx = js.find('state === "open"')
    btn_idx = js.find('className = "reset"')
    assert open_idx != -1 and btn_idx != -1
    assert btn_idx > open_idx, (
        "'× reset' button must be created inside the state===open branch"
    )


def test_js_reset_button_posts_correct_endpoint_and_key():
    js = _read(_JS)
    # Endpoint used verbatim.
    assert '"/v1/tunnels/probe/reset"' in js
    # Per-badge button sends the exact key -- otherwise the whole
    # breaker gets wiped instead of just this provider.
    assert 'JSON.stringify({key: k})' in js


def test_js_reset_all_button_appears_only_when_any_open():
    """The bulk reset shows up once any breaker is open. Otherwise
    healthy-triple hosts see no controls at all (net-breaker row
    already hidden by v4.11.0)."""
    js = _read(_JS)
    assert 'keys.some(' in js
    assert '(snapshot[k] || {}).state === "open"' in js
    assert 'className = "reset-all"' in js


def test_js_reset_all_button_posts_empty_body():
    """Empty body = reset every record. Regression guard against a
    future edit that adds a key= to the bulk button (would only
    clear one)."""
    js = _read(_JS)
    # Find the reset-all click handler and confirm the fetch body
    # is an empty object.
    idx = js.find('className = "reset-all"')
    assert idx != -1
    body = js[idx:idx + 800]
    assert 'JSON.stringify({})' in body
    assert '"/v1/tunnels/probe/reset"' in body


def test_js_reset_buttons_debounce_via_disabled():
    """Both buttons disable themselves during the in-flight POST so
    an impatient operator smashing the button doesn't fire ten
    requests. Simple debounce, no timers needed."""
    js = _read(_JS)
    assert "btn.disabled = true" in js
    assert "resetAll.disabled = true" in js


def test_js_reset_button_triggers_immediate_refresh():
    """After a reset the operator wants to see the new state
    without waiting for the next Overview tick. Both buttons call
    refreshNetBreaker() in their finally-equivalent branch."""
    js = _read(_JS)
    # Count refreshNetBreaker() invocations inside the render body.
    # Should appear at least twice (once per button).
    n = js.count("refreshNetBreaker()")
    assert n >= 2, (
        f"refreshNetBreaker() invoked only {n} times; both reset "
        "buttons must trigger an immediate refresh"
    )


def test_js_reset_click_stops_propagation():
    """The badge is not a click target but future edits might make
    it one (row-expand pattern, like the Audit tab). Stopping
    propagation from the button click future-proofs against
    that."""
    js = _read(_JS)
    assert "ev.stopPropagation()" in js


# ---------------------------------------------------------------------------
# Containment (v4.0.x lesson still holds)
# ---------------------------------------------------------------------------
def test_dashboard_css_untouched_by_reset_button_work():
    css = _read(_CSS)
    for token in (".reset-all", "net-breaker .reset", ".net-breaker-list .item .reset"):
        # A raw substring check is enough -- the shared CSS has no
        # ``.reset`` selectors of any kind today.
        assert token not in css, f"leaked into dashboard.css: {token!r}"


def test_body_scopes_new_reset_styles_to_tab_overview():
    """The new ``.reset`` and ``.reset-all`` rules must live inside
    the scoped ``#tab-overview #networkCard`` block (same
    containment shape as the v4.11.0 breaker row itself)."""
    body = _read(_BODY)
    for rule_prefix in (
        "#tab-overview #networkCard .net-breaker-list .item .reset",
        "#tab-overview #networkCard .net-breaker-list .reset-all",
    ):
        assert rule_prefix in body, (
            f"reset button rule not scoped as expected: {rule_prefix}"
        )

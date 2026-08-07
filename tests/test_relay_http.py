"""The relay over HTTP: auth, clamping, and the honesty flag.

The store is covered by `test_relay_store.py`; this file is about the
five endpoints and the two properties that only exist at this layer.

**A long-poll must not park a worker forever.** The bridge runs a fixed
`max_concurrent`; a caller asking for `wait=99999` would hold a thread
until the tunnel gave up, and enough of them would take the bridge down
without a single malformed request. `wait` is clamped to `MAX_WAIT_S`,
which is also under the idle timeout most tunnels use -- a poll that
outlives the proxy looks to the operator like a lost message.

**Polling must be recorded even when it finds nothing.** That is the
whole basis for `send` telling the truth about whether anyone is
listening. Report delivery to an empty room and you have rebuilt bug #66
in a new place.
"""
from __future__ import annotations

import pytest

from arena.relay import handlers as H


class _Ctx:
    """Minimal stand-in for the wiring context."""

    def __init__(self, root):
        self._root = root
        self.audits: list[dict] = []

    def relay_root(self):
        return self._root

    def require_auth(self, request):
        return None

    def record_request(self, *a, **k):
        return None

    def audit(self, entry):
        self.audits.append(entry)

    @property
    def executor(self):
        return None

    def cors_json_response(self, payload, status=200):
        return ("json", payload, status)


# --------------------------------------------------------------------
# Clamping: the property that keeps a public endpoint from being a DoS.
# --------------------------------------------------------------------

@pytest.mark.parametrize(("raw", "expected"), [
    ("0", 0.0),
    ("5", 5.0),
    ("25", 25.0),
    ("26", H.MAX_WAIT_S),
    ("99999", H.MAX_WAIT_S),
    ("1e9", H.MAX_WAIT_S),
    ("-5", 0.0),
    ("-99999", 0.0),
])
def test_wait_is_clamped_into_a_survivable_range(raw, expected):
    assert H._clamp_wait(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", None, "NaN", [], {}])
def test_garbage_wait_falls_back_to_the_default(raw):
    """Never raise out of a query-string parse; never inherit a huge value."""
    assert H._clamp_wait(raw, default=3.0) == 3.0


@pytest.mark.parametrize("raw", ["inf", "Infinity", "-inf", float("inf"),
                                 float("-inf")])
def test_infinity_cannot_park_a_worker(raw):
    """`float("inf")` parses fine and compares greater than any cap.

    It must land inside the range rather than raising or slipping
    through: `min(inf, MAX)` is MAX and `max(0, -inf)` is 0, so the clamp
    holds -- but only because the comparison order is right, which is
    what this pins.
    """
    value = H._clamp_wait(raw)
    assert 0.0 <= value <= H.MAX_WAIT_S


def test_the_cap_is_under_a_typical_proxy_idle_timeout():
    """30s is the common default for tunnels and reverse proxies.

    A long-poll that outlives the proxy is cut mid-flight and reads to
    the operator as a dropped message, so the cap has to sit below it
    with room to spare.
    """
    assert 0 < H.MAX_WAIT_S < 30


def test_poll_freshness_covers_a_full_long_poll_cycle():
    """Otherwise an agent mid-poll would be reported as absent."""
    assert H.POLL_FRESH_S > H.MAX_WAIT_S * 2


# --------------------------------------------------------------------
# The honesty flag, end to end through the handler layer.
# --------------------------------------------------------------------

@pytest.fixture
def wired(tmp_path):
    """Real handlers, real store, executor stubbed to run inline."""
    import asyncio

    ctx = _Ctx(tmp_path / "relay")
    handlers = H.make_relay_handlers(ctx)

    class _Loop:
        async def run_in_executor(self, _ex, fn):
            return fn()

    real_get_loop = asyncio.get_running_loop
    return ctx, handlers, _Loop(), real_get_loop


def _run(coro):
    import asyncio

    return asyncio.run(coro)


class _Req:
    def __init__(self, payload=None, query=None):
        self._payload = payload
        self.query = query or {}
        self.remote = "127.0.0.1"

    async def json(self):
        if self._payload is None:
            raise ValueError("no body")
        return self._payload

    def __setitem__(self, key, value):
        pass


def test_send_reports_no_listener_before_anyone_polls(wired, monkeypatch):
    import asyncio

    ctx, handlers, loop, _ = wired
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)

    _kind, payload, status = _run(
        handlers.relay_send(_Req({"body": "hello"})))
    assert status == 200
    assert payload["ok"] is True
    assert payload["agent_polling"] is False, (
        "nobody has polled yet; claiming otherwise is the bug #66 shape"
    )
    assert payload["inbox_depth"] == 1


def test_send_reports_a_listener_after_a_poll(wired, monkeypatch):
    import asyncio

    ctx, handlers, loop, _ = wired
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)

    # An agent polls an EMPTY inbox and finds nothing. It is still
    # listening, and the next `send` has to say so.
    _run(handlers.relay_poll(_Req(query={"wait": "0"})))
    _kind, payload, _status = _run(
        handlers.relay_send(_Req({"body": "hello"})))
    assert payload["agent_polling"] is True
    assert payload["last_poll_age_s"] is not None


def test_an_empty_body_is_a_400_not_a_500(wired, monkeypatch):
    import asyncio

    _ctx, handlers, loop, _ = wired
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)
    _kind, payload, status = _run(handlers.relay_send(_Req({"body": "   "})))
    assert status == 400
    assert payload["ok"] is False


def test_unparseable_json_is_a_400(wired, monkeypatch):
    import asyncio

    _ctx, handlers, loop, _ = wired
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)
    _kind, payload, status = _run(handlers.relay_send(_Req(None)))
    assert status == 400
    assert "invalid json" in payload["error"]


def test_the_full_round_trip_through_the_handlers(wired, monkeypatch):
    import asyncio

    _ctx, handlers, loop, _ = wired
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)

    _k, sent, _s = _run(handlers.relay_send(_Req({"body": "fix bug 99"})))
    _k, polled, _s = _run(handlers.relay_poll(_Req(query={"wait": "0"})))
    assert polled["message"]["body"] == "fix bug 99"

    _k, replied, _s = _run(handlers.relay_reply(
        _Req({"in_reply_to": sent["id"], "body": "done"})))
    assert replied["ok"] is True

    _k, got, _s = _run(handlers.relay_replies(
        _Req(query={"in_reply_to": sent["id"], "wait": "0"})))
    assert [r["body"] for r in got["replies"]] == ["done"]


def test_every_send_and_claim_is_audited(wired, monkeypatch):
    """The relay carries instructions; an unlogged instruction is a gap."""
    import asyncio

    ctx, handlers, loop, _ = wired
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)
    _run(handlers.relay_send(_Req({"body": "do a thing"})))
    _run(handlers.relay_poll(_Req(query={"wait": "0"})))
    kinds = [a.get("type") for a in ctx.audits]
    assert "relay.send" in kinds
    assert "relay.claim" in kinds


def test_the_audit_records_size_not_content(wired, monkeypatch):
    """Message bodies can carry anything; the audit log is not the place."""
    import asyncio

    ctx, handlers, loop, _ = wired
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: loop)
    _run(handlers.relay_send(_Req({"body": "secret instruction"})))
    entry = next(a for a in ctx.audits if a["type"] == "relay.send")
    assert "secret instruction" not in str(entry)
    assert entry["bytes"] == len("secret instruction")


# --------------------------------------------------------------------
# Wiring: the endpoints must actually be reachable.
# --------------------------------------------------------------------

def test_all_five_routes_are_registered():
    """A handler nobody routed to is a handler that does not exist."""
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[1]
    routes = (repo / "arena" / "route_registry" / "domain.py").read_text(
        encoding="utf-8")
    for path in ("/v1/relay/send", "/v1/relay/poll", "/v1/relay/reply",
                 "/v1/relay/replies", "/v1/relay/status"):
        assert path in routes, f"{path} is not wired into the router"


def test_the_route_registry_lists_them_for_the_auth_audit():
    """tests/test_auth_surface_guard.py walks this list.

    A route missing here is a route nobody checks for authentication --
    exactly how bug #57 left 66 of 274 endpoints unverified.
    """
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[1]
    registry = (repo / "arena" / "route_registry" / "registry.py").read_text(
        encoding="utf-8")
    for name in ("handle_v1_relay_send", "handle_v1_relay_poll",
                 "handle_v1_relay_reply", "handle_v1_relay_replies",
                 "handle_v1_relay_status"):
        assert name in registry, f"{name} missing from the auth-audited registry"

"""Unit tests for arena.mcp.ws_push (v4.79.0 coverage lift).

The module implements the topic-based push notification extension
for the standalone MCP WebSocket server. Until v4.79.0 it had
0% line coverage (52 statements, 18 branches, never imported by
any test). These tests cover the pure data-plane operations
(subscribe, unsubscribe, broadcast) without spawning the
notify-watcher thread.
"""
from __future__ import annotations

import json

import pytest

from arena.mcp import ws_push


@pytest.fixture(autouse=True)
def _reset_subs():
    """Wipe the module-level SUBS dict before each test."""
    with ws_push.SUBS_LOCK:
        ws_push.SUBS.clear()
    yield
    with ws_push.SUBS_LOCK:
        ws_push.SUBS.clear()


# --------------------------------------------------------------------
# _subscribe / _unsubscribe_all
# --------------------------------------------------------------------
def test_subscribe_adds_sock_to_topic():
    s = object()  # sentinel -- we never call _send_text on it
    ws_push._subscribe(s, "alpha")
    with ws_push.SUBS_LOCK:
        assert s in ws_push.SUBS["alpha"]


def test_subscribe_is_idempotent():
    s = object()
    ws_push._subscribe(s, "alpha")
    ws_push._subscribe(s, "alpha")
    with ws_push.SUBS_LOCK:
        assert len(ws_push.SUBS["alpha"]) == 1


def test_subscribe_distinct_topics():
    s = object()
    ws_push._subscribe(s, "alpha")
    ws_push._subscribe(s, "beta")
    with ws_push.SUBS_LOCK:
        assert s in ws_push.SUBS["alpha"]
        assert s in ws_push.SUBS["beta"]


def test_unsubscribe_all_removes_sock_from_every_topic():
    s = object()
    ws_push._subscribe(s, "alpha")
    ws_push._subscribe(s, "beta")
    ws_push._unsubscribe_all(s)
    with ws_push.SUBS_LOCK:
        assert "alpha" not in ws_push.SUBS
        assert "beta" not in ws_push.SUBS


def test_unsubscribe_all_clears_empty_topics():
    s = object()
    ws_push._subscribe(s, "alpha")
    ws_push._unsubscribe_all(s)
    with ws_push.SUBS_LOCK:
        # An empty topic bucket should be removed to keep SUBS tidy.
        assert "alpha" not in ws_push.SUBS


def test_unsubscribe_unknown_sock_is_noop():
    s = object()
    ws_push._subscribe(s, "alpha")
    ws_push._unsubscribe_all(object())  # different sentinel
    with ws_push.SUBS_LOCK:
        # Original subscriber is untouched.
        assert s in ws_push.SUBS["alpha"]


# --------------------------------------------------------------------
# _broadcast
# --------------------------------------------------------------------
class _FakeSock:
    def __init__(self, fail_on_send=False):
        self.sent: list[str] = []
        self._fail = fail_on_send

    def __hash__(self):  # so SUBS can hold it in a set
        return id(self)

    def __eq__(self, other):  # identity equality for set membership
        return self is other


def test_broadcast_sends_to_all_subscribers():
    # Historical note: ws_push used to rely on `from ws_frames import *` for
    # `_send_text`, which never provided it (star imports skip underscore
    # names) -- so broadcasts silently sent nothing. Fixed in v4.155.0 by an
    # explicit import; see tests/test_ws_push_star_import_regression.py.
    sent: list[str] = []

    def fake_send_text(sock, msg):
        sent.append(msg)

    # v4.155.0: ws_push now imports _send_text explicitly, so it IS present.
    # Patch unconditionally -- the old `only inject if missing` dance quietly
    # became a no-op the moment the real bug was fixed, and the assertions
    # below then measured nothing.
    real = ws_push._send_text
    ws_push._send_text = fake_send_text
    try:
        s1, s2 = _FakeSock(), _FakeSock()
        ws_push._subscribe(s1, "alpha")
        ws_push._subscribe(s2, "alpha")
        ws_push._broadcast("alpha", {"hello": "world"})

        assert len(sent) == 2
        for msg in sent:
            parsed = json.loads(msg)
            assert parsed["method"] == "notify"
            assert parsed["params"]["topic"] == "alpha"
            assert parsed["params"]["data"] == {"hello": "world"}
    finally:
        ws_push._send_text = real


def test_broadcast_skips_unknown_topic():
    # No subscribers -> no send, no error.
    ws_push._broadcast("never-subscribed", {"x": 1})


def test_broadcast_drops_dead_sockets():
    dead = _FakeSock(fail_on_send=True)
    alive = _FakeSock()
    sent: list[tuple] = []

    def fake_send_text(sock, msg):
        if sock is dead:
            raise RuntimeError("connection reset")
        sent.append((sock, msg))

    # v4.155.0: ws_push now imports _send_text explicitly, so it IS present.
    # Patch unconditionally -- the old `only inject if missing` dance quietly
    # became a no-op the moment the real bug was fixed, and the assertions
    # below then measured nothing.
    real = ws_push._send_text
    ws_push._send_text = fake_send_text
    try:
        ws_push._subscribe(dead, "alpha")
        ws_push._subscribe(alive, "alpha")
        ws_push._broadcast("alpha", {"k": 1})

        # Only the alive socket got the message.
        assert len(sent) == 1
        assert sent[0][0] is alive
        # And the dead socket was unsubscribed.
        with ws_push.SUBS_LOCK:
            assert dead not in ws_push.SUBS.get("alpha", set())
    finally:
        ws_push._send_text = real


def test_broadcast_payload_is_json_safe_with_unicode():
    sent: list[str] = []

    def fake_send_text(sock, msg):
        sent.append(msg)

    # v4.155.0: ws_push now imports _send_text explicitly, so it IS present.
    # Patch unconditionally -- the old `only inject if missing` dance quietly
    # became a no-op the moment the real bug was fixed, and the assertions
    # below then measured nothing.
    real = ws_push._send_text
    ws_push._send_text = fake_send_text
    try:
        s = _FakeSock()
        ws_push._subscribe(s, "i18n")
        ws_push._broadcast("i18n", {"greeting": "привет"})
        parsed = json.loads(sent[0])
        assert parsed["params"]["data"]["greeting"] == "привет"
    finally:
        ws_push._send_text = real

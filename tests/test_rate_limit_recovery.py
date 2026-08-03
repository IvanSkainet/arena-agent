"""A rate limiter must let a retrying client back in.

``check_rate_limit_v2`` used to append the *rejected* request's timestamp to
the same sliding window it consults to decide rejection::

    if remaining <= 0:
        ep_store.append(now)      # <-- the bug
        ...
        return 429

That makes the window self-sustaining.  ``ep_store`` is pruned with
``now - t < window``, so as long as the client knocks more often than
``window`` seconds, every knock refreshes the newest entry *and* the oldest
entry never gets a chance to age out -- the store stays at the limit
forever.  The client is not throttled, it is permanently banned, and the
trigger is the single most ordinary client behaviour there is: retrying.

Measured before the fix, with limit=10 and a 60s window:

    knock every 70s  -> recovered after 70s
    knock every  5s  -> still blocked after 1000s
    knock every  1s  -> still blocked after 600s

Only the client polite enough to back off past the whole window recovered,
which is exactly backwards: the dashboard polls every second, and any agent
with a retry loop hammers harder than that.

``check_rate_limit`` (v1, the older limiter in the same module) never had
this bug -- it returns the 429 without touching the list -- so the two
limiters stacked on the same request disagreed about what a window means.

Time is injected rather than slept, so this runs in milliseconds and tests
the algorithm instead of the clock.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.rate_limit as RL  # noqa: E402


class _Resp:
    def __init__(self, body, status):
        self.body = body
        self.status = status
        self.headers: dict[str, str] = {}


def _resp_fn(body, status=200):
    return _Resp(body, status)


class _Req(dict):
    """Minimal stand-in for aiohttp's Request (the limiter only needs these)."""

    def __init__(self, path: str = "/mcp", remote: str = "10.0.0.1") -> None:
        super().__init__()
        self.path = path
        self.remote = remote
        self.headers: dict[str, str] = {}


@pytest.fixture
def limiter(monkeypatch):
    """A v2 limiter with a controllable clock and an isolated store."""
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(RL.time, "time", lambda: clock["t"])
    RL._rl_v2_store.clear()
    saved = dict(RL._rl_v2_config)
    RL._rl_v2_config.update({"enabled": True, "default_limit": 10,
                             "window_seconds": 60, "per_user_limits": {},
                             "per_endpoint_limits": {}})

    def hit(path="/mcp"):
        return RL.check_rate_limit_v2(
            _Req(path), check_auth_with_role_fn=lambda r: (True, "admin"),
            cors_json_response_fn=_resp_fn)

    def advance(seconds):
        clock["t"] += seconds

    yield hit, advance
    RL._rl_v2_config.clear()
    RL._rl_v2_config.update(saved)
    RL._rl_v2_store.clear()


def _exhaust(hit, advance, limit=10):
    for _ in range(limit):
        assert hit() is None, "limiter rejected before the limit was reached"
        advance(0.001)
    assert hit() is not None, "limiter did not reject after the limit"


@pytest.mark.parametrize("retry_every", [0.5, 1, 5, 15, 59])
def test_impatient_client_recovers_within_one_window(limiter, retry_every):
    """Retrying faster than the window must not extend the ban."""
    hit, advance = limiter
    _exhaust(hit, advance)

    elapsed = 0.0
    limit_window = RL._rl_v2_config["window_seconds"]
    # Poll for three full windows; recovery must arrive inside roughly one.
    while elapsed < limit_window * 3:
        advance(retry_every)
        elapsed += retry_every
        if hit() is None:
            assert elapsed <= limit_window + retry_every + 1, (
                f"recovered, but only after {elapsed:.1f}s for a "
                f"{limit_window}s window")
            return
    pytest.fail(
        f"client retrying every {retry_every}s was still blocked after "
        f"{elapsed:.0f}s of a {limit_window}s window -- rejected requests are "
        "extending the window, which is a permanent ban, not throttling")


def test_patient_client_still_recovers(limiter):
    """The well-behaved case must keep working (no over-correction)."""
    hit, advance = limiter
    _exhaust(hit, advance)
    advance(RL._rl_v2_config["window_seconds"] + 1)
    assert hit() is None


def test_limiter_still_actually_limits(limiter):
    """A gate that never rejects would make the test above vacuous."""
    hit, advance = limiter
    for _ in range(RL._rl_v2_config["default_limit"]):
        assert hit() is None
        advance(0.001)
    rejected = hit()
    assert rejected is not None and rejected.status == 429
    assert rejected.headers["Retry-After"]


def test_v1_limiter_also_recovers_while_being_hammered(monkeypatch):
    """The older limiter is stacked on the same request; check it agrees."""
    clock = {"t": 2_000_000.0}
    monkeypatch.setattr(RL.time, "time", lambda: clock["t"])
    RL._rate_limit_store.clear()
    monkeypatch.setattr(RL, "_rate_limit_max", 5)
    monkeypatch.setattr(RL, "_rate_limit_window", 60.0)

    def hit():
        return RL.check_rate_limit(_Req(), cors_json_response_fn=_resp_fn)

    for _ in range(5):
        assert hit() is None
        clock["t"] += 0.001
    assert hit() is not None

    elapsed = 0.0
    while elapsed < 180:
        clock["t"] += 1
        elapsed += 1
        if hit() is None:
            assert elapsed <= 62, f"v1 recovered only after {elapsed}s"
            return
    pytest.fail("v1 limiter never recovered while being polled every second")

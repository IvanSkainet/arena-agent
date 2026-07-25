"""v4.83.0 — contract tests for the mobile recording request shape.

These guard the two honesty/correctness fixes that came out of the
"voice memo -> transcription" scenario drive:

  1. ``audio_unsupported_error`` — the bridge must no longer silently
     write a *silent* MP4 when ``audio`` is requested. The screenrecord
     CLI records video only (verified against AOSP), so the honest
     behaviour is a loud ``unsupported_capability`` error.

  2. ``resolve_duration_ms`` — the requested recording length must no
     longer be silently ignored. The MCP surface sends ``time_limit``
     (seconds, screenrecord semantics) while the handler historically
     read only ``duration_ms``; both must now resolve correctly with
     ``duration_ms`` taking precedence.

Both helpers are pure, so these tests need neither adb nor a device.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mobile import recording as _rec


# ---------------------------------------------------------------------------
# audio_unsupported_error — refuse loudly, never lie by omission
# ---------------------------------------------------------------------------
def test_audio_requested_returns_honest_error():
    err = _rec.audio_unsupported_error({"audio": True})
    assert err is not None
    assert err["ok"] is False
    assert err["error_type"] == "unsupported_capability"
    # The message must state the real limitation (video only, no audio).
    assert "video only" in err["error"]
    assert "screenrecord" in err["error"]
    # And point the agent at a path that actually works.
    assert "tap_by" in err["hint"]


def test_audio_truthy_values_all_refused():
    for val in (True, 1, "yes", {"any": "thing"}):
        assert _rec.audio_unsupported_error({"audio": val}) is not None


def test_audio_absent_or_false_falls_through():
    assert _rec.audio_unsupported_error({}) is None
    assert _rec.audio_unsupported_error({"audio": False}) is None
    assert _rec.audio_unsupported_error({"audio": 0}) is None
    assert _rec.audio_unsupported_error({"audio": ""}) is None
    assert _rec.audio_unsupported_error(None) is None
    assert _rec.audio_unsupported_error({"duration_ms": 5000}) is None


def test_audio_error_is_a_fresh_copy_each_call():
    a = _rec.audio_unsupported_error({"audio": True})
    b = _rec.audio_unsupported_error({"audio": True})
    assert a is not b
    # Mutating one must not poison the template the next caller sees.
    a["mutated"] = True
    assert "mutated" not in _rec.audio_unsupported_error({"audio": True})


# ---------------------------------------------------------------------------
# resolve_duration_ms — honour the requested length from either field
# ---------------------------------------------------------------------------
def test_duration_ms_canonical():
    assert _rec.resolve_duration_ms({"duration_ms": 1234}, 5000) == 1234


def test_time_limit_seconds_converted_to_ms():
    assert _rec.resolve_duration_ms({"time_limit": 8}, 5000) == 8000
    assert _rec.resolve_duration_ms({"time_limit": 2.5}, 5000) == 2500


def test_duration_ms_wins_over_time_limit():
    assert _rec.resolve_duration_ms(
        {"duration_ms": 1000, "time_limit": 9}, 5000) == 1000


def test_string_numbers_are_coerced():
    assert _rec.resolve_duration_ms({"duration_ms": "1500"}, 5000) == 1500
    assert _rec.resolve_duration_ms({"time_limit": "8"}, 5000) == 8000


def test_unparseable_falls_back_then_to_default():
    # Bad duration_ms but good time_limit -> use time_limit.
    assert _rec.resolve_duration_ms(
        {"duration_ms": "abc", "time_limit": 3}, 5000) == 3000
    # Bad everything -> default.
    assert _rec.resolve_duration_ms({"duration_ms": "abc"}, 5000) == 5000
    assert _rec.resolve_duration_ms({}, 30_000) == 30_000
    assert _rec.resolve_duration_ms(None, 5000) == 5000

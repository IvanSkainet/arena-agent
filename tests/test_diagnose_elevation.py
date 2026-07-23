"""v4.60.20 - tests for the browser-launch diagnostic helper.

Covers:
  * Empty stdout/stderr + rc=0 returns an isError (the "elevation"
    symptom we observe in practice).
  * Known Chromium "running elevated: 1" warning is detected and
    surfaces a helpful, actionable isError.
  * Healthy stderr (no refusals) returns None.
  * Expected-substring mismatch is detected.
  * Multiple known markers all produce useful messages.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "arena" / "browser"))

import diagnose_elevation  # noqa: E402


# ---------------------------------------------------------------------------
# diagnose_browser_stderr: pure-text heuristics
# ---------------------------------------------------------------------------


def test_diagnose_returns_none_for_empty_stderr() -> None:
    assert diagnose_elevation.diagnose_browser_stderr("") is None


def test_diagnose_returns_none_for_healthy_stderr() -> None:
    s = "[INFO:CONSOLE] Hello from the page.\n[INFO:fetch] OK"
    assert diagnose_elevation.diagnose_browser_stderr(s) is None


def test_diagnose_detects_running_elevated_marker() -> None:
    s = (
        "[14152:18352:0723/182504.999:WARNING:"
        "chrome\\browser\\chrome_browser_main_win.cc:1655] "
        "Edge is running elevated: 1"
    )
    out = diagnose_elevation.diagnose_browser_stderr(s)
    assert out is not None
    assert out["isError"] is True
    msg = out["content"][0]["text"].lower()
    assert "elevat" in msg
    # The message must mention the docs file or one of the workarounds
    # (BrowserAct, Camoufox, non-admin).
    assert any(
        word in msg
        for word in ("browseract", "camoufox", "non-admin", "docs/")
    ), f"message should mention a workaround, got: {msg!r}"


def test_diagnose_detects_alternate_marker() -> None:
    s = "Some warning: elevation is not supported on this build."
    out = diagnose_elevation.diagnose_browser_stderr(s)
    assert out is not None
    assert out["isError"] is True


def test_diagnose_message_is_actionable() -> None:
    """The isError must give the user a concrete next step, not just
    'something went wrong'."""
    s = "Edge is running elevated: 1"
    out = diagnose_elevation.diagnose_browser_stderr(s)
    assert out is not None
    msg = out["content"][0]["text"]
    # Length sanity: at least 80 chars of actionable text.
    assert len(msg) > 80, f"message too short, got: {msg!r}"
    # Mentions at least one known workaround.
    assert any(
        w in msg.lower()
        for w in ("browseract", "camoufox", "non-admin", "docs/")
    )


# ---------------------------------------------------------------------------
# diagnose_browser_exit: combined heuristics
# ---------------------------------------------------------------------------


def test_exit_returns_none_for_normal_run() -> None:
    out = diagnose_elevation.diagnose_browser_exit(
        return_code=0,
        stdout="<html><body>OK</body></html>",
        stderr="[INFO] page loaded",
    )
    assert out is None


def test_exit_detects_empty_output_with_rc_zero() -> None:
    """The exact symptom of the v4.60.18 smoke failure."""
    out = diagnose_elevation.diagnose_browser_exit(
        return_code=0,
        stdout="",
        stderr="",
    )
    assert out is not None
    assert out["isError"] is True
    msg = out["content"][0]["text"].lower()
    assert "no output" in msg or "produced nothing" in msg


def test_exit_detects_elevated_in_stderr() -> None:
    out = diagnose_elevation.diagnose_browser_exit(
        return_code=0,
        stdout="",
        stderr="Edge is running elevated: 1",
    )
    assert out is not None
    assert out["isError"] is True
    assert "elevat" in out["content"][0]["text"].lower()


def test_exit_detects_substring_mismatch() -> None:
    out = diagnose_elevation.diagnose_browser_exit(
        return_code=0,
        stdout="<html>some other page</html>",
        stderr="",
        expected_output_substr="<title>Expected</title>",
    )
    assert out is not None
    assert out["isError"] is True
    assert "expected substring" in out["content"][0]["text"]


def test_exit_elevated_takes_priority_over_empty() -> None:
    """If both empty-output AND elevation-warning are present, the
    more specific elevation message wins (it's the actual cause)."""
    out = diagnose_elevation.diagnose_browser_exit(
        return_code=0,
        stdout="",
        stderr="Edge is running elevated: 1",
    )
    msg = out["content"][0]["text"].lower()
    assert "elevat" in msg, f"expected elevation, got: {msg!r}"

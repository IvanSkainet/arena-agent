"""v4.60.19 - tests for mcp/tool_speckit.py

These tests run **without** requiring the `specify` CLI to be on PATH:
- When the CLI is missing, the tool must return a graceful isError.
- When the CLI is present, version + unknown-subcommand + dispatcher
  flows must all behave as documented.

We do not stub the CLI to fake a "present" state; the live binary is
already on the Windows test host (installed via `uv tool install
specify-cli` for v4.60.19). Tests are skipped if the binary is
absent, so this suite is a no-op on hosts where spec-kit was not
opted into.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "arena" / "mcp"))

import tool_speckit as ts  # noqa: E402


HAS_SPECIFY = shutil.which("specify") is not None
skip_no_cli = pytest.mark.skipif(
    not HAS_SPECIFY,
    reason="specify CLI not on PATH (install with: uv tool install specify-cli)",
)


# ---------------------------------------------------------------------------
# Pure-Python contracts (no subprocess)
# ---------------------------------------------------------------------------


def test_handle_speccy_unknown_tool_returns_iserror() -> None:
    """A tool name we did not register must come back as isError, never
    as ok=True with a confusing shape."""
    out = ts.handle_speccy("speccy.no-such-thing", {}, ctx=None)
    assert out.get("isError") is True
    assert any("unknown" in c.get("text", "").lower()
               for c in out.get("content", []))


def test_handle_speccy_run_rejects_non_list_args() -> None:
    """`args` must be a list[str]; strings/None must come back as
    isError rather than crashing the scenario runtime."""
    out = ts.handle_speccy("speccy.run", {"args": "not a list"}, ctx=None)
    assert out.get("isError") is True


def test_handle_speccy_run_rejects_non_string_elements() -> None:
    out = ts.handle_speccy("speccy.run", {"args": ["ok", 42]}, ctx=None)
    assert out.get("isError") is True


# ---------------------------------------------------------------------------
# Live subprocess tests (require `specify` on PATH)
# ---------------------------------------------------------------------------


@skip_no_cli
def test_run_speccy_version_returns_string() -> None:
    """`specify --version` should print a single line like
    `specify 0.13.4`; we don't pin the version, just the prefix."""
    r = ts.run_speccy(args=["--version"], timeout=15)
    assert r.get("ok") is True
    assert r.get("exit_code") == 0
    assert r["stdout"].startswith("specify ")
    assert r.get("cli")  # we record the resolved binary path


@skip_no_cli
def test_run_speccy_unknown_subcommand_has_nonzero_exit() -> None:
    """An unknown subcommand should return ok=True with exit_code != 0
    (so the scenario runtime can decide whether to continue)."""
    r = ts.run_speccy(args=["this-is-not-a-real-subcommand"], timeout=15)
    assert r.get("ok") is True
    assert r.get("exit_code") != 0


@skip_no_cli
def test_run_speccy_cli_absent_returns_iserror(tmp_path, monkeypatch) -> None:
    """Force PATH to be empty and call `run_speccy`; we must get a
    graceful isError, not a crash."""
    monkeypatch.setattr(shutil, "which", lambda _: None)
    r = ts.run_speccy(args=["--version"], timeout=5)
    assert r.get("isError") is True
    assert any("not on PATH" in c.get("text", "")
               for c in r.get("content", []))


@skip_no_cli
def test_handle_speccy_version_dispatches_to_run() -> None:
    r = ts.handle_speccy("speccy.version", {}, ctx=None)
    assert r.get("ok") is True
    assert r["stdout"].startswith("specify ")


@skip_no_cli
def test_handle_speccy_check_runs_specify_check() -> None:
    r = ts.handle_speccy("speccy.check", {}, ctx=None)
    # `specify check` itself is non-interactive and may pass or fail
    # depending on which tools are installed. We only assert that the
    # call returns a structured result with stdout/stderr populated.
    assert "ok" in r
    assert "exit_code" in r
    assert "stdout" in r
    assert "stderr" in r

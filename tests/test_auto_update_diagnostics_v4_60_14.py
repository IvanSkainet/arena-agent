"""v4.60.14: audit + on-disk diagnostics so future auto-update failures
can be root-caused without re-instrumenting after the fact.

Two additions:
1. handlers_update.py emits an ``admin.update.apply.restart_scheduled``
   audit event immediately before calling ``restart_process``. Presence
   of this event tells us the handler reached the restart point. If the
   event is missing after an apply attempt, the handler bailed earlier.
2. auto_update_windows.py's generated mover writes a phase-by-phase log
   to ``.arena-update-apply.log`` next to itself, so a failed restart
   can be diagnosed from disk even when the mover ran detached.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from arena.admin import handlers_update as _hu_mod
from arena.admin import auto_update  # noqa: F401 — needed for circular import order
from arena.admin.auto_update_windows import _write_windows_installer


def _executable_source(mod) -> str:
    src = inspect.getsource(mod)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                if len(node.body) > 1:
                    node.body.pop(0)
                else:
                    node.body[0].value.value = ""
    return ast.unparse(tree)


def test_handler_emits_restart_scheduled_audit_event():
    """The apply handler must audit ``admin.update.apply.restart_scheduled``
    right before calling ``restart_process`` so field diagnosis can tell
    'handler reached the restart point' from 'handler bailed earlier'."""
    src = _executable_source(_hu_mod)
    assert '"admin.update.apply.restart_scheduled"' in src or (
        "'admin.update.apply.restart_scheduled'" in src
    ), (
        "handlers_update must emit an ``admin.update.apply.restart_scheduled`` "
        "audit event before calling restart_process()"
    )


@pytest.fixture
def paren_install_root(tmp_path):
    root = tmp_path / "arena-agent (7)" / "arena-agent"
    root.mkdir(parents=True)
    payload = tmp_path / "payload" / "arena-agent"
    payload.mkdir(parents=True)
    (payload / "arena").mkdir()
    (payload / "arena" / "__init__.py").write_text("")
    marker = tmp_path / "done.txt"
    return payload, root, marker


def test_mover_writes_phase_log(paren_install_root):
    """Generated mover must include ``echo [%DATE% %TIME%] ...`` phase
    lines redirected to ``.arena-update-apply.log`` next to itself."""
    payload, root, marker = paren_install_root
    script = _write_windows_installer(payload, root, marker)
    text = script.read_text(encoding="utf-8")
    assert ".arena-update-apply.log" in text, (
        "mover missing on-disk phase log (.arena-update-apply.log)"
    )
    # Sanity: at least three phases logged (start, after-wait, done).
    log_lines = [l for l in text.splitlines() if ".arena-update-apply.log" in l and "echo" in l]
    assert len(log_lines) >= 4, (
        f"mover should log start / bridge-exited / copy-done / mover-done "
        f"(found only {len(log_lines)} log echo lines)"
    )


def test_mover_logs_no_relaunch_warning_branch(paren_install_root):
    """If neither schtasks nor start_hidden.vbs nor start_bridge.bat is
    available, the mover must at least record that fact rather than
    silently vanish."""
    payload, root, marker = paren_install_root
    script = _write_windows_installer(payload, root, marker)
    text = script.read_text(encoding="utf-8")
    assert "WARN no relaunch mechanism found" in text
    assert ":no_relaunch" in text


def test_mover_log_path_uses_install_root(paren_install_root):
    """The log must live next to the mover (i.e. inside the install
    root), not in the payload temp dir which gets cleaned up."""
    payload, root, marker = paren_install_root
    script = _write_windows_installer(payload, root, marker)
    text = script.read_text(encoding="utf-8")
    expected_prefix = str(root).replace("/", "\\")
    assert expected_prefix in text
    # The .log path must contain the install root, not the payload dir
    log_lines = [l for l in text.splitlines() if ".arena-update-apply.log" in l]
    for line in log_lines:
        # payload path should not appear in a line that redirects to the log
        # (it's fine for the mover to *copy from* payload, but the log path
        # itself should be under install root)
        assert str(payload).replace("/", "\\") not in line or ">>" not in line

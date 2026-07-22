"""v4.60.13: /v1/admin/update/apply must schedule restart_process on
Windows too (previously gated on ``platform != "windows"``).

Pre-v4.60.4 ``restart_process`` on Windows was a no-op returning
``{"restart": "pending"}``, so the handler deliberately skipped calling
it. v4.60.4 fixed ``restart_process`` to schedule an ``os._exit(0)`` on
a daemon thread, but this handler-side gate was never removed. The
symptom in the field: Dashboard "Install" click -> ``apply_update``
runs (downloads zip, spawns detached mover, returns HTTP 200) -> mover
waits for our PID to disappear FOREVER -> version never changes.

Ivan's audit trail from v4.60.11 install click (2026-07-22T11:16):
```
apply    swapped=null  (normal for Windows path)
check    needs_update=true  (bridge still 4.60.11)
check    needs_update=true  ...
```
No ``admin.update.restart`` event, because the handler never called
``restart_process`` on the Windows platform.

The fix is one line: drop the ``!= "windows"`` gate.
"""
from __future__ import annotations

import ast
import inspect

from arena.admin import handlers_update as _hu_mod
from arena.admin.handlers_update import make_update_handlers  # noqa: F401


def _executable_source() -> str:
    """Return handlers_update source with docstrings and comments
    stripped so tests match on real code, not on documentation."""
    src = inspect.getsource(_hu_mod)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0) if len(node.body) > 1 else setattr(
                    node.body[0].value, "value", ""
                )
    return ast.unparse(tree)


def test_handler_restart_branch_is_platform_agnostic():
    """The apply handler must no longer gate restart_process on a
    ``platform != "windows"`` check. Otherwise Windows never restarts,
    the mover waits for us forever, and auto-update silently fails."""
    src = _executable_source()
    assert 'platform") != "windows"' not in src, (
        "handlers_update still gates the auto-restart branch on Windows. "
        "restart_process() has been Windows-aware since v4.60.4 -- the "
        "gate must be removed."
    )
    assert "!= 'windows'" not in src, "same gate written with single quotes"


def test_handler_still_calls_restart_process_when_restart_true():
    src = _executable_source()
    assert "restart_process(delay_sec=1.0)" in src, (
        "apply handler no longer calls restart_process(delay_sec=1.0) at all -- "
        "did a refactor remove the auto-restart path?"
    )
    assert 'restart and res.get("platform")' not in src, (
        "old ``restart and res.get('platform') != 'windows'`` gate is back"
    )


def test_handler_still_returns_scheduled_marker():
    """Dashboard's 39-admin-update.js checks ``step2.restart === 'scheduled'``
    to decide whether to auto-refresh the page. Do not regress that."""
    src = _executable_source()
    assert "res['restart'] = 'scheduled'" in src or 'res["restart"] = "scheduled"' in src

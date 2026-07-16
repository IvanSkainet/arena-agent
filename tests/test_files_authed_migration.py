"""v3.97.0 regression guards: file handlers migrated to @authed.

Confirms both arena.files.handlers (upload/download/edit/apply/rollback)
and arena.files.fs_view_create (view/create) are wrapped by the
shared decorator and don't carry the old inline auth prelude.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.files.handlers import make_file_handlers  # noqa: E402
from arena.files.fs_view_create import make_fs_view_create_handlers  # noqa: E402
from arena.handler_context import FileHandlerContext  # noqa: E402
from arena.files.safe_edit import apply_preview, create_preview, rollback_change  # noqa: E402


def _ctx(tmp_path: Path) -> FileHandlerContext:
    return FileHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        audit=ub.audit,
        home=tmp_path,
        bridge_py=tmp_path / "unified_bridge.py",
        create_edit_preview=create_preview,
        apply_edit_preview=apply_preview,
        rollback_edit_change=rollback_change,
    )


def test_file_handlers_use_authed_decorator(tmp_path):
    handlers = make_file_handlers(_ctx(tmp_path))
    for name in ("upload", "download", "fs_edit",
                 "fs_edit_apply", "fs_edit_rollback"):
        h = getattr(handlers, name)
        assert hasattr(h, "__wrapped__"), (
            f"file handler `{name}` is not wrapped by @authed — "
            f"v3.97.0 migration expects arena.files.handlers to use "
            f"arena.handler_helpers.authed."
        )


def test_fs_view_create_handlers_use_authed_decorator(tmp_path):
    handlers = make_fs_view_create_handlers(_ctx(tmp_path))
    for name in ("view", "create"):
        h = getattr(handlers, name)
        assert hasattr(h, "__wrapped__"), (
            f"fs_view_create handler `{name}` is not wrapped by @authed."
        )


def test_files_modules_free_of_manual_auth_prelude():
    """Confirm the inline ``r = ctx.require_auth(request); if r: return r``
    prelude has been removed from both file modules."""
    import inspect
    from arena.files import handlers as _fh, fs_view_create as _fvc
    for mod in (_fh, _fvc):
        src = inspect.getsource(mod)
        assert "r = ctx.require_auth(request)" not in src, (
            f"{mod.__name__} still contains the inline auth prelude — "
            f"v3.97.0 migrated it to @authed."
        )

"""Gate: fs-edit routes refuse cleanly when their hooks are not wired.

`FileHandlerContext.create_edit_preview` / `apply_edit_preview` /
`rollback_edit_change` default to None. The three /v1/fs/edit* handlers used to
call them unconditionally, so an incompletely wired context produced
`TypeError: 'NoneType' object is not callable` inside the handler, which the
@authed wrapper turned into an opaque 500 with no hint of the cause.

Found by pyrefly ("Expected a callable, got None", 5x). The routes now fail
closed with 501 and name the missing hooks.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from aiohttp.test_utils import make_mocked_request

from arena.app_keys import APP_CFG
from arena.files.handlers import make_file_handlers
from arena.files.safe_edit import apply_preview, create_preview, rollback_change
from arena.handler_context import FileHandlerContext


class _JsonResponse:
    def __init__(self, data, status=200):
        self.status = status
        self.data = data


def _ctx(tmp_path: Path, **hooks) -> FileHandlerContext:
    bridge = tmp_path / "bridge.py"
    bridge.write_text("x", encoding="utf-8")
    return FileHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *a, **kw: None,
        cors_json_response=lambda data, status=200: _JsonResponse(data, status),
        audit=lambda entry: None,
        home=tmp_path,
        bridge_py=bridge,
        **hooks,
    )


def _req(body: dict, *, path: str, root: Path):
    req = make_mocked_request("POST", path, headers={"Authorization": "Bearer t"})
    req.app[APP_CFG] = {"root": root}

    async def _json():
        return body

    req.json = _json
    return req


@pytest.mark.parametrize(
    ("attr", "path", "body"),
    [
        ("fs_edit", "/v1/fs/edit", {"path": "x.txt", "old_text": "a", "new_text": "b"}),
        ("fs_edit_apply", "/v1/fs/edit/apply", {"preview_id": "p1"}),
        ("fs_edit_rollback", "/v1/fs/edit/rollback", {"rollback_id": "r1"}),
    ],
)
def test_unwired_hooks_refuse_with_501(tmp_path, attr, path, body):
    handlers = make_file_handlers(_ctx(tmp_path))
    resp = asyncio.run(getattr(handlers, attr)(_req(body, path=path, root=tmp_path)))
    assert resp.status == 501
    assert resp.data["ok"] is False
    # The refusal names what is missing rather than saying "Internal error".
    assert "unwired" in resp.data["error"]
    assert "create_edit_preview" in resp.data["error"]


def test_partially_wired_context_is_also_refused(tmp_path):
    """Two of three wired is still not a working fs-edit surface."""
    handlers = make_file_handlers(
        _ctx(tmp_path, create_edit_preview=create_preview, apply_edit_preview=apply_preview),
    )
    resp = asyncio.run(handlers.fs_edit_apply(_req({"preview_id": "p1"}, path="/v1/fs/edit/apply", root=tmp_path)))
    assert resp.status == 501
    assert "rollback_edit_change" in resp.data["error"]
    assert "create_edit_preview" not in resp.data["error"]


def test_fully_wired_context_runs_the_edit(tmp_path):
    target = tmp_path / "demo.py"
    target.write_text("print('one')\n", encoding="utf-8")
    handlers = make_file_handlers(
        _ctx(
            tmp_path,
            create_edit_preview=create_preview,
            apply_edit_preview=apply_preview,
            rollback_edit_change=rollback_change,
        ),
    )
    resp = asyncio.run(
        handlers.fs_edit(
            _req(
                {"path": str(target), "old_text": "one", "new_text": "two"},
                path="/v1/fs/edit",
                root=tmp_path,
            ),
        ),
    )
    assert resp.status == 200, json.dumps(resp.data, default=str)
    assert resp.data["ok"] is True
    assert "two" in target.read_text(encoding="utf-8")

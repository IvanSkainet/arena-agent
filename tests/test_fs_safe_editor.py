"""Safe editor preview/apply/rollback regressions."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.app_keys import APP_CFG  # noqa: E402
from arena.files.handlers import make_file_handlers  # noqa: E402
from arena.files.safe_edit import apply_preview, create_preview, rollback_change  # noqa: E402
from arena.handler_context import FileHandlerContext  # noqa: E402


class _JsonResponse:
    def __init__(self, data, status=200):
        self.status = status
        self._data = data
        self.text = json.dumps(data)



def _ctx(tmp_path: Path):
    bridge = tmp_path / "bridge.py"
    bridge.write_text("x", encoding="utf-8")
    audit = []
    return FileHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda **kw: None,
        cors_json_response=lambda data, status=200: _JsonResponse(data, status),
        audit=audit.append,
        home=tmp_path,
        bridge_py=bridge,
        create_edit_preview=create_preview,
        apply_edit_preview=apply_preview,
        rollback_edit_change=rollback_change,
    ), audit



def _req(method: str, body: dict, *, path: str):
    req = make_mocked_request(method, path, headers={"Authorization": "Bearer t"})
    req.app[APP_CFG] = {"root": Path(path).parent if path.startswith("/") else Path("/tmp")}
    async def _json():
        return body
    req.json = _json
    return req



def test_safe_edit_preview_apply_and_rollback_helpers(tmp_path):
    f = tmp_path / "demo.py"
    f.write_text("print('one')\n", encoding="utf-8")
    preview = create_preview(f, "one", "two", replace_all=False)
    assert preview["ok"] is True
    assert f.read_text(encoding="utf-8") == "print('one')\n"
    applied = apply_preview(preview["preview_id"])
    assert applied["ok"] is True
    assert "two" in f.read_text(encoding="utf-8")
    rolled = rollback_change(applied["rollback_id"])
    assert rolled["ok"] is True
    assert f.read_text(encoding="utf-8") == "print('one')\n"



def test_safe_edit_apply_detects_file_changed_since_preview(tmp_path):
    f = tmp_path / "demo.py"
    f.write_text("alpha\n", encoding="utf-8")
    preview = create_preview(f, "alpha", "beta", replace_all=False)
    f.write_text("gamma\n", encoding="utf-8")
    applied = apply_preview(preview["preview_id"])
    assert applied["ok"] is False
    assert applied["status"] == 409



def test_safe_edit_rest_preview_apply_and_rollback(tmp_path):
    f = tmp_path / "demo.py"
    f.write_text("hello\n", encoding="utf-8")
    ctx, audit = _ctx(tmp_path)
    handlers = make_file_handlers(ctx)

    preview_req = make_mocked_request("PATCH", "/v1/fs/edit", headers={"Authorization": "Bearer t"})
    preview_req.app[APP_CFG] = {"root": tmp_path}
    async def _preview_json():
        return {"path": str(f), "old_text": "hello", "new_text": "world", "preview": True}
    preview_req.json = _preview_json
    preview_resp = asyncio.run(handlers.fs_edit(preview_req))
    assert preview_resp.status == 200
    preview_data = json.loads(preview_resp.text)
    assert preview_data["preview"] is True
    assert "world" not in f.read_text(encoding="utf-8")

    apply_req = make_mocked_request("POST", "/v1/fs/edit/apply", headers={"Authorization": "Bearer t"})
    apply_req.app[APP_CFG] = {"root": tmp_path}
    async def _apply_json():
        return {"preview_id": preview_data["preview_id"]}
    apply_req.json = _apply_json
    apply_resp = asyncio.run(handlers.fs_edit_apply(apply_req))
    apply_data = json.loads(apply_resp.text)
    assert apply_data["ok"] is True
    assert "world" in f.read_text(encoding="utf-8")

    rollback_req = make_mocked_request("POST", "/v1/fs/edit/rollback", headers={"Authorization": "Bearer t"})
    rollback_req.app[APP_CFG] = {"root": tmp_path}
    async def _rollback_json():
        return {"rollback_id": apply_data["rollback_id"]}
    rollback_req.json = _rollback_json
    rollback_resp = asyncio.run(handlers.fs_edit_rollback(rollback_req))
    rollback_data = json.loads(rollback_resp.text)
    assert rollback_data["ok"] is True
    assert f.read_text(encoding="utf-8") == "hello\n"
    assert any(ev["type"] == "file_edit_rollback" for ev in audit)

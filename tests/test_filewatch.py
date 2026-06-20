"""File watcher runtime, handler, and MCP regressions."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.app_keys import APP_CFG  # noqa: E402
from arena.filewatch.handlers import make_file_watch_handlers  # noqa: E402
from arena.filewatch.runtime import FileWatchRuntimeContext, make_file_watch_runtime  # noqa: E402
from arena.handler_context import FileWatchHandlerContext  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.mcp.tool_watch import handle_watch_tool  # noqa: E402
import unified_bridge as ub  # noqa: E402


class _Events(list):
    async def __call__(self, event_type, data=None):
        self.append((event_type, data or {}))


def _runtime(tmp_path: Path):
    events = _Events()
    runtime = make_file_watch_runtime(
        FileWatchRuntimeContext(
            home=tmp_path,
            default_root=tmp_path,
            emit_event=events,
            utc_now=lambda: "now",
            log_info=lambda *args, **kwargs: None,
            log_warning=lambda *args, **kwargs: None,
            poll_interval_s=0.01,
            max_files_per_watch=50,
        )
    )
    return runtime, events


def test_file_watch_runtime_add_list_remove_and_detect_change(tmp_path):
    runtime, events = _runtime(tmp_path)
    watched = tmp_path / "watched"
    watched.mkdir()
    file_path = watched / "a.txt"
    file_path.write_text("one", encoding="utf-8")
    added = runtime.add_sync(path=str(watched), root=tmp_path, recursive=True, patterns=["*.txt"], label="demo", created_at="now")
    assert added["ok"] is True
    listed = runtime.list_sync()
    assert listed["count"] == 1
    file_path.write_text("two-two", encoding="utf-8")

    async def _run_once():
        task = asyncio.create_task(runtime.loop(None))
        await asyncio.sleep(0.03)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_run_once())
    assert any(ev[0] == "file_watch_change" and ev[1]["event"] == "modified" for ev in events)
    removed = runtime.remove_sync(added["id"])
    assert removed["ok"] is True
    assert runtime.list_sync()["count"] == 0


async def _json_request(method: str, path: str, body: dict):
    req = make_mocked_request(method, path, headers={"Authorization": "Bearer t"})
    req.app[APP_CFG] = {"root": str(Path(path).parent if path.startswith("/") else Path("/tmp"))}
    async def _json():
        return body
    req.json = _json
    return req


def test_file_watch_handler_add_list_delete(tmp_path):
    runtime, _events = _runtime(tmp_path)
    watched = tmp_path / "watched"
    watched.mkdir()
    (watched / "a.txt").write_text("x", encoding="utf-8")
    handlers = make_file_watch_handlers(
        FileWatchHandlerContext(
            require_auth=lambda request: None,
            record_request=lambda *args, **kwargs: None,
            cors_json_response=ub._cors_json_response,
            app_cfg_key=APP_CFG,
            home=tmp_path,
            list_sync=runtime.list_sync,
            add_sync=runtime.add_sync,
            remove_sync=runtime.remove_sync,
            utc_now=lambda: "now",
        )
    )
    add_req = make_mocked_request("POST", "/v1/watch/files", headers={"Authorization": "Bearer t"})
    add_req.app[APP_CFG] = {"root": tmp_path}
    async def _json_add():
        return {"path": str(watched), "recursive": True, "patterns": ["*.txt"]}
    add_req.json = _json_add
    add_resp = asyncio.run(handlers.watch_files(add_req))
    add_data = json.loads(add_resp.text)
    assert add_data["ok"] is True

    list_req = make_mocked_request("GET", "/v1/watch/files", headers={"Authorization": "Bearer t"})
    list_req.app[APP_CFG] = {"root": tmp_path}
    list_resp = asyncio.run(handlers.watch_files(list_req))
    list_data = json.loads(list_resp.text)
    assert list_data["count"] == 1

    del_req = make_mocked_request("DELETE", "/v1/watch/files", headers={"Authorization": "Bearer t"})
    del_req.app[APP_CFG] = {"root": tmp_path}
    async def _json_del():
        return {"id": add_data["id"]}
    del_req.json = _json_del
    del_resp = asyncio.run(handlers.watch_files(del_req))
    del_data = json.loads(del_resp.text)
    assert del_data["ok"] is True


def test_watch_tool_and_registry(tmp_path):
    runtime, _events = _runtime(tmp_path)
    watched = tmp_path / "watched"
    watched.mkdir()
    (watched / "a.py").write_text("print(1)", encoding="utf-8")
    ctx = type(
        "Ctx",
        (),
        {
            "app_config": staticmethod(lambda: {"root": str(tmp_path)}),
            "file_watch_list_sync": staticmethod(runtime.list_sync),
            "file_watch_add_sync": staticmethod(runtime.add_sync),
            "file_watch_remove_sync": staticmethod(runtime.remove_sync),
            "utc_now": staticmethod(lambda: "now"),
        },
    )()
    add = handle_watch_tool("watch.files", {"action": "add", "path": str(watched), "patterns": ["*.py"]}, ctx=ctx)
    payload = json.loads(add["content"][0]["text"])
    assert payload["ok"] is True
    assert any(tool["name"] == "watch.files" for tool in MCP_TOOLS)


def test_watch_route_registered():
    app = ub.make_app({"token": "test"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/watch/files") in paths
    assert ("POST", "/v1/watch/files") in paths
    assert ("DELETE", "/v1/watch/files") in paths

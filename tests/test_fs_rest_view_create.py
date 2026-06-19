"""Tests for REST POST /v1/fs/view and POST /v1/fs/create endpoints.

Two layers of coverage:
  1. validate_view_target / validate_create_target (sandbox layer) — pure functions
  2. The actual REST handlers via make_fs_view_create_handlers with a controlled
     FileHandlerContext (home = tmp_path), using aiohttp make_mocked_request.
     This avoids the live wiring, which bakes `Path.home()` into the handler
     closure at build time and can't be monkeypatched per-request.
  3. Route registration in the app (confirms both POST routes are wired).

Async handlers are driven with asyncio.run(), matching the pattern in
tests/test_lifecycle.py (no pytest-asyncio dependency).
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.app_keys import APP_CFG  # noqa: E402
from arena.files.fs_view_create import make_fs_view_create_handlers, FsViewCreateHandlers  # noqa: E402
from arena.files.sandbox import validate_view_target, validate_create_target  # noqa: E402
from arena.handler_context import FileHandlerContext  # noqa: E402

try:
    from aiohttp.test_utils import make_mocked_request
except ImportError:  # pragma: no cover
    make_mocked_request = None


def _make_ctx(tmp_path):
    """Build a FileHandlerContext whose home is tmp_path (so sandbox checks pass)."""
    bridge = tmp_path / "unified_bridge.py"
    bridge.write_text("x")
    audit_log = []

    def require_auth(request):
        auth = request.headers.get("Authorization", "")
        if auth != "Bearer t":
            from aiohttp import web
            return web.Response(status=401, text="unauthorized")
        return None

    return FileHandlerContext(
        require_auth=require_auth,
        record_request=lambda **kw: None,
        cors_json_response=lambda data, status=200: _JsonResponse(data, status),
        audit=audit_log.append,
        home=tmp_path,
        bridge_py=bridge,
    ), audit_log


class _JsonResponse:
    """Minimal stand-in for web.Response exposing status + json body."""
    def __init__(self, data, status=200):
        self.status = status
        self._data = data


def _mock_request(method, path, body: dict, token="t"):
    """Build a mocked aiohttp request with a JSON body."""
    payload = json.dumps(body).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = make_mocked_request(method, path, headers=headers, payload=payload)
    # make_mocked_request does not parse JSON; emulate request.json()
    async def _json():
        return body
    req.json = _json
    # app cfg needed by handlers for root
    req.app[APP_CFG] = {"root": "/tmp"}
    return req


# ============================================================
# validate_view_target tests (sandbox layer)
# ============================================================

def test_validate_view_target_success(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    f = home / "file.py"; f.write_text("x")
    path, err, status = validate_view_target("file.py", root=home, home=home)
    assert err is None and status == 200 and path == f


def test_validate_view_target_blocks_traversal(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    path, err, status = validate_view_target("../x", root=home, home=home)
    assert err == "path traversal not allowed" and status == 400


def test_validate_view_target_blocks_sensitive_files(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    for blocked_name in ["token.txt", ".env", "id_rsa", "users.json"]:
        f = home / blocked_name; f.write_text("secret")
        path, err, status = validate_view_target(blocked_name, root=home, home=home)
        assert err is not None and status == 403, f"expected block for {blocked_name}"
        assert "not allowed" in err


def test_validate_view_target_file_not_found(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    path, err, status = validate_view_target("missing.py", root=home, home=home)
    assert err == "file not found" and status == 404


def test_validate_view_target_missing_path(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    path, err, status = validate_view_target("", root=home, home=home)
    assert err == "missing path" and status == 400


# ============================================================
# validate_create_target tests (sandbox layer)
# ============================================================

def test_validate_create_target_success(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    bridge = home / "bridge.py"; bridge.write_text("x")
    path, err, status = validate_create_target("new.py", root=home, home=home, bridge_py=bridge)
    assert err is None and status == 200 and path == home / "new.py"


def test_validate_create_target_blocks_traversal(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    bridge = home / "bridge.py"; bridge.write_text("x")
    path, err, status = validate_create_target("../x", root=home, home=home, bridge_py=bridge)
    assert err == "path traversal not allowed" and status == 400


def test_validate_create_target_blocks_sensitive_files(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    bridge = home / "bridge.py"; bridge.write_text("x")
    for blocked_name in ["token.txt", ".env", "id_rsa", "users.json"]:
        path, err, status = validate_create_target(blocked_name, root=home, home=home, bridge_py=bridge)
        assert err is not None and status == 403, f"expected block for {blocked_name}"
        assert "not allowed" in err


def test_validate_create_target_blocks_bridge_itself(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    bridge = home / "unified_bridge.py"; bridge.write_text("x")
    path, err, status = validate_create_target("unified_bridge.py", root=home, home=home, bridge_py=bridge)
    assert err == "cannot overwrite the bridge itself" and status == 403


def test_validate_create_target_already_exists(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    bridge = home / "bridge.py"; bridge.write_text("x")
    existing = home / "exists.py"; existing.write_text("y")
    path, err, status = validate_create_target("exists.py", root=home, home=home, bridge_py=bridge)
    assert err is not None and status == 409
    assert "already exists" in err


def test_validate_create_target_missing_path(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    bridge = home / "bridge.py"; bridge.write_text("x")
    path, err, status = validate_create_target("", root=home, home=home, bridge_py=bridge)
    assert err == "missing path" and status == 400


# ============================================================
# REST handler tests (via make_fs_view_create_handlers + mocked request)
# ============================================================

def test_handler_fs_view_full_file(tmp_path):
    f = tmp_path / "test.py"; f.write_text("line1\nline2\nline3\n")
    ctx, audit = _make_ctx(tmp_path)
    handlers = make_fs_view_create_handlers(ctx)
    resp = asyncio.run(handlers.view(_mock_request("POST", "/v1/fs/view", {"path": str(f)})))
    assert resp.status == 200, resp._data
    assert resp._data["ok"] is True
    assert resp._data["content"] == "line1\nline2\nline3\n"
    assert resp._data["total_lines"] == 4  # split("a\n") -> ['line1','line2','line3','']
    assert resp._data["start"] == 1 and resp._data["end"] == 4
    assert audit and audit[-1]["type"] == "file_view"


def test_handler_fs_view_with_range(tmp_path):
    f = tmp_path / "test.py"; f.write_text("l1\nl2\nl3\nl4\nl5\n")
    ctx, _ = _make_ctx(tmp_path)
    handlers = make_fs_view_create_handlers(ctx)
    resp = asyncio.run(handlers.view(_mock_request("POST", "/v1/fs/view", {"path": str(f), "view_range": [2, 4]})))
    assert resp.status == 200, resp._data
    assert resp._data["content"] == "l2\nl3\nl4"
    assert resp._data["start"] == 2 and resp._data["end"] == 4


def test_handler_fs_view_invalid_range(tmp_path):
    f = tmp_path / "test.py"; f.write_text("l1\nl2\n")
    ctx, _ = _make_ctx(tmp_path)
    handlers = make_fs_view_create_handlers(ctx)
    resp = asyncio.run(handlers.view(_mock_request("POST", "/v1/fs/view", {"path": str(f), "view_range": [5, 1]})))
    assert resp.status == 400, resp._data
    assert "invalid view_range" in resp._data["error"]


def test_handler_fs_view_blocked_sensitive(tmp_path):
    f = tmp_path / "token.txt"; f.write_text("secret\n")
    ctx, _ = _make_ctx(tmp_path)
    handlers = make_fs_view_create_handlers(ctx)
    resp = asyncio.run(handlers.view(_mock_request("POST", "/v1/fs/view", {"path": str(f)})))
    assert resp.status == 403, resp._data
    assert "not allowed" in resp._data["error"]


def test_handler_fs_view_not_found(tmp_path):
    ctx, _ = _make_ctx(tmp_path)
    handlers = make_fs_view_create_handlers(ctx)
    resp = asyncio.run(handlers.view(_mock_request("POST", "/v1/fs/view", {"path": str(tmp_path / "nope.py")})))
    assert resp.status == 404, resp._data
    assert "file not found" in resp._data["error"]


def test_handler_fs_view_requires_auth(tmp_path):
    f = tmp_path / "test.py"; f.write_text("x")
    ctx, _ = _make_ctx(tmp_path)
    handlers = make_fs_view_create_handlers(ctx)
    resp = asyncio.run(handlers.view(_mock_request("POST", "/v1/fs/view", {"path": str(f)}, token=None)))
    assert resp.status == 401


def test_handler_fs_create_success(tmp_path):
    f = tmp_path / "new.py"
    ctx, audit = _make_ctx(tmp_path)
    handlers = make_fs_view_create_handlers(ctx)
    resp = asyncio.run(handlers.create(_mock_request("POST", "/v1/fs/create", {"path": str(f), "content": "print('hi')\n"})))
    assert resp.status == 200, resp._data
    assert resp._data["ok"] is True
    assert resp._data["bytes"] == 12  # "print('hi')\n"
    assert f.read_text() == "print('hi')\n"
    assert audit and audit[-1]["type"] == "file_create"


def test_handler_fs_create_creates_parent_dirs(tmp_path):
    f = tmp_path / "sub" / "nested" / "file.py"
    ctx, _ = _make_ctx(tmp_path)
    handlers = make_fs_view_create_handlers(ctx)
    resp = asyncio.run(handlers.create(_mock_request("POST", "/v1/fs/create", {"path": str(f), "content": "x = 1\n"})))
    assert resp.status == 200, resp._data
    assert f.read_text() == "x = 1\n"


def test_handler_fs_create_already_exists(tmp_path):
    f = tmp_path / "existing.py"; f.write_text("original\n")
    ctx, _ = _make_ctx(tmp_path)
    handlers = make_fs_view_create_handlers(ctx)
    resp = asyncio.run(handlers.create(_mock_request("POST", "/v1/fs/create", {"path": str(f), "content": "new\n"})))
    assert resp.status == 409, resp._data
    assert "already exists" in resp._data["error"]
    assert f.read_text() == "original\n"


def test_handler_fs_create_empty_content(tmp_path):
    f = tmp_path / "empty.py"
    ctx, _ = _make_ctx(tmp_path)
    handlers = make_fs_view_create_handlers(ctx)
    resp = asyncio.run(handlers.create(_mock_request("POST", "/v1/fs/create", {"path": str(f), "content": ""})))
    assert resp.status == 400, resp._data
    assert "content" in resp._data["error"]
    assert not f.exists()


def test_handler_fs_create_blocked_sensitive(tmp_path):
    f = tmp_path / "token.txt"
    ctx, _ = _make_ctx(tmp_path)
    handlers = make_fs_view_create_handlers(ctx)
    resp = asyncio.run(handlers.create(_mock_request("POST", "/v1/fs/create", {"path": str(f), "content": "secret\n"})))
    assert resp.status == 403, resp._data
    assert "not allowed" in resp._data["error"]


def test_handler_fs_create_requires_auth(tmp_path):
    ctx, _ = _make_ctx(tmp_path)
    handlers = make_fs_view_create_handlers(ctx)
    resp = asyncio.run(handlers.create(_mock_request("POST", "/v1/fs/create", {"path": str(tmp_path / "f.py"), "content": "x"}, token=None)))
    assert resp.status == 401


def test_handler_fs_view_invalid_json(tmp_path):
    ctx, _ = _make_ctx(tmp_path)
    handlers = make_fs_view_create_handlers(ctx)
    # Build a request whose .json() raises
    req = make_mocked_request("POST", "/v1/fs/view", headers={"Authorization": "Bearer t"}, payload=b"not json")
    async def _bad():
        raise ValueError("bad json")
    req.json = _bad
    req.app[APP_CFG] = {"root": "/tmp"}
    resp = asyncio.run(handlers.view(req))
    assert resp.status == 400, resp._data
    assert "invalid JSON" in resp._data["error"]


# ============================================================
# Route registration + dataclass tests
# ============================================================

def test_rest_fs_view_create_routes_registered():
    """POST /v1/fs/view and POST /v1/fs/create routes are registered in the app."""
    app = ub.make_app({"token": "t", "profile": "owner-shell", "root": "/tmp", "active_exec": 0, "max_concurrent": 3, "audit": "audit"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("POST", "/v1/fs/view") in paths, f"POST /v1/fs/view not in routes"
    assert ("POST", "/v1/fs/create") in paths, f"POST /v1/fs/create not in routes"


def test_fs_view_create_handlers_have_fields():
    """FsViewCreateHandlers dataclass has view and create fields."""
    import dataclasses
    fields = {f.name for f in dataclasses.fields(FsViewCreateHandlers)}
    assert fields == {"view", "create"}, f"unexpected fields: {fields}"

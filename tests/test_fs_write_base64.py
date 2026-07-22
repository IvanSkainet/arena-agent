import base64

import pytest

from arena.mcp import tool_fs


class _Ctx:
    # Scenarios/fs tools only require under_root for path validation.
    def under_root(self, resolved, home):
        return True


def test_fs_write_base64_roundtrip(tmp_path):
    ctx = _Ctx()
    payload = base64.b64encode(b"hello-binary-\x00\x01\xff").decode("ascii")
    target = tmp_path / "out.bin"
    res = tool_fs.handle_fs_tool(
        "fs.write_base64",
        {"path": str(target), "base64": payload},
        ctx=ctx,
    )
    assert res and not res.get("isError"), res
    assert target.read_bytes() == b"hello-binary-\x00\x01\xff"


def test_fs_write_base64_rejects_non_base64_gracefully(tmp_path):
    ctx = _Ctx()
    target = tmp_path / "bad.bin"
    res = tool_fs.handle_fs_tool(
        "fs.write_base64",
        {"path": str(target), "base64": "!!!not-base64!!!"},
        ctx=ctx,
    )
    # Must return an error envelope, not raise an unhandled exception.
    assert res.get("isError"), res
    assert not target.exists()

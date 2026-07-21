"""v4.60.6 - admin.run cross-platform + sudo.run PermissionError fix."""
from pathlib import Path
from unittest import mock

from arena import constants
from arena.mcp.tool_registry import MCP_TOOLS
from arena.mcp.tool_registry_net import NET_MCP_TOOLS
from arena.mcp.tool_net import _handle_admin_run, _handle_sudo_run, handle_net_tool
from arena.extension_bridge.policy import classify_tool_risk


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(p: str) -> str:
    return (REPO_ROOT / p).read_text(encoding="utf-8")


def test_version_is_4_60_6():
    assert constants.VERSION in ("4.60.6",)


def test_pyproject_version_is_4_60_6():
    assert 'version = "4.60.6"' in _read("pyproject.toml")


def test_admin_run_registered_in_net_tools():
    names = {t["name"] for t in NET_MCP_TOOLS}
    assert "admin.run" in names
    assert "sudo.run" in names


def test_admin_run_appears_in_MCP_TOOLS():
    mcp = {t["name"] for t in MCP_TOOLS}
    assert "admin.run" in mcp


def test_admin_run_is_dangerous():
    assert classify_tool_risk("admin.run") == "dangerous"


def test_admin_run_requires_cmd():
    class _Ctx:
        def blocked_reason(self, _): return None
    out = _handle_admin_run({}, ctx=_Ctx())
    assert out.get("isError")


def test_admin_run_blocked_by_pattern():
    """BLOCK_PATTERNS still gates admin.run."""
    class _Ctx:
        def blocked_reason(self, cmd):
            if "rm" in cmd and "/" in cmd:
                return "dangerous rm"
            return None
    out = _handle_admin_run({"cmd": "rm -rf /"}, ctx=_Ctx())
    assert out.get("isError")
    assert "blocked" in out["content"][0]["text"].lower()


def test_admin_run_linux_delegates_to_sudo_run(monkeypatch):
    """Linux path proxies to _handle_sudo_run."""
    import platform as _p
    monkeypatch.setattr(_p, "system", lambda: "Linux")
    called = {}
    def _fake_sudo(args, *, ctx, run_sd):
        called["args"] = args
        return {"ok": True, "proxied": True}
    import arena.mcp.tool_net as tn
    monkeypatch.setattr(tn, "_handle_sudo_run", _fake_sudo)
    class _Ctx:
        def blocked_reason(self, _): return None
    out = tn._handle_admin_run({"cmd": "id"}, ctx=_Ctx())
    assert out.get("proxied") is True
    assert called["args"]["cmd"] == "id"


def test_sudo_run_no_longer_uses_run_sd():
    """v4.60.6: sudo.run switched to direct subprocess.run.

    Regression guard so we don't re-add the sd-exec wrapper that
    broke the tool on setups where sd-exec isn't executable in
    every context (v4.59.0 field bug).
    """
    src = _read("arena/mcp/tool_net.py")
    # In the _handle_sudo_run body, direct subprocess is used
    idx = src.index("def _handle_sudo_run(")
    end = src.index("\ndef _handle_admin_run(", idx)
    body = src[idx:end]
    assert "subprocess" in body.lower() or "_sp.run" in body, "subprocess call expected"
    # And run_sd should NOT be called in the body (parameter kept for compat)
    assert "run_sd(" not in body, "sudo.run must not route through run_sd on POSIX"


def test_ps_quote_helper_escapes_single_quote():
    from arena.mcp.tool_net import _ps_quote
    assert _ps_quote("hello") == "'hello'"
    assert _ps_quote("it's fine") == "'it''s fine'"
    assert _ps_quote("nested 'inner' quotes") == "'nested ''inner'' quotes'"


def test_changelog_mentions_v4_60_6():
    assert "4.60.6" in _read("CHANGELOG.md")
    assert "4.60.6" in _read("CHANGELOG.ru.md")

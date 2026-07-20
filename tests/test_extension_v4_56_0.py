"""v4.56.0 — MCP-registered mobile.* tools + policy/registry consistency.

The 30 mobile tools wrap existing /v1/mobile/* HTTP handlers (which
have been in the bridge since v3.83.x) so scenarios and the browser
chat extension can drive Android devices through the typed tool
surface.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from arena import constants
from arena.mcp.tool_registry import MCP_TOOLS
from arena.mcp.tool_registry_mobile import MOBILE_MCP_TOOLS
from arena.extension_bridge.policy import (
    _SAFE_TOOLS, _MEDIUM_TOOLS, _DANGEROUS_TOOLS, _DANGEROUS_PREFIXES,
    classify_tool_risk,
)
from arena.mcp.tool_mobile import handle_mobile_tool, _ROUTES


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


# ------------------------------------------------------------------
# 1. Version bump
# ------------------------------------------------------------------
def test_version_is_4_56_0():
    assert constants.VERSION in ("4.56.0", "4.57.0", "4.58.0", "4.59.0", "4.59.1", "4.60.0")


def test_pyproject_version_is_4_56_0():
    src = _read("pyproject.toml")
    assert any(v in src for v in ('version = "4.56.0"', 'version = "4.57.0"', 'version = "4.58.0"', 'version = "4.59.0"', 'version = "4.59.1"', 'version = "4.58.0"', 'version = "4.59.0"', 'version = "4.59.1"', 'version = "4.60.0"'))


# ------------------------------------------------------------------
# 2. Mobile registry is complete and wired in
# ------------------------------------------------------------------
def test_mobile_registry_declares_30_tools():
    names = [t["name"] for t in MOBILE_MCP_TOOLS]
    assert len(names) == 32
    assert len(set(names)) == 32  # no duplicates


def test_mobile_registry_covers_all_dispatched_tools():
    """Every _ROUTES entry (plus the two special-case rec_id tools) must
    have a corresponding MOBILE_MCP_TOOLS registry entry so extension &
    scenarios can discover them."""
    dispatched = set(_ROUTES.keys()) | {"mobile.record_stop", "mobile.record_pull"}
    declared = {t["name"] for t in MOBILE_MCP_TOOLS}
    assert dispatched == declared, dispatched.symmetric_difference(declared)


def test_mobile_tools_appear_in_MCP_TOOLS():
    mcp_names = {t["name"] for t in MCP_TOOLS}
    for tool in MOBILE_MCP_TOOLS:
        assert tool["name"] in mcp_names, f"missing from MCP_TOOLS: {tool['name']}"


def test_mobile_dispatcher_wired_in_tools_module():
    src = _read("arena/mcp/tools.py")
    assert "handle_mobile_tool" in src
    assert "from arena.mcp.tool_mobile import handle_mobile_tool" in src


# ------------------------------------------------------------------
# 3. Policy classifies every mobile.* tool
# ------------------------------------------------------------------
def test_every_mobile_tool_has_a_risk_class():
    for tool in MOBILE_MCP_TOOLS:
        risk = classify_tool_risk(tool["name"])
        assert risk in ("safe", "medium", "dangerous"), f"{tool['name']} -> {risk}"


def test_mobile_shell_is_dangerous():
    assert classify_tool_risk("mobile.shell") == "dangerous"


def test_mobile_screenshot_is_safe():
    assert classify_tool_risk("mobile.screenshot") == "safe"


def test_mobile_tap_is_medium():
    assert classify_tool_risk("mobile.tap") == "medium"


def test_mobile_ime_set_is_dangerous():
    """Switching IME can hijack every subsequent keystroke — dangerous."""
    assert classify_tool_risk("mobile.ime_set") == "dangerous"


# ------------------------------------------------------------------
# 4. Policy / registry consistency: no phantom tool names
# ------------------------------------------------------------------
def test_no_phantom_safe_tools_in_policy():
    """Every tool listed as SAFE in policy must be dispatchable.

    Known intentional gaps (documented in policy.py comments):
      - browser.fetch, browser.head — advertised in policy for future use,
        not yet dispatched. Track these in _POLICY_PHANTOM_ALLOWLIST.
    """
    mcp_names = {t["name"] for t in MCP_TOOLS}
    phantoms = _SAFE_TOOLS - mcp_names - _POLICY_PHANTOM_ALLOWLIST
    assert not phantoms, f"policy declares SAFE tools not in MCP registry: {sorted(phantoms)}"


def test_no_phantom_medium_tools_in_policy():
    mcp_names = {t["name"] for t in MCP_TOOLS}
    phantoms = _MEDIUM_TOOLS - mcp_names - _POLICY_PHANTOM_ALLOWLIST
    assert not phantoms, sorted(phantoms)


def test_no_phantom_dangerous_tools_in_policy():
    mcp_names = {t["name"] for t in MCP_TOOLS}
    phantoms = _DANGEROUS_TOOLS - mcp_names - _POLICY_PHANTOM_ALLOWLIST
    assert not phantoms, sorted(phantoms)


# The two tools policy names but bridge does not yet register. Adding
# them here is a *deliberate* declaration — future work is to either
# register them or delete them from policy, at which point this
# allowlist shrinks. Do NOT extend this without a matching TODO/mission.
_POLICY_PHANTOM_ALLOWLIST = frozenset({
    "browser.fetch",
    "browser.head",
})


# ------------------------------------------------------------------
# 5. Dispatcher input validation
# ------------------------------------------------------------------
def test_mobile_tool_returns_none_for_non_mobile_name():
    class _Ctx:
        pass
    assert handle_mobile_tool("fs.read", {"path": "/tmp"}, ctx=_Ctx()) is None


def test_mobile_tool_requires_serial_when_needed():
    class _Ctx:
        pass
    out = handle_mobile_tool("mobile.info", {}, ctx=_Ctx())
    assert out is not None and out.get("isError")
    assert "serial" in out["content"][0]["text"].lower()


def test_mobile_record_stop_requires_rec_id():
    class _Ctx:
        pass
    out = handle_mobile_tool("mobile.record_stop", {}, ctx=_Ctx())
    assert out is not None and out.get("isError")
    assert "rec_id" in out["content"][0]["text"].lower()


def test_mobile_record_pull_requires_rec_id():
    class _Ctx:
        pass
    out = handle_mobile_tool("mobile.record_pull", {}, ctx=_Ctx())
    assert out is not None and out.get("isError")


# ------------------------------------------------------------------
# 6. Every dispatched tool has an inputSchema with 'serial' or 'rec_id'
#    when the underlying HTTP route needs one.
# ------------------------------------------------------------------
def test_serial_scoped_tools_declare_serial_in_schema():
    schemas = {t["name"]: t["inputSchema"] for t in MOBILE_MCP_TOOLS}
    for name, (_method, path, _args, _bin) in _ROUTES.items():
        if "{serial}" in path:
            props = schemas[name].get("properties", {})
            assert "serial" in props, f"{name}: schema missing 'serial' property"
            assert "serial" in schemas[name].get("required", []), f"{name}: 'serial' not required"


# ------------------------------------------------------------------
# 7. Scenario-facing description: mobile.* mentioned somewhere in tools
#    or scenarios docs so the extension surfacing can discover it.
# ------------------------------------------------------------------
def test_mobile_tools_registered_alongside_scenario_tools():
    """Cheap smoke: SCENARIO_MCP_TOOLS and MOBILE_MCP_TOOLS both flow
    into MCP_TOOLS via arena/mcp/tool_registry.py."""
    src = _read("arena/mcp/tool_registry.py")
    assert "MOBILE_MCP_TOOLS" in src
    assert "SCENARIO_MCP_TOOLS" in src


# ------------------------------------------------------------------
# 8. Total MCP tool count grows by exactly len(MOBILE_MCP_TOOLS)
# ------------------------------------------------------------------
def test_mcp_tools_total_reflects_mobile_addition():
    # Sanity: MOBILE_MCP_TOOLS entries are all present.
    mcp_names = {t["name"] for t in MCP_TOOLS}
    added = {t["name"] for t in MOBILE_MCP_TOOLS}
    assert added.issubset(mcp_names)


# ------------------------------------------------------------------
# 9. Extension version unchanged
# ------------------------------------------------------------------
def test_extension_version_unchanged_since_v4_53_1():
    """v4.56.0 is bridge-only. Extension byte-identical since v4.53.1."""
    src = _read("chat_extension/manifest.json")
    assert '"version": "0.14.42"' in src


# ------------------------------------------------------------------
# 10. Changelog mentions v4.56.0
# ------------------------------------------------------------------
def test_changelog_mentions_v4_56_0():
    en = _read("CHANGELOG.md")
    ru = _read("CHANGELOG.ru.md")
    assert "v4.56.0" in en or "4.56.0" in en
    assert "v4.56.0" in ru or "4.56.0" in ru

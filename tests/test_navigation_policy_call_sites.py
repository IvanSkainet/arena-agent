"""Fail-closed guard: no agent-facing surface may take a URL and navigate.

Why this exists
---------------
``check_navigation`` is only worth as much as its coverage. The behavioural
suite in ``test_cdp_navigation_policy.py`` drives today's entry points, but a
*new* handler that reads ``url`` from a request and passes it to ``navigate()``
would sail past it — nothing goes red, and the SSRF hole from #103 quietly
returns under a different route name.

So this reads the source. Every module that both accepts a caller-supplied
URL and reaches a navigation must import the policy; anything else has to be
listed below with a stated reason. Same shape as
``tests/test_auth_surface_guard.py``: an explicit, reviewable allow-list
rather than a grep that silently drifts.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

POLICY_MODULE = "arena.browser.navigation_policy"

#: Modules that reach a navigation without consulting the policy, and why.
#: Adding an entry is a deliberate decision that the URL cannot originate
#: from an agent request.
NAVIGATION_WITHOUT_POLICY: dict[str, str] = {
    "arena/browser/cdp_client/browser_page.py": (
        "the CDP transport itself -- it issues Page.navigate for whatever the "
        "layer above already approved, and cannot distinguish an agent "
        "request from an operator CLI call"
    ),
    "arena/browser/cdp_client/tab_ops.py": (
        "thin per-tab delegate to browser_page.navigate, same transport layer"
    ),
    "arena/browser/cdp_client/sync_browser.py": (
        "synchronous debugging client, not wired into any route or MCP tool"
    ),
    "arena/browser/cdp_client/cli.py": (
        "operator CLI: the URL comes from the local command line, and a "
        "human typing localhost is the documented use of this tool"
    ),
    "arena/browser/cdp_client/cli_demo.py": (
        "demo script with a hardcoded https://example.org target"
    ),
    "arena/browser/cdp_client/tab_manager_tab_lifecycle.py": (
        "internal tab bookkeeping; every caller that accepts a URL from a "
        "request (cdp/tabs.py) validates before reaching it"
    ),
    "arena/browser/browse_cdp.py": (
        "executes an already-validated URL: browse_handlers.py applies the "
        "policy before dispatching to run_cdp_extract/run_cdp_shot"
    ),
}

NAVIGATION_CALLS = {"navigate"}
NAVIGATION_CDP_METHOD = "Page.navigate"


def _python_sources() -> list[Path]:
    return sorted(
        path
        for path in (ROOT / "arena").rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _module_navigates(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in NAVIGATION_CALLS:
                return True
            for arg in node.args:
                if isinstance(arg, ast.Constant) and arg.value == NAVIGATION_CDP_METHOD:
                    return True
    return False


def _imports_policy(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == POLICY_MODULE:
            return True
        if isinstance(node, ast.Import):
            if any(alias.name == POLICY_MODULE for alias in node.names):
                return True
    return False


def _navigating_modules() -> dict[str, ast.AST]:
    found: dict[str, ast.AST] = {}
    for path in _python_sources():
        if path.name == "navigation_policy.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if _module_navigates(tree):
            found[path.relative_to(ROOT).as_posix()] = tree
    return found


def test_every_navigating_module_consults_the_policy_or_is_allow_listed():
    unguarded = [
        rel
        for rel, tree in _navigating_modules().items()
        if not _imports_policy(tree) and rel not in NAVIGATION_WITHOUT_POLICY
    ]
    assert not unguarded, (
        "these modules reach a browser navigation without importing "
        f"{POLICY_MODULE}: {unguarded}. Either apply check_navigation(), or "
        "add the module to NAVIGATION_WITHOUT_POLICY with the reason it "
        "cannot receive an agent-supplied URL."
    )


def test_the_allow_list_has_no_stale_entries():
    """A listed module that no longer navigates must leave the list."""
    navigating = set(_navigating_modules())
    stale = sorted(set(NAVIGATION_WITHOUT_POLICY) - navigating)
    assert not stale, (
        f"NAVIGATION_WITHOUT_POLICY lists modules that no longer navigate: "
        f"{stale}. Remove them so the exemption list stays honest."
    )


def test_every_allow_list_entry_states_a_reason():
    for module, reason in NAVIGATION_WITHOUT_POLICY.items():
        assert reason.strip(), f"{module} is exempted without a reason"
        assert len(reason) > 30, f"{module}: reason is too terse to review"


@pytest.mark.parametrize("module", sorted(NAVIGATION_WITHOUT_POLICY))
def test_allow_listed_modules_exist(module):
    assert (ROOT / module).is_file(), (
        f"{module} is exempted but does not exist -- the path is stale"
    )


def test_the_known_agent_facing_handlers_are_guarded():
    """Positive control: the entry points from #103 must import the policy.

    Without this, emptying NAVIGATION_WITHOUT_POLICY's counterpart -- i.e.
    adding every handler to the exemption list -- would keep the suite green.
    """
    required = [
        "arena/browser/cdp/page_nav.py",
        "arena/browser/cdp/advanced_stealth_extract.py",
        "arena/browser/cdp/advanced_stealth_shot.py",
        "arena/browser/cdp/tabs.py",
        "arena/browser/browse_handlers.py",
        "arena/profiles/load_handler.py",
        "arena/mcp/tool_browser_headed.py",
    ]
    missing = []
    for rel in required:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        if not _imports_policy(tree):
            missing.append(rel)
        if rel in NAVIGATION_WITHOUT_POLICY:
            missing.append(f"{rel} (must not be exempted)")
    assert not missing, f"agent-facing navigation surfaces lost the policy: {missing}"


# The tests above run the gate against the repository, which is compliant by
# construction: they prove today's tree is clean, not that the detector still
# detects. These drive the two predicates with synthetic source, so a
# regression that makes `_module_navigates` blind (or `_imports_policy`
# credulous) fails here instead of silently exempting the whole codebase.

_UNGUARDED_ATTRIBUTE_CALL = "async def go(tab, url):\n    return await tab.navigate(url)\n"
_UNGUARDED_RAW_CDP = (
    "async def go(conn, url):\n"
    "    return await conn.send('Page.navigate', {'url': url})\n"
)
_GUARDED = (
    "from arena.browser.navigation_policy import check_navigation\n"
    "async def go(tab, url):\n"
    "    return await tab.navigate(check_navigation(url))\n"
)
_INERT = "def render(template, data):\n    return template.format(**data)\n"


@pytest.mark.parametrize("source", [_UNGUARDED_ATTRIBUTE_CALL, _UNGUARDED_RAW_CDP])
def test_the_detector_sees_a_navigating_module(source):
    assert _module_navigates(ast.parse(source))


def test_the_detector_ignores_a_module_that_does_not_navigate():
    """Positive control: without this, a detector stuck on True would pass."""
    assert not _module_navigates(ast.parse(_INERT))


def test_an_unguarded_navigating_module_would_be_reported():
    tree = ast.parse(_UNGUARDED_ATTRIBUTE_CALL)
    assert _module_navigates(tree)
    assert not _imports_policy(tree)


def test_a_guarded_navigating_module_would_be_accepted():
    tree = ast.parse(_GUARDED)
    assert _module_navigates(tree)
    assert _imports_policy(tree)


def test_the_policy_import_check_is_not_satisfied_by_a_lookalike():
    """`import arena.browser.navigation` must not pass for the policy."""
    tree = ast.parse("from arena.browser import fetch\nimport arena.browser.cdp\n")
    assert not _imports_policy(tree)

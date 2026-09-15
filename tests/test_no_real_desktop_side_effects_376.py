"""Running the suite must not disturb the machine it runs on (#376).

The dispatch contract test calls every declared MCP tool with `{}`, and
`sys.notify` is one of them. Its handler called the module-level
`send_notification` it had imported, so a full local run fired a real
Windows toast -- attributed to "Windows PowerShell", because
`arena/system/notification.py` deliberately uses PowerShell's registered
AppUserModelID (an arbitrary one is dropped silently by Windows, so that
part is correct for the product and only wrong in a test).

Two things made it survive:

* `McpToolContext` already carried `send_notification_sync`, and the
  contract test already substituted it -- the handler just did not use
  it, so the substitution looked effective and was not.
* CI is headless Linux, where there is no toast service and nothing
  visibly happens. The defect was only observable on a developer
  desktop, which is exactly where it was reported from.

These tests pin the property rather than the wiring: no test may reach a
real notification API, and the tool must route through the context.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_MISC = REPO_ROOT / "arena" / "mcp" / "tool_misc.py"

def _imports_from(tree: ast.AST, module: str) -> bool:
    """True if `from <module> import ...` appears anywhere in `tree`."""
    return any(
        isinstance(node, ast.ImportFrom) and node.module == module
        for node in ast.walk(tree)
    )


def _calls_attribute(tree: ast.AST, attr: str) -> bool:
    """True if `<something>.<attr>(...)` is called anywhere in `tree`."""
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
        for node in ast.walk(tree)
    )


def test_sys_notify_goes_through_the_context_not_a_module_import() -> None:
    """The structural guard, and the deterministic one.

    A behavioural check needs a desktop session to observe, so on a
    headless runner it proves nothing -- which is how this shipped. The
    call site is checkable exactly, so it is checked exactly.
    """
    tree = ast.parse(TOOL_MISC.read_text(encoding="utf-8"))

    assert not _imports_from(tree, "arena.system.notification"), (
        "tool_misc imports the notifier directly again; `from ... import` "
        "binds by value, so substituting it in the context has no effect "
        "and the suite shows real toasts (#376)"
    )

    assert _calls_attribute(tree, "send_notification_sync"), (
        "nothing calls ctx.send_notification_sync -- sys.notify is either "
        "gone or has stopped routing through the injectable seam"
    )


def test_the_dispatch_contract_substitution_actually_reaches_the_handler(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The control: the seam must be usable, not merely present.

    Drives the real dispatcher the way the contract test does and
    asserts the injected notifier -- not the OS -- received the call.
    Without this, the structural test above is satisfied by a handler
    that takes the context and ignores it.
    """
    from arena.mcp.tool_misc import handle_misc_tool

    seen: list[tuple[str, str]] = []

    class _Ctx:
        def send_notification_sync(self, title: str, message: str) -> dict:
            seen.append((title, message))
            return {"ok": True, "method": "injected"}

        def play_beep_sync(self, *a, **k) -> dict:
            return {}

    result = handle_misc_tool(
        "sys.notify", {"title": "t", "message": "m"},
        ctx=_Ctx(), run_local=None)

    assert seen == [("t", "m")], (
        "the handler bypassed the injected notifier, so a test that "
        "substitutes it still reaches the real desktop")
    assert result is not None


def test_no_test_calls_the_real_notifier_unsubstituted() -> None:
    """No test may call `send_notification` without replacing the backend.

    A plain grep for the notification APIs was the first attempt and it
    was wrong: `test_android_is_linux_v4_169_11.py` mentions
    `notify-send` and `termux-notification` as *expected return values*
    while monkeypatching every backend, which is a correct test. The
    string appearing in a file says nothing; calling the entry point
    with the platform notifiers live is what matters.

    Checked at the source because on a headless runner there is nothing
    to observe, and a test that silently cannot fail is worse than none.
    """
    offenders = []
    for path in sorted((REPO_ROOT / "tests").glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "send_notification(" not in text:
            continue
        # Substituting any of the platform backends, or the entry point
        # itself, means the call cannot reach the OS.
        substituted = any(
            marker in text for marker in (
                "notify_windows", "notify_linux", "notify_macos",
                "notify_android", "send_notification_sync",
                'setattr(notification, "send_notification"',
            )
        )
        if not substituted:
            offenders.append(path.name)

    assert not offenders, (
        "these tests call send_notification with the real platform "
        "backends live; they pop a toast on whoever runs the suite:\n  "
        + "\n  ".join(offenders))


def test_the_probe_that_found_this_is_not_left_behind() -> None:
    """The investigation plugin was a branch-local tool, not a fixture.

    It patched `subprocess.run` globally, which broke anyio's backend
    import on Windows the first time and made a dead run look like a
    clean one. Useful once; dangerous to leave loadable.

    Checked on disk rather than with `git ls-files`: a test that shells
    out to git has to join the git budget in `test_git_budget.py`, and
    spending that budget on one existence check is not worth it.
    """
    assert not (REPO_ROOT / "tests" / "conftest_sideeffect_probe.py").exists(), (
        "the side-effect probe is still in the tree; it globally replaces "
        "subprocess.run and must not be loadable by an ordinary run")

"""Running the suite must not disturb the machine it runs on (#376, #378).

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
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_MISC = REPO_ROOT / "arena" / "mcp" / "tool_misc.py"

def _reaches_notifier(tree: ast.AST) -> list[str]:
    """Every import in `tree` that can reach `arena.system.notification`.

    Matching only `from arena.system.notification import ...` was not
    enough (review): `import arena.system.notification as _n` and
    `from arena.system import notification` both bypassed it, and a
    handler could then call the real notifier while still making a
    decorative `ctx.send_notification_sync` call to satisfy the check
    below. Verified -- that exact shape passed all four tests and still
    showed a toast.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        found += _notifier_imports(node)
    return found


_NOTIFIER_MODULE = "arena.system.notification"


def _notifier_imports(node: ast.AST) -> list[str]:
    """The notifier modules one import statement brings into scope."""
    return [name for name in _imported_names(node)
            if name == _NOTIFIER_MODULE]


def _imported_names(node: ast.AST) -> list[str]:
    """Every dotted module path an import statement could refer to.

    For `from X import a, b` that is `X`, `X.a` and `X.b`, because
    `from arena.system import notification` reaches the notifier just as
    surely as importing it by its full path does.
    """
    if isinstance(node, ast.Import):
        return [a.name for a in node.names]
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        return [module] + [f"{module}.{a.name}" for a in node.names]
    return []


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

    reached = _reaches_notifier(tree)
    assert not reached, (
        f"tool_misc imports the notifier directly again ({reached}); the "
        "context substitution then has no effect and the suite shows real "
        "toasts (#376)"
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
    from arena.mcp import tool_misc
    from arena.system import notification

    seen: list[tuple[str, str]] = []
    real_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        notification, "send_notification",
        lambda t, m: real_calls.append((t, m)) or {"ok": False})

    class _Ctx:
        def send_notification_sync(self, title: str, message: str) -> dict:
            seen.append((title, message))
            return {"ok": True, "method": "injected"}

        def play_beep_sync(self, *a, **k) -> dict:
            return {}

    result = tool_misc.handle_misc_tool(
        "sys.notify", {"title": "t", "message": "m"},
        ctx=_Ctx(), run_local=None)

    assert seen == [("t", "m")], (
        "the handler bypassed the injected notifier, so a test that "
        "substitutes it still reaches the real desktop")
    assert result is not None
    # Calling the injected notifier *and* the real one would satisfy the
    # assertion above while still lighting up the desktop (review), so
    # the real entry point is watched for the duration of the call.
    assert real_calls == [], (
        f"the handler also called the real notifier {real_calls}; the "
        "injected seam is decorative")


def _substitutes_the_notifier(tree: ast.AST) -> bool:
    """True if the module replaces the notifier or one of its backends.

    Looks for the assignment, not for the word. The first version of
    this guard accepted any file that *mentioned* a backend name, which
    a file can do in a comment while calling the live notifier two lines
    later -- demonstrated, it passed (review).
    """
    return any(
        _replaces_by_call(node) or _replaces_by_assignment(node)
        for node in ast.walk(tree)
    )


_NOTIFIER_NAMES = frozenset({
    "send_notification", "notify_windows", "notify_linux",
    "notify_macos", "notify_android", "send_notification_sync",
})


def _replaces_by_call(node: ast.AST) -> bool:
    """`monkeypatch.setattr(..., "notify_linux", ...)` or `patch("...")`."""
    if not isinstance(node, ast.Call):
        return False
    return any(
        isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        and arg.value.rsplit(".", 1)[-1] in _NOTIFIER_NAMES
        for arg in node.args
    )


def _replaces_by_assignment(node: ast.AST) -> bool:
    """`notification.send_notification = ...`"""
    if not isinstance(node, ast.Assign):
        return False
    return any(
        isinstance(tgt, ast.Attribute) and tgt.attr in _NOTIFIER_NAMES
        for tgt in node.targets
    )


def _calls_send_notification(tree: ast.AST) -> bool:
    """True if `send_notification(...)` is called, however it is spelled."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "send_notification":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "send_notification":
            return True
    return False


def test_no_test_calls_the_real_notifier_unsubstituted() -> None:
    """No test may call `send_notification` without replacing the backend.

    Two earlier versions of this guard were too loose, both caught in
    review:

    * a plain grep for `notify-send` flagged
      `test_android_is_linux_v4_169_11.py`, which is a *correct* test
      that monkeypatches every backend and merely names those strings as
      expected return values;
    * matching the substitution by text accepted a file that mentioned a
      backend in a comment while calling the live notifier.

    So both halves are read from the AST now. It also walks
    subdirectories: `tests/e2e/` was invisible to `glob`, which is where
    a live-bridge test is most likely to reach a real desktop.
    """
    offenders = []
    for path in sorted((REPO_ROOT / "tests").rglob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:                       # pragma: no cover
            continue
        if _calls_send_notification(tree) and not _substitutes_the_notifier(tree):
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "these tests call send_notification with the real platform "
        "backends live; they pop a toast on whoever runs the suite:\n  "
        + "\n  ".join(offenders))


# Win32 entry points that move the pointer or synthesise input.
_INPUT_APIS = frozenset({"SetCursorPos", "mouse_event", "SendInput"})


def _moves_the_pointer(tree: ast.AST) -> bool:
    """True if the module calls a Win32 input API directly."""
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _INPUT_APIS
        for node in ast.walk(tree)
    )


def _restores_what_it_moved(tree: ast.AST) -> bool:
    """True if a `finally:` block puts the pointer back.

    Scoped to the teardown deliberately: a restore on the happy path
    only is not a restore, because a failing assertion is exactly when
    the pointer is left somewhere the user did not put it.
    """
    return any(_is_pointer_move(call) for call in _teardown_calls(tree))


def _teardown_calls(tree: ast.AST) -> Iterator[ast.Call]:
    """Every call inside a `finally:` block.

    Two flat generators rather than one triple-nested loop: CodeScene
    reads three levels as Deep Nested Complexity even when each level is
    a single statement (learned the same way in #366).
    """
    for stmt in _finally_statements(tree):
        for child in ast.walk(stmt):
            if isinstance(child, ast.Call):
                yield child


def _finally_statements(tree: ast.AST) -> Iterator[ast.stmt]:
    """Every statement in a `finally:` block anywhere in `tree`."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            yield from node.finalbody


def _is_pointer_move(call: ast.Call) -> bool:
    """`<something>.mouse_move(...)` or a raw `SetCursorPos(...)`."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    return func.attr in ("mouse_move", "SetCursorPos")


def test_a_test_that_moves_the_real_pointer_puts_it_back() -> None:
    """Moving the mouse mid-run is the user's machine, not the suite's.

    `test_live_cursor_move_and_read_roundtrip` jumped the pointer to an
    absolute (500, 500) and left it there (#378). CI could not see it --
    the Windows runners have no interactive session -- so it was only
    ever visible to whoever ran the suite on a desktop, which is who
    reported it.

    The live backend tests are worth keeping: they are the only thing
    exercising the real round trip. What they must not do is finish with
    the pointer somewhere else.
    """
    offenders = []
    for path in sorted((REPO_ROOT / "tests").rglob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:                       # pragma: no cover
            continue
        if _calls_mouse_move(tree) and not _restores_what_it_moved(tree):
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "these tests move the real mouse pointer without restoring it in a "
        "finally; the pointer ends the run wherever they left it:\n  "
        + "\n  ".join(offenders))


def _calls_mouse_move(tree: ast.AST) -> bool:
    """True if the module drives the pointer at all."""
    return any(
        isinstance(node, ast.Call) and _is_pointer_move(node)
        for node in ast.walk(tree)
    ) or _moves_the_pointer(tree)


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

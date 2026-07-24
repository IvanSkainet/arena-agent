"""Tests for the v4.69.0 deprecation of bare tool names.

The four bare tool names ``ping`` / ``echo`` / ``exec`` /
``snapshot`` are deprecated as of v4.69.0 in favour of their
``exec.*`` namespaced twins. The deprecation is communicated
in three places:

1. The catalogue entry carries a JSON-schema
   ``deprecationMessage`` field (so well-behaved clients can
   surface the deprecation in their tool palette).
2. The catalogue ``description`` carries a
   ``[DEPRECATED v4.69.0; use exec.X]`` suffix.
3. The dispatch layer emits a
   ``PendingDeprecationWarning`` at call time so server-side
   logs surface any caller that hasn't migrated.

These tests pin the three behaviours so a future refactor
can't silently regress them. They also verify the namespaced
twins do NOT carry the deprecation metadata (so the migration
target is unambiguous).
"""
from __future__ import annotations

import json
import re
import sys
import warnings
from pathlib import Path

import pytest


# Skip the whole module if the catalogue can't be imported
# (e.g. running outside the repo checkout).
try:
    from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
except Exception:  # pragma: no cover
    pytest.skip("MCP_TOOLS not importable; run from repo root", allow_module_level=True)


_BARE_TO_NAMESPACED = {
    "ping": "exec.ping",
    "echo": "exec.echo",
    "exec": "exec.exec",
    "snapshot": "exec.snapshot",
}


def _by_name(name: str) -> dict:
    for entry in MCP_TOOLS:
        if entry.get("name") == name:
            return entry
    raise AssertionError(f"no catalogue entry for {name!r}")


# -------------------------------------------------------------------
# 1. Catalogue entries carry the deprecation metadata.
# -------------------------------------------------------------------


@pytest.mark.parametrize("bare", sorted(_BARE_TO_NAMESPACED))
def test_bare_entry_has_deprecation_message(bare: str) -> None:
    entry = _by_name(bare)
    msg = entry.get("deprecationMessage")
    assert isinstance(msg, str), (
        f"bare entry {bare!r} is missing deprecationMessage; v4.69.0 requires it"
    )
    assert msg.strip(), f"bare entry {bare!r} has empty deprecationMessage"
    # The migration target should be mentioned in the message.
    target = _BARE_TO_NAMESPACED[bare]
    assert target in msg, (
        f"deprecationMessage for {bare!r} does not mention the namespaced twin {target!r}: {msg!r}"
    )
    # And the version that introduced the deprecation.
    assert "v4.69.0" in msg, (
        f"deprecationMessage for {bare!r} does not mention the deprecation version v4.69.0: {msg!r}"
    )


@pytest.mark.parametrize("bare", sorted(_BARE_TO_NAMESPACED))
def test_bare_entry_description_is_marked_deprecated(bare: str) -> None:
    entry = _by_name(bare)
    desc = entry.get("description", "")
    target = _BARE_TO_NAMESPACED[bare]
    assert "DEPRECATED" in desc, (
        f"bare entry {bare!r} description missing DEPRECATED marker: {desc!r}"
    )
    assert "v4.69.0" in desc, (
        f"bare entry {bare!r} description missing v4.69.0 marker: {desc!r}"
    )
    assert target in desc, (
        f"bare entry {bare!r} description should mention the namespaced twin {target!r}: {desc!r}"
    )


# -------------------------------------------------------------------
# 2. Namespaced twins are NOT marked deprecated.
# -------------------------------------------------------------------


@pytest.mark.parametrize("bare", sorted(_BARE_TO_NAMESPACED))
def test_namespaced_twin_has_no_deprecation_message(bare: str) -> None:
    target = _BARE_TO_NAMESPACED[bare]
    entry = _by_name(target)
    assert "deprecationMessage" not in entry, (
        f"namespaced twin {target!r} should NOT carry deprecationMessage; "
        f"it is the migration target, not the deprecated form. got: {entry.get('deprecationMessage')!r}"
    )


@pytest.mark.parametrize("bare", sorted(_BARE_TO_NAMESPACED))
def test_namespaced_twin_description_is_clean(bare: str) -> None:
    target = _BARE_TO_NAMESPACED[bare]
    entry = _by_name(target)
    desc = entry.get("description", "")
    assert "DEPRECATED" not in desc, (
        f"namespaced twin {target!r} description should not be marked deprecated: {desc!r}"
    )


# -------------------------------------------------------------------
# 3. inputSchema is still hardened on bare entries (don't trade
#    a deprecation for a missing additionalProperties: false).
# -------------------------------------------------------------------


@pytest.mark.parametrize("bare", sorted(_BARE_TO_NAMESPACED))
def test_bare_entry_input_schema_still_hardened(bare: str) -> None:
    entry = _by_name(bare)
    schema = entry.get("inputSchema", {})
    assert schema.get("additionalProperties") is False, (
        f"bare entry {bare!r} lost additionalProperties: false on its inputSchema"
    )


# -------------------------------------------------------------------
# 4. Dispatch emits PendingDeprecationWarning for bare calls.
# -------------------------------------------------------------------


@pytest.mark.parametrize("bare", sorted(_BARE_TO_NAMESPACED))
def test_dispatch_emits_pending_deprecation_warning_for_bare_name(bare: str) -> None:
    """Calling the dispatcher with a bare name must emit a PendingDeprecationWarning.

    The dispatcher functions (``handle_exec_tool``,
    ``handle_misc_tool``) take a ``ctx`` and either ``run_sd`` or
    ``run_local`` callable. We construct a minimal stub for both
    so the warning fires before the actual side-effect.
    """
    from arena.mcp.tool_exec import handle_exec_tool
    from arena.mcp.tool_misc import handle_misc_tool

    class _StubCtx:
        def blocked_reason(self, cmd): return None
        def first_word(self, cmd): return ""
        cautious_allow = None
        def app_config(self): return {}
        def common_status(self, cfg): return {}
        def skills_list_sync_with_cache(self): return {"skills": []}
        def skills_run_sync(self, name, extra): return {"ok": True, "skill": name, "extra": extra}
        bridge_dir = Path("/tmp")
        bin_dir = "/tmp"

    def _run_stub(*args, **kwargs):
        return 0, "", ""

    if bare in {"ping", "echo", "exec"}:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            handle_exec_tool(bare, {"cmd": "true"} if bare == "exec" else {"text": "x"} if bare == "echo" else {}, ctx=_StubCtx(), run_sd=_run_stub)
    elif bare == "snapshot":
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            handle_misc_tool(bare, {}, ctx=_StubCtx(), run_local=_run_stub)
    else:  # pragma: no cover
        pytest.fail(f"unhandled bare name {bare!r}")

    pendings = [w for w in caught if issubclass(w.category, PendingDeprecationWarning)]
    assert pendings, (
        f"calling dispatcher with bare name {bare!r} did not emit a "
        f"PendingDeprecationWarning; expected at least one."
    )
    msg = str(pendings[0].message)
    target = _BARE_TO_NAMESPACED[bare]
    assert target in msg, f"warning for {bare!r} does not mention {target!r}: {msg!r}"


# -------------------------------------------------------------------
# 5. Namespaced calls do NOT emit the deprecation warning.
# -------------------------------------------------------------------


@pytest.mark.parametrize("bare", sorted(_BARE_TO_NAMESPACED))
def test_dispatch_does_not_warn_for_namespaced_name(bare: str) -> None:
    from arena.mcp.tool_exec import handle_exec_tool
    from arena.mcp.tool_misc import handle_misc_tool

    class _StubCtx:
        def blocked_reason(self, cmd): return None
        def first_word(self, cmd): return ""
        cautious_allow = None
        def app_config(self): return {}
        def common_status(self, cfg): return {}
        def skills_list_sync_with_cache(self): return {"skills": []}
        def skills_run_sync(self, name, extra): return {"ok": True, "skill": name, "extra": extra}
        bridge_dir = Path("/tmp")
        bin_dir = "/tmp"

    def _run_stub(*args, **kwargs):
        return 0, "", ""

    target = _BARE_TO_NAMESPACED[bare]
    if target in {"exec.ping", "exec.echo", "exec.exec"}:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            handle_exec_tool(target, {"cmd": "true"} if target == "exec.exec" else {"text": "x"} if target == "exec.echo" else {}, ctx=_StubCtx(), run_sd=_run_stub)
    elif target == "exec.snapshot":
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            handle_misc_tool(target, {}, ctx=_StubCtx(), run_local=_run_stub)
    else:  # pragma: no cover
        pytest.fail(f"unhandled namespaced name {target!r}")

    pendings = [w for w in caught if issubclass(w.category, PendingDeprecationWarning)]
    assert not pendings, (
        f"calling dispatcher with namespaced name {target!r} emitted a "
        f"PendingDeprecationWarning; the namespaced form should be quiet. "
        f"Got: {[str(w.message) for w in pendings]}"
    )


# -------------------------------------------------------------------
# 6. The legacy-name guard is wired into the catalogue-harden
#    audit (smoke test for the script's CLI).
# -------------------------------------------------------------------


def test_legacy_name_guard_script_runs_clean(tmp_path: Path) -> None:
    """Running the guard on a clean repo should exit 0.

    We don't shell out to the script (it would have to find
    the right cwd), we import and call its ``_run`` function
    on the actual repo root.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    try:
        import legacy_name_guard as guard
    finally:
        # Don't pollute sys.path for the rest of the test session.
        sys.path.pop(0)

    repo_root = Path(__file__).resolve().parent.parent
    rc = guard._run(repo_root)
    assert rc == 0, f"legacy_name_guard._run returned {rc}; expected 0 (clean repo)"


def test_legacy_name_guard_script_fails_on_new_dispatch(tmp_path: Path) -> None:
    """A new dispatch file that uses a bare name should fail the guard.

    We create a throwaway ``tool_bare_test.py`` inside
    ``arena/mcp/`` (a real file on disk, not a symlink), run
    the guard, then delete the file. The guard should return 1
    and the file should not be visible to other tests.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    try:
        import legacy_name_guard as guard
    finally:
        sys.path.pop(0)

    repo_root = Path(__file__).resolve().parent.parent
    target = repo_root / "arena" / "mcp" / "tool_bare_test_tmp.py"
    if target.exists():
        target.unlink()
    try:
        target.write_text(
            "def handle_test_bare(name, args):\n"
            "    if name == 'ping':\n"
            "        return None\n",
            encoding="utf-8",
        )
        rc = guard._run(repo_root)
        assert rc == 1, f"guard returned {rc}; expected 1 (violation detected)"
    finally:
        if target.exists():
            target.unlink()

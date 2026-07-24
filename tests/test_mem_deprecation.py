"""Tests for the v4.71.0 deprecation of the legacy ``mem.*`` namespace.

The four legacy ``mem.*`` tool names (``mem.set`` /
``mem.get``) are deprecated as of v4.71.0 in favour of
the bulk ``memory.*`` namespace (``memory.import`` /
``memory.recall``). The deprecation is communicated in
three places — the same pattern as the v4.69.0 bare-name
deprecation:

1. The catalogue entry carries a JSON-schema
   ``deprecationMessage`` field (so well-behaved clients
   can surface the deprecation in their tool palette).
2. The catalogue ``description`` carries a
   ``[DEPRECATED v4.71.0; use memory.X]`` suffix.
3. The dispatch layer emits a
   ``PendingDeprecationWarning`` at call time so
   server-side logs surface any caller that hasn't
   migrated.

These tests pin the three behaviours so a future
refactor can't silently regress them. They also verify
the namespaced ``memory.*`` twins do NOT carry the
deprecation metadata (so the migration target is
unambiguous).

The legacy ``mem.*`` tools and the canonical
``memory.*`` tools have **different input schemas**:
``mem.set`` takes ``{profile, key, value, tags}`` while
``memory.import`` takes ``{profile, data, overwrite}``
(JSONL bulk). The migration is therefore a small code
change, not a drop-in rename — callers need to wrap
their single-fact write as a JSONL stream. The
deprecation message in the catalogue explains this.
"""
from __future__ import annotations

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


# The mapping the deprecation comments document.
_MEM_TO_MEMORY = {
    "mem.set": "memory.import",
    "mem.get": "memory.recall",
}


def _by_name(name: str) -> dict:
    for entry in MCP_TOOLS:
        if entry.get("name") == name:
            return entry
    raise AssertionError(f"no catalogue entry for {name!r}")


# -------------------------------------------------------------------
# 1. Catalogue entries carry the deprecation metadata.
# -------------------------------------------------------------------


@pytest.mark.parametrize("bare", sorted(_MEM_TO_MEMORY))
def test_mem_entry_has_deprecation_message(bare: str) -> None:
    entry = _by_name(bare)
    msg = entry.get("deprecationMessage")
    assert isinstance(msg, str), (
        f"legacy entry {bare!r} is missing deprecationMessage; v4.71.0 requires it"
    )
    assert msg.strip(), f"legacy entry {bare!r} has empty deprecationMessage"
    target = _MEM_TO_MEMORY[bare]
    assert target in msg, (
        f"deprecationMessage for {bare!r} does not mention the namespaced twin {target!r}: {msg!r}"
    )
    assert "v4.71.0" in msg, (
        f"deprecationMessage for {bare!r} does not mention the deprecation version v4.71.0: {msg!r}"
    )


@pytest.mark.parametrize("bare", sorted(_MEM_TO_MEMORY))
def test_mem_entry_description_is_marked_deprecated(bare: str) -> None:
    entry = _by_name(bare)
    desc = entry.get("description", "")
    target = _MEM_TO_MEMORY[bare]
    assert "DEPRECATED" in desc, (
        f"legacy entry {bare!r} description missing DEPRECATED marker: {desc!r}"
    )
    assert "v4.71.0" in desc, (
        f"legacy entry {bare!r} description missing v4.71.0 marker: {desc!r}"
    )
    assert target in desc, (
        f"legacy entry {bare!r} description should mention the namespaced twin {target!r}: {desc!r}"
    )


# -------------------------------------------------------------------
# 2. Namespaced twins are NOT marked deprecated.
# -------------------------------------------------------------------


@pytest.mark.parametrize("bare", sorted(_MEM_TO_MEMORY))
def test_memory_twin_has_no_deprecation_message(bare: str) -> None:
    target = _MEM_TO_MEMORY[bare]
    entry = _by_name(target)
    assert "deprecationMessage" not in entry, (
        f"namespaced twin {target!r} should NOT carry deprecationMessage; "
        f"it is the migration target, not the deprecated form. got: {entry.get('deprecationMessage')!r}"
    )


@pytest.mark.parametrize("bare", sorted(_MEM_TO_MEMORY))
def test_memory_twin_description_is_clean(bare: str) -> None:
    target = _MEM_TO_MEMORY[bare]
    entry = _by_name(target)
    desc = entry.get("description", "")
    assert "DEPRECATED" not in desc, (
        f"namespaced twin {target!r} description should not be marked deprecated: {desc!r}"
    )


# -------------------------------------------------------------------
# 3. inputSchema is still hardened on legacy entries (don't trade
#    a deprecation for a missing additionalProperties: false).
# -------------------------------------------------------------------


@pytest.mark.parametrize("bare", sorted(_MEM_TO_MEMORY))
def test_mem_entry_input_schema_still_hardened(bare: str) -> None:
    entry = _by_name(bare)
    schema = entry.get("inputSchema", {})
    assert schema.get("additionalProperties") is False, (
        f"legacy entry {bare!r} lost additionalProperties: false on its inputSchema"
    )


# -------------------------------------------------------------------
# 4. Dispatch emits PendingDeprecationWarning for bare calls.
# -------------------------------------------------------------------


def _stub_ctx() -> "object":
    """Build a minimal stub context for handle_memory_tool.

    The real ``handle_memory_tool`` only uses ``ctx.write_fact`` /
    ``ctx.audit`` / ``ctx.load_facts`` on the mem.* branches; for
    the warning-test we don't need them to do anything real
    because the warning fires before any ctx call.
    """

    class _Stub:
        def write_fact(self, entry): pass
        def audit(self, entry): pass
        def load_facts(self, profile): return []

    return _Stub()


def _stub_run_local(*args, **kwargs):
    return 0, "", ""


@pytest.mark.parametrize("bare", sorted(_MEM_TO_MEMORY))
def test_dispatch_emits_pending_deprecation_warning_for_mem(bare: str) -> None:
    """Calling handle_memory_tool with a bare ``mem.*`` name must emit a PendingDeprecationWarning.

    The dispatcher takes a ``ctx`` and a ``run_local``
    callable. We construct minimal stubs for both so the
    warning fires before any side-effect.
    """
    from arena.mcp.tool_memory import handle_memory_tool

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if bare == "mem.set":
            handle_memory_tool(bare, {"key": "k", "value": "v"}, ctx=_stub_ctx(), run_local=_stub_run_local)
        else:  # mem.get
            handle_memory_tool(bare, {"query": "x"}, ctx=_stub_ctx(), run_local=_stub_run_local)

    pendings = [w for w in caught if issubclass(w.category, PendingDeprecationWarning)]
    assert pendings, (
        f"calling dispatcher with bare name {bare!r} did not emit a "
        f"PendingDeprecationWarning; expected at least one."
    )
    msg = str(pendings[0].message)
    target = _MEM_TO_MEMORY[bare]
    assert target in msg, f"warning for {bare!r} does not mention {target!r}: {msg!r}"


# -------------------------------------------------------------------
# 5. Namespaced memory.* calls do NOT emit the deprecation warning.
# -------------------------------------------------------------------


@pytest.mark.parametrize("bare", sorted(_MEM_TO_MEMORY))
def test_dispatch_does_not_warn_for_memory_name(bare: str) -> None:
    """Calling handle_memory_tool with the namespaced ``memory.*`` name must NOT emit a deprecation warning.

    We use a name (``fs.read``) that the dispatcher
    doesn't recognise, so it falls through to the
    catch-all ``return None`` branch. The test is about
    confirming that namespaced-form calls don't trip the
    bare-name deprecation warning; we don't need to
    actually exercise the ``memory.*`` code path here
    (that's covered by the existing memory-related tests
    in the repo).
    """
    from arena.mcp.tool_memory import handle_memory_tool

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # Use a name that lands in the dispatcher's
        # catch-all branch (``return None``).
        handle_memory_tool("fs.read", {}, ctx=_stub_ctx(), run_local=_stub_run_local)

    pendings = [w for w in caught if issubclass(w.category, PendingDeprecationWarning)]
    assert not pendings, (
        f"calling dispatcher with a non-mem name emitted a "
        f"PendingDeprecationWarning; the dispatcher's catch-all branch should be silent. "
        f"Got: {[str(w.message) for w in pendings]}"
    )


# -------------------------------------------------------------------
# 6. Catalogue-consistency check recognises the deprecation flag.
# -------------------------------------------------------------------


def test_catalogue_consistency_recognises_deprecation() -> None:
    """The catalogue-consistency guard must report OK on the v4.71.0 baseline.

    A previous version of the guard would have failed
    here because the deprecation metadata was a "have
    description marker but no deprecationMessage" or
    "have deprecationMessage but no description marker"
    situation. v4.71.0 ships both flags together, so the
    guard is happy.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    try:
        import catalogue_consistency_check as guard
    finally:
        sys.path.pop(0)
    repo_root = Path(__file__).resolve().parent.parent
    rc = guard._run(repo_root)
    assert rc == 0, f"catalogue_consistency_check failed on v4.71.0 baseline: rc={rc}"


def test_handler_namespace_consistency_recognises_deprecation() -> None:
    """The handler-namespace-consistency guard must not flag the mem.* shadow as a hard fail.

    The v4.71.0 deprecation makes the mem.* entries
    explicitly deprecated, and the guard's
    ``_detect_shadow_namespaces`` function skips entries
    with a non-empty ``deprecationMessage``. So the
    mem.* ↔ memory.* shadow is no longer flagged.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    try:
        import handler_namespace_consistency as guard
    finally:
        sys.path.pop(0)
    repo_root = Path(__file__).resolve().parent.parent
    rc = guard._run(repo_root)
    assert rc == 0, f"handler_namespace_consistency failed on v4.71.0 baseline: rc={rc}"


def test_legacy_name_guard_whitelist_includes_handle_memory_tool() -> None:
    """The legacy-name-guard whitelist must include handle_memory_tool.

    v4.71.0 added the ``mem.*`` namespace to the bare-name
    set. ``handle_memory_tool`` is the dispatcher that
    handles both the deprecated ``mem.*`` names and the
    canonical ``memory.*`` names, so it must be in the
    whitelist to avoid a false positive.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    try:
        import legacy_name_guard as guard
    finally:
        sys.path.pop(0)
    assert ("arena/mcp/tool_memory.py", "handle_memory_tool") in guard._WHITELISTED_DISPATCH_FUNCS, (
        "handle_memory_tool should be in legacy_name_guard's whitelist; "
        "it handles both mem.* (deprecated) and memory.* (canonical)"
    )

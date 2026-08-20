"""agentctl dispatch must reject a mistyped subcommand instead of silently
running the first command of the namespace.

Regression guard for #126. Before the fix, `main()` fell through to
`list(ns_map.values())[0]` whenever the subcommand was not in the table, so:

  * `agentctl mem st KEY VALUE`  silently ran `mem set` and POSTed to /v1/memory
  * `agentctl skill new core/x`  silently ran `skill list` and exited 0
  * `agentctl mcp lst`           silently ran `mcp install` with no arguments

The `print("Unknown command: ...")` branch was unreachable dead code, because
`ns_map` had already been checked for truthiness a few lines earlier.

These tests drive `main()` through argv rather than calling helpers directly:
the bug lived in the dispatch wiring, so a test that calls the handlers cannot
see it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.agentctl_cli import agentctl_main  # noqa: E402


def _spy_dispatch(monkeypatch):
    """Replace every command with a recorder; return the shared call log."""
    calls: list[tuple[str, str, list[str]]] = []
    patched: dict[str, dict[str, object]] = {}
    for ns, ns_map in agentctl_main.DISPATCH.items():
        if not isinstance(ns_map, dict):
            continue
        new_map = {}
        for sub in ns_map:
            def rec(args, _ns=ns, _sub=sub):
                calls.append((_ns, _sub, list(args)))
            new_map[sub] = rec
        patched[ns] = new_map
    monkeypatch.setattr(agentctl_main, "DISPATCH", {**agentctl_main.DISPATCH, **patched})
    return calls


def _run(monkeypatch, argv: list[str]):
    calls = _spy_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["agentctl", *argv])
    code = None
    try:
        agentctl_main.main()
    except SystemExit as exc:
        code = exc.code
    return calls, code


# Namespace, mistyped subcommand, and the command that used to run instead.
# The third element is what makes each case worth guarding: every one of these
# fallbacks was a mutating or misleading action.
UNKNOWN_SUBCOMMANDS = [
    ("mem", "st", "set"),          # silently wrote a memory fact
    ("mem", "write", "set"),       # ditto
    ("skill", "new", "list"),      # the #126 headline: exit 0, no scaffold
    ("mcp", "lst", "install"),     # ran an installer with no arguments
    ("sub", "lst", "spawn"),       # spawned a subagent
    ("backup", "status", "run"),   # ran a backup
    ("browser", "opne", "search"), # searched for a URL instead of opening it
    ("task", "ls2", "list"),
    ("audit", "taill", "stats"),
]


@pytest.mark.parametrize(("namespace", "typo", "would_have_run"), UNKNOWN_SUBCOMMANDS)
def test_unknown_subcommand_runs_nothing_and_exits_2(
    monkeypatch, capsys, namespace, typo, would_have_run
):
    calls, code = _run(monkeypatch, [namespace, typo, "arg1", "arg2"])

    assert calls == [], (
        f"'agentctl {namespace} {typo}' executed {calls} instead of refusing; "
        f"the pre-fix behaviour was to run '{namespace} {would_have_run}'"
    )
    assert code == 2, f"expected exit code 2 for an unknown subcommand, got {code}"

    # Compare whole lines, not substrings: a substring assertion still passes
    # when the message is corrupted around the edges, which lets a broken
    # error message ship.
    lines = capsys.readouterr().out.splitlines()
    expected_commands = " | ".join(
        k for k in agentctl_main.DISPATCH[namespace] if k
    )
    assert lines == [
        f"Unknown command: {namespace} {typo}",
        f"Valid {namespace} commands: {expected_commands}",
        "Run: agentctl commands",
    ]
    # The message must name the real alternatives, otherwise the user is left
    # guessing exactly as they were with the silent fallback.
    assert would_have_run in expected_commands


def test_mistyped_mem_set_performs_no_write(monkeypatch):
    """The worst case of #126, pinned on its own.

    A typo must not reach the HTTP layer at all. Asserting on the return value
    is not enough - it cannot distinguish "refused" from "tried and failed", so
    this spies on the outbound POST helper itself.
    """
    import arena.agentctl_cli.agentctl_memory as agentctl_memory

    posted: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        agentctl_memory,
        "bridge_post",
        lambda path, body: posted.append((path, body)) or {"ok": True},
    )
    monkeypatch.setattr(sys, "argv", ["agentctl", "mem", "st", "secret-key", "secret-value"])

    with pytest.raises(SystemExit) as excinfo:
        agentctl_main.main()

    assert excinfo.value.code == 2
    assert posted == [], f"a mistyped subcommand issued a real write: {posted}"


# Namespace, subcommand, expected arguments forwarded to the handler.
VALID_INVOCATIONS = [
    ("mem", "set", ["K", "V"]),
    ("mem", "get", ["K"]),
    ("skill", "list", []),
    ("skill", "run", ["core/demo"]),
    ("task", "list", []),
]


@pytest.mark.parametrize(("namespace", "sub", "args"), VALID_INVOCATIONS)
def test_valid_subcommand_still_dispatches_with_its_arguments(
    monkeypatch, namespace, sub, args
):
    calls, code = _run(monkeypatch, [namespace, sub, *args])

    assert calls == [(namespace, sub, args)]
    assert code is None


@pytest.mark.parametrize("namespace", ["breaker", "bridge", "commands"])
def test_bare_namespace_keeps_its_documented_default(monkeypatch, namespace):
    """`agentctl breaker` (no subcommand) is a deliberate default, not a typo.

    Those namespaces register an explicit "" key. Removing the fallback must
    not break them.
    """
    calls, code = _run(monkeypatch, [namespace])

    assert len(calls) == 1, f"bare '{namespace}' should run exactly one command, got {calls}"
    assert calls[0][0] == namespace
    assert code is None


def test_bare_namespace_without_explicit_default_passes_no_junk_argument(monkeypatch):
    """A bare namespace must not forward an empty-string positional.

    The old code rebuilt `args` as `[sub] + args[1:]`, so `agentctl sys` handed
    `['']` to `sys status`.
    """
    calls, code = _run(monkeypatch, ["sys"])

    assert calls == [("sys", "status", [])], f"got {calls}"
    assert code is None


def test_namespace_whose_only_command_is_the_bare_default(monkeypatch, capsys):
    """A namespace registering only "" has no named commands to suggest.

    `commands` is such a namespace today. The listing must degrade to an
    explicit marker rather than printing an empty tail.
    """
    calls = _spy_dispatch(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["agentctl", "commands", "bogus"])

    with pytest.raises(SystemExit) as excinfo:
        agentctl_main.main()

    assert excinfo.value.code == 2
    assert calls == []
    assert capsys.readouterr().out.splitlines() == [
        "Unknown command: commands bogus",
        "Valid commands commands: (none)",
        "Run: agentctl commands",
    ]


def test_unknown_namespace_still_rejected(monkeypatch, capsys):
    calls, code = _run(monkeypatch, ["nosuchns", "whatever"])

    assert calls == []
    assert code == 2
    assert "Unknown namespace: nosuchns" in capsys.readouterr().out


def test_no_namespace_maps_a_typo_onto_a_real_command(monkeypatch):
    """Table-wide sweep: no namespace may absorb an unknown subcommand.

    The per-namespace cases above enumerate today's dispatch table; this one
    fails if a namespace is added later that reintroduces the fallback.
    """
    offenders = []
    for namespace, ns_map in agentctl_main.DISPATCH.items():
        if not isinstance(ns_map, dict) or not ns_map:
            continue
        calls, code = _run(monkeypatch, [namespace, "zzz-definitely-not-a-command"])
        if calls or code != 2:
            offenders.append((namespace, calls, code))

    assert offenders == [], f"namespaces still absorbing typos: {offenders}"

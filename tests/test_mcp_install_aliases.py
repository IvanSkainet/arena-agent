"""`agentctl mcp install` reported success for packages that do not exist.

Bug #69. `arena/agentctl_extras/integrations.py` came back from the sweep
with **152 of 152 mutants surviving** -- nothing executed it. Reading it
against the live npm registry found that all four built-in aliases were
dead names:

    @anthropic-ai/desktop-commander     404
    @modelcontextprotocol/filesystem    404
    @modelcontextprotocol/sqlite        404
    @modelcontextprotocol/fetch         404

The real servers carry a `server-` prefix, and desktop-commander is
published under a different scope entirely. `@anthropic-ai/...` is the
one that matters most: it named an **unclaimed** package in a scope this
project does not control, so the command sat one registration away from
installing a stranger's code.

The failure mode compounded it. The old order was: write the mcp.json
entry, then attempt the install, then `return 0` regardless. So a typo or
a dead name printed "[OK] Registered", printed a warning nobody scripts
against, exited successfully, and left the bridge trying to launch a
package that does not exist on every start. The consolation line -- "npx
will download the package on first run automatically" -- is true only
when the package exists; for a 404 it is a promise that cannot be kept.

Install first, register second, and fail loudly.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request

import pytest


def _fresh_modules(home: str):
    """Reimport with ARENA_AGENT_HOME pointed at a scratch directory."""
    os.environ["ARENA_AGENT_HOME"] = home
    import arena.agentctl_extras.common as common

    importlib.reload(common)
    import arena.agentctl_extras.integrations as integ

    importlib.reload(integ)
    return common, integ


@pytest.fixture
def sandbox(monkeypatch):
    home = tempfile.mkdtemp()
    previous = os.environ.get("ARENA_AGENT_HOME")
    common, integ = _fresh_modules(home)
    yield common, integ
    if previous is None:
        os.environ.pop("ARENA_AGENT_HOME", None)
    else:
        os.environ["ARENA_AGENT_HOME"] = previous
    _fresh_modules(previous or os.path.expanduser("~/arena-bridge"))


# --------------------------------------------------------------------
# The alias table must name packages that actually exist.
# --------------------------------------------------------------------

def test_no_alias_points_at_an_unclaimed_scope():
    """An unclaimed name in someone else's scope is a supply-chain hole.

    `@anthropic-ai/desktop-commander` did not exist. Anyone could have
    registered it and had this command install their code.
    """
    from arena.agentctl_extras.integrations import known_aliases

    for alias, pkg in known_aliases().items():
        assert pkg, alias
        assert not pkg.startswith("@anthropic-ai/"), (
            f"{alias} -> {pkg}: that scope is not published by this project "
            f"and the name was unclaimed"
        )


@pytest.mark.parametrize(
    ("alias", "pkg"),
    sorted(
        __import__(
            "arena.agentctl_extras.integrations", fromlist=["known_aliases"]
        ).known_aliases().items()
    ),
)
def test_every_alias_resolves_in_the_npm_registry(alias, pkg):
    """Network gate: a shipped alias must be installable.

    Skipped when the registry is unreachable -- an offline runner must not
    turn into a false accusation. It must also not turn into a false
    reassurance, so an HTTP error other than 404 is a skip, while a 404 is
    a failure.
    """
    quoted = urllib.parse.quote(pkg, safe="")
    url = f"https://registry.npmjs.org/{quoted}"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310
            assert resp.status == 200
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            pytest.fail(
                f"alias {alias!r} points at {pkg!r}, which is not published "
                f"(404). `agentctl mcp install {alias}` cannot work."
            )
        pytest.skip(f"registry returned {exc.code}; cannot verify offline")
    except OSError as exc:
        pytest.skip(f"npm registry unreachable: {exc}")


# --------------------------------------------------------------------
# A failed install must not leave a config entry behind.
# --------------------------------------------------------------------

def test_a_failed_install_returns_nonzero_and_writes_nothing(sandbox, monkeypatch):
    common, integ = sandbox
    monkeypatch.setattr(integ.shutil, "which", lambda name: "/usr/bin/npm")

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="npm error code E404\nnpm error 404 Not Found"
        )

    monkeypatch.setattr(integ.subprocess, "run", fake_run)
    rc = integ.cmd_mcp_install(["totally-made-up-package-name"])
    assert rc == 1
    assert not (common.ROOT / "mcp" / "mcp.json").exists(), (
        "a package that could not be installed was still registered"
    )


def test_a_failed_install_does_not_disturb_existing_entries(sandbox, monkeypatch):
    """The config belongs to the operator; a bad install must not touch it."""
    common, integ = sandbox
    cfg_path = common.ROOT / "mcp" / "mcp.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    original = {"mcpServers": {"existing": {"command": "npx", "args": ["-y", "ok"]}}}
    cfg_path.write_text(json.dumps(original), encoding="utf-8")

    monkeypatch.setattr(integ.shutil, "which", lambda name: "/usr/bin/npm")
    monkeypatch.setattr(
        integ.subprocess, "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "E404"),
    )
    assert integ.cmd_mcp_install(["nope"]) == 1
    assert json.loads(cfg_path.read_text(encoding="utf-8")) == original


def test_a_successful_install_registers_the_alias(sandbox, monkeypatch):
    """Reverse sabotage: the guard must not block the working path."""
    common, integ = sandbox
    monkeypatch.setattr(integ.shutil, "which", lambda name: "/usr/bin/npm")
    monkeypatch.setattr(
        integ.subprocess, "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "added 1 package", ""),
    )
    assert integ.cmd_mcp_install(["filesystem"]) == 0
    cfg = json.loads((common.ROOT / "mcp" / "mcp.json").read_text(encoding="utf-8"))
    entry = cfg["mcpServers"]["filesystem"]
    assert entry["args"] == ["-y", "@modelcontextprotocol/server-filesystem"]


def test_install_runs_before_the_config_is_written(sandbox, monkeypatch):
    """Ordering is the fix; assert it directly rather than by side effect."""
    common, integ = sandbox
    events: list[str] = []
    monkeypatch.setattr(integ.shutil, "which", lambda name: "/usr/bin/npm")

    def fake_run(argv, **kwargs):
        events.append("install")
        return subprocess.CompletedProcess(argv, 0, "", "")

    real_write = integ.json.dumps

    def spy_dumps(*a, **kw):
        events.append("write")
        return real_write(*a, **kw)

    monkeypatch.setattr(integ.subprocess, "run", fake_run)
    monkeypatch.setattr(integ.json, "dumps", spy_dumps)
    integ.cmd_mcp_install(["filesystem"])
    assert events and events[0] == "install", events


# --------------------------------------------------------------------
# npm/npx confusion.
# --------------------------------------------------------------------

def test_npx_without_npm_is_a_clean_refusal_not_a_traceback(sandbox, monkeypatch):
    """`if npm or npx:` then calling npm raised FileNotFoundError.

    Real setups hit this: corepack, bun-first images, trimmed containers.
    A CLI command must not exit by traceback.
    """
    common, integ = sandbox
    monkeypatch.setattr(
        integ.shutil, "which",
        lambda name: "/usr/bin/npx" if name == "npx" else None,
    )
    rc = integ.cmd_mcp_install(["filesystem"])
    assert rc == 3
    assert not (common.ROOT / "mcp" / "mcp.json").exists()


def test_an_oserror_from_npm_is_reported_not_raised(sandbox, monkeypatch):
    common, integ = sandbox
    monkeypatch.setattr(integ.shutil, "which", lambda name: "/usr/bin/npm")

    def boom(argv, **kwargs):
        raise OSError("exec format error")

    monkeypatch.setattr(integ.subprocess, "run", boom)
    assert integ.cmd_mcp_install(["filesystem"]) == 3


def test_a_hanging_npm_is_bounded(sandbox, monkeypatch):
    common, integ = sandbox
    monkeypatch.setattr(integ.shutil, "which", lambda name: "/usr/bin/npm")

    def timeout(argv, **kwargs):
        assert kwargs.get("timeout"), "npm must be called with a timeout"
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(integ.subprocess, "run", timeout)
    assert integ.cmd_mcp_install(["filesystem"]) == 4


def test_no_arguments_still_prints_usage(sandbox):
    _common, integ = sandbox
    assert integ.cmd_mcp_install([]) == 2


def test_the_false_npx_promise_is_gone():
    """"npx will download it on first run" is untrue for a 404."""
    from pathlib import Path

    text = Path(
        __import__(
            "arena.agentctl_extras.integrations", fromlist=["__file__"]
        ).__file__
    ).read_text(encoding="utf-8")
    assert "will download the package on first run" not in text, (
        "that line reassures the operator about a package that does not exist"
    )


def test_the_dead_package_names_are_gone():
    from pathlib import Path

    text = Path(
        __import__(
            "arena.agentctl_extras.integrations", fromlist=["__file__"]
        ).__file__
    ).read_text(encoding="utf-8")
    body = text[text.index("def cmd_mcp_install"):]
    for dead in ('"@modelcontextprotocol/filesystem"',
                 '"@modelcontextprotocol/sqlite"',
                 '"@modelcontextprotocol/fetch"'):
        assert dead not in body, f"{dead} is a 404 and is back in the table"

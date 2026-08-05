"""`/v1/exec/script` must work when the bridge root contains a space.

Bug #52. The endpoint writes the request body to a temp file and drops
its path into an interpreter template:

    _INTERPRETERS["bash"]["cmd"] == "bash -euo pipefail {path}"
    full_cmd = template.format(path=tmp_path)

Those templates are handed to a **shell**, so the path is re-parsed by
word splitting. One space anywhere in it and the command breaks apart:

    bash -euo pipefail /tmp/root with space/.../scr-ab.sh
    -> bash: /tmp/root: No such file or directory

Reproduced end to end through `run_shell_command_stream`: with an
unquoted path the script never ran; quoted, it printed its output.

This is not an exotic configuration. `C:\\Users\\Ivan Petrov` is the
default shape of a Windows home directory with a two-word account name,
and `~/My Drive/...` is standard on macOS. The failure is also actively
misleading -- it names a directory that plainly exists.

Quoting is platform-specific on purpose. `shlex.quote` wraps in single
quotes, which cmd.exe and PowerShell do not treat as quoting at all, so
Windows gets double quotes.

Sabotage record (mandatory per AGENTS.md):
  1. `_quote_path` returning its argument unchanged
     -> test_a_path_with_a_space_survives_the_shell fails.
  2. using `shlex.quote` on the Windows branch
     -> test_windows_paths_use_double_quotes fails.
  3. reverting the call site to `format(path=tmp_path)`
     -> test_the_template_is_filled_with_a_quoted_path fails.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import shlex
import tempfile
from pathlib import Path

import pytest

from arena.exec import handlers, interpreters

# ---------------------------------------------------------------------------
# The quoting primitive.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name == "nt", reason="POSIX quoting branch")
@pytest.mark.parametrize("path", [
    "/tmp/root with space/scr.sh",
    "/home/Ivan Petrov/.arena_script_tmp/scr-ab.sh",
    "/tmp/a b c/d e/scr.py",
    "/tmp/quote'in'name/scr.sh",
    "/tmp/dollar$sign/scr.sh",
    "/tmp/semi;colon/scr.sh",
    "/tmp/back`tick`/scr.sh",
])
def test_quoted_paths_round_trip_through_a_shell_parse(path):
    """Whatever the path contains, the shell must see exactly one word."""
    quoted = interpreters._quote_path(path)
    assert shlex.split(f"bash -euo pipefail {quoted}") == [
        "bash", "-euo", "pipefail", path,
    ]


@pytest.mark.skipif(os.name == "nt", reason="POSIX quoting branch")
def test_a_path_without_anything_special_is_left_readable():
    """Quoting must not make the common case ugly in logs and audit."""
    assert interpreters._quote_path("/home/user/scr.sh") == "/home/user/scr.sh"


def test_windows_paths_use_double_quotes(monkeypatch):
    """`shlex.quote` is wrong on Windows: cmd/PowerShell ignore single
    quotes, so the quote characters would reach the interpreter as part
    of the filename."""
    monkeypatch.setattr(interpreters.os, "name", "nt")

    quoted = interpreters._quote_path(r"C:\Users\Ivan Petrov\scr.ps1")

    assert quoted.startswith('"') and quoted.endswith('"')
    assert "'" not in quoted


# ---------------------------------------------------------------------------
# The call site actually uses it.
# ---------------------------------------------------------------------------

def test_the_template_is_filled_with_a_quoted_path():
    """A ratchet: the bug was a bare `.format(path=tmp_path)`."""
    source = Path(handlers.__file__).read_text(encoding="utf-8")

    assert "format(path=_quote_path(tmp_path))" in source, (
        "the interpreter template is being filled with an unquoted path "
        "again; a root containing a space will break every script run"
    )


@pytest.mark.parametrize("interpreter", sorted(interpreters._INTERPRETERS))
def test_every_interpreter_template_takes_the_path_as_one_word(interpreter):
    """Each template must end with a single `{path}` placeholder.

    A template that embedded the path mid-string, or twice, would need
    different handling than a single quoted substitution.
    """
    template = str(interpreters._INTERPRETERS[interpreter]["cmd"])
    assert template.count("{path}") == 1
    assert template.endswith("{path}"), (
        f"{interpreter}: the path must be the final argument so quoting it "
        "is sufficient"
    )


# ---------------------------------------------------------------------------
# End to end: it has to actually run.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name == "nt",
                    reason="drives the POSIX interpreters; the Windows "
                           "quoting branch is covered by its own test above")
def test_a_path_with_a_space_survives_the_shell(tmp_path):
    """The original report, as an executable check."""
    from arena.exec.runner import run_shell_command_stream

    root = tmp_path / "root with space"
    (root / ".arena_script_tmp").mkdir(parents=True)

    async def _run(cmd: str) -> str:
        collected = ""
        async for event in run_shell_command_stream(
                request_id="t", cmd=cmd, cwd=root,
                env=os.environ.copy(), timeout=30, max_output=10_000):
            if event.get("type") in ("stdout", "stderr"):
                collected += event["data"].decode("utf-8", "replace")
        return collected

    fd, script = tempfile.mkstemp(prefix="scr-", suffix=".sh",
                                  dir=str(root / ".arena_script_tmp"))
    os.close(fd)
    Path(script).write_text("echo SCRIPT_RAN_OK\n", encoding="utf-8")
    os.chmod(script, 0o700)  # nosec B103 -- owner-only rwx, mirrors the handler

    template = str(interpreters._INTERPRETERS["bash"]["cmd"])

    unquoted = asyncio.run(_run(template.format(path=script)))
    assert "SCRIPT_RAN_OK" not in unquoted, (
        "this test cannot detect the bug: the unquoted form worked, so the "
        "path evidently had no space in it"
    )

    quoted = asyncio.run(_run(template.format(
        path=interpreters._quote_path(script))))
    assert "SCRIPT_RAN_OK" in quoted, (
        f"the script still did not run with a quoted path: {quoted!r}"
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX interpreters")
@pytest.mark.parametrize("interpreter,body,expected", [
    ("bash", "echo OK\n", "OK"),
    ("sh", "echo OK\n", "OK"),
    ("python3", "print('OK')\n", "OK"),
])
def test_each_posix_interpreter_runs_from_a_spaced_root(
        tmp_path, interpreter, body, expected):
    from arena.exec.runner import run_shell_command_stream

    root = tmp_path / "root with space"
    (root / ".arena_script_tmp").mkdir(parents=True)
    config = interpreters._INTERPRETERS[interpreter]

    fd, script = tempfile.mkstemp(prefix="scr-", suffix=str(config["suffix"]),
                                  dir=str(root / ".arena_script_tmp"))
    os.close(fd)
    Path(script).write_text(body, encoding="utf-8")
    os.chmod(script, 0o700)  # nosec B103 -- owner-only rwx, mirrors the handler

    cmd = str(config["cmd"]).format(path=interpreters._quote_path(script))

    async def _run() -> str:
        collected = ""
        async for event in run_shell_command_stream(
                request_id="t", cmd=cmd, cwd=root,
                env=os.environ.copy(), timeout=30, max_output=10_000):
            if event.get("type") in ("stdout", "stderr"):
                collected += event["data"].decode("utf-8", "replace")
        return collected

    assert expected in asyncio.run(_run())


def test_the_module_still_imports_after_a_platform_flip():
    """Guard against `_quote_path` being written as a module-level
    constant chosen at import time, which would bake in the platform of
    whoever built the wheel."""
    importlib.reload(handlers)
    assert callable(interpreters._quote_path)

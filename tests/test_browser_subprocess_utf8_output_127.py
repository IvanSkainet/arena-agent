"""`browser.*` tools must survive non-Latin-1 characters in their output.

Regression guard for #127.

`bin/py_browser.py` prints its JSON with `ensure_ascii=False`, and the MCP
tools capture it through `run_local`. Neither end pinned an encoding, so on
Windows the child inherited the console codepage (cp1251 on a Russian
install) and a single emoji in a DuckDuckGo snippet raised:

    'charmap' codec can't encode character '\\U0001f4fa' ... maps to <undefined>

Because TextIOWrapper encodes the whole buffered write before emitting any
bytes, **nothing** reached stdout - the caller got no partial JSON, only the
error. That killed `browser.search` for exactly the queries that need it
(movie/streaming results), and `browser.read` for any page whose title or
body contains an emoji.

These tests run real subprocesses with the codepage forced, because the bug
is invisible on the UTF-8 Linux runner where the suite normally executes -
which is precisely why it shipped. They do not touch the network.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp.tool_utils import make_run_local, utf8_child_env  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
PY_BROWSER = REPO_ROOT / "bin" / "py_browser.py"

TV = "\U0001f4fa"  # the exact character from the bug report
PAYLOAD = {"query": "атака титанов смотреть", "results": [{"snippet": f"сериал {TV} онлайн"}]}

# A stand-in for py_browser's print path: same ensure_ascii=False JSON dump,
# same reconfigure guard, no network and no third-party imports.
CHILD = textwrap.dedent(
    '''
    import json, sys

    def _force_utf8_stdio():
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                try:
                    reconfigure(encoding="utf-8", errors="replace")
                except (AttributeError, OSError, ValueError):
                    pass

    if "--reconfigure" in sys.argv:
        _force_utf8_stdio()
    print(json.dumps(PAYLOAD_JSON, ensure_ascii=False))
    '''
)


@pytest.fixture
def child_script(tmp_path):
    path = tmp_path / "emit.py"
    # `repr`, not `json.dumps(..., ensure_ascii=True)`: the latter escapes an
    # astral character as a UTF-16 surrogate pair (\ud83d\udcfa), which Python
    # source then reads back as two lone surrogates that encode to "??" under
    # errors="replace" - a test artefact that looks exactly like the bug.
    path.write_text(CHILD.replace("PAYLOAD_JSON", repr(PAYLOAD)), encoding="utf-8")
    return path


def _cp1251_env() -> dict[str, str]:
    """Emulate a Windows console codepage on any host."""
    env = {**os.environ, "PYTHONIOENCODING": "cp1251"}
    env.pop("PYTHONUTF8", None)
    return env


def test_the_bug_reproduces_without_the_fix(child_script):
    """Pin the failure mode itself, so the guard below cannot pass vacuously.

    Captured as raw bytes: with the codepage forced and neither end fixed, the
    child dies and stdout is empty - not truncated, empty.
    """
    proc = subprocess.run(
        [sys.executable, str(child_script)],
        capture_output=True,
        env=_cp1251_env(),
        timeout=60,
        check=False,
    )

    assert proc.returncode != 0
    assert proc.stdout == b"", "the failure is total, not partial - nothing should be emitted"
    assert "codec can't encode character" in proc.stderr.decode("utf-8", "replace")


def test_child_reconfigure_survives_a_hostile_codepage(child_script):
    """`py_browser.py` must be usable straight from a cp1251 console."""
    proc = subprocess.run(
        [sys.executable, str(child_script), "--reconfigure"],
        capture_output=True,
        env=_cp1251_env(),
        timeout=60,
        check=False,
    )

    assert proc.returncode == 0
    decoded = json.loads(proc.stdout.decode("utf-8"))
    assert decoded == PAYLOAD, "the emoji and the Cyrillic text must both round-trip"


def test_parent_env_rescues_a_child_that_does_not_reconfigure(child_script, monkeypatch):
    """The caller-side half of the fix must stand on its own.

    The hostile codepage is injected into *this* process's environment, which
    the child inherits, so the test fails unless run_local overrides it. On a
    UTF-8 host the child would otherwise succeed by accident - which is how
    the original bug reached production despite a green suite.
    """
    monkeypatch.setenv("PYTHONIOENCODING", "cp1251")
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    run_local = make_run_local(lambda: {})

    rc, out, err = run_local([sys.executable, str(child_script)], timeout=60)

    assert rc == 0, f"child failed: {err}"
    assert json.loads(out) == PAYLOAD


def test_run_local_decodes_as_utf8_not_the_platform_default(child_script, monkeypatch):
    """Pin the decode side: the child emits UTF-8 whatever the parent's locale.

    `errors="replace"` on the read side is not enough on its own - without
    `encoding="utf-8"` the parent decodes with the host default and mangles
    every multi-byte character.
    """
    monkeypatch.setenv("PYTHONIOENCODING", "cp1251")
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    run_local = make_run_local(lambda: {})

    rc, out, _ = run_local([sys.executable, str(child_script), "--reconfigure"], timeout=60)

    assert rc == 0
    assert TV in out
    assert "сериал" in out
    assert "?" not in out, "a mangled decode silently degrades the payload"


def test_run_local_pins_the_decoder_instead_of_trusting_the_locale(child_script, tmp_path):
    """`encoding="utf-8"` on the read side must be explicit, not inherited.

    Without it `subprocess` decodes with `locale.getencoding()`. That is
    invisible here - CPython enables UTF-8 mode in this container, so the
    default happens to be right - so the check runs in a nested interpreter
    with UTF-8 mode *off* and the C locale, where a locale decode raises
    UnicodeDecodeError on the very first emoji byte.
    """
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import locale, sys\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        'locale.setlocale(locale.LC_ALL, "C")\n'
        "from arena.mcp.tool_utils import make_run_local\n"
        "run_local = make_run_local(lambda: {})\n"
        "rc, out, err = run_local(\n"
        f"    [sys.executable, {str(child_script)!r}, '--reconfigure'], timeout=60\n"
        ")\n"
        "assert rc == 0, err\n"
        f"assert {TV!r} in out, ascii(out)\n"
        'print("OK")\n',
        encoding="utf-8",
    )

    env = {**os.environ, "PYTHONUTF8": "0", "LC_ALL": "C", "LANG": "C"}
    proc = subprocess.run(
        [sys.executable, str(probe)],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
    )

    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


def test_standalone_run_local_gets_the_same_treatment(child_script, monkeypatch):
    """The second `run_local` must not drift from the first.

    `arena/mcp/standalone_common.py` carries its own copy for the standalone
    server. A fix applied to only one of them leaves half the tool surface
    broken, which is indistinguishable from no fix at all for whichever
    entrypoint the user happens to hit.
    """
    from arena.mcp import standalone_common

    monkeypatch.setenv("PYTHONIOENCODING", "cp1251")
    monkeypatch.delenv("PYTHONUTF8", raising=False)

    rc, out, err = standalone_common.run_local([sys.executable, str(child_script)], timeout=60)

    assert rc == 0, f"child failed: {err}"
    assert json.loads(out) == PAYLOAD


def test_undecodable_bytes_degrade_one_character_not_the_payload(tmp_path, monkeypatch):
    """`errors="replace"` is load-bearing, not decoration.

    A page can hand back bytes that are not valid UTF-8 at all. Strict
    decoding would raise inside `subprocess.communicate` and lose the whole
    response - the exact failure mode #127 is about, just moved to the read
    side. One U+FFFD is an acceptable price; an exception is not.
    """
    emitter = tmp_path / "bad_bytes.py"
    emitter.write_text(
        "import sys\n"
        'sys.stdout.buffer.write("ok ".encode())\n'
        "sys.stdout.buffer.write(b'\\xff\\xfe')\n"
        'sys.stdout.buffer.write(" tail".encode())\n',
        encoding="utf-8",
    )
    run_local = make_run_local(lambda: {})

    rc, out, _ = run_local([sys.executable, str(emitter)], timeout=60)

    assert rc == 0
    assert out.startswith("ok ")
    assert out.rstrip().endswith("tail"), "text after the bad bytes must survive"
    assert "\ufffd" in out


def test_utf8_child_env_sets_both_switches():
    env = utf8_child_env()

    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUTF8"] == "1"
    # Must extend the real environment, not replace it: the child needs PATH.
    assert "PATH" in env or "SystemRoot" in env


def test_run_local_still_forwards_subprocess_kwargs(child_script, monkeypatch):
    """The env addition must not displace caller-supplied kwargs.

    `_subprocess_kwargs()` supplies `creationflags` on Windows to suppress
    console windows; losing it would make every tool call flash a window.
    """
    seen: list[dict] = []

    monkeypatch.setenv("PYTHONIOENCODING", "cp1251")
    monkeypatch.delenv("PYTHONUTF8", raising=False)

    def kwargs():
        seen.append({})
        return {"cwd": str(child_script.parent)}

    run_local = make_run_local(kwargs)
    rc, out, _ = run_local([sys.executable, str(child_script), "--reconfigure"], timeout=60)

    assert seen, "subprocess_kwargs was never consulted"
    assert rc == 0
    assert json.loads(out) == PAYLOAD


def test_caller_kwargs_win_over_the_default_env(child_script):
    """A caller passing its own env must not be silently overridden."""
    marker = "ARENA_TEST_MARKER_127"
    custom = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", marker: "1"}

    run_local = make_run_local(lambda: {"env": custom})
    probe = child_script.parent / "probe.py"
    probe.write_text(
        f'import os, sys; sys.stdout.write(os.environ.get("{marker}", "absent"))',
        encoding="utf-8",
    )

    _, out, _ = run_local([sys.executable, str(probe)], timeout=60)

    assert out.strip() == "1"


@pytest.mark.skipif(not PY_BROWSER.exists(), reason="py_browser.py not present")
def test_py_browser_module_reconfigures_before_parsing_arguments():
    """The guard must run for every command, not just search.

    `cmd_head`, `cmd_read` and `cmd_dump` print with the same
    `ensure_ascii=False`, so the call belongs at the top of main(), ahead of
    argument parsing - a per-command fix would leave three commands broken.
    """
    source = PY_BROWSER.read_text(encoding="utf-8")

    assert "_force_utf8_stdio" in source
    body = source[source.index("def main()"):]
    call = body.index("_force_utf8_stdio()")
    parse = body.index("argparse.ArgumentParser")
    assert call < parse, "stdio must be reconfigured before any output can occur"


@pytest.mark.skipif(not PY_BROWSER.exists(), reason="py_browser.py not present")
def test_py_browser_help_runs_under_a_hostile_codepage():
    """End-to-end smoke on the real script, still without network access."""
    proc = subprocess.run(
        [sys.executable, str(PY_BROWSER), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=_cp1251_env(),
        timeout=60,
        check=False,
    )

    assert proc.returncode == 0
    assert "py_browser" in proc.stdout

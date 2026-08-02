"""The standalone MCP dispatcher must refuse paths outside $HOME.

Background worth keeping, because it is the whole lesson:

`arena/mcp/standalone_tools.py` backs the standalone HTTP and WebSocket MCP
servers. Unlike the main bridge, it never routes through
`arena/mcp/tool_fs.py`, so it never inherited that module's path jail. Until
v4.155.0 `fs.read` / `fs.write` / `fs.list` here took a caller-supplied path,
ran `os.path.expanduser` on it, and opened it. Reading `/etc/hostname` was a
one-liner; `~/../../etc/hostname` worked too.

The bug was years old and no gate caught it. CodeQL only raised
py/path-injection once the E701 cleanup moved `open()` off the shared inline
line and the dataflow became visible to the scanner. A scanner's silence had
never been evidence of safety -- it was evidence of a line it could not read.

These tests execute the dispatcher rather than inspecting it, because the
previous "proof" that this code was fine was exactly that nobody had run it
against a hostile path.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp import standalone_tools as st  # noqa: E402


def _text(res: dict) -> str:
    return res["content"][0]["text"]


def _fake_home(monkeypatch, home: Path) -> None:
    """Point BOTH Path.home() and os.path.expanduser("~") at `home`.

    Patching HOME alone is not portable: on Windows ntpath.expanduser reads
    USERPROFILE first and ignores HOME entirely (see CPython's ntpath source),
    so _jail()'s expanduser and the patched Path.home() would disagree and a
    legitimate ~ path would be refused. That desync turned all five
    windows-latest jobs red while Linux and macOS stayed green.
    """
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)


def _is_refusal(res: dict) -> bool:
    return bool(res.get("isError")) and "PathJailError" in _text(res)


# ---------------------------------------------------------------------------
# Escapes must be refused
# ---------------------------------------------------------------------------

# Paths that must be refused regardless of whether they exist on this host --
# the jail decides on location, not on existence. Kept portable: Windows has no
# /etc, and asserting on POSIX system paths is what turned macOS/Windows red.
ESCAPES = [
    "/etc/hostname",
    "/etc/passwd",
    "~/../../etc/hostname",
    "~/../../../etc/passwd",
    "/",
    os.path.abspath(os.sep),
]


@pytest.mark.parametrize("tool", ["fs.read", "fs.write", "fs.list"])
@pytest.mark.parametrize("path", ESCAPES)
def test_paths_outside_home_are_refused(tool, path):
    args = {"path": path}
    if tool == "fs.write":
        args["content"] = "x"
    res = st.call_tool(tool, args)
    assert _is_refusal(res), f"{tool} accepted {path!r}: {_text(res)[:120]}"


def test_a_real_file_outside_home_is_not_read(tmp_path, monkeypatch):
    """Not just 'an error' -- the file's contents must never appear.

    Uses a file this test creates outside a fake home rather than a
    system path. The first version asserted on /etc/hostname, which does not
    exist on macOS or Windows and turned every non-Linux CI job red: the same
    host-specific coupling this repo keeps paying for. The invariant is
    "outside home is unreadable", and that is expressible portably.
    """
    home = tmp_path / "home"
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    secret_file = outside / "secret.txt"
    secret_file.write_text("TOP-SECRET-CONTENTS", encoding="utf-8")

    _fake_home(monkeypatch, home)

    res = st.call_tool("fs.read", {"path": str(secret_file)})
    assert _is_refusal(res), _text(res)[:120]
    assert "TOP-SECRET-CONTENTS" not in _text(res)


def test_write_outside_home_creates_nothing(tmp_path, monkeypatch):
    """A refusal that still creates the file is not a refusal."""
    home = tmp_path / "home"
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _fake_home(monkeypatch, home)

    target = outside / "should_not_exist.txt"
    res = st.call_tool("fs.write", {"path": str(target), "content": "pwned"})
    assert _is_refusal(res), _text(res)[:120]
    assert not target.exists(), "jail refused but the file was created anyway"


@pytest.mark.parametrize("name", ["id_rsa", ".env", ".netrc", ".git-credentials"])
def test_sensitive_basenames_are_refused_even_inside_home(name, tmp_path, monkeypatch):
    """The file must EXIST, or a refusal proves nothing.

    The first version of this test used a path that did not exist, so
    FileNotFoundError satisfied "isError" and the assertion passed for the
    wrong reason -- on a host where the file did exist it would have read it.
    Create the file inside a fake home, then demand the basename rule fires.
    """
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    target = home / ".ssh" / name
    target.write_text("SUPER-SECRET-VALUE", encoding="utf-8")
    _fake_home(monkeypatch, home)

    res = st.call_tool("fs.read", {"path": str(target)})
    assert res.get("isError"), f"{name} was readable: {_text(res)[:80]}"
    assert "not allowed" in _text(res), _text(res)
    assert "SUPER-SECRET-VALUE" not in _text(res)


def test_symlink_out_of_home_cannot_escape(tmp_path, monkeypatch):
    """resolve() must happen before the check, or a symlink walks right out."""
    home = tmp_path / "home"
    home.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "loot.txt").write_text("classified", encoding="utf-8")
    link = home / "shortcut"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this host")

    _fake_home(monkeypatch, home)
    res = st.call_tool("fs.read", {"path": str(link / "loot.txt")})
    assert _is_refusal(res)
    assert "classified" not in _text(res)


# ---------------------------------------------------------------------------
# Legitimate use must still work
# ---------------------------------------------------------------------------

def test_reading_and_writing_inside_home_still_works(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    _fake_home(monkeypatch, home)

    target = home / "notes.txt"
    w = st.call_tool("fs.write", {"path": str(target), "content": "hello"})
    assert not w.get("isError"), _text(w)
    assert target.read_text(encoding="utf-8") == "hello"

    r = st.call_tool("fs.read", {"path": str(target)})
    assert not r.get("isError"), _text(r)
    assert _text(r) == "hello"

    ls = st.call_tool("fs.list", {"path": str(home)})
    assert not ls.get("isError"), _text(ls)
    assert "notes.txt" in _text(ls)


def test_tilde_expansion_still_works(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "f.txt").write_text("via tilde", encoding="utf-8")
    _fake_home(monkeypatch, home)
    res = st.call_tool("fs.read", {"path": "~/f.txt"})
    assert not res.get("isError"), _text(res)
    assert _text(res) == "via tilde"


def test_empty_path_is_refused_not_crashed():
    res = st.call_tool("fs.read", {"path": ""})
    assert res.get("isError")
    assert "missing" in _text(res)


# ---------------------------------------------------------------------------
# The jail must stay wired in
# ---------------------------------------------------------------------------

def test_every_fs_tool_routes_through_the_jail():
    """A new fs.* branch added later must not bypass _jail()."""
    src = Path(st.__file__).read_text(encoding="utf-8")
    body = src.split("def call_tool", 1)[1]
    for tool in ("fs.read", "fs.write", "fs.list"):
        marker = f'if name == "{tool}":'
        assert marker in body, f"{tool} branch vanished"
        branch = body.split(marker, 1)[1].split('if name ==', 1)[0]
        assert "_jail(" in branch, f"{tool} no longer routes through _jail()"
        assert "os.path.expanduser(args" not in branch, (
            f"{tool} went back to raw expanduser -- that is the original bug"
        )

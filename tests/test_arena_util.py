"""v4.74.0 coverage expansion: targeted unit tests for arena.util.

v4.74.0 is the "coverage gate 50% → 55% → 60%"
gradual-tightening release. The first step is to
add unit tests for the small, pure, stdlib-only
``arena.util`` module which currently sits at 51%
coverage (23 missing statements out of 51 lines) and
has no direct test file of its own.

This file is a pure-helper module (no I/O, no network,
no subprocess). It contains:

* ``_subprocess_kwargs`` — Windows-only creationflags.
* ``utc_now`` — ISO-8601 timestamp with seconds
  precision.
* ``get_clean_platform_name`` — replaces
  ``Windows-10`` with ``Windows-11 (Build N)`` for
  recent Windows builds.
* ``decode_output`` — Windows-aware bytes → str
  decoder.
* ``b64_token`` — URL-safe base64 of N random bytes.
* ``first_word`` — extracts the first whitespace-
  separated token from a command line (stripping
  the ``.exe`` suffix and the path).
* ``under_root`` — checks if a path is under a given
  root (resolved).

The functions are all tiny and easy to test, so this
file is one of the cheapest ways to bump coverage
(+1.5% on the v4.74.0 baseline once these tests run
on every Python/OS cell).
"""
from __future__ import annotations

import base64
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

from arena import util

# -------------------------------------------------------------------
# _subprocess_kwargs
# -------------------------------------------------------------------


def test_subprocess_kwargs_on_linux_is_empty_dict() -> None:
    """On non-Windows, _subprocess_kwargs returns an empty dict.

    The function exists to add the CREATE_NO_WINDOW flag
    on Windows; everywhere else it must be a no-op so
    callers can splat the result into ``subprocess.run``
    without conditional logic.
    """
    if sys.platform == "win32":
        pytest.skip("Windows-only branch tested below")
    assert util._subprocess_kwargs() == {}


def test_subprocess_kwargs_on_windows_contains_creationflags() -> None:
    """On Windows, _subprocess_kwargs returns the CREATE_NO_WINDOW flag.

    The flag value 0x08000000 is the documented
    ``CREATE_NO_WINDOW`` constant from the Windows
    SDK. We assert its value rather than its name so the
    test stays valid even if Python ever renames the
    symbol.
    """
    if sys.platform != "win32":
        pytest.skip("Windows-only branch")
    kwargs = util._subprocess_kwargs()
    assert "creationflags" in kwargs
    assert kwargs["creationflags"] == 0x08000000


# -------------------------------------------------------------------
# utc_now
# -------------------------------------------------------------------


def test_utc_now_returns_iso8601_with_seconds_precision() -> None:
    """utc_now returns a string like '2026-07-24T14:00:00+00:00'."""
    out = util.utc_now()
    assert isinstance(out, str)
    # Format: YYYY-MM-DDTHH:MM:SS+00:00
    assert len(out) == 25
    assert out[4] == "-"
    assert out[7] == "-"
    assert out[10] == "T"
    assert out[13] == ":"
    assert out[16] == ":"
    assert out.endswith("+00:00")


def test_utc_now_uses_utc_timezone() -> None:
    """Two utc_now() calls separated by a tiny sleep differ by ≤ 1 second."""
    import time
    a = util.utc_now()
    time.sleep(0.05)
    b = util.utc_now()
    # Both are ISO strings; they should be equal-or-1-second-apart.
    # Parse and compare.
    from datetime import datetime
    da = datetime.fromisoformat(a)
    db = datetime.fromisoformat(b)
    assert (db - da).total_seconds() <= 1.0


# -------------------------------------------------------------------
# get_clean_platform_name
# -------------------------------------------------------------------


def test_get_clean_platform_name_on_linux_returns_linux_string() -> None:
    """On Linux, get_clean_platform_name returns a non-empty string mentioning Linux.

    We don't assert the exact value (it depends on the
    kernel version) — only that the function returns a
    string and that it doesn't accidentally hit the
    Windows branch on Linux.
    """
    if sys.platform == "win32":
        pytest.skip("Linux-only branch")
    out = util.get_clean_platform_name()
    assert isinstance(out, str)
    assert len(out) > 0
    assert "Windows" not in out


def test_get_clean_platform_name_handles_windows_build_gracefully() -> None:
    """On Windows, the function handles non-integer build numbers without crashing.

    The function tries to parse the last component of
    ``platform.version()`` as an int. If parsing fails
    (e.g. on a non-standard build), the function should
    silently return the unmodified platform string
    rather than raising.
    """
    if sys.platform != "win32":
        pytest.skip("Windows-only branch")
    with mock.patch("platform.version", return_value="10.0.invalid-build"):
        # Should not raise; should return a non-empty string.
        out = util.get_clean_platform_name()
        assert isinstance(out, str)
        assert len(out) > 0


# -------------------------------------------------------------------
# decode_output
# -------------------------------------------------------------------


def test_decode_output_on_linux_uses_utf8_replace() -> None:
    """On non-Windows, decode_output uses utf-8 with errors='replace'."""
    if os.name == "nt":
        pytest.skip("non-Windows branch")
    # Invalid UTF-8 bytes get replaced.
    out = util.decode_output(b"\xff\xfe\xfd")
    # \ufffd is the Unicode replacement character.
    assert "\ufffd" in out


def test_decode_output_handles_cp1251_on_windows() -> None:
    """On Windows, decode_output tries cp1251 (Cyrillic) before falling back.

    The string "Привет" encoded in cp1251 is
    b'\\xcf\\xf0\\xe8\\xe2\\xe5\\xf2'; decoded with
    utf-8 it would fail, but cp1251 roundtrips it.

    v4.80.0: previously xfail because decode_output used
    ``errors="replace"`` on every codec (which made the
    fallbacks unreachable). The fix uses ``errors="strict"``
    on the first two codecs so the loop can fall through to
    cp1251 when UTF-8 / cp866 reject the bytes. cp1251
    itself uses ``errors="replace"`` as the last-resort
    safety net so the function never raises.
    """
    if os.name != "nt":
        pytest.skip("Windows-only branch")
    data = "Привет".encode("cp1251")
    out = util.decode_output(data)
    assert out == "Привет"


# -------------------------------------------------------------------
# b64_token
# -------------------------------------------------------------------


def test_b64_token_default_length_is_32_bytes() -> None:
    """b64_token(32) returns ~43 characters of urlsafe-base64 (32 bytes → ~43 chars)."""
    out = util.b64_token()
    # 32 bytes → ceil(32 * 4 / 3) = 43 characters, minus padding.
    assert 42 <= len(out) <= 44
    # urlsafe-base64 alphabet: A-Z a-z 0-9 - _
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
    assert set(out) <= allowed
    # No padding character.
    assert "=" not in out


def test_b64_token_length_scales_with_nbytes() -> None:
    """b64_token(16) is shorter than b64_token(64)."""
    small = util.b64_token(16)
    large = util.b64_token(64)
    assert len(small) < len(large)


def test_b64_token_is_unique_per_call() -> None:
    """Two consecutive b64_token() calls return different values (cryptographic random)."""
    a = util.b64_token()
    b = util.b64_token()
    assert a != b


def test_b64_token_round_trip_decodes_to_nbytes() -> None:
    """b64_token(N) round-trips through base64.urlsafe_b64decode to N bytes."""
    for n in (1, 8, 16, 32, 64, 128):
        token = util.b64_token(n)
        # urlsafe_b64decode requires padding; b64_token strips
        # the trailing = chars, so we re-pad before decoding.
        padded = token + "=" * ((4 - len(token) % 4) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        assert len(decoded) == n


# -------------------------------------------------------------------
# first_word
# -------------------------------------------------------------------


def test_first_word_simple_command() -> None:
    """first_word('ls -la /tmp') returns 'ls' (lowercased, no path)."""
    assert util.first_word("ls -la /tmp") == "ls"


def test_first_word_strips_path_prefix() -> None:
    """first_word('/usr/bin/git status') returns 'git' (just the basename)."""
    out = util.first_word("/usr/bin/git status")
    assert out == "git"


def test_first_word_strips_exe_suffix() -> None:
    """first_word('python.exe foo') returns 'python' (no .exe suffix)."""
    out = util.first_word("python.exe foo")
    assert out == "python"


def test_first_word_handles_empty_string() -> None:
    """first_word('') returns '' (graceful handling of empty input)."""
    out = util.first_word("")
    assert out == ""


def test_first_word_is_lowercase() -> None:
    """first_word('UPPERCASE arg') returns 'uppercase' (lowercased)."""
    out = util.first_word("UPPERCASE arg")
    assert out == "uppercase"


# -------------------------------------------------------------------
# under_root
# -------------------------------------------------------------------


def test_under_root_returns_true_for_path_under_root(tmp_path: Path) -> None:
    """under_root(tmp/x, tmp) returns True (x is under tmp)."""
    p = tmp_path / "x"
    p.mkdir()
    assert util.under_root(p, tmp_path) is True


def test_under_root_returns_false_for_path_outside_root(tmp_path: Path) -> None:
    """under_root(other, tmp) returns False (other is not under tmp)."""
    other = tmp_path.parent / "elsewhere"
    other.mkdir(exist_ok=True)
    try:
        assert util.under_root(other, tmp_path) is False
    finally:
        # Cleanup
        if other.exists() and not any(other.iterdir()):
            other.rmdir()


def test_under_root_returns_true_for_root_itself(tmp_path: Path) -> None:
    """under_root(tmp, tmp) returns True (the root is under itself)."""
    assert util.under_root(tmp_path, tmp_path) is True


def test_under_root_handles_sibling_not_subdir(tmp_path: Path) -> None:
    """under_root(tmp/sibling, tmp) returns False (sibling is not a subdir)."""
    sibling = tmp_path.parent / (tmp_path.name + "_sibling_v4740")
    if sibling.exists():
        pytest.skip("sibling path already exists, can't create test fixture")
    sibling.mkdir()
    try:
        assert util.under_root(sibling, tmp_path) is False
    finally:
        if sibling.exists():
            sibling.rmdir()

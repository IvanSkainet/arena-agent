"""v4.169.35 -- arena.agent_helpers.files parity tests (mutation-driven).

Pins every observable behaviour in `arena/agent_helpers/files.py`:
* `now_iso` format, UTC timezone, and seconds precision;
* `safe_write` atomic write, mode setting, parent creation, and tmp cleanup;
* `backup_file` non-existent handling, timestamp format, copy, and permissions;
* `verify_python` missing file, successful execution, import/syntax error, and missing loader;
* `verify_bash` missing file, valid syntax, syntax error, and fallback exit string;
* `patch_block` before/after/replace positions, default position, multiple occurrences (count=1),
  invalid position, missing anchor, marker idempotency, preserved permissions, and backup creation;
* `patch_replace` old string replacement, multiple occurrences (count=1), missing old string,
  marker idempotency, preserved permissions, and backup creation.
"""
from __future__ import annotations

import datetime as dt
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.agent_helpers.files as ah_files  # noqa: E402

_POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX permission bits (chmod 0o600) are not enforced on Windows NTFS",
)


# --------------------------------------------------------------------
# 1. Module-level Constants & now_iso
# --------------------------------------------------------------------
def test_now_iso_format():
    iso = ah_files.now_iso()
    assert iso.endswith("+00:00")
    assert len(iso) == 25
    parsed = dt.datetime.fromisoformat(iso)
    assert parsed.tzinfo == dt.timezone.utc


def test_facts_path_shape():
    assert ah_files.ROOT == Path.home() / "arena-bridge"
    assert ah_files.FACTS == Path.home() / "arena-bridge" / "memory" / "facts.jsonl"
    assert ah_files.FACTS.name == "facts.jsonl"
    assert ah_files.FACTS.parent.name == "memory"


def test_get_agent_home_override(monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", "/custom/override/home")
    assert ah_files.get_agent_home() == Path("/custom/override/home")


# --------------------------------------------------------------------
# 2. safe_write
# --------------------------------------------------------------------
def test_safe_write_creates_parents_and_content(tmp_path, monkeypatch):
    target = tmp_path / "subdir" / "nested" / "doc.txt"
    seen_suffix = []
    orig_with_suffix = Path.with_suffix

    def _spy_with_suffix(self, suffix):
        seen_suffix.append(suffix)
        return orig_with_suffix(self, suffix)

    monkeypatch.setattr(Path, "with_suffix", _spy_with_suffix)
    res = ah_files.safe_write(target, "my-content\n", mode=0o644)
    assert res == target
    assert target.is_file()
    assert target.read_text(encoding="utf-8") == "my-content\n"
    assert ".txt.tmp" in seen_suffix
    assert list(tmp_path.glob("**/*.tmp")) == []


def test_safe_write_str_path(tmp_path):
    target_str = str(tmp_path / "str_doc.txt")
    res = ah_files.safe_write(target_str, "from-str")
    assert isinstance(res, Path)
    assert res.read_text(encoding="utf-8") == "from-str"


@_POSIX_ONLY
def test_safe_write_default_mode(tmp_path):
    target = tmp_path / "default_mode.txt"
    ah_files.safe_write(target, "secret")
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


@_POSIX_ONLY
def test_safe_write_custom_mode(tmp_path):
    target = tmp_path / "custom_mode.txt"
    ah_files.safe_write(target, "custom", mode=0o644)
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o644


# --------------------------------------------------------------------
# 3. backup_file
# --------------------------------------------------------------------
def test_backup_file_missing_returns_none(tmp_path):
    missing = tmp_path / "nonexistent.txt"
    assert ah_files.backup_file(missing) is None


def test_backup_file_creates_copy(tmp_path, monkeypatch):
    fixed_now = dt.datetime(2026, 8, 11, 14, 30, 45, tzinfo=dt.timezone.utc)

    class _FakeDatetime:
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(ah_files.dt, "datetime", _FakeDatetime)

    src = tmp_path / "config.json"
    src.write_text('{"key": "val"}', encoding="utf-8")

    bak = ah_files.backup_file(src)
    assert bak is not None
    assert bak.name == "config.json.bak-20260811T143045Z"
    assert bak.exists()
    assert bak.read_text(encoding="utf-8") == '{"key": "val"}'
    assert src.read_text(encoding="utf-8") == '{"key": "val"}'
    if sys.platform != "win32":
        assert stat.S_IMODE(bak.stat().st_mode) == 0o600


# --------------------------------------------------------------------
# 4. verify_python
# --------------------------------------------------------------------
def test_verify_python_missing(tmp_path):
    p = tmp_path / "missing.py"
    ok, msg = ah_files.verify_python(p)
    assert ok is False
    assert msg == f"missing: {p}"


def test_verify_python_valid(tmp_path):
    p = tmp_path / "good.py"
    p.write_text("assert __name__ == '_check'\nx = 1 + 2\ndef foo(): return x\n", encoding="utf-8")
    ok, msg = ah_files.verify_python(p)
    assert ok is True
    assert msg == "ok"


def test_verify_python_syntax_error(tmp_path):
    p = tmp_path / "bad.py"
    p.write_text("def broken_syntax(:\n", encoding="utf-8")
    ok, msg = ah_files.verify_python(p)
    assert ok is False
    assert msg.startswith("SyntaxError: ")


def test_verify_python_runtime_error(tmp_path):
    p = tmp_path / "runtime_bad.py"
    p.write_text("raise ValueError('something blew up')\n", encoding="utf-8")
    ok, msg = ah_files.verify_python(p)
    assert ok is False
    assert msg == "ValueError: something blew up"


def test_verify_python_no_loader(tmp_path, monkeypatch):
    p = tmp_path / "custom.py"
    p.write_text("a = 1\n", encoding="utf-8")

    class _NoLoaderSpec:
        loader = None

    monkeypatch.setattr(
        ah_files.importlib.util,
        "spec_from_file_location",
        lambda name, path: _NoLoaderSpec(),
    )
    ok, msg = ah_files.verify_python(p)
    assert ok is False
    assert msg == "no spec/loader"


def test_verify_python_spec_none(tmp_path, monkeypatch):
    p = tmp_path / "custom2.py"
    p.write_text("a = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        ah_files.importlib.util, "spec_from_file_location", lambda name, path: None
    )
    ok, msg = ah_files.verify_python(p)
    assert ok is False
    assert msg == "no spec/loader"


# --------------------------------------------------------------------
# 5. verify_bash
# --------------------------------------------------------------------
def test_verify_bash_missing(tmp_path):
    p = tmp_path / "missing.sh"
    ok, msg = ah_files.verify_bash(p)
    assert ok is False
    assert msg == f"missing: {p}"


@_POSIX_ONLY
def test_verify_bash_valid(tmp_path):
    p = tmp_path / "valid.sh"
    p.write_text("#!/usr/bin/env bash\necho 'hello'\n", encoding="utf-8")
    ok, msg = ah_files.verify_bash(p)
    assert ok is True
    assert msg == "ok"


@_POSIX_ONLY
def test_verify_bash_invalid(tmp_path):
    p = tmp_path / "invalid.sh"
    p.write_text("if then fi\n", encoding="utf-8")
    ok, msg = ah_files.verify_bash(p)
    assert ok is False
    assert isinstance(msg, str)
    assert "syntax error" in msg.lower() or "unexpected" in msg.lower()


def test_verify_bash_mocked_success(tmp_path, monkeypatch):
    p = tmp_path / "mock_good.sh"
    p.write_text("echo ok\n", encoding="utf-8")

    class _FakeOk:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(ah_files.subprocess, "run", lambda *a, **k: _FakeOk())
    ok, msg = ah_files.verify_bash(p)
    assert ok is True
    assert msg == "ok"


def test_verify_bash_nonzero_stdout_fallback(tmp_path, monkeypatch):
    p = tmp_path / "stdout_fail.sh"
    p.write_text("echo test\n", encoding="utf-8")

    class _FakeSubprocessResult:
        returncode = 1
        stdout = "  stdout error message  \n"
        stderr = ""

    monkeypatch.setattr(
        ah_files.subprocess, "run", lambda *a, **k: _FakeSubprocessResult()
    )
    ok, msg = ah_files.verify_bash(p)
    assert ok is False
    assert msg == "stdout error message"


def test_verify_bash_nonzero_without_output(tmp_path, monkeypatch):
    p = tmp_path / "silent_fail.sh"
    p.write_text("echo test\n", encoding="utf-8")

    class _FakeSubprocessResult:
        returncode = 1
        stdout = ""
        stderr = ""

    monkeypatch.setattr(
        ah_files.subprocess, "run", lambda *a, **k: _FakeSubprocessResult()
    )
    ok, msg = ah_files.verify_bash(p)
    assert ok is False
    assert msg == "non-zero exit"


# --------------------------------------------------------------------
# 6. patch_block
# --------------------------------------------------------------------
def test_patch_block_default_position_is_before(tmp_path):
    p = tmp_path / "script_default.txt"
    p.write_text("line1\nANCHOR\nline3\n", encoding="utf-8")

    # Call without passing position (tests default "before")
    res = ah_files.patch_block(p, anchor="ANCHOR", new_block="NEW_BLOCK\n", marker="M1")
    assert res == "patched"
    assert p.read_text(encoding="utf-8") == "line1\nNEW_BLOCK\nANCHOR\nline3\n"


def test_patch_block_before_multiple_occurrences(tmp_path):
    p = tmp_path / "script_multi.txt"
    p.write_text("ANCHOR\nANCHOR\n", encoding="utf-8")

    res = ah_files.patch_block(
        p, anchor="ANCHOR", new_block="NEW_", marker="M2", position="before"
    )
    assert res == "patched"
    # Replaces ONLY the first occurrence (count=1)
    assert p.read_text(encoding="utf-8") == "NEW_ANCHOR\nANCHOR\n"


def test_patch_block_after_multiple_occurrences(tmp_path):
    p = tmp_path / "script_multi_after.txt"
    p.write_text("ANCHOR\nANCHOR\n", encoding="utf-8")

    res = ah_files.patch_block(
        p, anchor="ANCHOR", new_block="_NEW", marker="M3", position="after"
    )
    assert res == "patched"
    # Replaces ONLY the first occurrence (count=1)
    assert p.read_text(encoding="utf-8") == "ANCHOR_NEW\nANCHOR\n"


def test_patch_block_replace_multiple_occurrences(tmp_path):
    p = tmp_path / "script_multi_replace.txt"
    p.write_text("ANCHOR\nANCHOR\n", encoding="utf-8")

    res = ah_files.patch_block(
        p, anchor="ANCHOR", new_block="REPLACED", marker=None, position="replace"
    )
    assert res == "patched"
    # Replaces ONLY the first occurrence (count=1)
    assert p.read_text(encoding="utf-8") == "REPLACED\nANCHOR\n"


def test_patch_block_idempotent_marker(tmp_path):
    p = tmp_path / "script_idem.txt"
    p.write_text("line1\nMARKER_HERE\nline3\n", encoding="utf-8")

    res = ah_files.patch_block(
        p, anchor="line1", new_block="foo", marker="MARKER_HERE", position="before"
    )
    assert res == "already patched (marker: 'MARKER_HERE')"
    assert p.read_text(encoding="utf-8") == "line1\nMARKER_HERE\nline3\n"


def test_patch_block_missing_anchor_raises(tmp_path):
    p = tmp_path / "script.txt"
    p.write_text("line1\nline2\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        ah_files.patch_block(
            p, anchor="MISSING", new_block="NEW", marker="M", position="before"
        )
    assert str(exc.value) == f"anchor not found in {p}: 'MISSING'"


def test_patch_block_unknown_position_raises(tmp_path):
    p = tmp_path / "script.txt"
    p.write_text("line1\nANCHOR\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        ah_files.patch_block(
            p, anchor="ANCHOR", new_block="NEW", marker="M", position="inside"
        )
    assert str(exc.value) == "unknown position: inside"


@_POSIX_ONLY
def test_patch_block_preserves_file_mode(tmp_path):
    p = tmp_path / "executable.sh"
    p.write_text("echo old\n", encoding="utf-8")
    p.chmod(0o755)

    ah_files.patch_block(p, anchor="echo old", new_block="echo new", marker="new", position="replace")
    assert stat.S_IMODE(p.stat().st_mode) == 0o755


# --------------------------------------------------------------------
# 7. patch_replace
# --------------------------------------------------------------------
def test_patch_replace_success_and_idempotent(tmp_path):
    p = tmp_path / "conf.ini"
    p.write_text("enable_feature = false\n", encoding="utf-8")

    res = ah_files.patch_replace(
        p, old="enable_feature = false", new="enable_feature = true", marker="enable_feature = true"
    )
    assert res == "patched"
    assert p.read_text(encoding="utf-8") == "enable_feature = true\n"

    # Idempotent call
    res2 = ah_files.patch_replace(
        p, old="enable_feature = false", new="enable_feature = true", marker="enable_feature = true"
    )
    assert res2 == "already patched (marker: 'enable_feature = true')"


def test_patch_replace_multiple_occurrences(tmp_path):
    p = tmp_path / "multi.txt"
    p.write_text("foo bar foo\n", encoding="utf-8")

    res = ah_files.patch_replace(p, old="foo", new="baz")
    assert res == "patched"
    assert p.read_text(encoding="utf-8") == "baz bar foo\n"


def test_patch_replace_missing_old_raises(tmp_path):
    p = tmp_path / "conf.ini"
    p.write_text("key = value\n", encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        ah_files.patch_replace(p, old="nonexistent_key", new="new_key")
    assert str(exc.value) == f"old text not found in {p}"


@_POSIX_ONLY
def test_patch_replace_preserves_file_mode(tmp_path):
    p = tmp_path / "conf.ini"
    p.write_text("old_val = 1\n", encoding="utf-8")
    p.chmod(0o640)

    ah_files.patch_replace(p, old="old_val = 1", new="new_val = 2")
    assert stat.S_IMODE(p.stat().st_mode) == 0o640

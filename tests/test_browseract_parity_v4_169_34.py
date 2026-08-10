"""v4.169.34 -- BrowserAct discovery parity tests (mutation-driven).

Baseline measured with mutmut 2.5.1: 155/196 mutants of
``arena/admin/browseract.py`` survived. Cause: the pre-existing tests were
environment-dependent (they probe the real PATH and assert almost nothing
when the CLI happens to be installed) and pinned almost no observable
behaviour.

This file pins everything behaviourally:

* test-side copies of every user-facing string (hints, classifications) and
  every expected path list -- an assertion parametrised from the module's
  own constants would be tautological, because a mutant deleting an entry
  deletes it from the iteration too (trap recorded in v4.169.33);
* fully monkeypatched environment -- no real ``shutil.which``, no real file
  system probes, no real subprocess ever runs here;
* exact argv/kwargs capture for both subprocess call sites (the CLI
  contract: ``--version`` and the ``get-skills`` handshake).

Two former equivalent-mutant families were removed from the module itself
(dead ``not path`` guard; dead ``"\\uv/tools/"`` disjunct subsumed by
``"uv/tools" in path``) -- see comments in the module.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.admin.browseract as ba  # noqa: E402

# ---------------------------------------------------------------------------
# Test-side copies -- kept deliberately independent from the module. If the
# module changes one of these legitimately (a real contract change), the
# reviewer must update the copy; a mutant breaking one turns the tests red.
# ---------------------------------------------------------------------------
EXPECTED_TIMEOUT = 10
EXPECTED_PACKAGE = "browser-act-cli"

HOME = "/h"


def _portable_paths(paths):
    """Compare path ordering without depending on the host separator."""
    return [str(path).replace("\\\\", "/") for path in paths]


EXPECTED_WINDOWS_NAMES = ["browser-act.exe", "browser-act.bat", "browser-act.cmd", "browser-act"]
EXPECTED_POSIX_NAMES = ["browser-act"]

EXPECTED_WINDOWS_FALLBACKS = [
    "/h/.local/bin/browser-act.exe",
    "/h/AppData/Roaming/uv/tools/browser-act-cli/Scripts/browser-act.exe",
    "/h/AppData/Local/pipx/venvs/browser-act-cli/Scripts/browser-act.exe",
]
EXPECTED_POSIX_FALLBACKS = [
    "/h/.local/bin/browser-act",
    "/h/.local/share/uv/tools/browser-act-cli/bin/browser-act",
    "/h/.local/pipx/venvs/browser-act-cli/bin/browser-act",
    "/usr/local/bin/browser-act",
    "/opt/homebrew/bin/browser-act",
]

EXPECTED_INSTALL_HINT_WINDOWS = (
    "Install BrowserAct CLI: `winget install --id=astral-sh.uv` "
    "then `uv tool install browser-act-cli --python 3.12`. "
    "See https://www.browseract.com/ for docs."
)
EXPECTED_INSTALL_HINT_DARWIN = (
    "Install BrowserAct CLI: `brew install uv` "
    "then `uv tool install browser-act-cli --python 3.12`. "
    "See https://www.browseract.com/ for docs."
)
EXPECTED_INSTALL_HINT_OTHER = (
    "Install BrowserAct CLI: install uv "
    "(https://docs.astral.sh/uv/getting-started/installation/) "
    "then `uv tool install browser-act-cli --python 3.12`. "
    "See https://www.browseract.com/ for docs."
)

EXPECTED_UPDATE_HINT_UV = "Update via: `uv tool upgrade browser-act-cli`"
EXPECTED_UPDATE_HINT_PIPX = "Update via: `pipx upgrade browser-act-cli`"
EXPECTED_UPDATE_HINT_SYSTEM = (
    "Update via your package manager (or reinstall with the tool of your choice)."
)
EXPECTED_UPDATE_HINT_UNKNOWN = (
    "Reinstall the CLI to update: `uv tool install --force browser-act-cli --python 3.12`"
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _Proc:
    def __init__(self, returncode=0, stdout=None, stderr=None):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeSubprocess:
    """Stands in for the subprocess module and records every call.

    ``TimeoutExpired`` must be the real class: the ``except`` clauses in the
    module resolve it through this object at raise time.
    """

    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self, result=None, raises=None):
        self._result = result
        self._raises = raises
        self.calls = []

    def run(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        if self._raises is not None:
            raise self._raises
        return self._result


class _Env:
    """Records patched-environment interactions for later assertions."""

    def __init__(self):
        self.which_args = []
        self.expand_args = []


def _patch_env(monkeypatch, system="Linux", which_map=None, files=(), execs=()):
    """Replace every host probe _cli_candidates performs. Nothing real runs."""
    env = _Env()
    which_map = which_map or {}
    files_set = {ba.os.path.normpath(path) for path in files}
    execs_set = {ba.os.path.normpath(path) for path in execs}

    monkeypatch.setattr(ba.platform, "system", lambda: system)

    def _which(name):
        env.which_args.append(name)
        return which_map.get(name)

    monkeypatch.setattr(ba.shutil, "which", _which)

    def _expanduser(p):
        env.expand_args.append(p)
        return HOME if p == "~" else p

    monkeypatch.setattr(ba.os.path, "expanduser", _expanduser)
    monkeypatch.setattr(ba.os.path, "isfile", lambda p: p in files_set)
    monkeypatch.setattr(
        ba.os,
        "access",
        lambda p, mode: mode == ba.os.X_OK and p in execs_set,
    )
    return env


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------
def test_module_constants_are_pinned():
    assert ba.DEFAULT_TIMEOUT == EXPECTED_TIMEOUT
    assert isinstance(ba.DEFAULT_TIMEOUT, int)
    assert ba.UPSTREAM_PACKAGE == EXPECTED_PACKAGE


# ---------------------------------------------------------------------------
# _cli_candidates
# ---------------------------------------------------------------------------
def test_candidates_windows_fallbacks_exact(monkeypatch):
    env = _patch_env(monkeypatch, system="Windows", which_map={},
                     files=EXPECTED_WINDOWS_FALLBACKS, execs=EXPECTED_WINDOWS_FALLBACKS)
    assert _portable_paths(ba._cli_candidates()) == _portable_paths(EXPECTED_WINDOWS_FALLBACKS)
    assert env.which_args == EXPECTED_WINDOWS_NAMES
    assert env.expand_args == ["~"]


def test_candidates_posix_fallbacks_exact(monkeypatch):
    env = _patch_env(monkeypatch, system="Linux", which_map={},
                     files=EXPECTED_POSIX_FALLBACKS, execs=EXPECTED_POSIX_FALLBACKS)
    assert _portable_paths(ba._cli_candidates()) == _portable_paths(EXPECTED_POSIX_FALLBACKS)
    assert env.which_args == EXPECTED_POSIX_NAMES
    assert env.expand_args == ["~"]


def test_candidates_darwin_uses_posix_fallbacks(monkeypatch):
    env = _patch_env(monkeypatch, system="Darwin", which_map={},
                     files=EXPECTED_POSIX_FALLBACKS, execs=EXPECTED_POSIX_FALLBACKS)
    assert _portable_paths(ba._cli_candidates()) == _portable_paths(EXPECTED_POSIX_FALLBACKS)
    assert env.which_args == EXPECTED_POSIX_NAMES


def test_candidates_system_name_is_lowercased(monkeypatch):
    env = _patch_env(monkeypatch, system="WINDOWS", which_map={},
                     files=EXPECTED_WINDOWS_FALLBACKS, execs=EXPECTED_WINDOWS_FALLBACKS)
    assert _portable_paths(ba._cli_candidates()) == _portable_paths(EXPECTED_WINDOWS_FALLBACKS)
    assert env.which_args == EXPECTED_WINDOWS_NAMES


def test_candidates_which_hit_comes_first(monkeypatch):
    hit = "/w/bin/browser-act"
    all_paths = [hit] + EXPECTED_POSIX_FALLBACKS
    _patch_env(monkeypatch, system="Linux", which_map={"browser-act": hit},
               files=all_paths, execs=all_paths)
    assert _portable_paths(ba._cli_candidates()) == _portable_paths(all_paths)


def test_candidates_windows_which_hit_comes_first(monkeypatch):
    hit = "C:/Tools/browser-act.exe"
    all_paths = [hit] + EXPECTED_WINDOWS_FALLBACKS
    _patch_env(monkeypatch, system="Windows",
               which_map={"browser-act.exe": hit},
               files=all_paths, execs=all_paths)
    assert _portable_paths(ba._cli_candidates()) == _portable_paths(all_paths)


def test_candidates_dedup_keeps_first_occurrence(monkeypatch):
    hit = EXPECTED_POSIX_FALLBACKS[0]  # shutil.which returns the same path as a fallback
    _patch_env(monkeypatch, system="Linux", which_map={"browser-act": hit},
               files=EXPECTED_POSIX_FALLBACKS, execs=EXPECTED_POSIX_FALLBACKS)
    assert _portable_paths(ba._cli_candidates()) == _portable_paths(EXPECTED_POSIX_FALLBACKS)


def test_candidates_non_executable_file_dropped(monkeypatch):
    _patch_env(monkeypatch, system="Linux", which_map={},
               files=EXPECTED_POSIX_FALLBACKS,
               execs=EXPECTED_POSIX_FALLBACKS[1:])
    assert _portable_paths(ba._cli_candidates()) == _portable_paths(EXPECTED_POSIX_FALLBACKS)[1:]


def test_candidates_non_file_dropped_even_if_accessible(monkeypatch):
    """Kills the and->or mutant on the isfile/access check."""
    _patch_env(monkeypatch, system="Linux", which_map={},
               files=EXPECTED_POSIX_FALLBACKS[1:],
               execs=EXPECTED_POSIX_FALLBACKS)
    assert _portable_paths(ba._cli_candidates()) == _portable_paths(EXPECTED_POSIX_FALLBACKS)[1:]


def test_candidates_nothing_found_returns_empty(monkeypatch):
    _patch_env(monkeypatch, system="Linux", which_map={}, files=(), execs=())
    assert ba._cli_candidates() == []


def test_candidates_expanduser_arg_is_tilde(monkeypatch):
    env = _patch_env(monkeypatch, system="Linux", which_map={})
    ba._cli_candidates()
    assert env.expand_args == ["~"]


# ---------------------------------------------------------------------------
# _cli_source
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path,expected", [
    ("/home/t/.local/share/uv/tools/browser-act-cli/bin/browser-act", "uv-tool"),
    ("C:\\Users\\t\\AppData\\Roaming\\uv\\tools\\browser-act-cli\\Scripts\\browser-act.exe", "uv-tool"),
    ("/Users/t/.local/bin/browser-act", "uv-tool"),
    ("C:\\USERS\\T\\.LOCAL\\BIN\\BROWSER-ACT.EXE", "uv-tool"),
    ("/home/t/.local/pipx/venvs/browser-act-cli/bin/browser-act", "pipx"),
    ("D:\\TOOLS\\PIPX\\X", "pipx"),
    ("C:\\Users\\t\\AppData\\Local\\pipx\\venvs\\browser-act-cli\\Scripts\\browser-act.exe", "pipx"),
    ("/usr/local/bin/browser-act", "system"),
    ("/USR/LOCAL/BIN/BROWSER-ACT", "system"),
    ("/opt/homebrew/bin/browser-act", "system"),
    ("/home/t/bin/browser-act", "unknown"),
    ("/usr/locals/bin/browser-act", "unknown"),
    ("/opt/homebrews/bin/browser-act", "unknown"),
])
def test_cli_source_classification(path, expected):
    assert ba._cli_source(path) == expected


# ---------------------------------------------------------------------------
# _get_version
# ---------------------------------------------------------------------------
def _patched_subprocess(monkeypatch, result=None, raises=None):
    fake = _FakeSubprocess(result=result, raises=raises)
    monkeypatch.setattr(ba, "subprocess", fake)
    return fake


def test_get_version_argv_and_kwargs_exact(monkeypatch):
    fake = _patched_subprocess(monkeypatch, result=_Proc(0, "x 1.2.3", ""))
    ba._get_version("/x/cli")
    assert fake.calls == [
        (["/x/cli", "--version"], {"capture_output": True, "text": True, "timeout": 10})
    ]


@pytest.mark.parametrize("stdout,stderr,expected", [
    ("browser-act 2.0.2", "", "2.0.2"),
    ("browser-act, version 2.0.2", "", "2.0.2"),
    ("", "browser-act 3.1.0", "3.1.0"),
    ("browser-act 1.2.3.4", "", "1.2.3.4"),
    ("browser-act 2.0.0b1", "", "2.0.0b1"),
    ("browser-act v3.1.4-rc.1 ready", "", "3.1.4-rc.1"),
    ("hello world", "", "world"),
    ("tool 1.2", "", "1.2"),
    # Need >= 3 tokens: with exactly 2, [-1] and [+1] are the same element
    # and the sign-of-index mutant survives (measured, mutant #101).
    ("release candidate build", "", "build"),
    ("   ", None, None),
    (None, None, None),
    (None, "browser-act 4.4.4", "4.4.4"),
])
def test_get_version_parsing_matrix(monkeypatch, stdout, stderr, expected):
    _patched_subprocess(monkeypatch, result=_Proc(0, stdout, stderr))
    assert ba._get_version("/x/cli") == expected


def test_get_version_nonzero_exit_returns_none(monkeypatch):
    _patched_subprocess(monkeypatch, result=_Proc(2, "browser-act 2.0.2", ""))
    assert ba._get_version("/x/cli") is None


def test_get_version_missing_binary_returns_none(monkeypatch):
    _patched_subprocess(monkeypatch, raises=FileNotFoundError("gone"))
    assert ba._get_version("/x/cli") is None


def test_get_version_timeout_returns_none(monkeypatch):
    _patched_subprocess(monkeypatch,
                        raises=subprocess.TimeoutExpired(cmd="/x/cli", timeout=10))
    assert ba._get_version("/x/cli") is None


def test_get_version_unexpected_error_propagates(monkeypatch):
    """A widened except-clause would swallow this and fail the test."""
    _patched_subprocess(monkeypatch, raises=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        ba._get_version("/x/cli")


# ---------------------------------------------------------------------------
# _install_hint / _update_hint
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("system,expected", [
    ("Windows", EXPECTED_INSTALL_HINT_WINDOWS),
    ("Darwin", EXPECTED_INSTALL_HINT_DARWIN),
    ("Linux", EXPECTED_INSTALL_HINT_OTHER),
    ("Haiku", EXPECTED_INSTALL_HINT_OTHER),
])
def test_install_hint_exact_per_os(monkeypatch, system, expected):
    monkeypatch.setattr(ba.platform, "system", lambda: system)
    assert ba._install_hint() == expected


@pytest.mark.parametrize("source,expected", [
    ("uv-tool", EXPECTED_UPDATE_HINT_UV),
    ("pipx", EXPECTED_UPDATE_HINT_PIPX),
    ("system", EXPECTED_UPDATE_HINT_SYSTEM),
    ("unknown", EXPECTED_UPDATE_HINT_UNKNOWN),
    ("", EXPECTED_UPDATE_HINT_UNKNOWN),
    ("anything-else", EXPECTED_UPDATE_HINT_UNKNOWN),
])
def test_update_hint_exact_per_source(source, expected):
    assert ba._update_hint(source) == expected


# ---------------------------------------------------------------------------
# browseract_status
# ---------------------------------------------------------------------------
def test_status_not_installed_exact_dict(monkeypatch):
    monkeypatch.setattr(ba.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ba, "_cli_candidates", lambda: [])
    assert ba.browseract_status() == {
        "ok": False,
        "installed": False,
        "cli_path": None,
        "cli_source": None,
        "version": None,
        "platform": "linux",
        "hint": EXPECTED_INSTALL_HINT_OTHER,
    }


def test_status_installed_exact_dict(monkeypatch):
    """Two candidates with distinct classifications also pin candidates[0]."""
    monkeypatch.setattr(ba.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        ba, "_cli_candidates",
        lambda: ["/usr/local/bin/browser-act",
                 "/h/.local/pipx/venvs/browser-act-cli/bin/browser-act"],
    )
    seen_version_args = []

    def _fake_version(cli, *, subprocess_kwargs=None):
        seen_version_args.append(cli)
        return "9.9.9"

    monkeypatch.setattr(ba, "_get_version", _fake_version)
    assert ba.browseract_status() == {
        "ok": True,
        "installed": True,
        "cli_path": "/usr/local/bin/browser-act",
        "cli_source": "system",
        "version": "9.9.9",
        "platform": "darwin",
        "hint": None,
        "update_hint": EXPECTED_UPDATE_HINT_SYSTEM,
    }
    assert seen_version_args == ["/usr/local/bin/browser-act"]


def test_status_installed_windows_platform_passes_lowercased(monkeypatch):
    monkeypatch.setattr(ba.platform, "system", lambda: "WINDOWS")
    monkeypatch.setattr(
        ba, "_cli_candidates",
        lambda: ["C:\\USERS\\T\\.LOCAL\\BIN\\BROWSER-ACT.EXE"],
    )
    monkeypatch.setattr(ba, "_get_version", lambda cli, **kwargs: None)
    result = ba.browseract_status()
    assert result["platform"] == "windows"
    assert result["installed"] is True
    assert result["cli_source"] == "uv-tool"
    assert result["version"] is None
    assert result["update_hint"] == EXPECTED_UPDATE_HINT_UV


# ---------------------------------------------------------------------------
# browseract_doctor
# ---------------------------------------------------------------------------
_CANON_STATUS = {
    "ok": True,
    "installed": True,
    "cli_path": "/c/x",
    "cli_source": "system",
    "version": "1.2.3",
    "platform": "linux",
    "hint": None,
    "update_hint": EXPECTED_UPDATE_HINT_SYSTEM,
}


def _doctor_env(monkeypatch, status, proc=None, raises=None):
    monkeypatch.setattr(ba, "browseract_status", lambda **kwargs: dict(status))
    return _patched_subprocess(monkeypatch, result=proc, raises=raises)


def test_doctor_not_installed_returns_early(monkeypatch):
    fake = _doctor_env(monkeypatch, {"ok": False, "installed": False, "hint": "h"})
    assert ba.browseract_doctor() == {
        "ok": False,
        "installed": False,
        "hint": "h",
        "handshake": False,
        "error": "browser-act not installed",
    }
    assert fake.calls == []


def test_doctor_handshake_happy_path(monkeypatch):
    fake = _doctor_env(monkeypatch, _CANON_STATUS, proc=_Proc(0, '{"skills": 3}', ""))
    assert ba.browseract_doctor() == {
        **_CANON_STATUS,
        "handshake": True,
        "handshake_error": None,
    }
    assert fake.calls == [
        (["/c/x", "get-skills", "core", "--skill-version", "2.0.0"],
         {"capture_output": True, "text": True, "timeout": 10})
    ]


def test_doctor_rc_zero_but_silent_is_failure(monkeypatch):
    """rc==0 alone is not a handshake: stdout must be non-empty."""
    _doctor_env(monkeypatch, _CANON_STATUS, proc=_Proc(0, "", "boom"))
    result = ba.browseract_doctor()
    assert result["handshake"] is False
    assert result["handshake_error"] == "boom"


def test_doctor_rc_zero_totally_silent_reports_exit(monkeypatch):
    _doctor_env(monkeypatch, _CANON_STATUS, proc=_Proc(0, "", ""))
    result = ba.browseract_doctor()
    assert result["handshake"] is False
    assert result["handshake_error"] == "exit=0"


def test_doctor_error_prefers_stderr(monkeypatch):
    _doctor_env(monkeypatch, _CANON_STATUS, proc=_Proc(3, "weird-out", " bad juju "))
    result = ba.browseract_doctor()
    assert result["handshake"] is False
    assert result["handshake_error"] == "bad juju"


def test_doctor_error_falls_back_to_stdout(monkeypatch):
    _doctor_env(monkeypatch, _CANON_STATUS, proc=_Proc(3, "weird-out", ""))
    result = ba.browseract_doctor()
    assert result["handshake"] is False
    assert result["handshake_error"] == "weird-out"


def test_doctor_error_falls_back_to_exit_code(monkeypatch):
    _doctor_env(monkeypatch, _CANON_STATUS, proc=_Proc(3, "", ""))
    result = ba.browseract_doctor()
    assert result["handshake"] is False
    assert result["handshake_error"] == "exit=3"


def test_doctor_error_none_stderr_uses_stdout(monkeypatch):
    """Kills or->and mutants: None stderr must fall through to stdout."""
    _doctor_env(monkeypatch, _CANON_STATUS, proc=_Proc(3, "out-r3", None))
    result = ba.browseract_doctor()
    assert result["handshake_error"] == "out-r3"


def test_doctor_error_truncated_to_500(monkeypatch):
    _doctor_env(monkeypatch, _CANON_STATUS, proc=_Proc(3, "", "e" * 600))
    result = ba.browseract_doctor()
    assert result["handshake_error"] == "e" * 500
    assert len(result["handshake_error"]) == 500


def test_doctor_missing_binary_reports_exception(monkeypatch):
    _doctor_env(monkeypatch, _CANON_STATUS, raises=FileNotFoundError("gone-missing"))
    result = ba.browseract_doctor()
    assert result["handshake"] is False
    assert result["handshake_error"] == "gone-missing"


def test_doctor_timeout_reports_exception(monkeypatch):
    exc = subprocess.TimeoutExpired(cmd="/c/x", timeout=10)
    _doctor_env(monkeypatch, _CANON_STATUS, raises=exc)
    result = ba.browseract_doctor()
    assert result["handshake"] is False
    assert result["handshake_error"] == str(exc)


def test_doctor_unexpected_error_propagates(monkeypatch):
    _doctor_env(monkeypatch, _CANON_STATUS, raises=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        ba.browseract_doctor()


def test_doctor_carries_status_fields_through(monkeypatch):
    _doctor_env(monkeypatch, _CANON_STATUS, proc=_Proc(0, "ok", ""))
    result = ba.browseract_doctor()
    for key, value in _CANON_STATUS.items():
        assert result[key] == value
    assert set(result) == set(_CANON_STATUS) | {"handshake", "handshake_error"}

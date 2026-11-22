"""
Keep tests from starting programs that belong to the machine they run on.

Issue #376: on a developer's computer the suite opened a browser window,
started a ``browser-act`` daemon and queried the VPN client, because those
programs happened to be installed.  A clean CI runner has none of them, so
the same tests took a different path there and nothing was noticed.

This module makes both places behave alike.  It installs one audit hook for
the whole pytest process:

* A program named in :data:`HOST_PROGRAMS` is reported as *not installed*
  (``FileNotFoundError``), which is what a clean runner would answer.
* ``os.startfile`` and ``webbrowser.open`` are refused with ``OSError``.
* Every other program is started as usual and only counted, so the list of
  what the suite really runs can be read from a report.

Limits, stated so nobody relies on more than is here: the hook sees process
creation in the pytest process only.  A child process (for example a live
bridge started by an end-to-end test) is not covered, and neither are
``os.exec*``, ``os.spawn*`` and ``os.posix_spawn``.

Opt out for one test with ``@pytest.mark.allow_host_programs``, or for a
whole run with ``ARENA_TEST_ALLOW_HOST_PROGRAMS=1``.  A run started with
``ARENA_TEST_HOST_PROCESS_REPORT=<path>`` writes ``<path>.<worker>.json``.
Both names carry the ``ARENA_TEST_`` prefix, which the harness leaves in the
environment, so xdist workers see them too.

The module is a pytest plugin: ``tests/conftest.py`` names it in
``pytest_plugins`` and the hooks at the end of this file do the wiring.
"""
from __future__ import annotations

import errno
import json
import os
import re
import sys
import threading
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

ALLOW_VARIABLE = "ARENA_TEST_ALLOW_HOST_PROGRAMS"
REPORT_VARIABLE = "ARENA_TEST_HOST_PROCESS_REPORT"
NO_INSTALL_VARIABLE = "PYTHON_MANAGER_AUTOMATIC_INSTALL"
ALLOW_MARKER = "allow_host_programs"

# Programs that open windows, leave daemons behind, or whose presence depends
# on what the owner of the machine installed.  Names are lower case, without
# directory and without a Windows extension.
HOST_PROGRAMS = frozenset({
    # browsers
    "msedge", "chrome", "google-chrome", "google-chrome-stable", "google chrome",
    "chromium", "chromium-browser", "firefox", "librewolf", "brave",
    "brave-browser", "opera", "vivaldi", "microsoft edge", "safari", "xdg-open",
    # third-party command line tools probed by product code
    "browser-act", "specify", "winget",
    # VPN clients
    "tailscale", "zerotier-cli", "zerotier-one", "zerotier-one_x64",
})

_SHELLS = frozenset({"sh", "bash", "dash", "zsh", "cmd", "powershell", "pwsh"})
_SHELL_COMMAND_FLAGS = frozenset({"-c", "/c", "/k", "-command"})
_WINDOWS_EXTENSIONS = (".exe", ".cmd", ".bat", ".com")
_TOKEN = re.compile(r'"([^"]*)"|(\S+)')

_lock = threading.Lock()
_installed = False
_allowed_for_run = False
_report_path: str | None = None
_allowed_for_test = threading.Event()
started: Counter[str] = Counter()
started_by: Counter[tuple[str, str]] = Counter()
refused: list[tuple[str, str]] = []


def program_name(path: object) -> str:
    """Return the bare lower-case program name for a path or command word."""
    text = os.fsdecode(path) if isinstance(path, (bytes, os.PathLike)) else str(path)
    name = text.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()
    for extension in _WINDOWS_EXTENSIONS:
        if name.endswith(extension):
            return name[: -len(extension)]
    return name


def _words(command: object) -> list[str]:
    if isinstance(command, (bytes, os.PathLike)):
        command = os.fsdecode(command)
    if isinstance(command, str):
        return [quoted or bare for quoted, bare in _TOKEN.findall(command)]
    try:
        return [os.fsdecode(word) if isinstance(word, (bytes, os.PathLike)) else str(word)
                for word in command]  # type: ignore[union-attr]
    except TypeError:
        return []


def _shell_command(words: list[str]) -> str:
    """Return the command text a shell was given after ``-c`` or ``/c``."""
    for index, word in enumerate(words[1:-1], start=1):
        if word.lower() in _SHELL_COMMAND_FLAGS:
            return words[index + 1]
    return ""


def programs_in(executable: object, args: object) -> list[str]:
    """Return the program a ``Popen`` call starts, and the one behind a shell."""
    words = _words(args) if args else []
    first = executable or (words[:1] or [""])[0]
    if not first:
        return []
    names = [program_name(first)]
    if names[0] in _SHELLS:
        names.extend(program_name(word) for word in _words(_shell_command(words))[:1])
    return names


def _current_test() -> str:
    return os.environ.get("PYTEST_CURRENT_TEST", "")


def _permitted() -> bool:
    return _allowed_for_run or _allowed_for_test.is_set()


def _check(names: list[str]) -> None:
    if not _permitted():
        for name in names:
            if name in HOST_PROGRAMS:
                with _lock:
                    refused.append((name, _current_test()))
                raise FileNotFoundError(
                    errno.ENOENT,
                    f"host program {name!r} is treated as not installed in tests "
                    f"(mark the test {ALLOW_MARKER} or set {ALLOW_VARIABLE}=1)",
                    name,
                )
    if names:
        with _lock:
            started[names[0]] += 1
            started_by[(names[0], _current_test().split("::", 1)[0])] += 1


def _refuse_desktop(what: str, target: object) -> None:
    if _permitted():
        return
    with _lock:
        refused.append((what, _current_test()))
    raise OSError(
        f"{what}({target!r}) is refused in tests "
        f"(mark the test {ALLOW_MARKER} or set {ALLOW_VARIABLE}=1)"
    )


def _audit(event: str, args: tuple[Any, ...]) -> None:
    if event == "subprocess.Popen":
        _check(programs_in(args[0], args[1]))
    elif event == "os.system":
        _check(programs_in(None, args[0]))
    elif event == "os.startfile":
        _refuse_desktop("os.startfile", args[0])
    elif event == "webbrowser.open":
        _refuse_desktop("webbrowser.open", args[0])


def install() -> None:
    """Install the hook once per process."""
    global _installed, _allowed_for_run, _report_path
    _allowed_for_run = os.environ.get(ALLOW_VARIABLE) == "1"
    _report_path = os.environ.get(REPORT_VARIABLE) or None
    # On Windows `python3`, `pip` and `pip3` can be the Python install manager.
    # When it finds no runtime it downloads one, and with a reduced environment
    # it does so into the working directory -- the checkout (#376).  Version
    # probes are ordinary programs, so the guard lets them start; what a test
    # run must never do is install software.  Children inherit this.
    os.environ[NO_INSTALL_VARIABLE] = "false"
    if not _installed:
        sys.addaudithook(_audit)
        _installed = True


def allow_for_test(allowed: bool) -> None:
    if allowed:
        _allowed_for_test.set()
    else:
        _allowed_for_test.clear()


def _by_program(counts: Counter[tuple[str, str]]) -> dict[str, dict[str, int]]:
    """Group launch counts as ``{program: {test file: launches}}``."""
    result: dict[str, dict[str, int]] = {}
    for (name, test_file), count in sorted(counts.items()):
        result.setdefault(name, {})[test_file] = count
    return result


def write_report(worker: str, path: str | None = None) -> None:
    """Write what this process started and refused, if a path was requested."""
    path = path or _report_path
    if not path:
        return
    with _lock:
        data = {
            "worker": worker,
            "started": dict(sorted(started.items())),
            "started_by": _by_program(started_by),
            "refused": [{"program": name, "test": test} for name, test in refused],
        }
    target = Path(f"{path}.{worker}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=1), encoding="utf-8")



def pytest_configure(config: pytest.Config) -> None:
    """Register the opt-out marker and arm the guard for this process."""
    config.addinivalue_line(
        "markers",
        f"{ALLOW_MARKER}: test may start programs installed on the machine "
        "(browsers, VPN clients, third-party CLIs)",
    )
    install()


@pytest.fixture(autouse=True)
def _no_host_programs(request: pytest.FixtureRequest):
    """Treat programs installed on this machine as absent unless a test opts in."""
    allow_for_test(request.node.get_closest_marker(ALLOW_MARKER) is not None)
    yield
    allow_for_test(False)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config: pytest.Config) -> None:
    """Write the report of this worker, if one was requested."""
    write_report(getattr(config, "workerinput", {}).get("workerid", "main"))

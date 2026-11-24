"""The suite must not start programs that belong to the developer's machine (#376)."""
from __future__ import annotations

import importlib.machinery
import json
import os
import sys
import types
import webbrowser

import pytest

from tests import _host_process_guard as guard

# The tests raise the audit events themselves with ``sys.audit``.  That is the
# call ``subprocess.Popen`` and ``os.system`` make before they start anything,
# so it reaches the hook exactly as a real launch does, shows that the hook is
# installed in this process, and starts no program -- AGENTS.md forbids
# ``os.system`` and ``shell=True`` in this repository, tests included.
POPEN = "subprocess.Popen"
STDLIB_WEBBROWSER = str(webbrowser.__file__)


def launch(*command: str) -> None:
    """Raise the event ``subprocess.Popen(list(command))`` raises."""
    sys.audit(POPEN, command[0], list(command), None, None)


def this_test() -> str:
    """Return the test id pytest publishes for the running test."""
    return os.environ["PYTEST_CURRENT_TEST"]


@pytest.fixture(autouse=True)
def guard_is_armed(monkeypatch):
    """Describe the armed guard, also in a run that switched it off."""
    monkeypatch.setattr(guard, "_allowed_for_run", False)


@pytest.mark.parametrize(
    ("executable", "args", "expected"),
    [
        (None, ["tailscale", "status"], ["tailscale"]),
        (None, [r"C:\Program Files\Tailscale\tailscale.exe", "status"], ["tailscale"]),
        (r"C:\Windows\System32\cmd.exe", 'cmd.exe /c "browser-act --version"', ["cmd", "browser-act"]),
        (None, "cmd.exe /c winget list", ["cmd", "winget"]),
        ("/bin/sh", ["/bin/sh", "-c", "specify check"], ["sh", "specify"]),
        ("/bin/sh", ["/bin/sh", "-c", "/usr/bin/osascript"], ["sh", "osascript"]),
        (None, ["powershell", "-NoProfile", "-Command", "tailscale status"], ["powershell", "tailscale"]),
        (None, '"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe" --new-window', ["msedge"]),
        (None, [sys.executable, "-c", "pass"], [guard.program_name(sys.executable)]),
        (b"/usr/bin/git", [b"git", "status"], ["git"]),
        (None, ["sh", "-c"], ["sh"]),
        (None, ["sh", "-c", ""], ["sh"]),
        (None, [], []),
        (None, None, []),
    ],
)
def test_programs_are_read_from_the_command(executable, args, expected):
    """Read the program, and the one behind a shell, from every argument shape."""
    assert guard.programs_in(executable, args) == expected


def test_every_listed_name_is_already_normalised():
    """Keep the deny list in the form `program_name` produces."""
    assert {guard.program_name(name) for name in guard.HOST_PROGRAMS} == set(guard.HOST_PROGRAMS)


def test_a_host_program_counts_as_not_installed():
    """Answer a launch of a listed program the way a clean runner would."""
    before = len(guard.refused)
    with pytest.raises(FileNotFoundError, match="treated as not installed"):
        launch("tailscale", "status")
    assert guard.refused[before:] == [("tailscale", this_test())]


def test_a_host_program_behind_a_shell_is_refused_too():
    """Look through `sh -c`: the shell is not the program that matters."""
    with pytest.raises(FileNotFoundError, match="browser-act"):
        launch("/bin/sh", "-c", "browser-act --version")


def test_the_macos_script_host_is_refused_behind_a_shell():
    """Refuse `osascript`, the way Python 3.10 opens a URL on macOS."""
    # That version calls os.popen("/usr/bin/osascript") and raises no
    # `webbrowser.open` event, so the program itself has to be on the list.
    with pytest.raises(FileNotFoundError, match="osascript"):
        launch("/bin/sh", "-c", "/usr/bin/osascript")


@pytest.fixture(name="process_creation")
def _process_creation(monkeypatch):
    """Replace the calls that create a process, one step below the audit event."""
    # A regressed guard must fail these tests, not open a browser.  The names
    # are the ones `subprocess.Popen` calls right after raising its event:
    # fork_exec on POSIX (3.10 through the C module, 3.11+ through an alias),
    # CreateProcess on Windows.  The module is taken from sys.modules because
    # nothing here starts a program with it.
    launcher = sys.modules["subprocess"]
    reached = []

    def never(*args, **_kwargs):
        reached.append(args[0])
        raise RuntimeError("process creation was reached")

    if os.name == "nt":
        monkeypatch.setattr(launcher._winapi, "CreateProcess", never)
        return reached
    monkeypatch.setattr(launcher, "_USE_POSIX_SPAWN", False)
    monkeypatch.setattr(launcher, "_fork_exec", never, raising=False)
    monkeypatch.setattr(sys.modules["_posixsubprocess"], "fork_exec", never)
    return reached


@pytest.fixture(name="macos_controller")
def _macos_controller(monkeypatch):
    """Load the stdlib macOS browser controller on whatever system runs the test."""
    # `webbrowser` declares MacOSXOSAScript only when sys.platform is darwin,
    # so a second copy of the module is executed under that name.  Its open()
    # is the real stdlib code: the `webbrowser.open` event on Python 3.11+, a
    # bare os.popen("/usr/bin/osascript") on Python 3.10.  The class is built
    # directly, not through webbrowser.get(): the first lookup in a process
    # fills the registry and may run `xdg-settings`, an ordinary program that
    # the replaced process creation would refuse for the wrong reason.
    module = types.ModuleType("webbrowser_as_on_macos")
    with monkeypatch.context() as as_macos:
        as_macos.setattr(sys, "platform", "darwin")
        importlib.machinery.SourceFileLoader(module.__name__, STDLIB_WEBBROWSER).exec_module(module)
    return module.MacOSXOSAScript("default")


def test_the_macos_browser_controller_is_refused_on_any_machine(macos_controller, process_creation):
    """Refuse the stdlib macOS controller before it creates a process."""
    with pytest.raises(OSError, match="osascript|webbrowser.open"):
        macos_controller.open("https://example.invalid/")
    assert process_creation == []


@pytest.mark.allow_host_programs
def test_without_the_guard_the_controller_reaches_process_creation(macos_controller, process_creation):
    """Show that only the guard stands between the controller and a process."""
    # The same call, with the guard switched off for this test, arrives at the
    # replaced process creation: the refusal above is the guard's doing, and
    # the replacement really sits on the path a launch takes.
    with pytest.raises(RuntimeError, match="process creation was reached"):
        macos_controller.open("https://example.invalid/")
    assert len(process_creation) == 1


def test_os_system_is_covered():
    """Refuse the same program when it arrives as an `os.system` command."""
    with pytest.raises(FileNotFoundError, match="winget"):
        sys.audit("os.system", "winget list")


@pytest.mark.parametrize("event", ["webbrowser.open", "os.startfile"])
def test_opening_something_on_the_desktop_is_refused(event):
    """Refuse to hand a URL or file to the desktop."""
    with pytest.raises(OSError, match=event):
        sys.audit(event, "https://example.invalid/")
    assert guard.refused[-1] == (event, this_test())


@pytest.mark.allow_host_programs
@pytest.mark.parametrize("event", ["webbrowser.open", "os.startfile"])
def test_a_marked_test_may_open_the_desktop(event):
    """Step aside for a test that carries the marker."""
    sys.audit(event, "https://example.invalid/")


def test_ordinary_programs_are_let_through_and_counted():
    """Count, and do not stop, a program that is not on the list."""
    name = guard.program_name(sys.executable)
    before = guard.started[name]
    launch(sys.executable, "-c", "pass")
    assert guard.started[name] == before + 1


@pytest.mark.allow_host_programs
def test_a_marked_test_may_start_a_host_program():
    """Let a marked test start a listed program, and count it as started."""
    before = (guard.started["tailscale"], len(guard.refused))
    launch("tailscale", "status")
    assert (guard.started["tailscale"], len(guard.refused)) == (before[0] + 1, before[1])


def test_the_marker_does_not_leak_into_the_next_test():
    """Arm the guard again once a marked test has finished."""
    assert not guard._permitted()


def test_the_run_wide_switch_lets_host_programs_start(monkeypatch):
    """Honour ARENA_TEST_ALLOW_HOST_PROGRAMS=1 for the whole run."""
    monkeypatch.setattr(guard, "_allowed_for_run", True)
    launch("specify", "check")
    sys.audit("os.startfile", "report.html")


def test_the_report_lists_what_was_refused(tmp_path):
    """Write the refused launch and the worker name into the report."""
    with pytest.raises(FileNotFoundError):
        launch("specify", "check")
    guard.write_report("gw9", str(tmp_path / "report"))
    report = json.loads((tmp_path / "report.gw9.json").read_text(encoding="utf-8"))
    assert report["worker"] == "gw9"
    assert {"program": "specify", "test": this_test()} in report["refused"]


def test_the_report_names_the_test_file_that_started_a_program(tmp_path):
    """Say which test file started a program: a count alone fixes nothing."""
    # #376: nineteen `py` launches in a run, one test file behind the download.
    name = guard.program_name(sys.executable)
    launch(sys.executable, "-c", "pass")
    guard.write_report("gw9", str(tmp_path / "report"))
    report = json.loads((tmp_path / "report.gw9.json").read_text(encoding="utf-8"))
    assert report["started"][name] >= 1
    assert report["started_by"][name]["tests/test_host_process_guard.py"] >= 1


def test_no_report_is_written_unless_asked(tmp_path, monkeypatch):
    """Leave no file behind when no report path was given."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(guard, "_report_path", None)
    guard.write_report("main")
    assert list(tmp_path.iterdir()) == []


def test_installing_the_guard_forbids_the_python_manager_to_install(monkeypatch):
    """Tell the Windows Python install manager not to download a runtime."""
    # #376: a version probe of `python3`/`pip` put Python 3.15 into the
    # checkout.  The probe may run; the download may not.  The setting lives
    # in os.environ, which every child process inherits.
    monkeypatch.setattr(guard, "_allowed_for_run", guard._allowed_for_run)
    monkeypatch.setattr(guard, "_report_path", guard._report_path)
    monkeypatch.setenv(guard.NO_INSTALL_VARIABLE, "true")
    guard.install()
    assert os.environ[guard.NO_INSTALL_VARIABLE] == "false"


def test_the_switches_are_harness_variables():
    """Keep the switches under the prefix conftest leaves in the environment."""
    # Any other `ARENA_*` name is hidden as ambient configuration and would
    # never reach an xdist worker.
    assert guard.ALLOW_VARIABLE.startswith("ARENA_TEST_")
    assert guard.REPORT_VARIABLE.startswith("ARENA_TEST_")


def test_the_plugin_is_wired_into_this_run(request):
    """Prove conftest loaded the plugin: marker known, fixture active."""
    assert request.config.pluginmanager.has_plugin("tests._host_process_guard")
    assert "_no_host_programs" in request.fixturenames
    assert any(line.startswith(guard.ALLOW_MARKER) for line in request.config.getini("markers"))

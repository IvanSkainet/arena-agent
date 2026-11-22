"""The suite must not start programs that belong to the developer's machine (#376)."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from tests import _host_process_guard as guard


@pytest.fixture(autouse=True)
def guard_is_armed(monkeypatch):
    """These tests describe the armed guard, also in a run that switched it off."""
    monkeypatch.setattr(guard, "_allowed_for_run", False)


@pytest.mark.parametrize(
    ("executable", "args", "expected"),
    [
        (None, ["tailscale", "status"], ["tailscale"]),
        (None, [r"C:\Program Files\Tailscale\tailscale.exe", "status"], ["tailscale"]),
        (r"C:\Windows\System32\cmd.exe", 'cmd.exe /c "browser-act --version"', ["cmd", "browser-act"]),
        (None, "cmd.exe /c winget list", ["cmd", "winget"]),
        ("/bin/sh", ["/bin/sh", "-c", "specify check"], ["sh", "specify"]),
        (None, '"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe" --new-window', ["msedge"]),
        (None, [sys.executable, "-c", "pass"], [guard.program_name(sys.executable)]),
        (None, [], []),
    ],
)
def test_programs_are_read_from_the_command(executable, args, expected):
    assert guard.programs_in(executable, args) == expected


def test_every_listed_name_is_already_normalised():
    assert {guard.program_name(name) for name in guard.HOST_PROGRAMS} == set(guard.HOST_PROGRAMS)


def test_a_host_program_counts_as_not_installed():
    before = len(guard.refused)
    with pytest.raises(FileNotFoundError, match="treated as not installed"):
        subprocess.run(["tailscale", "status"], check=False)
    assert guard.refused[before:] == [("tailscale", os.environ["PYTEST_CURRENT_TEST"])]


def test_a_host_program_behind_a_shell_is_refused_too():
    with pytest.raises(FileNotFoundError, match="browser-act"):
        subprocess.run("browser-act --version", shell=True, check=False)


def test_os_system_is_covered():
    with pytest.raises(FileNotFoundError, match="winget"):
        os.system("winget list")  # noqa: S605,S607 - the call must not get as far as a shell


@pytest.mark.parametrize("event", ["webbrowser.open", "os.startfile"])
def test_opening_something_on_the_desktop_is_refused(event):
    """Called on the hook itself: whether the standard library raises these
    events depends on the platform and on a browser being registered."""
    with pytest.raises(OSError, match=event):
        guard._audit(event, ("https://example.invalid/",))
    assert guard.refused[-1] == (event, os.environ["PYTEST_CURRENT_TEST"])


@pytest.mark.allow_host_programs
@pytest.mark.parametrize("event", ["webbrowser.open", "os.startfile"])
def test_a_marked_test_may_open_the_desktop(event):
    guard._audit(event, ("https://example.invalid/",))


def test_ordinary_programs_still_run_and_are_counted():
    name = guard.program_name(sys.executable)
    before = guard.started[name]
    done = subprocess.run([sys.executable, "-c", "print('ok')"], capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "ok"
    assert guard.started[name] == before + 1


@pytest.mark.allow_host_programs
def test_a_marked_test_reaches_the_real_lookup():
    """With the marker the guard steps aside; a made-up name then fails for the
    ordinary reason, which proves the call left the guard."""
    assert guard._permitted()
    with pytest.raises(FileNotFoundError) as caught:
        subprocess.run(["arena-no-such-program-376"], check=False)
    assert "treated as not installed" not in str(caught.value)


def test_the_marker_does_not_leak_into_the_next_test():
    assert not guard._permitted()


def test_the_report_lists_started_and_refused(tmp_path):
    with pytest.raises(FileNotFoundError):
        subprocess.run(["specify", "check"], check=False)
    guard.write_report("gw9", str(tmp_path / "report"))
    text = (tmp_path / "report.gw9.json").read_text(encoding="utf-8")
    assert '"program": "specify"' in text
    assert '"worker": "gw9"' in text


def test_the_report_names_the_test_file_that_started_a_program(tmp_path):
    """A count alone does not say which test to fix (#376: nineteen `py`
    launches, one of which installed an interpreter into the checkout)."""
    name = guard.program_name(sys.executable)
    subprocess.run([sys.executable, "-c", "pass"], check=True)
    guard.write_report("gw9", str(tmp_path / "report"))
    report = json.loads((tmp_path / "report.gw9.json").read_text(encoding="utf-8"))
    assert report["started_by"][name]["tests/test_host_process_guard.py"] >= 1


def test_no_report_is_written_unless_asked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(guard, "_report_path", None)
    guard.write_report("main")
    assert list(tmp_path.iterdir()) == []


def test_installing_the_guard_forbids_the_python_manager_to_install(monkeypatch):
    """#376: a version probe of `python3`/`pip` downloaded Python 3.15 into the
    checkout.  The probe may run; the download may not, also in children."""
    monkeypatch.setattr(guard, "_allowed_for_run", guard._allowed_for_run)
    monkeypatch.setattr(guard, "_report_path", guard._report_path)
    monkeypatch.setenv(guard.NO_INSTALL_VARIABLE, "true")
    guard.install()
    assert os.environ[guard.NO_INSTALL_VARIABLE] == "false"
    child = subprocess.run(
        [sys.executable, "-c", f"import os; print(os.environ[{guard.NO_INSTALL_VARIABLE!r}])"],
        capture_output=True, text=True, check=True)
    assert child.stdout.strip() == "false"


def test_the_switches_are_harness_variables():
    """`ARENA_TEST_*` is the prefix conftest leaves in the environment, so the
    switches reach xdist workers instead of being hidden as ambient settings."""
    assert guard.ALLOW_VARIABLE.startswith("ARENA_TEST_")
    assert guard.REPORT_VARIABLE.startswith("ARENA_TEST_")

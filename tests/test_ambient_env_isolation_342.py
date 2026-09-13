"""The suite must not read the developer's own `ARENA_*` configuration.

#342: `resolve_token` consults `ARENA_TOKEN_FILE` before the path it was
handed, so on a machine where the bridge is installed
`test_resolve_token_reports_chmod_failure` exercised the real token file
and never reached the branch it was written for. It failed on the
developer machine and passed in CI, because hosted runners start clean.

That asymmetry is the expensive part. Every merge in this repo is gated
on a live run compared against a baseline of known failures by test id;
a test that fails only outside CI enters that baseline and stays there,
and each id parked in the baseline is one that can no longer report a
real regression. So these tests are about the measuring instrument, not
only about the two tests that were misreading.

The isolation is deliberately a `pytest_configure` hook rather than an
autouse fixture: `arena/agent_helpers/files.py` evaluates
`ROOT = get_agent_home()` at module scope, so by the time any fixture
runs the constant has already been computed from the leaked value.
"""
from __future__ import annotations

import os
import subprocess  # nosec B404 -- fixed argv built below, never a shell
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def suite_conftest(request: pytest.FixtureRequest) -> ModuleType:
    """The live `tests/conftest.py`, as pytest loaded it.

    Same approach as `tests/test_no_network_guard_331.py`: ask the plugin
    manager rather than re-importing, so this is the module object the
    running suite actually installed.
    """
    module = request.config.pluginmanager.get_plugin(
        str(Path(__file__).resolve().parent / "conftest.py"))
    assert module is not None, (
        "tests/conftest.py is not among the loaded plugins, so the "
        "environment isolation is not installed"
    )
    return module


def test_an_inherited_value_does_not_reach_a_running_test(tmp_path):
    """The property itself: what the shell exported is not visible.

    Run in a subprocess because the bug is in what the environment looks
    like *before* pytest starts. Asserting `os.environ` from inside this
    file would instead measure what earlier tests in the same session
    left behind -- a real but separate defect (#348), and one that would
    make this test fail for a reason that has nothing to do with #342.
    """
    probe = tmp_path / "test_probe.py"
    probe.write_text(
        "import os\n"
        "def test_ambient_is_hidden():\n"
        "    assert 'ARENA_TOKEN_FILE' not in os.environ\n"
        "    assert os.environ.get('ARENA_INSECURE_TLS') is None\n",
        encoding="utf-8",
    )
    polluted = dict(os.environ)
    polluted["ARENA_TOKEN_FILE"] = str(tmp_path / "token.txt")
    polluted["ARENA_INSECURE_TLS"] = "1"

    completed = subprocess.run(  # nosec B603 -- fixed argv, no shell
        [sys.executable, "-m", "pytest", str(probe),
         "--no-cov", "-p", "no:randomly", "-p", "no:cacheprovider", "-q",
         "-c", str(REPO_ROOT / "pyproject.toml"),
         "--rootdir", str(REPO_ROOT), "-p", "tests.conftest"],
        cwd=REPO_ROOT,
        env=polluted,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, (
        "an ARENA_* value exported by the shell reached a test:\n"
        + completed.stdout[-2000:]
    )


def test_the_harness_owned_names_are_left_alone(suite_conftest):
    """Clearing everything would disarm the guards CI relies on.

    `ARENA_TEST_EXECUTION_GUARD` arms the collection floor in
    `ci.yml`; the e2e job points `ARENA_E2E_SERVER_CMD` at the wheel it
    just built. Removing those would make the run pass while checking
    less, which is the failure mode this repo cares most about.
    """
    owned = suite_conftest._HARNESS_OWNED_VARIABLES
    assert "ARENA_TEST_EXECUTION_GUARD" in owned
    assert "ARENA_E2E_SERVER_CMD" in owned


def test_an_inherited_value_is_reported_as_ambient(monkeypatch, suite_conftest):
    """A name arriving from the shell is one the suite should hide."""
    monkeypatch.setenv("ARENA_TOKEN_FILE", "/nowhere/token.txt")
    assert "ARENA_TOKEN_FILE" in suite_conftest._ambient_arena_variables()


def test_a_harness_owned_value_is_not_reported_as_ambient(
        monkeypatch, suite_conftest):
    """...but the harness's own knobs are not."""
    monkeypatch.setenv("ARENA_TEST_EXECUTION_GUARD", "1")
    assert "ARENA_TEST_EXECUTION_GUARD" not in (
        suite_conftest._ambient_arena_variables())


def test_a_non_arena_variable_is_left_alone(monkeypatch, suite_conftest):
    """The sweep is scoped to this project's own namespace.

    `PATH`, `HOME` and the CI runner's own variables are not ours to
    clear, and a test that needs them must keep working.
    """
    monkeypatch.setenv("TOKEN_FILE", "/nowhere/token.txt")
    assert "TOKEN_FILE" not in suite_conftest._ambient_arena_variables()


def test_a_test_can_still_set_the_variable_itself(monkeypatch):
    """Isolation removes inherited values; it does not forbid setting one.

    The distinction matters: 58 test modules configure `ARENA_*` with
    `monkeypatch.setenv` on purpose, and clearing per-test would break
    every one of them.
    """
    monkeypatch.setenv("ARENA_TOKEN_FILE", "/chosen/by/the/test")
    assert os.environ["ARENA_TOKEN_FILE"] == "/chosen/by/the/test"


@pytest.mark.parametrize(
    ("variable", "value", "target"),
    [
        (
            "ARENA_TOKEN_FILE",
            "token.txt",
            "tests/test_bootstrap.py::test_resolve_token_reports_chmod_failure",
        ),
        (
            "ARENA_AGENT_HOME",
            "",
            "tests/test_agent_helpers_files_parity_v4_169_35.py"
            "::test_facts_path_shape",
        ),
    ],
)
def test_the_two_known_victims_pass_with_the_variable_set(
        tmp_path, variable, value, target):
    """The regression from #342, run the way it actually reached the user.

    A subprocess rather than `monkeypatch.setenv`, because the bug is in
    what the environment looks like *before* pytest starts: the fix is a
    `pytest_configure` hook and an in-process fixture could not exercise
    it. This is the only shape that would have caught the original.
    """
    polluted = dict(os.environ)
    if value:
        target_file = tmp_path / value
        target_file.write_text("a-valid-looking-token-1234567890",
                               encoding="utf-8")
        polluted[variable] = str(target_file)
    else:
        polluted[variable] = str(tmp_path)

    completed = subprocess.run(  # nosec B603 -- fixed argv, no shell
        [sys.executable, "-m", "pytest", target,
         "--no-cov", "-p", "no:randomly", "-p", "no:cacheprovider", "-q"],
        cwd=REPO_ROOT,
        env=polluted,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, (
        f"{target} fails when {variable} is set in the ambient "
        f"environment:\n{completed.stdout[-2000:]}"
    )

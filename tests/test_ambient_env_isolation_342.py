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
        + completed.stdout[-2000:] + "\n" + completed.stderr[-2000:]
    )


@pytest.mark.parametrize("name", [
    "ARENA_TEST_EXECUTION_GUARD",
    "ARENA_TEST_GIT_TIMEOUT",
    "ARENA_TEST_NODE_TIMEOUT",
    "ARENA_E2E_EXPECT_VERSION",
    "ARENA_E2E_SERVER_CMD",
    "ARENA_SKIP_BROWSER_E2E",
])
def test_the_harness_owned_names_are_left_alone(name, suite_conftest):
    """Clearing these would disarm the guards the run relies on.

    `ARENA_TEST_EXECUTION_GUARD` arms the collection floor in `ci.yml`,
    the e2e job points `ARENA_E2E_SERVER_CMD` at the wheel it just
    built, and `ARENA_SKIP_BROWSER_E2E=1` is how a developer turns
    browser E2E off. Removing any of them makes the run pass while
    checking less -- the failure mode this repo cares most about.
    """
    assert suite_conftest._is_harness_owned(name)


@pytest.mark.parametrize("name", [
    "ARENA_TEST_A_KNOB_ADDED_TOMORROW",
    "ARENA_E2E_TIMEOUT",
])
def test_the_harness_namespaces_are_matched_by_prefix(name, suite_conftest):
    """A new knob in an owned namespace is owned without an edit here.

    Raised in review by coderabbit and by cubic from opposite ends: an
    allowlist of literal names shrinks silently every time someone adds
    a variable, and the resulting breakage is the quiet kind -- the
    suite still passes, it just stops honouring the switch.
    """
    assert suite_conftest._is_harness_owned(name)


def test_the_browser_skip_switch_survives(monkeypatch, suite_conftest):
    """`ARENA_SKIP_BROWSER_E2E=1` must not be cleared into a *run*.

    `tests/e2e/test_dashboard_browser.py:48` reads it in a module-level
    `skipif`, so deleting it turns "skip these" into "run these" with
    no diagnostic at all.
    """
    monkeypatch.setenv("ARENA_SKIP_BROWSER_E2E", "1")
    assert "ARENA_SKIP_BROWSER_E2E" not in (
        suite_conftest._ambient_arena_variables())


def test_an_inherited_value_is_reported_as_ambient(monkeypatch, suite_conftest):
    """A name arriving from the shell is one the suite should hide."""
    monkeypatch.setenv("ARENA_TOKEN_FILE", "/nowhere/token.txt")
    assert "ARENA_TOKEN_FILE" in suite_conftest._ambient_arena_variables()


def test_a_product_name_that_merely_contains_e2e_is_still_ambient(
        monkeypatch, suite_conftest):
    """The prefix must not be read as "contains".

    `ARENA_SKIP_BROWSER_E2E` is owned by name, but a product variable
    that happens to mention E2E is not, and matching loosely would
    quietly re-open the hole this change closes.
    """
    monkeypatch.setenv("ARENA_BRIDGE_E2E_URL", "http://example.invalid")
    assert "ARENA_BRIDGE_E2E_URL" in (
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
        f"environment:\n{completed.stdout[-2000:]}\n"
        f"{completed.stderr[-2000:]}"
    )

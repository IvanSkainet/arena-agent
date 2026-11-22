"""T74: allowlisted environment and truthful CPU metrics."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from arena.governance import benchmark_runner as bench
from tests._benchmark_support import invoke, measurement_fixture as measurement_fixture, report


def bench_private_directories() -> tuple[str, ...]:
    """Name the per-user directories a measurement replaces with its own."""
    return ("HOME", "TMPDIR", "TMP", "TEMP", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
            "XDG_DATA_HOME", "XDG_STATE_HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA")


def test_private_environment_leaves_no_per_user_directory_to_the_checkout(tmp_path, monkeypatch):
    """Keep every per-user directory private and forbid installing Python."""
    # #376: on a Windows PC the measured run left `Python\\` in the checkout.
    # The environment had no LOCALAPPDATA, so the Python install manager
    # behind `python3`/`pip` fell back to the working directory, found no
    # runtime there and downloaded one.
    real = {key: f"operator-{key}" for key in bench_private_directories()}
    monkeypatch.setattr(bench, "os", SimpleNamespace(environ=real))
    actual = bench.private_environment(tmp_path, "Windows")
    for key in bench_private_directories():
        assert Path(actual[key]) == tmp_path / key.lower()
        assert Path(actual[key]).is_dir()
    assert actual["PYTHON_MANAGER_AUTOMATIC_INSTALL"] == "false"
    assert actual["RUNNER_OS"] == "Windows"


def test_private_environment_preserves_only_documented_os_and_locale_controls(tmp_path, monkeypatch):
    allowed = ["PATH", "LANG", "LANGUAGE", "TZ", "TERM", "SHELL", "SYSTEMROOT", "WINDIR",
               "PATHEXT", "COMSPEC", "SSL_CERT_FILE", "SSL_CERT_DIR", "USERNAME",
               "PROGRAMFILES", "PROGRAMFILES(X86)", "LC_ALL", "LC_MESSAGES"]
    values = {key: f"fixture-{key}" for key in allowed}
    monkeypatch.setattr(bench, "os", SimpleNamespace(environ={**values, "UNLISTED_CONTROL": "refused"}))
    actual = bench.private_environment(tmp_path, "Linux")
    assert {key: actual[key] for key in allowed} == values
    assert "UNLISTED_CONTROL" not in actual
    assert actual["ARENA_TEST_EXECUTION_GUARD"] == "1"
    assert actual["RUNNER_OS"] == "Linux"
    assert set(actual) == {*allowed, "ARENA_TEST_EXECUTION_GUARD", "RUNNER_OS",
                           "PYTHON_MANAGER_AUTOMATIC_INSTALL", *bench_private_directories()}
    if sys.platform != "win32":
        import stat

        paths = [Path(value) for key, value in actual.items() if value.startswith(str(tmp_path))]
        assert paths
        assert all(stat.S_IMODE(path.stat().st_mode) == 0o700 for path in paths)



def test_cpu_measurement_sums_child_user_and_system_time(monkeypatch):
    def getrusage(who):
        assert who == "child-fixture"
        return SimpleNamespace(ru_utime=1.5, ru_stime=2.25)

    monkeypatch.setitem(sys.modules, "resource", SimpleNamespace(
        RUSAGE_CHILDREN="child-fixture", getrusage=getrusage))
    assert bench.cpu_seconds() == 3.75
    monkeypatch.setitem(sys.modules, "resource", None)
    assert bench.cpu_seconds() is None



@pytest.mark.parametrize("cpu_values", [(None, None), (None, 3.0), (3.0, None)])
def test_unavailable_cpu_endpoint_is_unknown_not_an_invented_metric(measurement, monkeypatch, cpu_values):
    values = iter(cpu_values)
    monkeypatch.setattr(bench, "cpu_seconds", lambda: next(values))
    assert invoke(measurement) == 0
    assert report(measurement)["child_cpu_seconds"] is None



def test_synthetic_linux_measurement_is_independent_of_windows_resource_shim(measurement, monkeypatch):
    monkeypatch.setitem(sys.modules, "resource", SimpleNamespace())
    assert invoke(measurement) == 0
    assert report(measurement)["child_cpu_seconds"] is None



@pytest.mark.parametrize("name", ["ARENA_TOKEN", "ARENA_STATE_HOME", "ARENA_TEST_LIVE_DEVICE",
                                 "ARENA_E2E_WHEEL", "CI", "GITHUB_ACTIONS", "PYTEST_ADDOPTS",
                                 "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "PYTEST_PLUGINS"])
def test_measurement_does_not_inherit_operator_or_test_selection_controls(measurement, monkeypatch, name):
    monkeypatch.setenv(name, "fixture-private-control")
    assert invoke(measurement) == 0
    assert name not in measurement[3][0][1]["context"].env



def test_measurement_preserves_explicit_browser_skip_request(measurement, monkeypatch):
    monkeypatch.setenv("ARENA_SKIP_BROWSER_E2E", "1")
    assert invoke(measurement) == 0
    assert measurement[3][0][1]["context"].env["ARENA_SKIP_BROWSER_E2E"] == "1"

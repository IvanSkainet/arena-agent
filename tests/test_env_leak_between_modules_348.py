"""No test module may leave `ARENA_*` behind for the next one (#348).

Five modules set `ARENA_AGENT_HOME` with a bare `os.environ[...] = ...`
and never undid it. Two of them do it at module scope, deliberately:
`arena/chat_cli/common.py` and `arena/agent_helpers/files.py` evaluate
their constants at import, so a fixture runs too late and assigning
before the `import` is the only thing that works.

The consequence is that the value stays set for every module collected
*after* them, and `pytest-randomly` reorders collection, so what a
later test reads depends on the seed. That is the machinery behind
"fails once in a while, passes on re-run" -- and the ambient-variable
cleanup from #342 does not help, because it runs once at
`pytest_configure`, before these values exist.

Reproduced before fixing: the same one-line assertion passed or failed
purely on whether it ran before or after
`test_mcp_tool_dispatch_contract.py`.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

_REPOSITORY = Path(__file__).resolve().parents[1]


@pytest.fixture
def suite_conftest(request: pytest.FixtureRequest) -> ModuleType:
    """The live `tests/conftest.py`, as pytest loaded it.

    Not `from tests.conftest import ...`: `tests/` has no
    `__init__.py`, so that statement builds a *second* module object
    whose snapshot dicts are empty, and every assertion below would
    pass by measuring nothing. Confirmed by inspection -- `conftest`
    and `tests.conftest` were two distinct objects in `sys.modules`.
    Same lookup, and same reason, as `test_no_network_guard_331.py`.
    """
    module = request.config.pluginmanager.get_plugin(
        str(Path(__file__).resolve().parent / "conftest.py"))
    assert module is not None, (
        "tests/conftest.py is not among the loaded plugins, so the "
        "environment-leak guard is not installed")
    return module


def test_the_guard_under_test_is_the_one_pytest_loaded(
        suite_conftest: ModuleType) -> None:
    """Guards against the whole file silently measuring nothing.

    A duplicate conftest object has empty snapshots, so every leak
    check here would pass no matter how badly the suite leaked. The
    session-start snapshot is never empty in practice -- pytest's own
    machinery aside, the harness sets `ARENA_*` values of its own --
    but the failure being excluded is reading a module that was never
    populated at all.
    """
    assert suite_conftest.__file__ is not None
    assert Path(suite_conftest.__file__).resolve() == (
        Path(__file__).resolve().parent / "conftest.py")
    assert hasattr(suite_conftest, "_ARENA_AT_SESSION_START"), (
        "the loaded conftest has no session-start snapshot, so the guard "
        "below would compare two empty dicts and always pass")


def test_importing_every_test_module_sets_no_arena_variable(
        suite_conftest: ModuleType) -> None:
    """The deterministic half of the guard.

    Every leak in #348 is a module-level assignment, so it happens
    during collection. Comparing the environment before and after
    collection therefore gives the same answer whatever order
    `pytest-randomly` picks and whatever `-k` selects -- unlike an
    end-of-session check, which only sees the modules that ran.
    """
    leaked = suite_conftest.arena_variables_set_during_collection()

    assert leaked == {}, (
        "importing the test suite changed the ARENA_* environment; a module "
        "is assigning to os.environ at import scope without restoring it, "
        f"which makes later modules depend on collection order: {leaked}")


def test_no_module_changes_an_arena_variable_while_being_imported(
        suite_conftest: ModuleType) -> None:
    """Stricter than the endpoint comparison, and it names the culprit.

    A module can set a value that a later module restores: the
    start/end snapshots then match while every module imported in
    between saw the leak. Reproduced with a throwaway pair -- the
    endpoint check reported `{}`, this one reported both modules.
    """
    changed = suite_conftest.arena_variables_changed_per_module()

    assert changed == {}, (
        "these modules changed the ARENA_* environment while being "
        f"imported, which later modules then inherit: {changed}")


def test_a_module_that_binds_a_tmp_home_does_not_hand_it_to_the_next_importer(
        tmp_path: Path) -> None:
    """Restoring the variable is not enough on its own.

    `arena/agent_helpers/files.py` evaluates `ROOT` at import, so the
    value is frozen into the module object. While that object stays in
    `sys.modules`, the next module to import it is handed the first
    importer's tmp home regardless of what the environment says by
    then -- a second channel the environment snapshot cannot see,
    because the environment is by then perfectly clean.

    Found by shuffling collection order: `test_facts_path_shape` failed
    under two seeds out of three with every ARENA_* variable correctly
    restored.

    The temp directory is `tmp_path`-owned rather than a fresh
    `mkdtemp`, so the subprocess leaves nothing behind in the system
    temp on every run.
    """
    reader = tmp_path / "test_reads_root.py"
    reader.write_text(textwrap.dedent(f'''
        import os
        import sys
        from pathlib import Path

        os.environ["ARENA_AGENT_HOME"] = {str(tmp_path / "first-home")!r}
        import arena.agent_helpers.files  # noqa: E402
        sys.modules.pop("arena.agent_helpers.files", None)
        _package = sys.modules.get("arena.agent_helpers")
        if getattr(_package, "files", None) is not None:
            delattr(_package, "files")
        os.environ.pop("ARENA_AGENT_HOME", None)

        def test_a_later_qualified_import_is_not_given_the_first_tmp_home():
            import arena.agent_helpers.files as reimported
            assert reimported.ROOT == Path.home() / "arena-bridge"

        def test_a_later_import_through_the_parent_package_is_not_either():
            # `sys.modules` is not the only reference: importing a
            # submodule binds it on its parent package too, and this
            # import form reads that attribute. Verified by mutation --
            # dropping only the sys.modules entry fails here.
            from arena.agent_helpers import files
            assert files.ROOT == Path.home() / "arena-bridge"
    '''), encoding="utf-8")

    result = _run_pytest(tmp_path, "test_reads_root.py")

    assert result.returncode == 0, (
        "a module evicted from sys.modules was still handing its tmp home to "
        f"the next importer:\n{result.stdout}")


def test_the_end_of_session_guard_is_a_hook_not_a_test(tmp_path: Path) -> None:
    """The session-end check must not itself depend on collection order.

    Written first as a test, which was wrong in the way this file is
    about: a test only sees what ran before it, so reintroducing a leak
    left it green whenever `pytest-randomly` collected it first.
    Verified by mutation -- `M_reload_after_restore` survived the
    test-shaped version and is caught by the hook.

    Exercised out-of-process, because a leak inside this session is
    precisely what must not happen.
    """
    leaking = tmp_path / "test_leaks_at_teardown.py"
    leaking.write_text(textwrap.dedent('''
        import os

        def test_sets_and_forgets():
            os.environ["ARENA_LEAKED_BY_A_FIXTURE"] = "1"
    '''), encoding="utf-8")

    result = _run_pytest(tmp_path, "test_leaks_at_teardown.py")

    assert result.returncode != 0, (
        "a run whose tests all passed but which leaked ARENA_* was expected "
        f"to exit non-zero:\n{result.stdout}")
    assert "ARENA_LEAKED_BY_A_FIXTURE" in result.stdout, (
        f"the leaked name was not named in the report:\n{result.stdout}")


def test_a_clean_run_is_not_reported_as_leaking(tmp_path: Path) -> None:
    """The control: the hook must not fail every run it sees.

    Without it "leaking runs exit non-zero" is also satisfied by a hook
    that fails unconditionally, and the suite would be red for a reason
    nobody could read.
    """
    clean = tmp_path / "test_touches_nothing.py"
    clean.write_text(textwrap.dedent('''
        def test_placeholder():
            assert True
    '''), encoding="utf-8")

    result = _run_pytest(tmp_path, "test_touches_nothing.py")

    assert result.returncode == 0, (
        f"a run that leaked nothing was reported as leaking:\n{result.stdout}")


def _run_pytest(tmp_path: Path, *files: str) -> subprocess.CompletedProcess[str]:
    """Run pytest in `tmp_path` with this repository's conftest loaded.

    The conftest is copied in rather than inherited: pytest only picks
    up `conftest.py` from the rootdir and the collected paths, and
    `tmp_path` is under neither. Without the copy the guard being
    tested is simply absent from the subprocess, and the test would
    pass by measuring nothing.
    """
    conftest = tmp_path / "conftest.py"
    if not conftest.exists():
        conftest.write_text(
            (_REPOSITORY / "tests" / "conftest.py").read_text(encoding="utf-8"),
            encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "pytest", *files,
         "--no-cov", "-p", "no:randomly", "-p", "no:cacheprovider", "-q"],
        cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, "PYTHONPATH": str(_REPOSITORY)}, timeout=120)


@pytest.fixture
def a_leaking_module(tmp_path: Path) -> Path:
    """A miniature of the #348 defect: assignment at import, no undo."""
    leaking = tmp_path / "test_aaa_leaks.py"
    leaking.write_text(textwrap.dedent('''
        import os
        os.environ["ARENA_AGENT_HOME"] = "/leaked/from/another/module"

        def test_placeholder():
            assert True
    '''), encoding="utf-8")
    reader = tmp_path / "test_zzz_reads.py"
    reader.write_text(textwrap.dedent('''
        import os

        def test_sees_only_its_own_environment():
            assert os.environ.get("ARENA_AGENT_HOME") != "/leaked/from/another/module"
    '''), encoding="utf-8")
    return tmp_path


def test_a_leak_really_does_change_what_a_later_module_reads(
        a_leaking_module: Path) -> None:
    """The control, and the reproduction of the original defect.

    Without it the two guards above are satisfied by a suite that
    leaks nothing because nothing ever sets anything.

    Note what this measures. pytest imports *every* selected module
    before running *any* test, so the reader fails even when it runs
    first -- being collected second is enough. That is what makes the
    defect so slippery: it is not "the leaking test ran before mine",
    it is "the leaking file was collected at all", and with
    `pytest-randomly` shuffling collection, a single-file re-run then
    passes and the report looks like a flake.

    So the honest control is the presence of the leaking module, not
    the order of the two tests within the run.
    """
    together = _run_pytest(a_leaking_module, "test_aaa_leaks.py", "test_zzz_reads.py")
    alone = _run_pytest(a_leaking_module, "test_zzz_reads.py")

    assert together.returncode != 0, (
        "the reader was expected to fail once the leaking module was "
        f"collected alongside it:\n{together.stdout}")
    assert alone.returncode == 0, (
        "the reader was expected to pass on its own -- if it fails here the "
        f"fixture is wrong, not the suite:\n{alone.stdout}")

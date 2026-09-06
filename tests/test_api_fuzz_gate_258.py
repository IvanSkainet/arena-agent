"""The fuzzing gate has to keep meaning what it says (#258).

Schemathesis found #254 in 2.3 seconds, and the first gated run of it found
ten more 5xx that fourteen source scanners had not: the defects are runtime,
so nothing that reads the code can see them. This module guards the parts of
that setup that can quietly stop working -- a gate that no longer tests
anything still reports success, which is worse than not having one.

Three failure modes, one test each:

* the exception list drifts away from the operations that actually need a
  local tool, so a real 500 is allowed through as "documented 503";
* the fuzzer is pointed at a bridge whose limiters answer 429 to everything,
  so the run is green because almost nothing reached a handler;
* the job stops running the config, or the config stops naming the checks
  the measurement in #258 said were ready.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import tomllib

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "schemathesis.toml"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SERVER_PATH = REPO_ROOT / "scripts" / "serve_bridge_for_fuzzing.py"


@pytest.fixture(scope="module")
def config() -> dict:
    return tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fuzz_job() -> dict:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert "api-fuzz" in workflow["jobs"], "the fuzzing job is gone"
    return workflow["jobs"]["api-fuzz"]


def _operations_allowed_a_503(config: dict) -> set[str]:
    allowed = set()
    for operation in config.get("operations", []):
        statuses = (operation.get("checks", {})
                    .get("not_a_server_error", {})
                    .get("expected-statuses", []))
        if 503 in statuses:
            allowed.add(operation["include-name"])
    return allowed


def test_the_503_exceptions_are_exactly_the_operations_that_need_a_tool():
    """One list of tool-dependent operations, not two that drift.

    A 503 is allowed per operation rather than globally, because globally it
    would hide a real outage. That only holds while this list matches the
    one the document is built from -- an operation added to `_NEEDS_LOCAL_TOOL`
    and forgotten here turns the gate red for a documented answer, and one
    left here after its tool dependency goes away lets a genuine 503 pass.
    """
    from arena.public.openapi import _NEEDS_LOCAL_TOOL

    config = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    expected = {f"{method.upper()} {path}" for method, path in _NEEDS_LOCAL_TOOL}
    assert _operations_allowed_a_503(config) == expected


def test_the_gate_still_watches_for_server_errors(config):
    """The one check the measurement said was ready.

    `[checks] enabled = false` switches everything off, so a typo in the
    line that switches this one back on would leave a job that runs, passes,
    and asserts nothing at all.
    """
    checks = config["checks"]
    assert checks["enabled"] is False, "the other checks are not ready yet (#258)"
    assert checks["not_a_server_error"]["enabled"] is True


def test_the_token_endpoint_stays_out_of_the_run(config):
    """Fuzzing it ends the run: every later request carries a dead token.

    Measured -- the run that reached it reported six failures where the same
    run without it reported thirteen. The other seven were not fixed by
    calling it, they were hidden behind 401s.
    """
    disabled = {operation["include-name"]
                for operation in config.get("operations", [])
                if operation.get("enabled") is False}
    assert "POST /v1/token/regenerate" in disabled


def test_the_server_neutralises_both_limiters():
    """A fuzzer sharing one IP with itself trips both, and then tests nothing.

    The per-IP limiter allows 300 requests a minute against a run that sends
    thousands; the failed-auth throttle answers 429 to an address after ten
    rejected requests, which the coverage phase produces on purpose. Both
    are covered by their own tests -- what must not happen is a green run
    that never got past them.
    """
    source = SERVER_PATH.read_text(encoding="utf-8")
    assert '_rl_v2_config["enabled"] = False' in source
    assert "auth_fail:" in source


def test_the_server_runs_somewhere_disposable():
    """Parts of the bridge resolve paths against the process's own cwd.

    A run started from a checkout wrote `missions/[None, None]/`,
    `queue/running/*.json` and a live `token.txt` into the repository -- the
    fuzzer reaching the token endpoint through a relative path. The chdir is
    what keeps that inside the temporary root.
    """
    source = SERVER_PATH.read_text(encoding="utf-8")
    assert "os.chdir(root)" in source


def test_the_job_installs_hashes_and_starts_the_bridge_before_fuzzing(fuzz_job):
    """The shape Scorecard and the run both depend on.

    Unpinned installs are how a supply-chain swap lands with nothing turning
    red, and a fuzz run against a bridge that has not finished starting is a
    connection error dressed up as a pass.
    """
    steps = fuzz_job["steps"]
    runs = "\n".join(step.get("run", "") for step in steps)
    assert "--require-hashes -r requirements-fuzz.lock" in runs
    assert "--require-hashes -r requirements-ci.lock" in runs
    assert "serve_bridge_for_fuzzing.py" in runs
    assert "schemathesis run" in runs
    names = [step.get("name", "") for step in steps]
    assert names.index("Start the bridge") < names.index("Fuzz the documented API")


def test_the_seed_changes_between_runs(fuzz_job):
    """A fixed seed would test the same 4000 requests forever.

    Schemathesis is random, and pinning the seed turns a fuzzer into a
    fixture: the run that passes today passes tomorrow having explored not
    one new shape. `GITHUB_RUN_NUMBER` moves it every time while keeping any
    single failure reproducible -- the number is printed in the summary.
    """
    runs = "\n".join(step.get("run", "") for step in fuzz_job["steps"])
    assert "--seed \"${GITHUB_RUN_NUMBER}\"" in runs

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
  the measurement in #258 said were ready;
* the bridge under test writes into the checkout instead of its throwaway
  root, which is how a live token reached the repository once already.

PyYAML is imported normally, not through `pytest.importorskip`. AGENTS.md
forbids the latter for a gate dependency and greptile and cubic both caught
it here: skipping the module when the parser is missing means the gate
reports success having asserted nothing, which is the failure this file
exists to prevent. PyYAML is in requirements-ci.lock.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

from tests._git_budget import git_timeout

try:  # 3.11+ ships it; the 3.10 matrix cell installs tomli instead
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only on Python 3.10
    import tomli as tomllib

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


def test_the_second_batch_of_checks_is_on(config):
    """Step 2 of #258: the answer has to be one the document admits to.

    Turning these on took a fix per finding rather than an allowance
    (GET /v1/events answering an undocumented 400, plus 35 status codes
    the document simply never mentioned), so an `enabled = false` sneaking
    back in would quietly return the operations to being undocumented.
    """
    assert config["checks"]["status_code_conformance"]["enabled"] is True
    assert config["checks"]["unsupported_method"]["enabled"] is True


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


@pytest.mark.timeout(120)
def test_the_run_leaves_nothing_in_the_checkout():
    """Started for real, asked to write, and the checkout checked afterwards.

    Not a source-text assertion: the first two attempts at this *looked*
    isolated and were not. A chdir does not move `TOKEN_FILE`, which hangs
    off the source tree, so POST /v1/token/regenerate wrote a live token
    beside the code; `ARENA_AGENT_HOME` was missing, so mission and queue
    files landed in the repository. Both are things only a running bridge
    can demonstrate.

    """
    # Captured before the process starts: anything the bridge writes while
    # starting up is exactly what this test is about, and a baseline taken
    # after Popen would accept it as pre-existing (CodeRabbit).
    before = _bridge_written_paths()
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(SERVER_PATH), "--port", str(port)],
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "ARENA_FUZZ_TOKEN": "isolation-probe",
             "PYTHONDONTWRITEBYTECODE": "1"})
    try:
        _wait_until_listening(proc, port)
        # The two endpoints that wrote outside the workspace before #258:
        # one creates a mission directory, the other issues a token file.
        # Their status codes are asserted, so a probe that never reached a
        # handler fails the test instead of passing it quietly -- and the
        # token endpoint goes last, because it invalidates the credential
        # the previous line is using.
        # Three endpoints, three different destinations: a mission directory,
        # an audit line, and the token file. The audit one matters because a
        # sabotage test showed the check passing when only `TOKEN_FILE` was
        # redirected back -- nothing had written an audit entry yet.
        assert _post(port, "/v1/mission/compose",
                     {"goal": "isolation", "create": True}) == 200
        assert _post(port, "/v1/exec", {"cmd": "echo isolation"}) == 200
        assert _post(port, "/v1/token/regenerate", {}) == 200
    finally:
        proc.terminate()
        proc.wait(timeout=30)

    appeared = sorted(_bridge_written_paths() - before)
    assert appeared == [], f"the fuzz bridge wrote into the checkout: {appeared}"


@pytest.mark.timeout(120)
@pytest.mark.skipif(os.name != "posix",
                    reason="SIGTERM and mode bits are the POSIX half of this")
def test_the_workspace_is_private_and_goes_away_when_the_run_is_killed():
    """Both halves of what the temporary workspace has to guarantee.

    It holds `token.txt`, the audit log and every `ARENA_AGENT_HOME` file
    while the run lasts, in a directory other local users can list -- so
    0o700, not the umask default (cubic). And CI stops this process with
    SIGTERM, which by default takes the workspace to the grave with it,
    one directory per run.

    A source-text check would have missed both: the mode came from
    `mkdtemp`, which an edit replaced, and the signal path only exists in
    a live process.
    """
    import glob
    import signal
    import stat

    pattern = str(Path(tempfile.gettempdir()) / "fuzz-root-*")
    before = set(glob.glob(pattern))
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(SERVER_PATH), "--port", str(port)],
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "ARENA_FUZZ_TOKEN": "workspace-probe",
             "PYTHONDONTWRITEBYTECODE": "1"})
    try:
        _wait_until_listening(proc, port)
        created = sorted(set(glob.glob(pattern)) - before)
        assert len(created) == 1, f"expected one workspace, got {created}"
        mode = stat.S_IMODE(os.stat(created[0]).st_mode)
        assert mode == 0o700, f"workspace is {oct(mode)}, not 0o700"
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=60)

    left = sorted(set(glob.glob(pattern)) - before)
    assert left == [], f"SIGTERM left the workspace behind: {left}"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until_listening(proc: subprocess.Popen, port: int) -> None:
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            raise AssertionError(f"the bridge exited: {proc.communicate()[0]}")
        with socket.socket() as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    raise AssertionError("the bridge did not start within 60s")


def _post(port: int, path: str, body: dict) -> int:
    """POST to the bridge and return the status.

    Returns rather than swallows: the first version suppressed every HTTP
    and URL error, so a bridge that answered 500 -- or was not there at all
    -- still let the test pass with an empty diff (CodeRabbit). A 4xx is
    returned as itself so the caller can insist on what it expects.
    """
    url = f"http://127.0.0.1:{port}{path}"
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer isolation-probe",
                 "Content-Type": "application/json"})
    try:
        # The URL is a literal `http://127.0.0.1:` with an int port and a
        # path from this file, so bandit's B310 -- `urlopen` reaching
        # `file:` or a custom scheme -- cannot happen here. The guard that
        # used to say so in code was unreachable, which cubic called dead
        # and was right about.
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310  # nosec B310
            response.read()
            return int(response.status)
    except urllib.error.HTTPError as err:
        err.read()
        return int(err.code)


# What a bridge writes when it is pointed at the wrong place. Watching these
# rather than the whole checkout is deliberate: a full `git status` diff also
# catches whatever *other* tests are doing at that moment -- on Windows this
# test failed because a neighbour had just left `scripts/_global_patch_probe.py`
# behind (#276), which says nothing about the fuzz bridge.
#
# The completeness of this list is not assumed, it is checked: the test below
# derives the same set from `ArenaPaths` plus the three `arena.constants`
# files, so a new workspace directory in the bridge cannot slip past the
# isolation gate unnoticed (cubic).
BRIDGE_WRITES = (
    "token.txt", "audit.jsonl", "bridge.log", "requests.jsonl",
    "webhooks.json", "missions", "reports", "queue", "mission_schedules",
    "memory", "skills", "hooks", "agents", "subagents", "relay",
)


def test_the_watched_paths_cover_everything_the_bridge_derives(monkeypatch):
    """`BRIDGE_WRITES` against the bridge's own idea of its workspace.

    A hardcoded list is only as good as the day it was written; this asks
    `ArenaPaths` -- the thing that actually decides where the bridge puts
    its state -- and requires every entry it produces to be watched. A new
    directory added to the layout fails here rather than quietly falling
    outside the isolation check (cubic).
    """
    import dataclasses

    from arena.paths import ArenaPaths

    # `from_env` prefers ARENA_AGENT_HOME over its argument, and another test
    # in the same session may have set it -- on CI that turned this check
    # into a comparison against someone else's temporary directory.
    monkeypatch.delenv("ARENA_AGENT_HOME", raising=False)
    # A name, not a real directory: `from_env` only joins strings, and a
    # literal "/tmp/..." reads to bandit as code that writes there (B108).
    probe_root = Path(tempfile.gettempdir()) / "arena-paths-probe"
    paths = ArenaPaths.from_env(probe_root)
    # Every field, read off the dataclass rather than listed by hand: the
    # hand-written version had already lost `relay_dir` by the time cubic
    # pointed at it, which is the same failure this test exists to prevent,
    # one level up. `root_agent` is the workspace itself, not something
    # inside it.
    derived = {
        getattr(paths, field.name) for field in dataclasses.fields(paths)
        if field.name != "root_agent"
    }
    derived |= _constant_paths(probe_root)
    root = probe_root.as_posix() + "/"
    unwatched = sorted(
        str(path) for path in derived
        if not any(str(path).replace("\\", "/").startswith(root + name)
                   for name in BRIDGE_WRITES)
    )
    assert unwatched == [], (
        "these workspace paths are not covered by BRIDGE_WRITES, so the "
        f"isolation test would not notice them: {unwatched}")


def _constant_paths(root: Path) -> set[Path]:
    """The three files `arena.constants` puts beside the source tree.

    `ArenaPaths` does not know about them -- that is exactly why the fuzz
    runner has to repoint them by hand -- so the coverage check asks for
    them separately rather than claiming the dataclass covers everything
    (cubic).
    """
    return {root / "token.txt", root / "audit.jsonl", root / "bridge.log"}


def _bridge_written_paths() -> set[str]:
    """The paths in the checkout that a misdirected bridge would create.

    `__pycache__` is excluded on top of PYTHONDONTWRITEBYTECODE: importing
    the bridge writes bytecode, and that is Python doing its job rather than
    the bridge writing where it should not (cubic). Nothing in
    `BRIDGE_WRITES` can be a `.pyc`, so the exclusion cannot hide a real
    leak -- it only keeps the check from arguing with the interpreter.
    """
    listing = subprocess.run(
        ["git", "status", "--porcelain", "--ignored=matching"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        timeout=git_timeout())
    seen = set()
    for line in listing.stdout.splitlines():
        path = line[3:].strip().strip('"').replace("\\", "/")
        if "__pycache__" in path or path.endswith(".pyc"):
            continue
        if any(path == name or path.startswith(name + "/") for name in BRIDGE_WRITES):
            seen.add(path)
    return seen


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


def test_the_release_contract_lists_the_fuzz_cache(fuzz_job):
    """RELEASE.md is the contract; the exclusion has to be in both places.

    `.gitignore` keeps the cache out of commits and `make_release_zip.py`
    keeps it out of the archive, but the document that says what a release
    contains is what a person reads before cutting one (cubic).
    """
    release = (REPO_ROOT / "RELEASE.md").read_text(encoding="utf-8")
    assert ".schemathesis/" in release
    excluded = (REPO_ROOT / "scripts" / "make_release_zip.py").read_text(encoding="utf-8")
    assert '".schemathesis"' in excluded


def test_the_fuzzer_is_pointed_at_the_bridge_explicitly(fuzz_job):
    """`--url`, because the document does not describe where the run is.

    The served schema advertises `servers: [{"url": "http://<host>:8765"}]`
    -- the address the operator's bridge answers on, not the throwaway one
    the job starts on 127.0.0.1:8899. Schemathesis currently prefers the
    location it fetched the schema from, so the run works either way, but
    "currently prefers" is not something a required gate should rest on: the
    failure mode is thousands of requests into the void and a green result
    (cubic).
    """
    runs = "\n".join(step.get("run", "") for step in fuzz_job["steps"])
    assert "--url http://127.0.0.1:8899" in runs


def test_the_bridge_token_is_generated_rather_than_written_down(fuzz_job):
    """A token in the workflow is a known credential for a live bridge.

    The bridge under test grants shell, file and desktop access. It listens
    on 127.0.0.1 of an ephemeral runner, so the exposure is small, but a
    fixed string buys nothing in exchange for it (cubic). Generated per run
    and masked, so it is neither guessable nor visible in the log.
    """
    runs = "\n".join(step.get("run", "") for step in fuzz_job["steps"])
    assert "secrets.token_urlsafe" in runs
    assert "::add-mask::" in runs
    envs = " ".join(str(step.get("env", "")) for step in fuzz_job["steps"])
    assert "ci-fuzz-token" not in runs + envs
    # The bridge takes it from the environment: its process runs for the
    # whole job, so its /proc/<pid>/cmdline is what anything else on the
    # runner can read at leisure (cubic). curl and schemathesis still
    # interpolate it into their own argv, and that is a different exposure:
    # those processes live for seconds, and the alternative -- a config file
    # or a header file on disk -- trades one readable place for another.
    assert "ARENA_FUZZ_TOKEN=" in runs
    assert "serve_bridge_for_fuzzing.py --port 8899 &" in runs
    assert "--token" not in runs


def test_the_seed_changes_between_runs(fuzz_job):
    """A fixed seed would test the same 4000 requests forever.

    Schemathesis is random, and pinning the seed turns a fuzzer into a
    fixture: the run that passes today passes tomorrow having explored not
    one new shape. `GITHUB_RUN_NUMBER` moves it every time while keeping any
    single failure reproducible -- the number is printed in the summary.
    """
    runs = "\n".join(step.get("run", "") for step in fuzz_job["steps"])
    assert "--seed \"${GITHUB_RUN_NUMBER}\"" in runs

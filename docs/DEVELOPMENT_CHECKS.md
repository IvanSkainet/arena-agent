# Development checks: fast feedback without weaker acceptance

## Local iteration

Install the hash-locked CI environment and the project, following CONTRIBUTING.md:

```sh
python -m pip install --require-hashes -r requirements-ci.txt
python -m pip install --no-deps --no-build-isolation -e .
```

During an edit, run the affected test family and its guards first. A focused run
is feedback, not full acceptance. Assemble related review fixes locally rather
than publishing a new candidate for every line.

```sh
python -m pytest tests/test_pytest_worker_contracts.py --no-cov
python scripts/preflight.py
```

## Full local preflight

The default remains serial on every supported operating system:

```sh
python scripts/preflight.py --full
```

Linux has an explicit, measured two-worker option:

```sh
python scripts/preflight.py --full --workers 2
python scripts/preflight.py --full --workers 2 --list
```

Only the full pytest command is parallelized. Fast guards still execute, failures
still fail preflight, automatic worker restarts are disabled, and the check list
is not mutated. `--workers 2` requires `--full`; worker counts other than 1 or 2
are rejected. Windows/macOS keep serial preflight until their full-suite behavior
and throughput have been measured. Installing xdist does not enable parallelism.

The existing full-preflight pytest command uses `--no-cov` and disables random
ordering. This option preserves that contract; it does **not** replace CI's
randomized, coverage-enforced matrix or the security scan required before commit.
A missing plugin is an error, never a silent fallback to an unmeasured mode.

Two workers use more memory. Do not run multiple full suites simultaneously or
use `-n auto` based only on logical CPU count. If memory is constrained, keep
`--workers 1`. Diagnostic subprocess tests may themselves launch workers.

## Coverage-enforced diagnostic run

For a full Linux diagnostic comparable in shape to the test command in CI:

```sh
RUNNER_OS=Linux ARENA_TEST_EXECUTION_GUARD=1 python -m pytest \
  -p arena.governance.pytest_execution_guard \
  --cov-fail-under=51 --randomly-seed=17 \
  -n 2 --max-worker-restart=0 --junitxml=/path/outside/checkout/run.xml
```

Use a real, existing output directory. Keep the same dependencies, optional
tools, source tree, coverage options and seed when comparing against serial
(`-p no:xdist`, without `-n` or `--max-worker-restart`). Give each run a fresh
HOME/TMP/XDG on Linux and run pairs sequentially, alternating their order.
Record environment differences and skipped-test reasons. Do not set `CI=1` on a
personal machine merely to resemble hosted CI: some CI-only tests exercise real
input devices. Never benchmark through the owner's live bridge.

## Safety contracts

- Probe and baseline sabotage tests use private input trees. They retain real
  scanner inputs and scan-size thresholds instead of creating empty dummy trees.
- Release packaging probes use a private Git repository and real builder/index.
- The collection floor is unchanged. Under xdist, the controller checks each
  worker inventory and emits a clear refusal for insufficient collection.
- Workers forward environment-leak names, not values. A leak fails the controller.
- Real subprocess regressions cover successful runs, missing tests, assertions,
  worker termination, environment leaks, insufficient coverage and collection
  mismatches. Healthy controls must remain green; negative controls must fail.
- A barrier-controlled scanner test reproduces the deletion race with shared
  temporary inputs and proves that separate writer inputs avoid it. No sleep is
  used to choose the interleaving and the checkout is never used as sabotage data.

## Measured result and limits

A fixed local Linux development tree was tested with seeds 17, 271 and 20261119,
with two serial/parallel pairs per seed, fresh HOME/TMP/XDG per run, coverage and
collection enforcement. All 12 runs passed: 12,214 cases/run, 76 skips/run, equal
case outcomes and skip reasons within each pair, and unchanged source hashes.
Wall-time speedup ranged from 1.76 to 1.84, median 1.79. Sampled process-tree RSS
was higher with two workers; shared pages are counted more than once, so this is
not exact peak physical memory.

Across the six runs per mode, actual coverage arc inventories had no serial-only
arc. One individual pair differed on a lifecycle `except` header line; paired
and union evidence must both be retained rather than claiming byte-identical
coverage in every run. These results apply to the recorded development tree,
not a Windows/macOS machine, every future revision, or hosted CI. Later CLI/docs
and barrier-regression additions require their own final acceptance.

No OS/Python matrix cell, coverage threshold, scanner or branch protection is
removed. Hosted CI parallel rollout is a separate evidence-based decision within
this task, not something enabled by this local switch.

## Retaining a reproducible measurement

The Linux-only measurement entry point runs exactly one full suite. It does not
change preflight defaults or CI and does not retry failures:

```sh
python scripts/benchmark_tests.py --mode serial --seed 17 \
  --output /tmp/arena-measurements/serial-17-r1
python scripts/benchmark_tests.py --mode n2 --seed 17 \
  --output /tmp/arena-measurements/n2-17-r1
```

The output directory must be new and outside the checkout. Preserve it elsewhere
if your temporary directory is ephemeral. Keep the same source/environment for
pairs, alternate order, and repeat each of seeds 17, 271 and 20261119 twice for
an experiment matching the local matrix design. Run sequentially, not in two
terminals. No success or speedup is inferred from a single command.

Each directory contains `result.json`, `pytest.log`, `junit.xml`, `coverage.xml`
and `.coverage`, plus `coverage.toml` (the existing coverage settings with an
isolated data destination). The runner does not export `COVERAGE_FILE` to nested
pytest commands: their diagnostic coverage must not contaminate the parent run.
The JSON retains source HEAD and hashes (including unignored
new files), package versions, lock hashes, command, wall/child CPU times, case
identities/outcomes/skip reasons and actual measured lines/arcs. Peak memory is
explicitly unknown, not a sampled RSS estimate. CPU count is logical CPU count,
not an assertion about container CPU quota. Hardware/container limits must be
recorded separately when comparing different hosts. Raw reports can contain
application/test output: treat the evidence as private and inspect before sharing.
The harness never dumps environment variables, but does inherit the caller's
configuration. Use a disposable development environment, never the live bridge.

A `running` record is saved before pytest starts. Timeout, interruption, missing
reports, malformed/empty JUnit, contradictory JUnit counters, failing pytest
and changed sources cannot produce a passed result. Hard termination may leave
the record `running`; that is incomplete evidence, not success. On timeout the
runner terminates its Linux process group, including ordinary xdist descendants.
Subprocesses deliberately escaping that process group are outside this cleanup
contract. The script is Linux-only until equivalent cleanup/platform behavior
has been validated; it must not be used as evidence for Windows/macOS.

JUnit summary counts can include pytest subtests that are not separate `testcase`
elements. Both counts are retained separately. They are not proof of identical
collection: compare named outcomes and the enforced collection floor as well.

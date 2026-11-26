# Development checks: fast feedback without weaker acceptance

## Local iteration

Install the hash-locked CI test environment, then the project, as shown below:

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

Several workers are an explicit option on every platform:

```sh
python scripts/preflight.py --full --workers 2
python scripts/preflight.py --full --workers 2 --list
```

Only the full pytest command is parallelized. Fast guards still execute, failures
still fail preflight, automatic worker restarts are disabled, and the check list
is not mutated. `--workers` requires `--full`, accepts 1 to 4, and refuses a
count larger than the CPUs it counts: the affinity mask on Linux, the machine's
logical CPUs on Windows and macOS. CPU quotas and a Windows affinity mask are
not read, so under those the check can accept more workers than there are CPUs
to run them. Installing xdist does not enable parallelism, and there is no
`auto`.

Which count to use is a property of the machine, so measure once and keep the
answer. What has been measured, as the `full suite` line of preflight, on
2026-11-22 (one run per cell; a range is two to five runs):

| Machine | 1 worker | 2 | 4 |
| --- | --- | --- | --- |
| Windows 10, 4 logical CPUs, Python 3.14 | 775 s | 398 s | 245-264 s |
| Linux container, 2 CPUs, Python 3.13 | 451 s | 227-309 s | refused: 2 CPUs |

On GitHub's Windows runners, which report four CPUs on two cores, four workers
were no faster than two ("Hosted CI" below); on the Windows machine above they
were. Three workers have only been run on macOS, in hosted CI.

On Linux preflight owns the suite's process group and cleans it up when it is
interrupted. On Windows and macOS it does not, with one worker or with several.
In one trial on Windows, where preflight was killed during a two-worker run,
every process of the run had exited within 25 seconds and the two workers'
directories stayed in the temporary directory. That is one observation, not a
contract, and nothing was tried on macOS. On every platform a worker that is
killed leaves its `arena-test-worker-*` directory in the temporary directory;
a run that ends normally removes them.

The existing full-preflight pytest command uses `--no-cov` and disables random
ordering. This option preserves that contract; it does **not** replace CI's
randomized, coverage-enforced matrix or the security scan required before commit.
A missing plugin is an error, never a silent fallback to an unmeasured mode.

More workers use more memory. Do not run multiple full suites simultaneously or
use `-n auto` based only on logical CPU count. If memory is constrained, keep
`--workers 1`. Diagnostic subprocess tests may themselves launch workers.

## Coverage-enforced diagnostic run

Use the isolated Linux measurement entry point, with a new output directory
outside the checkout:

```sh
python scripts/benchmark_tests.py --mode n2 --seed 17 \
    --output /tmp/arena-measurements/n2-17
```

This arms the collection floor and coverage threshold and redirects the JUnit,
coverage XML and database to retained evidence. Use `--mode serial` for its
serial counterpart. Do not set `CI=1` to imitate hosted CI: some CI-only tests
exercise physical input devices. Never benchmark through the owner's live bridge.
Keep the same source tree, dependencies and seed for sequential comparisons.

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
- A test that leaves `<home>/update/post-update-smoke-pending.json` in a home
    other tests share fails by name and the marker is removed
    (`tests/_post_update_marker.py`). The marker tells the next bridge that
    starts to run the ship smoke; left behind, it made that smoke run on an
    executor thread under unrelated tests (#518, #534, #555, #587).

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
removed. The local switch and the hosted CI setting are independent of each
other; the hosted one is described next.

## Hosted CI

The test matrix in `ci.yml` runs under pytest-xdist: 4 workers on Linux, 2 on
Windows, 3 on macOS, always with `--max-worker-restart=0`. Random ordering, the
collection floor and the per-platform coverage floor are unchanged, and all 15
OS/Python cells still run.

The numbers come from a measurement on the hosted runners on 2026-11-22: Python
3.13, seeds 271, 1009 and 4242, two runs of each, timing the `Run tests` step
only. Median seconds, with the range in brackets:

| Runner | serial | 2 workers | all logical CPUs |
| --- | --- | --- | --- |
| Linux, 4 vCPU | 525 (432-593) | 282 (264-334) | 247 (161-263) with 4 |
| Windows, 4 vCPU | 1155 (964-1202) | 570 (455-738) | 609 (483-672) with 4 |
| macOS, 3 CPU | 520 (462-625) | 323 (297-432) | 290 (224-303) with 3 |

Windows stays at 2 workers: its four logical CPUs are two cores, and 4 workers
were no faster. One macOS runner reported 5 CPUs and finished in 153 s; the
setting is pinned to 3 so that what runs is what was measured. Within every
runner and seed the three modes collected the same test ids, and every outcome
agreed except for the failures listed below. Line coverage did not move (Linux
69.0 %, Windows 68.5 %, macOS 68.6 %).

That first measurement did not pass, and neither did the first attempt at a
fix. Between them they found five things no local run had shown:

- macOS, 3 of 12 parallel runs: `arena/mcp/ws_push.py` created its queue file at
  import. Two workers importing it together both called `openat(O_CREAT)` on the
  same new name and macOS answered one of them `ENOENT`. Importing the module
  now writes nothing; `ws_server.main()` prepares the queue.
- Windows: two workers initialised `~/arena-bridge/memory/facts.db` together
  (`trigger memory_facts_ai already exists`). Workers shared the account's home.
- macOS, once workers had a home each but still one temporary directory: a test
  expecting one `fuzz-root-*` workspace there found another worker's.
- Windows: one test asked whether a descriptor number was closed after the
  number had been reused. The test now records each close as it happens.
- Windows: one probe-isolation test hit its 20 s limit once. The cause was not
  established; the limit is now 120 s, so a repeat would point at a real block
  rather than a slow runner.

The two sharing defects are closed for every test at once:
`tests/_worker_directories.py` moves each worker to per-user and temporary
directories of its own before it imports a test module. A test that needs a
particular home still sets one; a test that names none can no longer meet
another worker there. The home sits beside the temporary directory, not inside
it, and the path contains no symlink: the first attempt put the home under
macOS's `/var/folders`, which is reached through a symlink and is inside
`TMPDIR`, and 32 tests failed for those two reasons while Linux stayed green.

A run without workers is moved the same way, as `arena-test-worker-serial-*`
(#608). It has no other worker to meet, but before this it wrote into the
account's own agent home: on an empty home, one serial run of the suite left
128 lines in `~/arena-bridge/audit.jsonl`, 1877 in `requests.jsonl`, a memory
database, and `~/.arena/last_urls.json` holding addresses of test servers.
`tmp_path` stays where pytest would have put it, so what a failed test left
there can still be read after the run. The controller of a parallel run is not
moved: it runs no test.

Playwright looks for its browsers under the per-user cache, so in a moved home
it finds none and `tests/e2e/test_dashboard_browser.py` skips every test. A run
without workers is told where they were installed (`PLAYWRIGHT_BROWSERS_PATH`,
unless the variable is already set). A worker is not: a parallel run skips the
browser tests, as it did before.

With those fixes in place the chosen setting was run again on every Python the
matrix uses (3.10-3.14) with four seeds on Windows and macOS and two on Linux:
50 runs, 49 passed. Median seconds of the test step: Linux 180 (154-262),
Windows 472 (380-611), macOS 308 (172-351).

The one failure was `test_live_windows_timeout_kills_nested_child` on Windows:
"nested child survived request timeout". The run kept no evidence that tells
two explanations apart. The test asked whether the process could still be
opened half a second after the kill, which is also true of a process that has
terminated while someone holds a handle to it. And its 2 s request timeout left
little room for two interpreters to start on a busy runner; `taskkill /T` walks
the tree that exists when it runs, so a child created during the kill is not in
it. The test now uses the product's wait-state probe, gives the tree 10 s and
checks that it was in place 2 s before the kill, and its failure message says
when the child became ready. If the product really does leave a child behind,
the next failure will say so. The second explanation is a real limit of
`taskkill /T`, not a test artefact.

That limit is closed (#516): a Windows command now runs inside a Job Object
and is killed through it. Measured on one Windows 10 machine with Python 3.14:

- A shell that exits and leaves a program holding its output pipes
  (`start "" /b ...`) has no tree left for `taskkill /T` to walk. Without the
  job the program outlived the request that timed out, every time;
  `test_live_timeout_kills_what_the_shell_left_behind_after_exiting` and
  `test_live_closed_stream_kills_what_the_shell_left_behind` fail when the job
  is taken out.
- Against a command that kept starting processes, about 40 a second,
  `taskkill /T /F` with no time limit took 56 s to stop it and 2183 processes
  were started meanwhile. `TerminateJobObject` returned in 1 ms and one process was started
  after it; that one died too. The live test of this case stops by itself
  after 30 processes, and it also passes without the job: it shows the job
  contains such a command, not that `taskkill` cannot.
- Holding a command costs about 0.1 ms on top of a 1.8 ms spawn. Resuming the
  suspended process through a thread snapshot instead would have cost 22 ms of
  event-loop time per command.

What this does not show: the measurement is one day on GitHub's runners and
says nothing about another runner size. A test that passes alone and fails
beside its neighbours is a defect to fix; do not add `--reruns`, raise
`--max-worker-restart`, or lower the worker count to make one go away.

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

A successful run directory contains `result.json`, `pytest.log`, `junit.xml`, `coverage.xml`
and `.coverage`, plus `coverage.toml` (the existing coverage settings with an
isolated data destination). Failed or interrupted runs may retain only partial
evidence; absence of artifacts is not success. The runner does not export `COVERAGE_FILE` to nested
pytest commands: their diagnostic coverage must not contaminate the parent run.
The JSON retains source HEAD and hashes (including unignored
new files), package versions, lock hashes, command, wall/child CPU times, case
identities/outcomes/skip reasons and actual measured lines/arcs. Peak memory is
explicitly unknown, not a sampled RSS estimate. CPU count is logical CPU count,
not an assertion about container CPU quota. Hardware/container limits must be
recorded separately when comparing different hosts. Raw reports can contain
application/test output: treat the evidence as private and inspect before sharing.
The harness uses an explicit OS/tool-lookup/locale environment allowlist. It
does not inherit operator credentials, Arena paths or live-test controls,
CI/GITHUB_ACTIONS, or hidden PYTEST_* selection/plugin options. The explicit
browser-E2E skip request is preserved. This is not a sandbox for hostile test
code: use a disposable development environment, never the live bridge.

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

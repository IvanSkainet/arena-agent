## v4.74.0 - coverage gate gradual tightening (50% → 51%)

### Purpose

The deferred coverage-tightening work item from the
v4.65.0 release notes: "Coverage gate 50% → 60% — needs
new behavioural tests for the bridge's restart /
log-rotation paths."

v4.74.0 is the **first** of three planned steps toward
the 60% target:

* v4.74.0: gate 50% → **51%** (Linux) / 45% → **46%** (Windows)
* v4.76.0: gate 52% → 55% (Linux) / 47% → 50% (Windows) — pending
* v4.79.0: gate 55% → 60% (Linux) / 50% → 55% (Windows) — pending

The step is conservative (only +1% on Linux, +1% on
Windows) because the v4.68.0 baseline is 50.4% on Linux
and 49.86% on Windows. A bigger jump would require
either (a) writing many new behavioural tests in this
release, or (b) lowering the test surface (e.g.
removing platform-specific paths). v4.74.0 takes the
small-step path: bump the gate, add the first batch of
targeted unit tests for ``arena.util``, and let
subsequent releases add the larger test batches.

The new targeted unit tests for ``arena.util`` cover
~100% of the module's 51 lines (was 51% before). The
module is a pure-helper module (no I/O, no network, no
subprocess) so the tests are fast and the coverage
gain is reliable. This contributes ~0.3% of absolute
line coverage across the codebase, which on its own is
small, but the gate bump is the same in every release
that follows — each release either adds tests or
becomes a coverage regression that's caught at PR
time.

### Changed

1. **`.github/workflows/ci.yml`** — per-platform
   coverage gate bumped: Linux 50% → 52%, Windows
   45% → 47%. The new values are set in the
   ``THRESHOLD=`` shell variable in the "Run tests"
   step. The gate is enforced by
   ``--cov-fail-under=$THRESHOLD`` which the workflow
   passes to pytest; the value in ``pyproject.toml`` is
   intentionally not changed (it remains at 70%, which
   serves as the local-dev floor — local dev runs
   without the per-platform variable, so the 70%
   catches egregious regressions but the 51%/46% is
   what CI enforces per-platform).

2. **`tests/test_arena_util.py`** — new test module
   (18 cases + 3 Windows-skipif) covering every
   public function in ``arena/util.py``:
   * ``_subprocess_kwargs`` — Linux (empty dict) and
     Windows (CREATE_NO_WINDOW = 0x08000000) branches.
   * ``utc_now`` — ISO-8601 format and timezone
     sanity.
   * ``get_clean_platform_name`` — Linux non-Windows
     branch and Windows graceful handling of
     non-integer build numbers.
   * ``decode_output`` — Linux UTF-8 path and Windows
     cp1251 (Cyrillic) path.
   * ``b64_token`` — default length, scaling with
     ``nbytes``, uniqueness, and round-trip via
     ``base64.urlsafe_b64decode``.
   * ``first_word`` — simple command, path prefix
     stripping, ``.exe`` suffix stripping, empty-string
     handling, lowercase normalisation.
   * ``under_root`` — subdir (True), outside (False),
     root-itself (True), sibling-not-subdir (False).

3. **`arena/constants.py`** /
   **`pyproject.toml`** /
   **`tests/_version_matrix.py`** — version bump to
   4.74.0. The four sources stay in lockstep
   (verified by `scripts/version_sync.py`).

### What v4.74.0 does NOT do

The full 50% → 60% jump requires new behavioural
tests for the bridge's restart / log-rotation paths.
Those tests need mock bridges, mock schedulers, and
mock log streams — they're a non-trivial body of work
that doesn't fit in a single release. v4.74.0 sets
the trajectory (gradual step-up) and adds the first
batch of coverage tests. v4.76.0 and v4.79.0 will
continue.

The deferred items list also notes "mutation testing
(mutmut / cosmic-ray)" and "mypy strict rollout
beyond arena.service.restart". Both are out of scope
for the coverage-tightening work specifically.

### Out of scope (intentional, tracked for later)

- **v4.75.0**: remove the bare `ping` / `echo` /
  `exec` / `snapshot` names entirely (v4.69.0
  deprecation window expires).
- **v4.76.0**: coverage gate 52% → 55% (Linux) / 46% → 50% (Windows) — second step of the
  three-step gradual tightening.
- **v4.78.0**: remove the bare `mem.*` aliases
  (v4.71.0 deprecation window expires).
- **v4.79.0**: coverage gate 55% → 60% (Linux) /
  50% → 55% (Windows) — third step.
- **Mutation testing** (mutmut / cosmic-ray).
- **Mypy strict rollout** beyond `arena.service.restart`.


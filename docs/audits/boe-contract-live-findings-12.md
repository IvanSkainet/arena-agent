# Issue #12 — Book of Eternity live contract findings

This file records live Windows findings separately from the implementation and
keeps failed green-looking assumptions visible. T41 remains open until a run on
the exact Arena head completes the full artifact-bound chain and its bounded
evidence is inspected.

## Run 31756622100 — deterministic package contaminated by second checkout

- Arena source: `5c37b0d4c03490e67693fe8b483f87b2c45b8e0d`.
- Observed boundary: the deterministic release packer failed before the live
  contract because the game checkout had already created untracked `game/`
  inside the Arena worktree.
- Root cause: workflow ordering, not a packer defect. The package was no longer
  being built from a clean exact Arena tree.
- Resolution: build and verify the Arena ZIP before checking out the pinned game
  source. A static regression assertion protects this order.

## Run 31756911952 — relay command did not invoke under PowerShell

- Arena pull-request head: `0df812b21f81678edafd41b3c1bbca0d8dd387bf`.
- GitHub pull-request merge SHA used by the first workflow version:
  `0d150e8de2de4f1937e9f0b66b963a4481b5bdaf`.
- Pinned game source: `11ddf9f5a0d1d5d8ccebedf576f8f5621162d168`.
- Passed before the live failure: deterministic Arena artifact build and
  verification, exact game checkout, GM bridge build, and all three selected
  upstream terminal-signal/repair contracts.
- Live failure: the harness timed out waiting for the persistent Arena terminal
  relay banner and READY state before dispatch 1.
- Root cause: `GmCliLaunchCommand` began with a quoted Python path but omitted
  PowerShell's call operator (`&`). The hosted PTY shell therefore did not invoke
  `arena-relay terminal`.
- Secondary evidence defect: failure unwound through `TemporaryDirectory` while
  the GM bridge still held the session directory. Windows cleanup then raised
  `WinError 32`, masking the READY timeout in `contract-evidence.json` even
  though the job log retained the primary traceback.
- Resolution:
  - emit a PowerShell-literal-safe command beginning with `&`;
  - capture bounded GM diagnostics on failure;
  - shut down the game helper/shell before deleting the temporary workspace;
  - stop and attest the Arena server process;
  - retry and attest temporary-directory removal without replacing the primary
    live failure;
  - bind checkout, evidence, and artifact naming to the pull-request head SHA
    rather than GitHub's synthetic pull-request merge SHA.

## Acceptance gate

Do not mark T41 complete from static tests or from the passed setup/build steps.
The next exact-head Windows run must demonstrate all three dispatches, terminal
correlations, drained mailbox queues, no partial files, terminated GM and Arena
processes, and successful temporary-workspace removal in the uploaded bounded
evidence.

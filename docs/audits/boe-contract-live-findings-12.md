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

## Run 31784757070 — multiline visibility needle crossed a line break

- Exact Arena head and evidence SHA:
  `5ae27d74659295e880d4bc1c9a44aa6fa24201e6`.
- The relay launch fix worked: diagnostics contained the real
  `Arena Terminal Relay` banner, READY footer, and the first long bracketed
  paste. The game helper/shell, Arena server, synthetic consumer, and temporary
  workspace all shut down cleanly; the primary failure remained intact in the
  uploaded evidence.
- Live failure: upstream `dispatchPrompt` refused to send Enter because its
  visibility policy did not recognize the pasted first prompt.
- Root cause: the game builds a 24-character visibility needle after compacting
  prompt whitespace, while the visible PTY text retains line breaks. The
  harness's short first line put a compacted space inside the needle, so that
  needle could not occur verbatim in the multiline terminal output even though
  the output visibly contained the prompt.
- Resolution in Arena scope: keep every dispatch's unique first line at least
  24 characters long. This exercises the upstream safeguard instead of adding
  a broad configured marker that could match stale output from an earlier
  dispatch. No C# policy or game rule is copied or changed.

## Run 31785241973 — raw ConPTY newlines changed the relay body

- Exact Arena head: `f56219e1136c893f44595d2b34ba16bb8cfc3c73`.
- The longer unique first line passed the upstream visibility safeguard. The
  first prompt reached the authenticated mailbox, proving dispatch and Enter.
- Live failure: the synthetic agent rejected dispatch 1 because the mailbox
  body was not byte-for-byte equal to the LF-normalized harness prompt.
- Root cause: `BufferedTextChunkReader` deliberately reads
  `sys.stdin.buffer.read1()` so ConPTY input is non-greedy and UTF-8 safe, but
  that bypasses `TextIOWrapper` universal-newline translation. Windows ConPTY
  can surface logical multiline input as CRLF/CR, which then leaked into the
  relay message body.
- Resolution: canonicalize CRLF and bare CR to LF at the generic terminal
  framing boundary before queueing. A Linux-runnable hostile-platform test
  injects mixed Windows line endings into a real bracketed paste. Mismatch
  failures now report only bounded lengths, digests, and newline counts rather
  than dumping prompt contents.

## Run 31785711910 — exact-head contract passed

- Exact Arena head: `aeae1a84bf0472599d5caa5aa51578f969106f2f`.
- Pinned game head: `11ddf9f5a0d1d5d8ccebedf576f8f5621162d168`.
- The deterministic release artifact verified as version `4.169.44`, 1,154
  files, 11,958,246 uncompressed bytes, SHA-256
  `37352d222fb2087ab170eb120eae202e636e308029c355105795aeabf5c1d906`;
  the versioned and alias ZIP identities matched.
- All three upstream focused contracts passed.
- The real Windows chain completed two consecutive multiline turn dispatches
  and the correlated validation-repair dispatch. Evidence contains three
  distinct message/reply pairs and three successful terminal signals; repair
  remains correlated to request/turn 102.
- Final inbox and reply depths were zero, no partial atomic files remained,
  GM helper/shell remaining PIDs were empty, the Arena server and synthetic
  consumer stopped, and the temporary workspace was removed without cleanup
  errors.
- `contract-evidence.json` is 7,362 bytes (below 64 KiB), contains the exact
  Arena/game SHAs, and does not contain the ephemeral bridge credential.

This run satisfied T41's live acceptance gate for the declared pin and PR #27
was merged.

## Post-merge run 31788059685 — freshness gate caught upstream movement

- Arena merge commit: `629b5e8a35590b2fd49427e85d2834d733eb771a`.
- The non-PR run stopped fail-closed before packaging because upstream `main`
  had advanced from tested pin `11ddf9f5a0d1d5d8ccebedf576f8f5621162d168`
  to `385979a01c08863cf3018b399aad7799b58b8929`.
- Inspection of the exact game diff found no changes to
  `BookOfEternityGMBridge`, the `bookofeternity.ps1` control surface, or the
  paste-visibility policy. The three selected upstream contracts remain
  present. The daemon and its contract tests did change: Mortal location
  materialization repair now carries full-turn resubmission instructions.
- This is not converted to a warning: schedule/manual/release paths intentionally
  require a current tested upstream pin. The compatibility manifest is advanced
  to `385979a0` and must pass the full Windows contract before Issue #12 closes.

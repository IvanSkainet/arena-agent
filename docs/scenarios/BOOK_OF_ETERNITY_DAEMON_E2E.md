# Book of Eternity: daemon-driven live E2E

- Status: **v4.169.43 released; v4.169.44 Windows hardening live-accepted, release pending**
- Started: 2026-08-13
- Bridge baseline: v4.169.42
- Current candidate: v4.169.44
- Scenario task: T34

## Purpose

This is a stress scenario for Skainet Bridge's generic core, not a request to
put Book of Eternity rules into the bridge.

The scenario is successful only when the original application architecture is
preserved end to end:

```text
C# client writes a request
  -> game_master_daemon.ps1 detects it
  -> daemon dispatches a prompt through its CLI/ConPTY transport
  -> Skainet Bridge queues that prompt for an already-running agent
  -> agent reads the application's files and writes its outputs
  -> agent acknowledges the correlated transport message
  -> client validates the outputs
  -> validation failure returns through the same daemon transport
  -> agent applies the bounded repair and the client accepts it
```

The bridge owns transport and host access. The game owns requests, validation,
progression, rules, and state. The agent owns reasoning and authorship.

## Hard boundary

The scenario must not be declared complete after manually polling
`input/turn_request.json` or writing `ready/turn_complete.json` while the daemon
is stopped. That proves only the file protocol. It does **not** prove the
daemon, ConPTY dispatch, prompt guidance, repair packet, or transport lifecycle.

An inactive Arena session cannot be started from the host. The supported and
honest behavior is a mailbox:

* while an agent turn is active, it may long-poll the relay;
* otherwise the daemon's message remains queued;
* the bridge must not claim that an agent is listening when none is polling;
* no browser automation against Arena is introduced.

## Baseline

On a Windows 10 host with bridge v4.169.42:

* the game client was built with .NET 8 and launched;
* a new Chaos Sea session was created;
* turn 1 was accepted through direct host file access;
* the UI rendered narrative and four structured choices;
* `stories/chaos_sea.jsonl` recorded turn 1.

That run proved the file half of the tunnel, but it bypassed the daemon and was
not daemon-driven E2E.

## Findings

### F1 — the daemon was bypassed

The first run launched `boe-arena-relay` in an ordinary `cmd.exe` window and
wrote game files directly. The session selected `ConPTYBridge`, so the daemon
actually dispatches to `BookOfEternityGMBridge` through its named pipe. No
`gm_bridge_status.json` and no live daemon status existed. The standalone
window was not the configured transport.

### F2 — multiline terminal framing was not tested

`game_master_daemon.ps1` sends long multiline prompts. The old pseudo-CLI used
`sys.stdin.readline()`, while its tests supplied only one-line text. A repair
prompt was therefore capable of becoming many unrelated messages even with a
green suite.

### F3 — a generic mailbox already exists

The bridge already ships authenticated `/v1/relay/send`, `/v1/relay/poll`,
`/v1/relay/reply`, and long-polling reply endpoints with durable atomic claims.
A second BoE-specific inbox is unnecessary for the transport problem.

### F4 — terminal dispatch needs correlated acknowledgement

A pseudo-CLI must remain busy while the agent processes one message and return
to idle only after the agent acknowledges that same message. Watching one
game's `ready/*.json` files in the terminal adapter is not generic. A relay
reply keyed by `in_reply_to` is generic and safely releases the next dispatch.

### F5 — strict game validation exposed bootstrap/state defects

The live session initially had one Guardian `coreValues` entry where the
validator required 3–5 and lacked `game_state/inventory/item_identity_index.json`.
Those are application bootstrap/state issues, not bridge features. They were
repaired locally to continue the scenario and must not become bridge-side game
logic.

### F6 — strict output shapes matter

Observed accepted shapes required structured dialogue options, complete actor
reasoning, actor-owned journal memory, and a progression report when requested.
The daemon prompt and repair packets are useful precisely because they direct
the agent to compact templates instead of forcing repository-wide archaeology.

### F7 — cancelled client wait left a stale snapshot

The client cancellation branch deleted `input/turn_request.json` and ready
signals but left `pending_turn_snapshot*`. The next pre-turn validation then
rejected an otherwise idle session because the orphaned snapshot was not
current for an active request. The stale artifacts were archived only when no
active request existed. This is an upstream client lifecycle defect; it is not
papered over by bridge game logic.

### F8 — terminal signal processing needed a console event

Several valid `turn_complete` / `turn_error` files remained visible on disk
until the active client console received a harmless F12 key. The wait then
completed immediately and cleaned its artifacts. The behavior reproduced for
success and error paths. This is recorded as an upstream Spectre/console wait
issue; the bridge does not inject periodic keys as a workaround.

### F9 — Windows line mode truncated the prompt to 510 characters

The first real daemon packet was stored as exactly 510 characters and ended in
the middle of a path. Windows Console line mode had truncated the ConPTY input.
The terminal adapter now temporarily enables raw virtual-terminal input and
restores the original mode in `finally`.

### F10 — ConPTY stripped bracketed-paste markers

Even in raw mode the Windows path did not deliver `ESC[200~` / `ESC[201~` to
the child. The stable evidence was the host's leading Ctrl+U clear-input
control, the bulk prompt write, a quiet interval, and a final newline-only Enter
write. The adapter now:

* treats Ctrl+U as a ConPTY dispatch start;
* reads non-greedily in binary chunks instead of 34,000 single-character calls;
* preserves embedded newlines;
* recognizes the delayed newline-only chunk as submission;
* echoes a bounded safe prefix so the C# visibility handshake can send Enter;
* rearms that echo at every Ctrl+U boundary.

Two consecutive four-line live probes were preserved exactly in one terminal
process (`sequence` 1 then 2), with no extra messages.

### F11 — atomic temp files raced the Windows reply reader

`relay/store.py` created `.tmp-*.json`. A concurrent reply long-poll included
the unfinished file in `glob("*.json")`, opened it, and made `os.replace` fail
with WinError 32. It reproduced twice during validation repair. Temp files now
end in `.partial`, so mailbox readers cannot observe them. After restarting the
bridge, a live concurrent long-poll + reply write returned HTTP 200 with exactly
one reply.

### F12 — standalone bootstrap is dead code upstream

`game_master_daemon.ps1` defines `Ensure-CliBootstrapSent` but never invokes it.
There is therefore no standalone bootstrap packet to accept in the current game
revision. Actual turn and repair prompts still carry the complete context-pack,
helper, template, and repair guidance. This is recorded rather than simulated
and claimed as daemon behavior.

### F13 — the canonical local pytest command was permanently red

`RELEASE.md` requires `python -m pytest -q`, but `pyproject.toml` still enforced
the abandoned v4.61.0 coverage floor of 70%. Current measured combined coverage
is 60.40%, while CI intentionally uses 51% on Linux and 46% on Windows/macOS.
The code suite was green at the CI floor, yet the documented local command could
never pass. The default is now the cross-platform 46% floor; CI keeps its
explicit stricter Linux override. This is a generic release-quality fix found by
running the scenario's full cycle, not game logic.

### F14 — a clean git tag still packed an ignored coverage report

The first v4.169.43 archive passed the builder's untracked-file guard but
contained root `coverage.xml` (about 1.9 MB). The builder walks the filesystem;
`git ls-files --others --exclude-standard` deliberately hides ignored files, so
the guard never evaluated the report against `should_exclude`. The archive was
rejected before upload. `coverage.xml` is now explicitly excluded and the
workspace guard queries both ordinary and ignored files, failing closed if git
cannot measure either set. Three regressions pin the exact artifact, the
ignored-file query, and the failure path.

### F15 — missing pyrefly was counted as zero errors locally

The first published v4.169.43 candidate passed local preflight but failed CI's
blocking quality ratchet: pyrefly found `ctypes.WinDLL` missing from its
cross-platform type surface. Locally pyrefly was not installed. Python returned
rc=1 with `No module named pyrefly`; `quality_ratchet.py` allowed rc=1 because it
also means findings, decoded empty stdout as `{}`, and reported zero errors.
The candidate release and remote tag were retracted immediately.

The Windows-only loader now resolves `WinDLL` lazily with `getattr`. More
importantly, pyrefly rc=1 must carry a parseable non-empty `errors` list,
malformed/empty output fails closed, and preflight declares the `pyrefly` binary
mandatory. Three regressions cover the exact missing-module false green, a real
structured finding, and preflight wiring. CI-pinned pyrefly 1.2.0 now reports
zero errors.

### F16 — the agent's timed-out PowerShell child consumed 44.5 GiB

The reported memory growth was reproduced while the game client used only
33.9 MB private memory. PID 15300 was an orphaned PowerShell process launched by
Skainet `/v1/exec/script`, not the game daemon or terminal relay. Audit linked it
to request `4f62ecbd-cce1-4c84-ae66-c52055f6fc03`: a 1,277-byte diagnostic
started at 10:34:21 UTC, timed out after 90 seconds, and was reported finished
at 95 seconds while its child continued for about three hours. At measurement
it held 44,521.9 MB private bytes and had accumulated 6,672 CPU-seconds.

The exact agent-authored probe survived in `/tmp/probe_t34.ps1`. It put output
from `Get-Content` into a deep `ConvertTo-Json`. PowerShell's content objects
carry extended `PSPath`, `PSDrive`, and provider metadata; serializing only 20
such lines at depth 5 reproduced 9.8 MB of recursive metadata. The original
100-item, depth-10 object expanded for hours. The daemon log itself was only
0.03 MB and did not grow during a 15-second sample. Garbage collection could
not help because serialization still held reachable work.

Bridge timeout cleanup was independently defective on Windows:
`CREATE_NEW_PROCESS_GROUP` was set, but `Process.kill()` killed only the
`cmd.exe` shell. The PowerShell child was reparented and escaped both the HTTP
timeout and temp-script deletion. v4.169.44 uses `taskkill /T /F`, retains a
direct-kill fallback, and adds `finally` cleanup for buffered and streaming
cancellation/shutdown paths. The confirmed runaway was killed explicitly;
remaining daemon, ConPTY, relay, bridge, and client processes showed 0 MB
private-memory growth over the next 30 seconds.

### F17 — manual `/admin/update/restart` invoked no relaunch mechanism

The candidate runner was uploaded and `/v1/admin/update/restart` returned
`restart=scheduled`, `can_restart=true`, and `mechanism=scheduled_task`. The
bridge exited, but the endpoint had only checked that launch artifacts existed;
it never ran the task, VBS, or batch launcher. The task is ONLOGON and does not
react to process death. Public health remained 502 beyond two minutes until the
operator manually ran `start_hidden.vbs`.

v4.169.44 now arms a detached Windows Script Host helper before scheduling
exit. The helper waits for the old PID, tries VBS, batch, then the Scheduled
Task, and uses the port as the success oracle after every attempt. If helper
startup fails, restart is refused without taking down the bridge. Auto-update
marks its existing mover as prepared so manual restart logic cannot launch the
old tree while files are being replaced.

## Core change

`arena-relay terminal` is a generic persistent terminal ingress:

1. accepts an ordinary line, a bracketed paste, or Windows ConPTY raw dispatch;
2. queues one complete prompt through the existing relay mailbox;
3. prints deterministic busy markers;
4. waits for a correlated agent reply;
5. prints the reply and returns to an idle prompt;
6. never attempts to start an Arena session.

The adapter contains no Book of Eternity paths, schemas, rules, or completion
file names.

## Acceptance matrix

- [x] Unit: ordinary terminal line becomes one relay message.
- [x] Unit: multiline bracketed paste becomes exactly one relay message.
- [x] Unit: raw ConPTY prompt preserves embedded newlines until delayed Enter.
- [x] Unit: truncated paste / raw dispatch is never delivered.
- [x] Unit: prompt size and visibility echo are bounded.
- [x] Unit: terminal remains busy until a correlated reply.
- [x] Unit: Ctrl+U rearms the next terminal dispatch.
- [x] Unit: unfinished relay temp file cannot match `*.json`.
- [x] Integration: file-backed relay preserves body, metadata, correlation,
  exactly-once claim, and idle/busy ordering.
- [x] Live: C# ConPTY bridge launches the generic terminal relay.
- [x] Live: a 33,937-character daemon turn prompt arrives as one message.
- [x] Live: agent acknowledgement returns the CLI to ready.
- [x] Live: client -> daemon -> ConPTY -> relay delivers turns 2 and 3.
- [x] Live: turn 2 is authored through compact templates and accepted.
- [x] Live: deliberate unknown output field creates a daemon-delivered repair
  packet with exact target file and correction.
- [x] Live: bounded repair removes only the sabotage and is accepted.
- [x] Live: two consecutive multiline packets remain one message each.
- [x] Live: concurrent reply long-poll + atomic write returns one HTTP 200 reply.
- [x] Live: queues return to `inbox=0`, `replies=0` after probes.
- [x] Regression: 8,307 tests collected; full suite, lint, security scan, and
  `preflight.py --full` pass.
- [x] Release: clean tagged build is installed and artifact signatures verified.

## Live log

### 2026-08-13 — baseline inspection

* Host bridge reported v4.169.42.
* Client and an obsolete standalone pseudo-CLI were alive; daemon and configured
  ConPTY helper were not.
* The old window was stopped. `BookOfEternityGMBridge` was built and configured
  to launch `arena-relay terminal` through the local authenticated bridge.

### 2026-08-13 — transport development

* Added `arena/relay/terminal.py` and `arena-relay terminal`.
* Reproduced 510-character truncation, raw-mode visibility timeout, slow
  per-character submission timeout, split repair continuation, echo rearm bug,
  and `.tmp-*.json` Windows sharing violation.
* Added chunked decoding, Ctrl+U/delayed-Enter framing, bounded handshake echo,
  per-message rearm, release-local token lookup, and `.partial` atomic temps.

### 2026-08-13 — game and repair acceptance

* Turn 2 prompt: 33,937 characters, one relay message, daemon dispatch accepted
  in about one second after the final framing fix.
* Turn 2 wrote Guardian journal memory, progression report, narrative, actor
  reasoning, structured options, and terminal signal. Client accepted it.
* Turn 3 intentionally added `t34Sabotage` to narrative output.
* Client generated `narrative_response_unknown_field` and a bounded
  `accepted_turn_output_artifact_repair` packet targeting only that file.
* Repair removed only the forbidden field and called
  `Complete-BoeValidationRepair` last. Client accepted the repaired turn and
  rendered the new options.
* Post-fix probes: two exact four-line messages, sequences 1 and 2, both replies
  HTTP 200; separate concurrent reply race probe also returned one HTTP 200
  reply; final relay depth was zero.

### 2026-08-13 — local release gates

* Focused relay/BoE/dead-code regression: 100 passed; relay/BoE subset: 99.
* Full collection: 8,307 tests. Bare `python -m pytest -q` passed after the
  default coverage-floor correction.
* Final coverage: 63.07% lines, 51.61% branches, 60.40% combined report.
* Critical ruff, compileall, `git diff --check`, normal preflight, and two final
  `preflight.py --full` runs passed.
* Security gate passed: Bandit 0 high/medium, Semgrep 0 findings, pip-audit
  0 known vulnerabilities across 18 runtime dependencies.
* First clean-tag ZIP was rejected before upload because archive inspection
  found ignored `coverage.xml`. Packaging now inspects ignored workspace files
  and excludes the report explicitly.
* The rebuilt candidate was signed and published, then immediately retracted
  with its remote tag when blocking CI exposed the missing-pyrefly local false
  green. The correction was added as an append-only commit; master history was
  not rewritten.

### 2026-08-13 — final release and installed-artifact recheck

* Final tag target: commit `713e72c543a91c3de8a7822845fc8c3cdfd77a62`.
* Clean-tag ZIP: 1,148 files; SHA-256
  `956d1d52d3754049b243378095e7aef18f2fe8735df5661d9a414dcce2ef7ff6`.
  Archive integrity, required terminal files, extracted version/CLI, and absence
  of tests, VCS state, credentials, and coverage artifacts were verified.
* The versioned ZIP and unversioned alias were anonymously downloaded, compared
  byte-for-byte, and checked against the public digest file. Independent
  `cosign verify-blob` passed for both ZIPs and the digest file. All nine release
  assets are present and the release is `latest`.
* Exact-commit GitHub runs all passed: CI `31701465595`, Security scan
  `31701465629`, CodeQL `31701464938`, release signing `31701513477`.
  Open Code Scanning, Dependabot, and Secret Scanning alert counts were 0/0/0.
* The public artifact was installed on the Windows host through the verified
  auto-update path. `/health`, update status, and armed post-update smoke all
  reported v4.169.43 with no failed checks or warnings. Installed terminal,
  relay-store, and quality-ratchet hashes matched the final source exactly.
* The final installed terminal shell was restarted. Two consecutive exact
  multiline C# dispatches then produced relay messages `eb0bd5520ae0` and
  `b52411719cb0`, sequences 1 and 2, 75 characters and four lines each; both
  correlated replies returned HTTP 200.
* A separate installed-artifact concurrent long-poll/reply probe produced
  message `a52253698389`, HTTP 200, and exactly one reply. Final relay depths
  were `inbox=0`, `replies=0`.

### 2026-08-13 — post-release memory incident and v4.169.44 acceptance

* Process attribution found one non-game PowerShell PID 15300 at 44,521.9 MB
  private bytes and 6,672 CPU-seconds. Audit mapped it to a timed-out agent
  diagnostic request. Client, daemon, ConPTY, terminal relay, and HTTP bridge
  were each between 18.3 and 96.3 MB private.
* The runaway was killed alone with no descendants. Thirty-second post-cleanup
  sampling showed 0 MB growth in every retained bridge/game process.
* The first candidate deployment exposed that manual restart only exited. Public
  health stayed 502 beyond two minutes; the operator recovered it once with the
  installed VBS launcher.
* The candidate restart helper was then pre-armed and returned the bridge. A
  second call exercised the fixed endpoint itself: response
  `relauncherPrepared=true`; detached log recorded
  `ready via start_hidden.vbs`; public health reported v4.169.44 automatically.
* Live timeout sabotage used a three-second budget and a PowerShell parent that
  launched a nested PowerShell child. HTTP 408 arrived at 3.174 seconds
  (4.072 seconds wall); parent PID 4552 and child PID 2848 were both gone after
  two seconds, and no `.arena_script_tmp` orphan remained.
* Fifteen-second post-sabotage sampling found no retained process above 96.4 MB
  private memory and zero growth in daemon, ConPTY, and terminal-relay
  processes.
* v4.169.44 local result: 8,320 tests collected; bare full suite,
  `preflight.py --full`, pyrefly zero, Bandit, Semgrep, and pip-audit all pass.

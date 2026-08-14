# Issue #13 — Arena Agent Mode GM productization findings

T42 is not accepted from unit tests or from a browser-extension toolbar alone.
This log records source and live observations while the generic Agent Mode GM
path is built and exercised.

## Baseline source inspection — 2026-08-14

### F1 — the shipped game skill describes the retired narrow path

`skills/book-of-eternity/SKILL.md` still names `boe-arena-relay`, tells the
agent to wait on `/v1/game/boe/*`, and instructs the Bridge-side agent to
calculate dice and realm rules. The accepted architecture now uses persistent
`arena-relay terminal` plus ordinary `relay.*`, `fs.*`, and `exec.*`; rules,
validation, progression, and canonical state remain game-owned.

### F2 — claiming a packet makes it undiscoverable to a fresh agent session

The file store moves a message from `inbox/` to `claimed/`, but MCP exposes only
`relay.check`, `relay.reply`, and `relay.send`. `relay.check` sees only `inbox/`.
After an Agent Mode session claims a daemon packet and closes, a fresh session
is told that no messages are waiting even though the durable claimed packet is
still on disk. `list_messages()` can see it, but no agent tool exposes that
fact or resumes it.

### F3 — relay status is too coarse for honest GM lifecycle reporting

`GET /v1/relay/status` reports inbox/reply depth and recent polling only. It does
not distinguish queued, claimed, actively processing, or replied packets. The
Dashboard therefore changes from “waiting” to zero as soon as a packet is
claimed, which can be read as completion while the agent is still authoring the
turn. Repair remains visible only inside the daemon packet body/context files.

### F4 — browser instructions have no relay or GM catalog scope

The extension supports arena.ai, remote HTTPS Bridge URLs, full MCP tool
execution, and operator-controlled global policy. Its instruction generator has
`fs`, `mission`, `memory`, and other topical scopes but no `relay` or generic GM
scope. Relay tools consequently fall into the generic `system` bucket and the
current Book of Eternity bootstrap cannot be copied as one coherent generic
capability set.

### F5 — the two supported Arena paths are not documented as one resume protocol

`docs/integrations/ARENA_AGENT_MODE.md` documents a direct prompt containing a
Bridge URL/token and basic smoke calls. The extension documentation separately
covers browser tool-block execution. Neither document defines the sequence a
new Arena session must follow: inspect relay lifecycle, claim or resume the
canonical daemon packet, read current game files, mark processing, author via
ordinary host tools, emit the game-owned terminal signal last, and only then
post the correlated relay reply.

## Candidate implementation findings

- Relay lifecycle is split into a bounded `arena/relay/lifecycle.py` module;
  physical inbox, claimed files, explicit busy markers and correlated replies
  remain the durable truth.
- HTTP `/v1/relay/check` and MCP `relay.check` now write the same file-backed
  heartbeat. Dashboard freshness therefore reflects Agent Mode polling rather
  than only HTTP polling.
- A durable `busy` marker does not prove a session is alive: once heartbeat is
  stale, Dashboard labels the packet recoverable and does not claim an active
  agent.
- `relay.busy` may attach `kind=turn|repair` only after the agent classifies the
  packet from game-owned evidence; lifecycle status can therefore expose a
  repair packet without Bridge implementing game rules.
- Fresh sessions resume only explicit claimed/busy packets. There is no timeout
  requeue that could deliver one turn to two sessions.
- **F6 — legacy claimed archives initially looked recoverable:** the first
  candidate bridge probe against the real Windows relay root reported 41
  claimed records. These were pre-lifecycle retained archive files whose
  replies had already been consumed, not a real backlog. The candidate now
  ignores claimed files without an explicit persisted lifecycle field for
  status/resume; this fails closed instead of inventing old work for a fresh
  session. A regression test constructs that legacy shape.

Static/focused verification completed before the accepted live run:

- full repository suite: `8354 passed, 36 skipped` with the configured
  coverage run also passing at `60.52%` (gate `46%`);
- relay/productization/architecture focused suites: `150 passed`;
- architecture/MCP/catalogue suite: `991 passed`;
- Ruff and lint ratchet: zero debt;
- Vulture/Pyrefly quality ratchets: zero debt;
- Bandit: zero high/medium, Semgrep: zero findings, pip-audit: zero CVEs
  across 11 resolved dependency entries;
- destructive controls made the fresh-session resume and honest Dashboard
  tests fail, followed by green restoration runs.

## PR review hardening — 2026-08-14

Review of the exact PR head found additional correctness and trust-boundary
issues. They are fixed in the candidate branch and covered by focused
regressions; none substitutes for the pending Windows live run.

- **F7 — trusted-host matching ignored scheme and port:** hostname-only matching
  enabled trusted-site behavior for HTTP and non-default ports. Trust now
  requires a canonical HTTPS origin on the default port; malformed origins
  degrade to manual confirmation.
- **F8 — `relay.check` was mislabeled read-only:** it atomically claims and moves
  queued work. It is now medium-risk while `relay.status` and read-only
  `relay.resume` remain safe.
- **F9 — heartbeat persistence could block delivery:** MCP and HTTP poll paths
  now treat heartbeat writes as best-effort. HTTP performs that disk I/O in the
  executor; a failed heartbeat write no longer prevents claiming the packet.
- **F10 — caller-controlled IDs reached a glob lookup:** externally supplied
  message IDs are now validated as generated 12-character lowercase hex and
  exact matched. Glob metacharacters cannot mark or resume another claim.
- **F11 — concurrent lifecycle writers could reopen replied work:** per-message
  OS file locking serializes cross-process read-modify-write updates, and
  `replied` is terminal-sticky. The OS releases ownership when a process dies,
  so the lock has no stale-owner timeout race.
- **F12 — malformed heartbeat JSON could fail status:** non-object JSON is now
  treated as absent listener evidence.
- **F13 — failed Windows move fallback inflated lifecycle counts:** snapshots
  deduplicate by message ID with the claimed record taking precedence over an
  inbox copy.
- **F14 — startup could select two packets:** both the replaceable game skill
  and generic guide now resume outstanding work first, otherwise claim one
  queued packet, and forbid selecting another before completion/status refresh.
- Reply records use the same `replied` lifecycle vocabulary as claimed records.
  Failure to persist the correlated claimed-record transition is logged without
  discarding the already-durable reply.
- Targeted resume now resolves the exact claimed path. Empty MCP polling uses a
  depth-only lifecycle scan instead of constructing a complete status snapshot.

Post-hardening verification:

- focused relay/HTTP/MCP/extension/version suites: `179 passed` on Linux and
  `179 passed` on the real Windows host (including the `msvcrt` lifecycle-lock
  branch);
- full repository suite without coverage instrumentation: `8367 passed, 36
  skipped`;
- Ruff 0.16.2 on all changed Python files and the lint ratchet: clean;
- Vulture/Pyrefly quality ratchet: zero findings;
- `git diff --check` and changed-module byte compilation: clean.

## Live baseline — installed v4.169.44 host

Authenticated probes against the running Windows bridge confirmed the source
findings rather than merely inferring them:

- `/v1/relay/status` returned `inbox_depth=0`, `reply_depth=0`, and
  `agent_polling=false`, but had no queued/claimed/busy/replied fields;
- requesting extension instructions with `category=gm` silently normalized to
  `category=safe`; `available_categories` did not contain `gm`, and the returned
  catalog began with unrelated ASR/browser/code tools.

No mailbox message was consumed or fabricated by these probes.

## Live findings discovered after the candidate was installed

### Game-side repair timeout and rollback boundary

The first intentional actor-memory failure reached the game-owned validator and
returned `actor_memory_persistence_repair` through the daemon and terminal
relay. The repair was authored after the client had already exhausted its
bounded wait, so the relay reply could not make that application turn accepted.
This proves why a relay-level `replied` state must not be represented as game
acceptance.

The late repair had already appended Guardian journal entry
`gtj_turn004_deed_before_name`. The accepted retry used a new request and entry
`gtj_turn004_deed_before_name_retry`; both entries remain. Unique IDs prevent a
physical duplicate write, but do not deduplicate two semantically equivalent
memories created on opposite sides of a client timeout. This is game-side
repair/rollback debt: canonical rollback and the later worker write are not one
transaction. It is recorded for the game repository and is not implemented in
the generic Bridge.

### GMBridge false Busy and deleted-status recovery

The shipped GMBridge readiness adapter recognized only Codex prompts. A healthy
Arena terminal relay could therefore be reported as Busy after completion. A
provisional game-side adapter patch now recognizes the generic relay's explicit
idle/busy markers, performs a fail-closed dispatch probe, and periodically
republishes a missing status file.

A final destructive check deleted `gm_bridge_status.json` while the helper was
idle. It was recreated in **248 ms** with the same PID and process start time;
the recovered document reported `state=Ready`, `ready=true`, and
`lastError=null`. No process restart or player action was required.

### F15 — canonical extension payload was parseable but not discoverable

The first real Arena.ai browser-extension attempt rendered no Run controls for a
canonical fenced payload:

```json
{"bridge":"arena","version":1,"calls":[{"id":"t42-browser-ui-status","tool":"relay.status","arguments":{}}]}
```

`parser.js` accepted that envelope, but the earlier `adapters.js` candidate
prefilter required the unrelated JSONL strings `function_call_start` or
`arena_tool`. The parser could therefore never receive the extension's own
normal format. Extension `0.14.44` removes the split grammar: candidate
discovery delegates to `parseArenaBlocks`, including its instruction/example
false-positive guards. Executable regressions cover canonical fenced and bare
envelopes, single calls, JSONL, ordinary prose, a foreign bridge, and echoed
Bridge instructions. Chromium and generated Firefox assets remain aligned.

Focused browser-extension/Bridge verification after the fix: **775 passed**;
the complete repository suite passed with **8375 passed, 36 skipped**.
After reloading the unpacked extension, the operator used the actual inline
**Run** control on arena.ai and the result was inserted into the composer/chat.
The Bridge audit independently recorded an `extension_execute` event at
`2026-08-14T16:13:32Z` with `adapter=arenaai`, canonical
`site=https://arena.ai`, one safe `relay.status` call, and `ok=true`. This is the
browser UI path; it is not a hand-authored request to `/v1/extension/execute`.

## Live acceptance — complete on 2026-08-14

The accepted run used the installed Windows Bridge, the real game client and
daemon, GMBridge/ConPTY, persistent `arena-relay terminal`, and ordinary
`relay.*`, `fs.*`, and `exec.*` capabilities. Process inventory contained no
Codex process; every Codex worker in GMBridge status was disabled.

### Honest inactivity, durability, and fresh-session recovery

- With no active Arena poller, packet `1e5a11fabd40` remained physically queued
  while `/v1/relay/status` reported `agent_polling=false` and
  `last_poll_age_s=221.69`. The daemon message was neither lost nor shown as an
  active listener.
- An older Arena session claimed turn packet `42982d4d9dfa` and then stopped
  heartbeating. At stale age `72.08s`, a fresh session performed exact targeted
  `relay.resume(message_id=42982d4d9dfa)` rather than claiming another packet.
- The fresh session reread the current turn request, Soul state, Guardian
  journal, and progression schedule from the host before authoring. It then
  marked the exact packet Busy, completed the host files, and posted the
  correlated reply. No chat-memory reconstruction was used.

### Multiple accepted authored turns

The game accepted and rendered all of these daemon-driven Arena turns:

| Turn | Request | Relay packet | Relay reply | Result |
| --- | --- | --- | --- | --- |
| 4 | `8c79a5fb65714d3d8c2d33aa05b25777` | `f66d336507e2` | `71baa561e482` | accepted retry |
| 5 | `c4bc99d160434f46941f9e54fa917234` | `42982d4d9dfa` | `71e7d1b88f6c` | accepted after fresh-session resume |
| 6 | `e6c0fdc9804f496fb044284c445980c2` | `1e5a11fabd40` | `42cf51c50ea0` | accepted after inactive queued persistence |
| 7 | `a0f68eb5f39a4db196cb68b868216b73` | `79c4143b6b1d` | `efa9c1110150` | accepted, then intentionally repaired |

Agent Console rendered each authored scene and three enabled player actions.
After turn 7, the Chaos Sea, Guardian-project, and resident-agency ordinals all
advanced to `7` with no pending cycles.

### Bounded intentional validation repair

Turn 7 deliberately added unsupported top-level field
`output/narrative_response.json.t42IntentionalProbe`. The game accepted the
terminal phase, rejected resulting state with
`narrative_response_unknown_field`, and sent repair packet `c07a21a12be7`
through daemon → ConPTY → relay. The Arena session classified it as `repair`,
read `validation_repair_request.json` and the named compact output-repair
template, changed only the allowlisted narrative artifact, emitted
`Complete-BoeValidationRepair` last, and replied as `c64960c42464`.

The trajectory ledger records both correlated acceptance stages:

- `repair.status=accepted`, `acceptanceScope=correlated_repair_ready`;
- `repair.status=cleared`, `acceptanceScope=full_canonical_state_after_repair`,
  `fullCanonicalStateAccepted=true`.

The repair packet was created at `16:00:48.557Z`, claimed at `16:00:48.691Z`,
marked Busy at `16:00:56.091Z`, and relay-replied at `16:01:04.022Z`; full
canonical revalidation cleared at `16:01:05.260Z`. Agent Console then rendered
the repaired turn-7 scene with no diagnostics.

### Final state

- Relay depths: queued `0`, claimed `0`, busy `0`, outstanding `0`, reply `0`;
  all seven observed turn/repair packets are terminal `replied` records.
- GMBridge: `Ready`, `ready=true`, `lastError=null`.
- Game progression: accepted ordinal `7` for all required Chaos Sea tracks.
- No Codex process was present in the accepted process inventory.
- The generic boundary remains intact: Bridge owns transport, lifecycle,
  policy, and host capabilities; the replaceable game skill owns bootstrap;
  **The Book of Eternity: Reborn** owns rules, validation, progression,
  canonical state, and repair semantics. No narrower game-specific core API is
  needed for other games or non-game applications.

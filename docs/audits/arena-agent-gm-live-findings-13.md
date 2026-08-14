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

Static/focused verification completed before the accepted live run:

- relay/productization/architecture focused suites: `150 passed`;
- architecture/MCP/catalogue suite: `991 passed`;
- Ruff and lint ratchet: zero debt;
- Vulture/Pyrefly quality ratchets: zero debt;
- Bandit: zero high/medium, Semgrep: zero findings, pip-audit: zero CVEs
  across 11 resolved dependency entries;
- destructive controls made the fresh-session resume and honest Dashboard
  tests fail, followed by green restoration runs.

## Live baseline — installed v4.169.44 host

Authenticated probes against the running Windows bridge confirmed the source
findings rather than merely inferring them:

- `/v1/relay/status` returned `inbox_depth=0`, `reply_depth=0`, and
  `agent_polling=false`, but had no queued/claimed/busy/replied fields;
- requesting extension instructions with `category=gm` silently normalized to
  `category=safe`; `available_categories` did not contain `gm`, and the returned
  catalog began with unrelated ASR/browser/code tools.

No mailbox message was consumed or fabricated by these probes.

## Live acceptance pending

The accepted run must still prove, without a Codex process:

1. inactive Arena leaves a durable queued daemon packet and is reported as
   inactive;
2. an Arena session claims and marks that packet busy using generic tools;
3. multiple game turns render successfully;
4. one intentional validation failure returns as a repair packet and is fixed;
5. a stopped Arena session leaves recoverable canonical work;
6. a fresh Arena session resumes without invented memory;
7. final queues, process trees, and atomic temp files are clean.

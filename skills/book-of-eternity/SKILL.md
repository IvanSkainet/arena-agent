# Book of Eternity (BoE) Game Master Skill

This skill equips an AI agent (Arena Agent Mode, Claude Code, Codex) to act as the
autonomous **Game Master (GM)** for the game **Book of Eternity**, communicating seamlessly
with the local Game Master daemon (`game_master_daemon.ps1`) through Skainet Bridge.

---

## 1. Architecture & Protocol

Book of Eternity uses a canonical **file protocol**. The GM never invokes proprietary APIs
or sends arbitrary socket packets; all interactions are governed by session files.

```
Player (Game / UI)
    │ writes input/turn_request.json
    ▼
game_master_daemon.ps1
    │ sends dispatch prompt
    ▼
boe-arena-relay (ConPTY / Bridge)
    │ writes arena_relay_inbox.json
    ▼
AI GM (via Skainet Bridge boe.* tools)
    │ reads state, resolves turn, writes output
    ▼
ready/turn_complete.json  (via boe.complete_turn)
    │ daemon advances the game
    ▼
Player receives turn results
```

---

Skainet Bridge is a **tunnel**, not a second copy of the game. Prefer the
vanilla host file tools (`fs.read`, `fs.write`, `fs.list`) against the
session directory on the operator's machine. The `boe.*` routes are a thin
helper for the same bytes. Do not invent realm rules, dice, or C# validators
inside the bridge — the client already owns those.

Official player-facing artifacts (unknown top-level fields are rejected):

| File | Allowed top-level fields |
|---|---|
| `output/narrative_response.json` | `response`, `timestamp` |
| `output/debug_logs.json` | `gm_thoughts_markdown`, `timestamp` |
| `output/interface_updates.json` | `dialogueOptions`, `image_prompt`, `timestamp` |
| `ready/turn_complete.json` | `sessionId`, `requestId`, `turnNumber`, `timestamp`, `status=success`, `filesModified` |

## 2. Autonomous GM Turn Loop

When acting as Game Master, execute the following continuous cycle:

### Step 1: Wait for Incoming Turn
Invoke the long-polling tool to await the next turn packet:
```json
POST /v1/game/boe/wait_inbox
{"timeout_sec": 25.0}
```
*If `has_packet` is false, poll again. When `has_packet` is true, extract `packet`.*

### Step 2: Read Game State & Prompt Directives
1. Read `packet.prompt` to identify the turn objective, `turnNumber`, and `requestId`.
2. Inspect `game_state/soul_state.json` and active rules/templates in the session directory.

### Step 3: Game Master Reasoning & Rules Resolution
Resolve the turn according to Book of Eternity rules:
- Respect the **Realm Gate** (Mortal vs Afterlife matrices);
- Calculate dice rolls, attribute checks, combat outcomes, and narrative state;
- Prepare state delta updates.

### Step 4: Write Game State Updates
Update session state safely using `boe.write_json`:
```json
POST /v1/game/boe/write_json
{
  "path": "game_state/soul_state.json",
  "data": { ... }
}
```
*(Prohibited paths: `input/`, `pending_turn_snapshot*`, `gm_bridge_status.json`, `stories/*.jsonl` — these are managed exclusively by the client/daemon).*

### Step 5: Complete the Turn (Terminal Signal)
Close the turn strictly through the completion tool:
```json
POST /v1/game/boe/complete_turn
{
  "summary": "Player succeeded check and advanced to next room",
  "turn_number": 42,
  "request_id": "req_12345"
}
```
*This generates `ready/turn_complete.json`, marks inbox as completed, and notifies the daemon to advance the game loop.*

### Step 6: Handle Validation Repairs (If Requested)
If `packet.kind == "repair"`:
Fix any discrepancy identified by the daemon's validator and call:
```json
POST /v1/game/boe/repair_turn
{
  "summary": "Repaired soul_state field formatting"
}
```

---

## 3. Tool Reference

| Tool / Route | Description |
|---|---|
| `GET /v1/game/boe/status` | Check session directory, active inbox, and ready files. |
| `POST /v1/game/boe/wait_inbox` | Wait (long-poll) for incoming turn packet from daemon. |
| `GET /v1/game/boe/read_turn` | Read current turn request, state, and inbox. |
| `POST /v1/game/boe/write_json` | Atomic safe write of session JSON with path traversal guards. |
| `POST /v1/game/boe/complete_turn` | Finalize active turn with `ready/turn_complete.json`. |
| `POST /v1/game/boe/fail_turn` | Emit terminal error with `ready/turn_error.json`. |
| `POST /v1/game/boe/repair_turn` | Acknowledge validation repair with `validation_repair_ready.json`. |

# The Book of Eternity: Reborn — Arena Agent Mode GM

Use an already-running Arena.ai Agent Mode session as the external Game Master
for **The Book of Eternity: Reborn** through Skainet Bridge.

The integration uses the normal Bridge surface: `relay.*`, `fs.*`, `exec.*`, and
any other generally available tool the task needs. A game-only token or a
hard-coded narrow tool subset is not required. The operator's global Bridge
profile remains the only capability policy layer.

## Authority boundary

Skainet Bridge is transport and host access, not a second game engine.

- The game owns rules, validation, progression, canonical state, request
  correlation, and terminal-signal formats.
- The daemon packet and its current `gm_context_pack` own turn instructions.
- The Arena agent owns reasoning and authorship.
- Do not copy C# validators, dice rules, realm matrices, or narrative rules into
  Bridge code or this skill.
- Do not treat chat history as canonical game memory. Read current host files.

No Codex process is required. Do not start or automate an Arena browser session;
the relay is a durable mailbox for a session the player started themselves.

## Transport chain

```text
player action
  -> game client writes canonical request
  -> game_master_daemon.ps1 builds the current packet
  -> BookOfEternityGMBridge hosts persistent arena-relay terminal in ConPTY
  -> generic authenticated relay mailbox
  -> active Arena Agent Mode session
  -> ordinary fs.* / exec.* host work
  -> game-owned terminal signal
  -> correlated relay.reply releases the terminal
  -> client validates and renders
```

## Connect Arena Agent Mode

Two supported paths expose the same full Bridge tool catalog.

### Browser-extension path

1. Install `chat_extension/` and configure the Bridge HTTPS URL and token.
2. On arena.ai, copy extension instructions with catalog scope
   **GM: relay.* + fs.* + exec.***.
3. Start Agent Mode yourself and paste this skill/bootstrap instruction.
4. Tool blocks execute through `/v1/extension/execute`; the extension does not
   automate login, model selection, or session creation.

### Direct HTTPS/MCP path

Connect Agent Mode to the authenticated Bridge MCP endpoint over the current
Tailscale/ngrok/Cloudflare HTTPS URL. Discover the full catalog normally. Do not
embed a token in game files, prompts committed to source, or relay messages.

## Fresh-session and resume protocol

Every new Arena session begins with transport facts, not assumed memory. The
canonical host files are the only resume authority.

1. Call `relay.status`.
2. If `outstanding_depth > 0` and no previous Arena session is still active,
   call `relay.resume`. Use `message_id` when status shows more than one packet.
   Never resume while another live session may still be authoring that message.
3. Otherwise, if `queued_depth > 0`, call `relay.check` once to atomically claim
   the oldest packet. A bootstrap pass must resume **or** claim, never both.
   Do not select another packet; refresh status only after completing this one.
4. Call `relay.busy` with the packet id and a fresh session correlation label;
   omit `kind` until the packet/control files prove it.
5. Read the packet body and metadata. Then inspect the canonical request and the
   current daemon context pack with `fs.read`, `fs.view`, `fs.list`, and
   `fs.search` as needed.
6. Reconstruct the turn only from current canonical files. Do not invent prior
   actions, accepted state, or repair history from conversation prose.

`relay.check` returning no queued packet while status reports claimed/busy work
is not an empty game: it is recoverable outstanding work. Conversely,
`agent_polling=false` means no Arena session is currently proven to be
listening; queued packets remain durable.

## Turn execution loop

For each claimed packet:

1. **Classify from the daemon packet and canonical control files.** Determine
   whether this is a normal turn or validation repair, then update `relay.busy`
   with `kind=turn` or `kind=repair`. Do not infer repair from Bridge-specific
   rules.
2. **Read before writing.** Read the exact current request, relevant canonical
   state, `game_state/control/gm_context_pack/README.md`, and compact templates
   named by the daemon. The packet may contain useful repair instructions that
   are absent from old chat context.
3. **Author through normal tools.** Use `fs.*` for bounded file reads/writes and
   `exec.*` for the game-owned helper or diagnostics. Other Bridge tools remain
   available when genuinely needed; this skill does not impose a narrow
   allowlist.
4. **Let the game validate.** Write only artifacts requested by the current
   game contract. Official output JSON must not gain unknown top-level fields.
5. **Emit the game-owned terminal signal last.** Invoke the exact current helper
   procedure named by the daemon/context pack through `exec.exec`; do not hand
   invent its schema in the Bridge.
6. **Release ConPTY only after durable completion.** Call
   `relay.reply(in_reply_to=<packet id>, body=<bounded completion summary>)`
   only after the terminal signal exists and all required writes are complete.
7. Call `relay.status` and continue with `relay.check(wait=25)` while the player
   session remains active.

Replying before the game-owned signal is a transport bug: it returns
`arena-relay terminal` to READY while the client still has no completed turn.

## Validation repair

A repair is another daemon packet in the same generic relay:

1. mark it busy;
2. read the current `validation_repair_request.json` and packet instructions;
3. change only what the current game contract requires;
4. invoke the current game-owned repair completion helper last;
5. post the correlated relay reply;
6. wait for client acceptance or a new repair packet.

Do not reuse a stale repair packet, fabricate request correlation, or transfer
rules into Bridge-side code.

## Honest lifecycle meanings

| Lifecycle | Meaning |
|---|---|
| `queued` | Durable packet exists; no agent has claimed it. |
| `claimed` | One agent atomically took the packet; active work is not yet asserted. |
| `busy` | An agent marked processing; it is active only while listener heartbeat is fresh, otherwise it is recoverable work. |
| `replied` | A correlated relay reply was durably written. This does not replace game validation. |
| `repair` | Packet metadata/control files identify validation repair; it still follows queued → claimed → busy → replied. |

Success requires both layers: a correlated relay reply and game acceptance.

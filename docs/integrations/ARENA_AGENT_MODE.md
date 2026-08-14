# Arena Agent Mode + Skainet Bridge

Arena Agent Mode is the reasoning/authorship layer. Skainet Bridge provides the
operator-owned machine, files, processes, hardware, and durable relay.

The supported design does not automate arena.ai. The operator starts the Arena
session themselves; Bridge tools and queued messages become available to that
already-running session.

## Connection paths

Both paths expose the ordinary full Bridge catalog. Neither requires a narrow
application-specific token or tool subset.

### Browser extension

1. Start Bridge and an HTTPS transport usable by the browser.
2. Install the unpacked extension from `chat_extension/`.
3. Set the Bridge URL and token in the extension popup.
4. Open arena.ai Agent Mode yourself.
5. Choose catalog scope **GM: relay.* + fs.* + exec.*** and copy the Arena
   instructions into the new session.
6. Tool blocks are detected on the page and executed through
   `/v1/extension/execute`. The extension never performs login, chooses a model,
   or summons a session.

Arena.ai is a trusted extension host over its canonical HTTPS origin. Lifecycle
inspection/resume is safe; `relay.check` is medium because it claims a queued
packet. Writes, shell execution, and outgoing messages still follow the
operator's normal global Bridge posture. Game integration does not add a second
policy layer.

### Direct remote MCP/HTTPS

Connect Agent Mode to the authenticated Bridge MCP endpoint over the active
Tailscale Funnel, ngrok, Cloudflare, ZeroTier, or other operator-selected HTTPS
transport. Discover and use the full tool catalog normally.

Do not commit or place the Bridge credential in game state, daemon packets,
relay messages, screenshots, or public prompts.

## Generic external-GM bootstrap

For The Book of Eternity: Reborn, paste/use
`skills/book-of-eternity/SKILL.md`. The same lifecycle applies to any local
program using `arena-relay terminal`:

1. `relay.status` — inspect queued/claimed/busy/replied state without claiming.
2. If outstanding claimed/busy work exists, confirm the old Arena session is
   gone and use `relay.resume` to recover exactly one packet.
3. Otherwise, if queued work exists, use `relay.check` to claim exactly one
   packet. A bootstrap pass must resume **or** claim, never both. Do not select
   another packet; refresh status only after completing this one.
4. `relay.busy` — make active processing explicit and session-correlated.
5. Use ordinary `fs.*`, `exec.*`, and other full Bridge tools to perform the
   host work described by the packet.
6. `relay.reply` only after durable host-side completion.

A fresh session must read canonical host files and the pending daemon packet. It
must not manufacture prior memory from the new chat's lack of context.

## Honest status contract

- `agent_polling=false`: no active Arena listener is proven. A packet may still
  be queued durably.
- `queued`: not claimed by an agent.
- `claimed`: atomically claimed, but active processing not yet asserted.
- `busy`: an agent marked active work; it is currently active only while the
  listener heartbeat is fresh, otherwise the packet is recoverable.
- `replied`: a correlated relay reply exists; application-level validation is a
  separate fact.
- `repair`: the application packet identifies repair while retaining the normal
  relay lifecycle.

Dashboard and `GET /v1/relay/status` expose these depths. A drop in
`inbox_depth` alone is not completion.

## General project workflow

For non-game project sessions:

1. call `sys.status` and `relay.status`;
2. inspect the relevant repository with `fs.*` and `git.*`;
3. use a scoped memory profile such as `projects/<repo>` when persistent
   project facts are useful;
4. execute changes through normal Bridge tools and verify on the host.

Arena remains the reasoning frontend; Skainet Bridge remains the self-hosted
execution and transport layer.

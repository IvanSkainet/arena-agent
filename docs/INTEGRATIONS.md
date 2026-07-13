# Arena Unified Bridge — Integration Recipes

This page is the entry point for using Arena as the **hands/tools layer** for
other AI frontends, IDE agents, and local model stacks.

## Before you start

You need:
- a running bridge
- your bridge URL
- your auth token from `token.txt`

Recommended first checks:

```bash
curl -H "Authorization: Bearer <TOKEN>" <BRIDGE_URL>/v1/status
curl -H "Authorization: Bearer <TOKEN>" <BRIDGE_URL>/v1/doctor
```

If you are experimenting with long-lived context, remember that Arena `v3.3.0+`
supports **Memory Profiles**. Start simple with:
- `default`
- `personal`
- `projects/<name>`
- `code`
- `browser`

## Choose a recipe

### Chat / web-agent frontends
- [Arena Agent Mode](integrations/ARENA_AGENT_MODE.md)
- [Claude / ChatGPT / generic custom-tools chats](integrations/CLAUDE_CHAT_PROMPT.md)

### IDE / coding agents
- [Cursor](integrations/CURSOR.md)
- [Cline](integrations/CLINE.md)
- [Windsurf](integrations/WINDSURF.md)

### Local agent shells
- [Open Interpreter](integrations/OPEN_INTERPRETER.md)
- [Local model backends (Ollama / OpenRouter / Groq / Together)](integrations/LOCAL_MODELS.md)

## Remote access — the unified tunnels facade

When you need clients outside your machine to reach the Bridge, use the
`/v1/tunnels/*` facade instead of stitching individual providers together.
It hides the differences between Tailscale Funnel, Cloudflare Quick Tunnel,
and ZeroTier behind one contract and picks the first healthy provider by
priority.

```bash
# What is currently reachable? Which provider owns the URL right now?
curl -sH "Authorization: Bearer <TOKEN>" <BRIDGE_URL>/v1/tunnels/active

# Full snapshot (every provider, installed/active/public_url + hints)
curl -sH "Authorization: Bearer <TOKEN>" <BRIDGE_URL>/v1/tunnels/status

# Start every configured provider by priority; stop on the first healthy one
curl -sH "Authorization: Bearer <TOKEN>" -X POST <BRIDGE_URL>/v1/tunnels/start

# Stop tunnels the Bridge started (ZeroTier membership is intentionally left alone)
curl -sH "Authorization: Bearer <TOKEN>" -X POST <BRIDGE_URL>/v1/tunnels/stop
```

Default priority is `tailscale > cloudflared > zerotier`. Override per host
via the `ARENA_TUNNEL_PRIORITY` env variable, e.g.
`ARENA_TUNNEL_PRIORITY=cloudflared,zerotier`. Providers you omit stay at
their default position, so nothing is silently dropped.

Tips per integration:

- **Chat frontends** (Claude / ChatGPT / etc.) — hand the client the URL from
  `/v1/tunnels/active.public_url`. If that provider drops, poll `/v1/tunnels/status`
  and switch clients over.
- **IDE agents** — most tools want a stable URL. Prefer a Tailscale Funnel
  hostname (`*.ts.net`) as the primary; the facade will fall back to
  Cloudflare Quick Tunnel or a ZeroTier LAN URL only when Tailscale is
  unavailable.
- **Local model shells** — usually you do not need remote access at all;
  keep the Bridge on `127.0.0.1:8765` and skip the facade entirely.

Per-provider primitives remain available (`/v1/tailscale/funnel/*`,
`/v1/cloudflared/tunnel/*`, `/v1/zerotier/*`) for cases where you want
granular control.

## General operating advice

1. Treat Arena as the **tool substrate**, not necessarily the model provider.
2. Start every new integration with a smoke test:
   - `/v1/status`
   - `/v1/memory?profile=default`
   - `/v1/browser/head?url=https://example.com`
3. Use **Memory Profiles** immediately for project work.
4. Prefer `PATCH /v1/fs/edit` / MCP `fs.edit` for code changes over full-file rewrites.
5. When exposing the Bridge remotely, drive it through the
   [tunnels facade](#remote-access--the-unified-tunnels-facade) so a single
   provider outage does not take the whole Bridge offline.
6. If an agent is too constrained by its own host product, move more logic into
   Arena-side tools, missions, and memory rather than fighting the frontend.

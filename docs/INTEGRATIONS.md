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

## Hardening the client side (v4.40.0 → v4.46.0)

Once you have chosen a tunnel and pointed a client at it, the CLI
(`agentctl`) has three security levers you should consider before
going into production. Full reference in [`SECURITY.md`](../SECURITY.md);
this section is the "what do I actually set" short list.

**1. TLS certificate pinning (v4.45.0).** By default the client trusts
any cert signed by any of the OS's ~150 CAs. Pin the bridge cert to
tighten that anchor to exactly the certificate you expect:

```bash
# Compute the SPKI (public-key) fingerprint. Survives cert rotation
# as long as the same private key is reused, which Tailscale does.
export ARENA_BRIDGE_PIN_SHA256=$(
  openssl s_client -connect your-bridge.tailnet.ts.net:443 </dev/null 2>/dev/null \
    | openssl x509 -pubkey -noout \
    | openssl pkey -pubin -outform DER \
    | sha256sum | cut -d' ' -f1
)
export ARENA_BRIDGE_PIN_KIND=spki
```

Multi-pin is supported (comma-separated) for rotation-safe
deployments — pin the current cert plus a spare and rotate lazily.

**2. Signed URL cache (v4.40.0).** Automatically enabled. On every
successful `/v1/agent/config` call the CLI writes an HMAC-signed
snapshot to `~/.arena/last_urls.json` (0o600). When the bootstrap
URL is unreachable, the CLI falls back to a URL from the cache —
but only if the signature verifies against the current bearer token.
An attacker with write access to your home can't poison this cache
because they don't have the token needed to forge the signature.
Disable with `ARENA_BRIDGE_URL_CACHE=0` if you prefer no persistent
state; you'll lose the offline-fallback behaviour.

**3. Peer-address logging privacy (v4.44.0).** `requests.jsonl`
records every request's peer IP by default. When shipping logs off
the box (bug reports, log aggregation) that's a fingerprint of every
client. Turn it into a hash or drop it entirely:

```bash
# Deterministic per-install hash — count-distinct still works,
# actual IPs never persist. Rotate the salt to invalidate old logs.
export ARENA_LOG_PEER=mask
export ARENA_LOG_PEER_SALT=$(openssl rand -hex 16)

# Or omit the field altogether:
export ARENA_LOG_PEER=off
```

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

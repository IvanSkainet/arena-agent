# Multi-agent sessions (v3.86.0+)

Run 2+ isolated agents against the same bridge without them fighting
over the master token. Each agent gets:

* Its own bearer token (`agent-XXXXXXXX-YYYYYYYYYYYYYYYY`).
* Its own request counter + audit ring (last 500 events) so you can
  tell what each agent has been doing.
* Atomic revocation — one `DELETE` and the token stops working
  immediately, even on in-flight requests.

The master token keeps full access. Agent tokens can call every
existing endpoint EXCEPT `/v1/agents/*` (management is master-only).

---

## Quick start (Dashboard)

Settings → **Multi-agent sessions**:

1. Type a label (e.g. `gardenxas-workstation`) → **Create agent**.
2. A yellow box appears with the new token. **Copy it now** — it
   won't be shown again after you Refresh.
3. Hand the token to whoever needs it (or paste it into your own
   agent's config).
4. When done, hit **Revoke** on the row.

## Quick start (curl)

Create:

```bash
MASTER=IUzqZNyZDH4f...             # your bridge's master token
BRIDGE=https://your-bridge.example  # public URL

curl -sSf -X POST \
  -H "Authorization: Bearer $MASTER" \
  -H "Content-Type: application/json" \
  -d '{"label":"gardenxas-workstation"}' \
  "$BRIDGE/v1/agents"
```

Response (this is the ONLY time the token is returned):

```json
{
  "ok": true,
  "action": "agents.create",
  "agent": {
    "agent_id": "46acc5f0",
    "label": "gardenxas-workstation",
    "created_at": 1784121364.88,
    "last_seen_at": 0,
    "request_count": 0,
    "audit_recent": [],
    "token": "agent-46acc5f0-8cfb6bbb51a77078"
  }
}
```

Save `agent.token`. Use it as a drop-in replacement for the master
token on every other endpoint:

```bash
AGENT=agent-46acc5f0-8cfb6bbb51a77078

# Works exactly like the master token would:
curl -sSf -H "Authorization: Bearer $AGENT" "$BRIDGE/v1/mobile/devices"
curl -sSf -H "Authorization: Bearer $AGENT" "$BRIDGE/v1/sysinfo"
# ... every other /v1/* endpoint.

# BUT: management endpoints refuse agent tokens (returns 403):
curl -sSf -H "Authorization: Bearer $AGENT" "$BRIDGE/v1/agents"
# {"ok":false,"error":"agent tokens cannot manage other agents; ..."}
```

List active agents (master only):

```bash
curl -sSf -H "Authorization: Bearer $MASTER" "$BRIDGE/v1/agents"
```

Response includes per-agent counters but NEVER the token:

```json
{
  "ok": true,
  "count": 2,
  "agents": [
    {
      "agent_id": "46acc5f0",
      "label": "gardenxas-workstation",
      "created_at": 1784121364.88,
      "last_seen_at": 1784121430.11,
      "request_count": 42,
      "audit_recent": [
        {"type": "mobile.camera.shutter", "serial": "2200ad3b",
         "ok": true, "ts": 1784121428.03}
      ]
    },
    ...
  ]
}
```

Revoke:

```bash
curl -sSf -X DELETE \
  -H "Authorization: Bearer $MASTER" \
  "$BRIDGE/v1/agents/46acc5f0"
# {"ok":true,"action":"agents.revoke","agent_id":"46acc5f0"}

# The agent's token immediately stops working:
curl -s -H "Authorization: Bearer $AGENT" "$BRIDGE/v1/mobile/devices"
# {"ok":false,"error":"unauthorized"}  (HTTP 401)
```

Get one agent's details:

```bash
curl -sSf -H "Authorization: Bearer $MASTER" \
  "$BRIDGE/v1/agents/46acc5f0"
```

---

## Cross-cutting notes

**Token durability.** Tokens are derived deterministically from the
master token + agent_id (HMAC-SHA256), so:

* Restarting the bridge revokes every agent (the registry is
  in-memory) — but if you know an agent_id + label from a prior
  session, you can't reconstruct the token without the master.
* Rotating the master token invalidates every agent token in one
  go. Useful for incident response: "everyone log back in."
* Forging a token for an existing agent_id is cryptographically
  infeasible without the master token.

**WebSocket auth.** The mobile mirror endpoint accepts `?token=`
query strings (browsers can't set `Authorization` on a WS upgrade).
Agent tokens work there too:

```
wss://your-bridge.example/v1/mobile/{serial}/mirror?token=agent-XXX-YYY
```

**Rate limits.** The bridge's IP-based auth-failure rate limit (10
per minute per peer) applies globally, not per-agent. A leaky agent
that keeps sending 401s will lock out its own peer address for a
minute, not other agents from the same address.

**Audit trail.** Every agent's request bumps its `request_count`
and events land in its `audit_recent` ring (bounded at 500 entries).
The bridge's main audit log ALSO records every request as usual,
so you never lose the global view.

**Not implemented (deliberately, per user feedback "excess that
distracts the model"):**

* Per-agent resource locks (two agents CAN try to run screenrecord
  on the same phone; last-writer-wins, same as master-token behaviour
  today).
* Per-agent rate limits.
* Per-agent tunnels / bridge home directories.
* Persistent agent registry across bridge restarts.

If you actually hit one of these, open an issue with a concrete
scenario — the design leaves room to add them without breaking the
current API.

# Arena Agent Local Home

Persistent local tool/memory layer for Arena Agent sessions on Ivan's CachyOS machine.

## Purpose

Arena's built-in sandbox is disposable. This directory is durable and lives on the user's computer.
It stores scripts, reports, projects, reusable tool setup, and non-secret session memory.

## Rules

- Access is explicit: only through `local_bridge.py` while Ivan runs the bridge/tunnel.
- Do not store passwords, tokens, cookies, SSH keys, browser profiles, or private secrets here unless Ivan explicitly asks.
- Every bridge command is audited at `~/.arena-local-bridge/audit.jsonl`.
- Prefer reproducible scripts over one-off shell commands.

## Common commands

```bash
~/arena-agent/bin/agentctl doctor
~/arena-agent/bin/agentctl inventory
~/arena-agent/bin/agentctl ip
~/arena-agent/bin/agentctl browser-smoke https://example.com
~/arena-agent/bin/agentctl logs 50
```

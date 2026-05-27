# core/snapshot

Create a full state archive — everything needed to reconstruct the platform
on a fresh machine. Like `agentctl backup` but more comprehensive and
self-describing.

## Inputs (optional flags)
- `--out PATH`   — output tarball path (default: `~/arena-bridge/backups/snapshot-<UTC>.tgz`)
- `--include-logs` — also include `~/arena-bridge/logs/` and the audit log

## Outputs
- `<out>.tgz` (chmod 600)
- `<out>.manifest.json` next to it: SHA256, file count, size, list of
  versions of all key scripts.
- Path to the tarball printed to stdout.

## What's included
- `bin/agentctl`, all of `scripts/`, `skills/`
- `memory/facts.jsonl`, `memory/sessions/`, `memory/RECOVERY_PROMPT_RU.md`
- `~/.config/systemd/user/arena-local-bridge.service`
- `~/.config/systemd/user/arena-task-runner.service`
- `~/arena-local-bridge/local_bridge.py`, `README_RU.md`

## What's NEVER included
- `~/arena-local-bridge/token.txt`
- any file matching `*token*`, `*secret*`, `*.key`
- browser profiles, SSH keys, cookies

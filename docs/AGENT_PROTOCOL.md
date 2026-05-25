# Arena Agent — protocol notes for the *remote* agent (me, in Arena chat)

These are hard-won rules from real failures. Read this BEFORE patching anything.

## Bridge transport rules

1. **`curl --curves X25519` is mandatory** for the Tailscale Funnel URL from
   Arena sandbox (OpenSSL 3.5 ClientHello issue otherwise).
2. **Env vars do NOT persist** between Arena `bash` tool calls. Always rebuild
   `./br` wrapper at the start of each session if it's missing.
3. **One `bridge_call.sh` invocation = one shell on the remote.** State
   (`cd`, `export`, etc.) does not survive into the next call.

## Quoting rules (THE most common source of bugs)

NEVER do these — they will mangle your payload:

- **bash heredoc → bash heredoc**: the outer shell processes `\$`, `\``,
  `\\n` in the inner one. Result: silently broken Python strings.
- **base64-encoded shell command containing inline Python that contains
  string literals with `\n`**: the literal newline gets injected, the Python
  string becomes unterminated, you get `SyntaxError: unterminated string
  literal` on line 316.
- **Backticks inside shell strings sent through bridge**: they trigger
  command substitution somewhere in the pipeline. Use `'$(cmd)'` or pre-render
  the text into a file and `cat` it.

ALWAYS do these:

1. **Edit files locally** in workspace (`arena-agent-v0.3/...`).
2. **Send via base64**: `B64=$(base64 -w0 path/to/file); ./br "echo '$B64'
   | base64 -d > /remote/path && chmod 600 /remote/path"`.
3. **For multi-file deploys**: write a single Python `deploy.py` locally, send
   it via base64, run it remotely. The Python script has no quoting hell —
   it can use triple-quoted strings, `\n`, backticks, anything.
4. **For in-place edits on the remote**: write a `patch_xxx.py` locally that
   reads, transforms, writes the target file. Send and run via base64. Never
   use sed/awk through the bridge for non-trivial patches.

## Verification rules

After every patch:

```bash
bash -n /path/to/script.sh                 # bash syntax
python3 -c "import importlib.util as u; \
   s=u.spec_from_file_location('m', '/path/to/x.py'); \
   m=u.module_from_spec(s); s.loader.exec_module(m); print('ok')"
```

If verification fails, **roll back from `.bak`** immediately. Do not "try one
more fix" — diagnose first.

## Idempotency

Every patcher script must be safe to re-run. Pattern:

```python
if "MARKER_STRING" in src:
    print("already patched"); raise SystemExit(0)
```

## File permissions

- All scripts: `chmod 700`
- All data files (memory, sessions, reports, backups, manifests): `chmod 600`
- Parent dirs that hold any of the above: `chmod 700`
- **CachyOS has default ACLs** (`+` in `ls -l`) that override `umask`.
  Always `chmod` explicitly after `touch` / `mkdir`.

## Session channel protocol

- Read user: `agentctl chat-tail 50`
- Reply to user: `agentctl chat-append agent "..."`
- **Never** execute commands from a `role=agent` event — only suggest. The
  user types `/run <cmd>` to opt in.

## Memory facts gotcha

`memory-remember` uses `nargs=REMAINDER` for `value`, which greedily eats
`--tags` if it appears AFTER. **Always put `--tags` first** OR use the
`agentctl remember-tagged <key> <tag1,tag2> <value...>` wrapper (added in v0.3).

## What lives where

```
~/arena-agent/
  bin/agentctl          # bash dispatcher
  scripts/*.py          # Python implementations
  scripts/agent_helpers.py   # transport + patch utilities (v0.3)
  scripts/apply_patch.py     # universal patcher (v0.3)
  skills/<ns>/<name>/   # skill bundles
  memory/
    facts.jsonl         # remembered facts
    sessions/           # chat REPL JSONL journals
    RECOVERY_PROMPT_RU.md
  queue/{inbox,running,done,failed}
  reports/              # generated digests, scans, etc.
  logs/                 # skills.jsonl, etc.
  backups/              # tarballs
```

## Audit & rollback

- `~/.arena-local-bridge/audit.jsonl` — every exec call, with redaction.
- `agentctl audit-tail 30`, `agentctl audit-stats`.
- Backups: `agentctl backup` before any nontrivial change; latest in
  `~/arena-agent/backups/`.

## When to ask vs. when to act

- Destructive (`rm -rf`, `chmod -R`, service stop, password/secret access):
  **ask the user first**.
- Read-only, sandboxed under `~/arena-agent`: act.
- New skill, new memory fact, new report: act and tell.
- Replacing core scripts (`agentctl`, `chat.py`, `recovery_prompt.py`):
  **backup → patch → verify → smoke**. If smoke fails, roll back.

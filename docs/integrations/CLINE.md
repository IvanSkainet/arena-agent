# Cline + Arena Unified Bridge

Cline is a strong fit for Arena because Arena already exposes many of the same
primitives Cline-style coding agents want: shell, file edits, search, diffs,
and memory.

## Recommended model

Use Cline for:
- planning the code change
- reading project context in-editor
- orchestrating edits

Use Arena for:
- MCP filesystem tools
- shell execution on the target machine
- browser research and diagnostics
- project memory via Memory Profiles

## Suggested memory policy

Tell Cline explicitly:

> Use Arena memory profile `projects/<repo>` for project facts, and do not write project state into `default` unless I ask.

## Good Arena tools for Cline

- `fs.edit`
- `fs.view`
- `fs.search`
- `fs.tree`
- `fs.diff`
- `git.status`
- `git.diff`
- `git.log`
- `git.commit`
- `memory.recall`
- `memory.digest`

## MCP concept

If your Cline setup supports remote MCP, point it at Arena's MCP transport and
pass the Bearer token in headers.

Pseudo-config concept:

```json
{
  "server": "arena",
  "url": "https://YOUR-BRIDGE/mcp",
  "headers": {
    "Authorization": "Bearer YOUR_TOKEN"
  }
}
```

## Validation checklist

- list tools
- call `fs.view`
- call `fs.edit`
- call `git.status`
- call `memory.recall` with `profile=projects/<repo>`

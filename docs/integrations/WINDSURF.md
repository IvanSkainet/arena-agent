# Windsurf + Arena Unified Bridge

Windsurf can use Arena as the external machine-control and memory layer while
keeping the IDE-native coding UX.

## Best role split

- Windsurf: code assistant, editor context, code review flow
- Arena: shell, browser, tasks, filesystem operations, memory profiles, desktop

## Practical recommendation

At the start of the chat/session, tell Windsurf:

> Use Arena Unified Bridge as the execution backend. Keep project facts in memory profile `projects/<repo>` and use `fs.edit` / `git.*` / `memory.*` tools where possible.

## Good first actions

1. `/v1/status`
2. `/v1/memory` write to `projects/<repo>`
3. `memory.recall` for that same profile
4. `git.status`
5. `fs.search` for TODO/FIXME or key symbols

## Remote MCP note

If your Windsurf version supports remote MCP or HTTP tool servers, use Arena's
`/mcp` or `/sse` transport with Bearer auth.

Pseudo-config concept:

```json
{
  "name": "arena",
  "url": "https://YOUR-BRIDGE/mcp",
  "headers": {
    "Authorization": "Bearer YOUR_TOKEN"
  }
}
```

## Why this pairing works

Arena gives Windsurf something many editor agents lack: a persistent,
profile-aware machine memory and a much broader local automation surface.

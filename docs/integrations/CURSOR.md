# Cursor + Arena Unified Bridge

Arena works well with Cursor when you treat Arena as the remote automation and
machine-control layer, while Cursor remains the coding UI.

## Recommended usage model

- Cursor handles coding/chat UX
- Arena handles:
  - filesystem actions beyond the editor
  - shell execution
  - browser fetch/read
  - task queue
  - desktop actions if needed
  - scoped memory via Memory Profiles

## Two integration styles

### Style A — prompt + custom tool wrapper
If you are using Cursor primarily as a chat/coding environment, give the agent a
system instruction that Arena is its external tool layer.

### Style B — MCP-style integration
If your current Cursor build supports remote MCP over HTTP/SSE, configure Arena
as a remote MCP server.

Pseudo-config concept:

```json
{
  "arena": {
    "transport": "http-or-sse",
    "url": "https://YOUR-BRIDGE/mcp",
    "headers": {
      "Authorization": "Bearer YOUR_TOKEN"
    }
  }
}
```

> Exact UI/JSON details may vary across Cursor versions. The stable part is the
> Arena side: `/mcp`, `/sse`, `/ws`, and Bearer auth.

## Best practices in Cursor

- Use Memory Profiles aggressively:
  - `projects/arena`
  - `projects/<repo>`
  - `code`
- Prefer MCP/REST `fs.edit` over full rewrites.
- Use `/v1/tasks` for long-running commands rather than blocking the editor chat.

## Smoke test

1. read status
2. write a fact to `projects/<repo>`
3. list or recall facts from that profile
4. run one safe command
5. perform one surgical file edit

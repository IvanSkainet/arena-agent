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

## General operating advice

1. Treat Arena as the **tool substrate**, not necessarily the model provider.
2. Start every new integration with a smoke test:
   - `/v1/status`
   - `/v1/memory?profile=default`
   - `/v1/browser/head?url=https://example.com`
3. Use **Memory Profiles** immediately for project work.
4. Prefer `PATCH /v1/fs/edit` / MCP `fs.edit` for code changes over full-file rewrites.
5. If an agent is too constrained by its own host product, move more logic into
   Arena-side tools, missions, and memory rather than fighting the frontend.

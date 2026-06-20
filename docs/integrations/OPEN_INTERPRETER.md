# Open Interpreter + Arena Unified Bridge

Open Interpreter is useful as a local chat/code shell, while Arena can provide a
more stable, structured execution API and persistent machine memory.

## Suggested split

- Open Interpreter: local reasoning/chat shell
- Arena: durable tools, filesystem editing, tasks, browser helpers, memory

## Minimal workflow

1. Put Arena bridge URL/token into your Open Interpreter session context.
2. Tell it to use Arena endpoints for machine actions.
3. Standardize on a Memory Profile such as `projects/<repo>`.

## Example instruction

> Use Arena Unified Bridge for command execution, file edits, and memory. Store project facts in `projects/<repo>`. Use `/v1/tasks` for long-running work.

## Good first smoke sequence

- `/v1/status`
- `/v1/memory` create fact in `projects/demo`
- `/v1/recall` from `projects/demo`
- `/v1/fs/edit` against a test file
- `/v1/browser/head?url=https://example.com`

## Why use Arena here?

Open Interpreter is great as a local shell interface, but Arena adds:
- profile-aware memory
- MCP tool surface
- browser helpers
- task queue
- richer observability and audit

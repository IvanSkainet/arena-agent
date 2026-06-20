# Claude / ChatGPT / generic custom-tools chats

This recipe is for chat products where you can provide a long system prompt and
optionally wire custom HTTP tools.

## Fastest route

Use [`../AI_PROMPT_TEMPLATE.md`](../AI_PROMPT_TEMPLATE.md) as the base prompt.

## What to tell the model

Add one project-scoping instruction near the top of the chat:

> Use Arena Memory Profiles. Put project facts in `projects/<name>`, personal facts in `personal`, and ad-hoc browser findings in `browser`.

## Recommended tool order

When the agent starts a new task, encourage this order:

1. `/v1/status`
2. `/v1/doctor` if the task depends on environment state
3. `/v1/memory` / `/v1/recall` in the relevant profile
4. `/v1/fs/edit` or MCP `fs.edit` for code work
5. `/v1/tasks` for long-running jobs

## Useful starter prompt

> You are using Arena Unified Bridge as the execution layer for my machine. Before acting, choose an appropriate Memory Profile (`default`, `personal`, `projects/<name>`, `code`, `browser`). Keep state in that profile consistently.

## Suggested verification task

Ask the model to do this sequence:

1. read `/v1/status`
2. create a memory fact in profile `projects/demo`
3. recall it back from the same profile
4. export all memory from that profile via MCP `memory.export`

If all four work, the chat is integrated correctly.

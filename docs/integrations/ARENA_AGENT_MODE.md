# Arena Agent Mode + Arena Unified Bridge

Use Arena Agent Mode as the **reasoning layer** and Arena Unified Bridge as the
**tools/hands layer**.

## Best use case

This recipe is ideal when you want:
- a strong hosted model experience
- Arena to execute commands, edit files, browse, and automate the desktop
- a simple copy/paste setup instead of a custom IDE integration

## Setup

1. Start the bridge.
2. Copy your bridge URL and token.
3. Open Arena Agent Mode.
4. Paste the system prompt from [`../AI_PROMPT_TEMPLATE.md`](../AI_PROMPT_TEMPLATE.md).
5. Replace:
   - `[YOUR_BRIDGE_URL_HERE]`
   - `[YOUR_BRIDGE_TOKEN_HERE]`

## Recommended opening instruction

After the prompt, start with something like:

> Use my Arena Unified Bridge as your tool backend. First call `/v1/status`, then save a fact into memory profile `projects/demo` saying this chat is attached to the demo project.

## Good first smoke tasks

- `GET /v1/status`
- `GET /v1/doctor`
- `POST /v1/memory` with `profile=projects/<name>`
- `GET /v1/browser/head?url=https://example.com`
- `PATCH /v1/fs/edit` on a test file

## Memory Profile recommendation

For project chats, tell the agent to use a scoped profile from the beginning:

- `projects/arena`
- `projects/<repo-name>`
- `browser`
- `personal`

Example instruction:

> For everything related to this repository, use memory profile `projects/arena` unless I explicitly say otherwise.

## Notes

Arena Agent Mode is a good reasoning frontend, but Arena remains the trusted
self-hosted execution layer.

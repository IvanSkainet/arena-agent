# Local / external model backends with Arena as the tools layer

Arena does not need to be the model provider to be useful. In many setups, the
best architecture is:

> model = brain, Arena = hands

## Good provider candidates

### Ollama
Best for:
- local sovereignty
- offline/near-offline workflows
- experimenting with smaller open models

Suggested use:
- run the model in Ollama
- feed it Arena's system prompt
- let Arena handle tools, files, browser, tasks, memory profiles

### OpenRouter
Best for:
- quick access to many hosted models
- switching providers rapidly

Suggested use:
- keep provider credentials outside Arena when possible
- still use Arena for execution and memory state

### Groq / Together / other OpenAI-compatible APIs
Best for:
- cheap hosted inference
- experiments with different reasoning speeds/costs

Suggested use:
- abstract the model provider at the chat/client layer
- keep Arena as the stable execution substrate

## Recommended memory policy for all providers

No matter which model you use, give it this rule:

> Use Memory Profiles. Store project facts in `projects/<repo>`, personal facts in `personal`, browser discoveries in `browser`, and keep unrelated state out of `default` when possible.

## Why this architecture is durable

Providers will change often.
Arena's value is more durable in:
- local execution
- memory continuity
- filesystem/browser/desktop automation
- observability and safety

That is why it is better to make model choice pluggable and keep Arena as the
stable operational core.

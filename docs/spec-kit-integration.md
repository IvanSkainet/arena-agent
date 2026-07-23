# Spec-Kit Integration (v4.60.19)

**Status:** Optional, opt-in. Nothing about this release is required
to run the bridge. The Spec-Kit integration is **added capability**,
not a dependency.

This document describes how `github/spec-kit` is integrated into the
Arena Unified Bridge as of v4.60.19. If you don't care about
spec-driven development, you can ignore everything in this file —
the bridge works fine without `specify` on PATH.

---

## What is Spec-Kit?

[`github/spec-kit`](https://github.com/github/spec-kit) is an external
tool that implements **Spec-Driven Development (SDD)**: a workflow
where the agent writes a `constitution.md` + `spec.md` + `plan.md` +
`tasks.md` first, gets the user's approval on the spec, and only then
writes code. The tasks are numbered (`T0`..`Tn`) and have explicit
RED/GREEN acceptance criteria.

The arena-bridge does **not** replace the user's spec-driven process.
It provides three **concrete integration points** that make the
process *executable* against the bridge's tools.

---

## What does the bridge add?

Three artefacts ship in v4.60.19:

1. **`scripts/spec_kit_to_scenarios.py`** — an adapter that reads a
   spec-kit `tasks.md` and emits a JSON document suitable for the
   bridge's existing `scenario.save` MCP tool. After running this,
   the spec-kit tasks become a real scenario that the bridge can
   execute (or just inspect, validate, and ship as an example).

2. **`arena/mcp/tool_speckit.py`** — a thin MCP-tool wrapper around
   the `specify` CLI. Scenarios and agents can call
   `speccy.run(args=["check"])`, `speccy.version`, etc. The wrapper
   is non-interactive (no TTY), handles missing-CLI gracefully, and
   never blocks on a prompt.

3. **Optional install step** in `install.bat` and `install.sh` —
   mirrors the existing Browseract / SuperPowers style. Default
   is **No**; the user must opt in.

The integration does **not** add a hard runtime dependency. If
`specify` is missing from PATH, the bridge runs fine and any scenario
calling `speccy.*` gets a clean `isError` response.

---

## How the integration works

### The adapter: `tasks.md` -> scenario.json

Spec-kit's `tasks.md` has a standard format (per the spec-kit
templates). Our adapter parses it line-by-line, treating each task
as a paragraph that may span multiple lines. The recognized shapes:

```markdown
# T<id> [P?] [Story?] `tool.path`: description. Args: {json}. Save as `name`.
```

Examples:

```markdown
- T0 [US1] In `mobile.record_start`: Begin mic recording. Args: `{"serial": "default", "audio": true, "time_limit": 5000}`. Save as `recording_id`.
- T1 [P] [US1] In `mobile.devices`: List phones. Args: `{}`.
- T2 [US1] In `mobile.record_stop`: Stop recording. Args: `{"serial": "default", "rec_id": "{{ steps.T0.result.id }}"}`.
```

The adapter produces a JSON document of this shape:

```json
{
  "name": "<scenario-name>",
  "description": "<from CLI arg>",
  "version": "1",
  "steps": [
    {
      "id": "T0",
      "tool": "mobile.record_start",
      "arguments": { "serial": "default", "audio": true, "time_limit": 5000 },
      "description": "Begin mic recording. ... [result -> recording_id]",
      "story": "US1"
    }
  ],
  "final": { "text": "{{ steps.T5.result.text }}" }
}
```

The shape matches the bridge's `arena/scenarios/runtime.py` schema
(step id, tool name, arguments, optional `parallel` flag, optional
`story` tag, `final` value). The adapter uses **balanced-brace
JSON extraction** with a `{{ ... }}` placeholder escape, so the
runtime can resolve inter-step references (`{{ steps.T0.result.id }}`)
without the adapter needing to know about them.

### The MCP tool: `speccy.*`

Three surface tools, dispatched by `handle_speccy` in
`arena/mcp/tool_speckit.py`:

| Tool                | Forwards to                | Returns                                      |
|---------------------|----------------------------|----------------------------------------------|
| `speccy.run`        | any `specify <args>`       | `{ok, stdout, stderr, exit_code, elapsed_sec, cli}` |
| `speccy.check`      | `specify check`            | same                                         |
| `speccy.version`    | `specify --version`        | same                                         |

Failure modes:

- **`specify` not on PATH** -> `isError` envelope with a clear
  install hint. No crash, no hang.
- **CLI exits non-zero** -> `ok: True, exit_code: N, stderr: "..."`.
  The scenario runtime decides whether to continue.
- **Timeout** (default 60s) -> `isError` with elapsed time.

The wrapper is intentionally **non-interactive**: it sets
`stdin=subprocess.DEVNULL` so the CLI's TUI prompts fail loudly
instead of hanging the bridge. Interactive `specify` flows are not
supported through this surface; they belong in a human-facing tool,
not a bridge tool.

### The install step

`install.bat` and `install.sh` each get a new section after the
Camoufox block. The default is **No** (matching the existing
Browseract / SuperPowers style). The CLI is installed globally via
`uv tool install specify-cli` so the bridge can find it on PATH.

---

## How to use it

End-to-end workflow:

1. In any project, run `specify init --here --ignore-agent-tools --integration generic --integration-options="--commands-dir .specify/commands-arena-bridge" --script sh --force`. This creates the `.specify/` directory in the project with the standard template.
2. Use the spec-kit slash-commands (or the manual equivalent) to write `constitution.md`, then `specs/###-feature/spec.md`, then `plan.md`, then `tasks.md`. The agent in your IDE will fill these in based on your high-level description.
3. Run the adapter: `python scripts/spec_kit_to_scenarios.py --tasks specs/###-feature/tasks.md --out scenario.json --name my_feature`. This produces a JSON scenario.
4. Hand the JSON to the bridge via `scenario.save` (or load it through your agent). The bridge can now execute the spec-kit tasks as a real scenario.

For day-to-day use, the bridge doesn't change. The spec-kit
integration is a tool you can pick up when you want to write a
complex feature with explicit task decomposition; for simpler work
you can keep writing scenarios directly in JSON.

---

## Testing

Two new test files:

- `tests/test_spec_kit_adapter.py` — 9 unit tests covering minimal
  tasks, parallel/story flags, JSON-args with placeholders, three
  `Save as` phrasings, malformed-args handling, and an end-to-end
  voice-transcription-shaped fixture.
- `tests/test_speckit_tool.py` — 8 unit tests covering dispatcher
  errors, missing-CLI handling, version probe, unknown-subcommand
  exit code, and live `specify check` invocation. Live tests skip
  cleanly if the CLI is not on PATH.

Run with:

```
python -m pytest tests/test_spec_kit_adapter.py tests/test_speckit_tool.py -v
```

---

## Out of scope

- **Custom integration as a new spec-kit "agent"**: We deliberately
  did **not** add a `src/specify_cli/integrations/arena_bridge/`
  subclass in the spec-kit repo. That would be a fork of spec-kit
  upstream. Instead we consume spec-kit as a process tool and
  provide an adapter at the boundary.
- **Live transcription services**: The original scenario that
  motivated this work (`voice on phone -> PC -> transcribe -> chat`)
  still requires picking a real online STT service. The
  `browser.interact` capability for that is a separate gap that
  remains open (it was identified in v4.60.18 but not closed).
- **Multi-agent coordination**: spec-kit is designed for a single
  human + single agent. The bridge's scenario runtime can run
  multiple agents; the spec-kit integration does not add or assume
  anything about that.

---

## Why this is "general" and not "task-specific"

The two pieces of code we added are both **tool-shaped** rather
than **task-shaped**:

- `spec_kit_to_scenarios.py` parses the spec-kit `tasks.md` format.
  The format is general (T0..Tn, Args, Save as, parallel/story
  flags) and reusable for *any* spec-kit project — not just
  "voice transcription".
- `tool_speckit.py` is a thin CLI wrapper. It can be used for any
  spec-kit operation (`specify check`, `specify self upgrade`,
  `specify extension add <name>`, etc.), not just one workflow.

This matches the bridge's general principle (Constitution principle
II in `constitution.md`): every feature is a general capability, never
a hardcoded fix for one task. The voice-transcription scenario was
the **stress test** that motivated the integration, but the
integration is broader than that one scenario.

---

## Files added in v4.60.19

- `scripts/spec_kit_to_scenarios.py` (new)
- `arena/mcp/tool_speckit.py` (new)
- `tests/test_spec_kit_adapter.py` (new)
- `tests/test_speckit_tool.py` (new)
- `install.bat` (modified — adds optional `SpecKit` install step)
- `install.sh` (modified — adds optional `SpecKit` install step)
- `CHANGELOG.md`, `CHANGELOG.ru.md` (modified — release notes)
- `arena/constants.py`, `pyproject.toml`, `tests/_version_matrix.py`
  (modified — version bump to 4.60.19)

The bridge's `git diff` for v4.60.19 lists these. No `cloudflared` or
other binary assets are added; Spec-Kit is installed by `uv tool`,
not bundled in the release zip.

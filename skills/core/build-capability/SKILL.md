# core/build-capability

When you need an ability the bridge does not have, **build it from the general
tools instead of asking for a bespoke one**. This skill is the map of how.

The bridge deliberately ships general primitives — processes, filesystem, HTTP,
input, screen, code execution — and the machinery to compose them into named
capabilities at runtime. A tool hard-wired to one application on one operating
system is the wrong shape: it rots when that application changes, it is dead
weight on every other platform, and it teaches nothing reusable. A composition
you author out of primitives runs wherever the primitives run.

## Decide first: does this need a new tool at all?

Work down this list and stop at the first that fits.

1. **An existing tool already does it.** 237 tools ship in the catalogue. Search
   before building: `tool.search` or `tools/list`, and read the namespace list —
   `fs`, `exec`, `net`, `proc`, `desktop`, `browser`, `ocr`, `image`, `git`,
   `code_run`, `document`, `memory`.
2. **A short composition does it.** Two or three existing calls chained with
   `custom.create` (see below). This is the common case and costs one call.
3. **It needs real logic** — parsing, protocol handling, state, retries. Build a
   project in Code Workbench and publish it with `tool_foundry.publish`.
4. **It cannot be built yet** — the primitive itself is missing. Record it with
   `capability_gap.record` so the gap is evidence rather than a memory.

## Composing a capability: `custom.create`

Authors a NEW named tool at runtime. No arbitrary code: each hop dispatches
through the normal tool chokepoint, so the risk policy and the agent HALT apply
at every level. A composite inherits the MAX risk of everything it touches.

Single call — a named alias with a narrower interface:

```json
{ "name": "read_config",
  "description": "Read the bridge config file",
  "input_schema": {"properties": {"path": {"type": "string"}}, "required": ["path"]},
  "call": {"tool": "fs.read", "args": {"path": "{path}"}} }
```

Composition — data flows between steps via `{input}` and `{steps.<id>.<field>}`:

```json
{ "name": "fetch_and_store",
  "input_schema": {"properties": {"url": {"type": "string"}}, "required": ["url"]},
  "steps": [
    {"id": "get",  "tool": "net.http", "args": {"url": "{url}"}},
    {"id": "save", "tool": "fs.write", "args": {"path": "out.json",
                                                "content": "{steps.get.body}"}}
  ] }
```

A step may target another authored tool (`custom.<name>`), so capabilities stack
into a library. References must be acyclic and built bottom-up.

Manage them with `custom.list` and `custom.remove`.

## Building a capability with real logic: Tool Foundry

When the work needs parsing, a protocol, or state, write it as a Code Workbench
project with a `.arena-tool.json` manifest and tests, then:

- `tool_foundry.validate` — manifest and tests, without publishing;
- `tool_foundry.publish` — publishes it as a callable `custom.<name>`.

Tests are part of the manifest on purpose: a capability nobody proved is a
capability nobody should call.

## Keep it portable

The point of building your own tool is that it outlives the thing it automates.

- **Prefer the general primitive** over shelling out to a platform-specific
  binary. `fs.*` over `cp`/`copy`, `net.http` over `curl`/`Invoke-WebRequest`,
  `proc.*` over `ps`/`tasklist`.
- **When a platform binary is unavoidable**, branch on the platform inside the
  capability rather than authoring three tools; keep the interface identical
  everywhere so callers never learn which OS they are on.
- **Never bake in absolute paths, ports, window titles or pixel coordinates.**
  Take them as inputs with sane defaults, or discover them at runtime.
- **Name for the intent, not the target.** `screen_region_text` survives; a name
  tied to one application's window does not.
- **Automate the interface, not the product.** Anything exposing an HTTP API, a
  CLI, or a file format can be driven by primitives that already exist. Reach
  for screen and input control only when there is genuinely no other surface.

The counter-example lives in this repo: the `mumu.*` namespace is eight tools
welded to one Android emulator on one platform. It works, and it taught us the
lesson — everything since is built as composition instead.

## Close the loop

- Record what was missing while the evidence is fresh: `capability_gap.record`.
- `capability_gap.promote` turns a gap into an autopilot task when it deserves
  real work; `capability_gap.report` shows what is still open.
- A capability worth keeping belongs in a skill so the next session finds it
  without re-deriving it: `skill.list`, `skill.run`.

## The honest test

Before publishing, answer two questions:

1. **Would this still work on another operating system?** If no, is the platform
   branch inside the tool, or did you just build a dead end?
2. **Did you run it, or only write it?** Publishing an untested capability moves
   the failure to whoever calls it next — which is usually you, later, with less
   context.

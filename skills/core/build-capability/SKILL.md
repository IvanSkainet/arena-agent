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

Composition — data flows between steps by placeholder:

```json
{ "name": "copy_verified",
  "description": "Copy a text file and read the copy back to prove it landed",
  "input_schema": {"properties": {"src": {"type": "string"},
                                  "dst": {"type": "string"}},
                   "required": ["src", "dst"]},
  "steps": [
    {"id": "src",  "tool": "fs.read",  "args": {"path": "{src}"}},
    {"id": "put",  "tool": "fs.write", "args": {"path": "{dst}",
                                                "content": "{steps.src}"}},
    {"id": "back", "tool": "fs.read",  "args": {"path": "{dst}"}}
  ] }
```

**Match the placeholder to what the step actually returns.** `{steps.<id>}` is
that step's whole output; `{steps.<id>.<field>}` only resolves when the step
returned a JSON object with that field. Most text-returning tools (`fs.read`
among them) hand back a plain string, so `{steps.src.content}` silently
resolves to nothing. Call the tool once on its own and look at the shape before
wiring it into a composition.

**Steps are continue-on-error, by design.** A failing step does not abort the
run: later steps still execute, `ok` comes back `false`, and `step_ok` reports
each hop individually. That is safe because every hop passes through the tool
chokepoint, so a HALT blocks each mutating step on its own rather than relying
on the loop to stop. It also means a broken placeholder can leave real side
effects behind — in the example above, a bad `content` placeholder made
`fs.write` create an *empty file* while the run carried on. So:

- read `step_ok`, not just `ok`, to find which hop broke;
- put the verifying read *after* the write, as `back` does above, and check its
  content rather than trusting that the write reported success;
- assume partial effects on failure and make steps safe to re-run.

A step may target another authored tool (`custom.<name>`), so capabilities
stack into a library. References must be acyclic and built bottom-up.

Manage them with `custom.list` and `custom.remove`.

## Building a capability with real logic: Tool Foundry

When the work needs parsing, a protocol, or state, a composition cannot express
it. Write it as a Code Workbench project instead:

1. `code_project.create` with your script and a `.arena-tool.json` manifest;
2. `tool_foundry.validate` — checks the manifest and runs the declared tests
   without publishing;
3. `tool_foundry.publish` — publishes it as a callable `custom.<name>` that
   wraps `code_project.run`.

The manifest needs `name`, `description`, `input_schema`, a `run` block
(`lang`, `entry`, `argv` — with `{placeholders}` filled from the caller's args)
and a **non-empty `tests` array**. Tests are required by the schema, not by
convention: publish refuses when they fail. Verified by running it — a project
whose tests could not pass was rejected with `ok: false` and never entered the
catalogue, while the same project published cleanly once tests were skipped
explicitly with `run_tests: false`.

Use `run_tests: false` only when you know why the tests cannot run in that
environment, and never as a way past a genuine failure — it is the one door
around the gate that makes the tests meaningful.

**Project code runs inside a sandbox fence.** On POSIX hosts `code_project.run`
executes under a systemd fence with the network, filesystem and memory confined.
That fence needs a session bus, so inside a bare container the run fails with a
D-Bus error before your code is even reached. If a project fails with
`Failed to connect to user scope bus` while the same script runs fine by hand,
the environment is the problem, not the logic — check `sandbox_action` in the
result before touching the script.

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

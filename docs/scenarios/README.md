# Scenario examples

Example scenarios for `~/.arena/scenarios/` — install by copying
the JSON files there, or use `scenario.save` from a chat via the
extension.

## `hello-world.json`

Bridge health check + template render. Verifies:

* `scenario.save` accepts JSON source
* step results are passed through `{{ steps.<id>.result.<field> }}`
* final `return` template renders

Run: `scenario.run(name="hello-world")`.

## Adding your own

Put a JSON file at `~/.arena/scenarios/<name>.json` with the shape:

```json
{
  "name": "<name>",
  "title": "...",
  "description": "...",
  "steps": [
    {"id": "s1", "tool": "sys.status", "arguments": {}},
    {"id": "s2", "return": "final answer with {{ steps.s1.result.field }}"}
  ]
}
```

The scenario runtime rejects unnamed steps that lack both `tool`
and `return`. Duplicate step ids are also rejected. Every step's
result is available to subsequent steps as `{{ steps.<id>.result.<path> }}`
where `<path>` walks nested dicts / lists.

## Risk classification

`scenario.run`'s risk is derived from the max risk of its
contained tools:

* all safe → `safe` (auto-runs on trusted sites)
* any `medium` (e.g. `fs.create`) → `medium` (approval required)
* any `dangerous` (`fs.write`, `exec`, `mission.run`, …) → `dangerous`

`scenario.list`, `scenario.get`, `scenario.preview`,
`scenario.history` are always `safe`. `scenario.save`,
`scenario.delete` are `medium`.

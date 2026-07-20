# Scenario examples

Example scenarios for `~/.arena/scenarios/` — install by copying
the JSON files there, or use `scenario.save` from a chat via the
extension.

## `hello-world.json`

Bridge health check + template render. Smoke test for the
scenario runtime.

## `wait-for-download.json`

Demonstrates v4.54.1 `retry` + `wait_for.file`: kick off a
download command, then wait up to 30s for the resulting file to
appear before returning. Retries the whole cycle 3 times with
1.5s→3s→6s backoff.

## Adding your own

Put a JSON file at `~/.arena/scenarios/<name>.json` with the shape:

```json
{
  "name": "<name>",
  "title": "...",
  "description": "...",
  "steps": [
    {
      "id": "s1",
      "tool": "sys.status",
      "arguments": {}
    },
    {
      "id": "s2",
      "return": "final answer with {{ steps.s1.result.field }}"
    }
  ]
}
```

## Step-level options

Each step (except pure `return:` steps) can carry these
optional blocks:

* **`continue_on_error: true`** — don't stop the scenario if
  this step fails; downstream steps still run.
* **`retry: {attempts, delay_seconds, backoff}`** — retry the
  step on failure with exponential backoff. Defaults:
  1 attempt (no retry), 0.5s initial delay, 2.0x backoff.
  Attempts capped at 10, delay at 60s, backoff at 5.0.
* **`wait_for: {file, http, timeout_seconds, poll_seconds}`** —
  after the tool call succeeds, block until a post-condition
  is met before considering the step "ok". Failure of the
  wait_for demotes the whole attempt so `retry` gets a chance.

### `wait_for.file`

```json
"wait_for": {
  "file": "~/Downloads/note.m4a",
  "timeout_seconds": 30,
  "poll_seconds": 1
}
```

Waits for the file to exist. Result carries `{ok, kind: "file",
path, size_bytes, waited_seconds}`.

### `wait_for.http`

```json
"wait_for": {
  "http": {
    "url": "https://api.example.com/status/xyz",
    "expect_status": 200,
    "expect_json_field": "done",
    "expect_json_value": true,
    "method": "GET"
  },
  "timeout_seconds": 60,
  "poll_seconds": 2
}
```

Polls the URL until `status == expect_status` AND (if
`expect_json_field` is set) the JSON body has that field equal
to `expect_json_value`. Any step with `wait_for.http` promotes
the scenario risk to at least `medium` (outbound HTTP from the
bridge host requires user approval).

## Template expressions

Minimal on purpose. Three namespaces:

* `{{ steps.<id>.result[.field.subfield] }}` — walk the result
  dict of an earlier step. Missing paths render as the empty
  string.
* `{{ steps.<id>.returned }}` — value of an earlier `return:`
  step.
* `{{ env.VAR }}` — process env.
* `{{ now }}` — ISO-8601 UTC timestamp.

## Risk classification

`scenario.run`'s risk is derived from the max risk of its
contained tools:

* all safe → `safe` (auto-runs on trusted sites)
* any `medium` (e.g. `fs.create`) → `medium` (approval required)
* any `dangerous` (`fs.write`, `exec`, `mission.run`, …) → `dangerous`
* any step with `wait_for.http` → `medium` (SSRF-adjacent)

`scenario.list`, `scenario.get`, `scenario.preview`,
`scenario.history` are always `safe`. `scenario.save`,
`scenario.delete` are `medium`.

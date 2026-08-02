# Android emulators

## The rule

**Booting is provider-specific. Everything after boot is ADB.**

An emulator manager is only needed for three things: knowing which instances
exist, starting one, and stopping one. The moment an instance is up it is an
ordinary ADB target, indistinguishable from a physical phone — so shell,
screenshot, input, install, logcat and UI dumps all go through the existing
cross-platform `mobile.*` tools. The bridge does not, and will not, grow a
second device API per emulator vendor.

## Tools

| Tool | Purpose |
| --- | --- |
| `emulator.providers` | Which managers exist, and which of them this host can actually drive. **Start here.** |
| `emulator.list` | Instances known to one provider. Raw provider output. |
| `emulator.start` | Boot an instance. |
| `emulator.stop` | Shut an instance down via the provider's own verb. |
| `emulator.attach` | ADB-visible devices, optionally waiting after a boot. Hand-off point to `mobile.*`. |

Typical sequence:

```
emulator.providers                      -> pick an available provider id
emulator.list      {provider: "avd"}    -> pick an instance id
emulator.start     {provider: "avd", instance: "Pixel_7"}
emulator.attach    {wait_s: 60}         -> get the ADB serial
mobile.screenshot  {serial: "emulator-5554"}
```

## Built-in providers

| id | Manager | Host OS | Instance id | Stop verb |
| --- | --- | --- | --- | --- |
| `avd` | Android Emulator (Android SDK) | Windows / Linux / macOS | AVD name | none — use ADB |
| `genymotion` | Genymotion Desktop | Windows / Linux / macOS | VM name | yes |
| `mumu` | MuMu Player | Windows | numeric vmindex | yes |
| `waydroid` | Waydroid | Linux | ignored (single session) | yes |

A provider is a row of data, not a module: where its CLI lives, and the argv
tails that list / start / stop. Nothing is invoked through a shell — every call
is an argv list, so there is no quoting surface to inject into.

`avd` is the reference provider: it ships with the Android SDK on all three
desktop OSes, so any host with Android tooling at all has at least one working
path. It has no shutdown verb, and `emulator.stop` says so explicitly rather
than guessing at a process kill — use `mobile.shell` with `reboot -p`, or
`adb -s <serial> emu kill`.

## Locating a CLI

Resolution order per provider:

1. the provider's pin environment variable (`ANDROID_EMULATOR`, `GMTOOL_PATH`,
   `ARENA_MUMU_CLI`, `WAYDROID_PATH`);
2. `PATH` lookup by binary name;
3. well-known absolute paths, with `$VAR` / `%VAR%` expanded at probe time.

A pin that points at a non-existent file is **reported**, not silently ignored:
`emulator.providers` returns `broken_pin` plus a hint. A typo in an env var
otherwise looks exactly like "the emulator is not installed", which is the kind
of false negative that costs an hour.

## Adding a provider without touching this repo

Set `ARENA_EMULATOR_PROVIDERS` to a JSON array. Each entry uses the same keys
as the built-in table; an entry sharing an `id` with a built-in **replaces** it,
so an operator can correct a wrong well-known path without a code change.

```json
[
  {
    "id": "myemu",
    "label": "In-house emulator farm",
    "os": ["linux"],
    "binary_env": "MYEMU_BIN",
    "binary_names": ["myemu"],
    "list_argv": ["instances", "--json"],
    "start_argv": ["boot", "{id}"],
    "stop_argv": ["halt", "{id}"],
    "docs": "https://internal/docs/myemu"
  }
]
```

`{id}` is the only placeholder, substituted with the `instance` argument.
Malformed JSON, or entries without an `id`, are ignored — the built-in table
survives, because bad host configuration must never take the bridge down.

## Why `emulator.list` returns raw text

Every vendor prints a different shape. Normalising output for managers we
cannot run on hardware we do not have would be a guess dressed up as a
contract. The raw `stdout` is honest; parse it in a composition or a
`tool_foundry` project where you can verify it against the real thing.

## History

Until v4.155.0 this was `mumu.*`: eight MCP tools around one vendor's CLI, on
one OS, with `C:\Users\Ivan\...` as a default argument, duplicating adb calls
that `mobile.*` already made portably. It was named as the counter-example in
the `core/build-capability` skill while still sitting in the codebase.
v4.155.0 removed it. MuMu survives as one row in the provider table.

## Green is not working

The test suite pins contracts: argv shapes, refusal paths, the absence of any
hardcoded operator home, the absence of `shell=True`. It does **not** prove an
emulator boots — no CI runner has one. Verify a provider by executing it on a
host that has the manager installed, and record what you find here.

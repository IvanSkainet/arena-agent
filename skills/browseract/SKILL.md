# browseract

Wrapper around the [`browser-act`][upstream] CLI for stealth-aware browser
automation. Works on **Windows, macOS, and Linux**.

[upstream]: https://www.browseract.com/

## Install (one-time)

BrowserAct is not bundled with Arena. Install it via [uv][uv] — a single
command that works identically on every OS:

[uv]: https://docs.astral.sh/uv/getting-started/installation/

```bash
uv tool install browser-act-cli --python 3.12
```

Then verify:

```bash
python skills/browseract/run.py doctor
```

You should see the CLI version and `handshake: ok`.

### Update

```bash
uv tool upgrade browser-act-cli
```

## Subcommands

The Python wrapper (`run.py`) works on every platform; the historical
`run.sh` remains for callers that expect a bash entrypoint on *nix.

Run via `python skills/browseract/run.py <sub>` (or the bash wrapper on
*nix / from `agentctl bact <sub>`):

- `doctor` — check install + handshake
- `extract <url>` — stealth-extract URL as markdown (saved under
  `$ARENA_AGENT_HOME/reports/bact-extract-*.md`)
- `shot <url>` — stealth screenshot (PNG saved under
  `$ARENA_AGENT_HOME/reports/bact-shot-*.png`)
- `open <url>` — start/use session, navigate
- `state` — show current page state
- `click <index>` — click element by index
- `type <text>` — type into focused element
- `input <index> <text>` — click then type
- `eval <js>` — execute JS, return result
- `close` — close current session
- `auth {set <KEY> | clear | status}` — manage browser-act API key
- `browsers` — list configured browsers
- `raw <args...>` — pass-through to `browser-act`

## When to use vs existing browser-* commands

- `agentctl http <url>` — raw curl, no JS, cheapest.
- `agentctl readability <url>` — headless Chromium + Readability.
- `agentctl bact extract <url>` — stealth Chromium + anti-bot + markdown.

## Boundaries

- Default = fully local. Bundled Camoufox / stealth Chromium, no upload
  of cookies or page content.
- Cloud features (residential IPs, hosted CAPTCHA) require an explicit
  `browser-act auth set <key>`. Not enabled by default.
- Reports saved to `$ARENA_AGENT_HOME/reports/bact-*` (default
  `~/arena-bridge/reports/`).

## Bridge integration

The Bridge exposes `browseract` status via
[`arena/admin/browseract.py`][browseract-py]. Query it with:

```
GET /v1/capabilities   → browser section includes browseract_installed / version / update_hint
```

[browseract-py]: ../../arena/admin/browseract.py

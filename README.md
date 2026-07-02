<div align="center">

# 🌉 Arena Unified Bridge

**Local automation bridge for AI agents — one process, one port, full control of your machine.**

Turn any AI chat or agent into a hands-on assistant that can run commands, read and edit files, browse the web, remember things, and drive your desktop — all through a single token-authenticated service you run yourself.

One process · One port · REST + MCP + browser extension · Windows / Linux / macOS

**🌐 English · [Русский](README.ru.md)**

[![CI](https://github.com/IvanSkainet/arena-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/IvanSkainet/arena-agent/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/release/IvanSkainet/arena-agent?color=blue&label=release)](https://github.com/IvanSkainet/arena-agent/releases)
[![Python](https://img.shields.io/badge/python-3.10%2B-green.svg)]()
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

</div>

---

## Contents

- [Why Arena Unified Bridge?](#why-arena-unified-bridge)
- [How it works](#how-it-works)
- [What it can do](#what-it-can-do)
- [Quick start](#quick-start)
- [Browser extension: Arena Chat Bridge](#browser-extension-arena-chat-bridge)
- [Optional components](#optional-components)
- [Security model](#security-model)
- [API overview](#api-overview)
- [Development](#development)
- [Documentation map](#documentation-map)
- [License](#license)

---

## Why Arena Unified Bridge?

Most "AI + your computer" setups mean juggling several servers: one for MCP, one
for a REST API, one for browser control, one for the web UI. Arena Unified Bridge
folds all of that into **a single local process** that you start once and point
your tools at.

- **Local-first.** Bind it to `127.0.0.1` and nothing leaves your machine. Expose
  it deliberately — via Tailscale Funnel or another HTTPS tunnel — only when you
  actually need remote access.
- **Protocol-agnostic.** REST, MCP, WebSocket/SSE events, and a browser extension
  all talk to the same runtime.
- **Safe by design.** A bearer credential, path restrictions, shell safety
  patterns, and explicit risk policies stand between an AI and your host.
- **Works with the chats you already use.** The companion browser extension lets
  plain ChatGPT / Claude / Gemini conversations trigger real local tools.

---

## How it works

```text
┌─────────────────────┐     ┌──────────────────────────┐     ┌──────────────┐
│  AI chat / agent    │     │  Arena Chat Bridge ext.  │     │ Arena Unified│
│  ChatGPT · Claude   │ ──▶ │       or MCP / REST      │ ──▶ │    Bridge    │ ──▶  your machine
│  Gemini · your CLI  │     │                          │     │ (local:8765) │
└─────────────────────┘     └──────────────────────────┘     └──────────────┘
        emits a                    detects / forwards              runs the
    structured tool block          the tool call safely         guarded action
```

An assistant emits a structured tool block, the extension (or an MCP/REST client)
forwards it to the local bridge, the bridge runs the guarded action, and the
result flows back — optionally straight into the chat composer.

---

## What it can do

| Area | Capability |
| --- | --- |
| **Shell** | Guarded command execution with safety patterns and secret-read blocking |
| **Files** | Read, search, and precise edit helpers with path restrictions |
| **Web** | Fetch / read / search page text on behalf of the agent |
| **Memory** | Persistent facts plus fuzzy recall |
| **Tasks** | Background task queue for long-running work |
| **Browser** | Chrome DevTools Protocol control for real browser automation |
| **Desktop** | Screenshots and input automation where the platform supports it |
| **Dashboard** | Built-in web UI at `/gui` |
| **Extension** | Connects ordinary AI chats to the local bridge with a lifecycle Command Center |

See [CHANGELOG.md](CHANGELOG.md) for the full release history.

---

## Quick start

### 1. Download a release

Grab the latest ZIP:

```text
https://github.com/IvanSkainet/arena-agent/releases/latest
```

Extract it somewhere convenient:

```text
C:\Users\You\arena-bridge        # Windows
~/arena-bridge                    # Linux/macOS
```

### 2. Run the installer

```cmd
:: Windows
install.bat
```

```bash
# Linux / macOS
chmod +x install.sh
./install.sh
```

The installer creates a local bearer credential in `token.txt`, prepares runtime
directories, and asks before installing any optional component.

### 3. Verify the bridge

```bash
curl http://127.0.0.1:8765/health      # health check
curl http://127.0.0.1:8765/v1/version  # version + platform
```

Open the dashboard at:

```text
http://127.0.0.1:8765/gui
```

### 4. Hand your AI the URL and credential

```text
Base URL: http://127.0.0.1:8765
Auth:     Authorization: Bearer <credential from token.txt>
```

For remote access, enable an HTTPS tunnel only if you understand the exposure
model. Tailscale Funnel is recommended: it gives you a real TLS hostname without
port forwarding.

---

## Browser extension: Arena Chat Bridge

The extension is an **Arena-native bridge for normal web chats**. It watches
assistant messages for structured tool blocks, previews/executes them through the
local bridge, and can insert the result back into the chat composer.

**Supported adapters:** ChatGPT · Claude · Gemini Web · Google AI Studio · Grok ·
Perplexity · OpenRouter · DeepSeek · Kimi · Qwen · generic fallback.

**Canonical payload:**

````text
```arena-tool
{
  "bridge": "arena",
  "version": 1,
  "calls": [
    {"id": "call_1", "tool": "sys.status", "arguments": {}}
  ]
}
```
````

MCP SuperAssistant-style JSONL is also accepted and normalized internally.

**Load it for development:**

1. open `chrome://extensions`;
2. enable **Developer mode**;
3. click **Load unpacked**;
4. select `chat_extension/`.

More detail: [chat_extension/README.md](chat_extension/README.md).

---

## Optional components

The bridge runs locally with just Python and `aiohttp`. Some features want extra
tools — and none of them are installed silently; the installer always asks first.

| Component | Purpose | Notes |
| --- | --- | --- |
| Tailscale | Recommended HTTPS exposure via Funnel | Optional, system-level install |
| cloudflared | Cloudflare Quick Tunnel fallback | Optional download, ~50 MB |
| BrowserAct / browser helpers | Rich browser automation | Optional |
| Camoufox | Stealth browser workflows | Optional |
| ydotool / xdotool | Linux desktop input automation | Optional / platform-specific |
| Tesseract | OCR for desktop/screenshot flows | Optional |

---

## Security model

Arena Unified Bridge can take powerful actions on the host, so the security model
is intentionally explicit:

- every non-local client authenticates with the bearer credential from `token.txt`;
- upload / download / edit paths are restricted;
- common dangerous shell patterns and secret reads are blocked;
- desktop automation has pause / resume / revoke controls;
- extension policies classify every tool by risk before auto-execution;
- public exposure must use HTTPS and a private credential;
- never paste credentials into an untrusted chat, log, or public issue.

> Found a security issue? Please report it privately instead of opening a public
> issue.

---

## API overview

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | unauthenticated health check |
| `GET` | `/v1/version` | version and platform info |
| `GET` | `/v1/status` | bridge status |
| `POST` | `/v1/exec` | guarded shell execution |
| `GET/POST` | `/v1/tasks` | background task queue |
| `GET/POST/DELETE` | `/v1/memory` | memory facts |
| `GET` | `/v1/recall` | fuzzy memory recall |
| `GET` | `/v1/browser/read` | fetch and extract web page text |
| `GET` | `/v1/desktop/screenshot` | desktop screenshot where supported |
| `GET` | `/v1/extension/policies` | extension policy metadata |
| `POST` | `/v1/extension/preview` | dry-run extension tool calls |
| `POST` | `/v1/extension/execute` | execute approved extension tool calls |

The full surface is modular; see the dashboard, route tests, and [`docs/`](docs/).

---

## Development

```bash
git clone https://github.com/IvanSkainet/arena-agent.git arena-bridge
cd arena-bridge
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"
pytest
```

Targeted checks for extension work:

```bash
pytest -q tests/test_chat_extension_assets.py tests/test_chat_extension_adapter_flow.py tests/test_chat_extension_sidepanel_flow.py tests/test_extension_bridge.py tests/test_project_modularity.py

for f in background content parser adapters insert_strategies insert_history adapter_sites popup settings sidepanel; do
  node --check "chat_extension/$f.js"
done
```

Contributor notes: [CONTRIBUTING.md](CONTRIBUTING.md) · Release checklist: [RELEASE.md](RELEASE.md).

---

## Documentation map

| Document | What's inside |
| --- | --- |
| [CHANGELOG.md](CHANGELOG.md) | Release history |
| [RELEASE.md](RELEASE.md) | Release packaging and publishing checklist |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, tests, workflow |
| [chat_extension/README.md](chat_extension/README.md) | Browser extension details |
| [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) | Integration notes |
| [docs/MODULE_MAP.md](docs/MODULE_MAP.md) | Codebase / module map |
| [docs/V3_MODULAR_ARCHITECTURE.md](docs/V3_MODULAR_ARCHITECTURE.md) | Modular architecture notes |

Some files in `docs/` are design notes or historical audits. The README and
CHANGELOG are the public entry points.

---

## License

MIT — see [LICENSE](LICENSE).

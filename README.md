<div align="center">

# 🌉 Arena Unified Bridge

**Local automation bridge for AI agents.**
One process · One port · REST + MCP + browser extension · Windows / Linux / macOS

**🌐 English · [Русский](README.ru.md)**

[![CI](https://github.com/IvanSkainet/arena-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/IvanSkainet/arena-agent/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/release/IvanSkainet/arena-agent?color=blue&label=release)](https://github.com/IvanSkainet/arena-agent/releases)
[![Python](https://img.shields.io/badge/python-3.10%2B-green.svg)]()
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

</div>

---

## What is it?

Arena Unified Bridge is a local HTTP/MCP server that lets AI agents work with your computer through a controlled, token-authenticated interface.

It can expose tools for:

- shell execution with safety guardrails;
- file read/search/edit helpers;
- browser fetch/read/search helpers;
- memory and recall;
- background task queues;
- Chrome DevTools Protocol browser control;
- desktop automation where supported;
- a web dashboard at `/gui`;
- a browser extension that connects ordinary AI chats to the local bridge.

The intended workflow is simple:

```text
AI chat / agent → Arena Chat Bridge Extension or MCP/REST → local Arena Unified Bridge → your machine
```

The project is local-first. You can keep it bound to `127.0.0.1`, or explicitly expose it through Tailscale Funnel or another HTTPS tunnel when you need remote access.

---

## Current highlights

| Area | Status |
| --- | --- |
| Runtime | One Python service, default `http://127.0.0.1:8765` |
| Protocols | REST, MCP, WebSocket/SSE events, built-in dashboard |
| Browser extension | Detects structured tool blocks in ChatGPT, Claude, Gemini, AI Studio and other web chats |
| Command Center | Sidepanel history with detected/preview/execute/insert/submit lifecycle cards |
| Security | Bearer token, path restrictions, command safety patterns, explicit policy checks |
| Installers | Windows, Linux and macOS scripts with optional components gated by prompts |
| Public HTTPS | Tailscale Funnel recommended; Cloudflare Quick Tunnels optional |
| Packaging | Release ZIPs are built from tracked files with sensitive-file exclusion checks |

See [CHANGELOG.md](CHANGELOG.md) for release history.

---

## Quick start

### 1. Download a release

Download the latest ZIP from:

```text
https://github.com/IvanSkainet/arena-agent/releases/latest
```

Extract it to a folder such as:

```text
C:\Users\You\arena-bridge        # Windows
~/arena-bridge                    # Linux/macOS
```

### 2. Run the installer

Windows:

```cmd
install.bat
```

Linux / macOS:

```bash
chmod +x install.sh
./install.sh
```

The installer creates a local bearer credential in `token.txt`, prepares runtime directories, and asks before installing optional components.

### 3. Start or verify the bridge

Local health check:

```bash
curl http://127.0.0.1:8765/health
```

Version endpoint:

```bash
curl http://127.0.0.1:8765/v1/version
```

The dashboard is available at:

```text
http://127.0.0.1:8765/gui
```

### 4. Give your AI the URL and credential

For local tools and MCP clients, use:

```text
Base URL: http://127.0.0.1:8765
Auth:     Authorization: Bearer <credential from token.txt>
```

For remote access, enable an HTTPS tunnel only if you understand the exposure model. Tailscale Funnel is the recommended option because it gives a real TLS hostname without port forwarding.

---

## Browser extension: Arena Chat Bridge

The extension is an Arena-native bridge for normal web chats. It watches assistant messages for structured tool blocks, previews/executes them through the local bridge, and can insert the result back into the chat composer.

Supported baseline adapters include:

- ChatGPT;
- Claude;
- Gemini Web;
- Google AI Studio;
- Grok;
- Perplexity;
- OpenRouter;
- DeepSeek;
- Kimi;
- Qwen;
- generic fallback.

Supported payload formats:

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

Load the extension for development:

1. open `chrome://extensions`;
2. enable **Developer mode**;
3. click **Load unpacked**;
4. select `chat_extension/`.

More details: [chat_extension/README.md](chat_extension/README.md).

---

## Optional components

The bridge works locally with Python and `aiohttp`. Some features need optional tools:

| Component | Purpose | Install behavior |
| --- | --- | --- |
| Tailscale | Recommended HTTPS exposure through Funnel | Optional, system-level install |
| cloudflared | Cloudflare Quick Tunnel fallback | Optional download, about 50 MB |
| BrowserAct / browser helpers | Rich browser automation | Optional |
| Camoufox | Stealth browser workflows | Optional |
| ydotool / xdotool | Linux desktop input automation | Optional / platform-specific |
| Tesseract | OCR for desktop/screenshot flows | Optional |

Optional components are not silently installed. The installer asks before adding them.

---

## Security model

Arena Unified Bridge can execute powerful actions on the host, so the security model is intentionally explicit:

- every non-local client should use the bearer credential from `token.txt`;
- upload/download/edit paths are restricted;
- common dangerous shell patterns and secret reads are blocked;
- desktop automation has pause/resume/revoke controls;
- extension policies classify tools by risk before auto-execution;
- public exposure should use HTTPS and a private credential;
- never paste credentials into an untrusted chat or public issue.

If you find a security issue, please report it privately instead of opening a public issue.

---

## API overview

Common endpoints:

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

Full surface is intentionally modular; see the dashboard, route tests, and docs in [`docs/`](docs/).

---

## Development

```bash
git clone https://github.com/IvanSkainet/arena-agent.git arena-bridge
cd arena-bridge
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"
pytest
```

Useful targeted checks for extension work:

```bash
pytest -q tests/test_chat_extension_assets.py tests/test_chat_extension_adapter_flow.py tests/test_chat_extension_sidepanel_flow.py tests/test_extension_bridge.py tests/test_project_modularity.py
node --check chat_extension/background.js
node --check chat_extension/content.js
node --check chat_extension/parser.js
node --check chat_extension/adapters.js
node --check chat_extension/insert_strategies.js
node --check chat_extension/insert_history.js
node --check chat_extension/adapter_sites.js
node --check chat_extension/popup.js
node --check chat_extension/settings.js
node --check chat_extension/sidepanel.js
```

Contributor notes: [CONTRIBUTING.md](CONTRIBUTING.md).
Release checklist: [RELEASE.md](RELEASE.md).

---

## Documentation map

- [CHANGELOG.md](CHANGELOG.md) — release history.
- [RELEASE.md](RELEASE.md) — release packaging and publishing checklist.
- [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) — integration notes.
- [docs/MODULE_MAP.md](docs/MODULE_MAP.md) — codebase/module map.
- [docs/V3_MODULAR_ARCHITECTURE.md](docs/V3_MODULAR_ARCHITECTURE.md) — modular architecture notes.
- [chat_extension/README.md](chat_extension/README.md) — browser extension details.

Some files in `docs/` are design notes or historical audits. The README and CHANGELOG are the public entry points.

---

## License

MIT. See [LICENSE](LICENSE).

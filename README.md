# Arena Unified Bridge

> **Cross-platform local automation bridge for AI agents.**
> One process, one port, one Python file — drives your computer from any chat, any AI, any OS.

[![Version](https://img.shields.io/badge/version-v2.1.0-blue.svg)](https://github.com/IvanSkainet/arena-agent/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-green.svg)]()
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](#license)

---

## What is this?

Arena Unified Bridge is a tiny local HTTP/MCP server that lets any AI (ChatGPT, Claude, Gemini, Grok, GLM, your own scripts, ...) safely drive your computer — execute commands, browse the web, save memory, capture screenshots, run skills, manage the queue of background tasks, and even control a real browser via Chrome DevTools Protocol.

It exposes a single secure URL like `https://your-machine.tail-XXXXX.ts.net` (over Tailscale Funnel) and listens to a REST API, MCP protocol, WebSocket and a built-in web dashboard at `/gui`.

**Goal:** *"Unzip the folder, run one installer, your AI has hands."*

---

## Highlights

- **Truly cross-platform** — installer auto-detects Windows / Linux / macOS and picks the right packaging strategy (NSSM Windows Service, Scheduled Task, systemd user unit, or launchd agent).
- **Unified single-process architecture** — REST API, MCP (HTTP/SSE/WebSocket), web gateway, dashboard, async task runner, all on **one port** (default `8765`).
- **110+ API endpoints** — including 30+ Chrome DevTools Protocol endpoints for real browser automation (navigate, click, type, screenshot, cookies, network interception, multi-tab management).
- **Token-authenticated** — Bearer token, persistent in `token.txt`, hot-rotatable from the dashboard.
- **Auto-restart everywhere** — NSSM on Windows, Scheduled Task as fallback, `Restart=on-failure` on systemd, `KeepAlive` on launchd. Survives crashes, reboots, login/logout.
- **Public HTTPS in one click** — Tailscale Funnel integration, no port-forward, no DDNS, real Let's Encrypt cert.
- **Modern web dashboard** at `/gui` — 15 tabs: Overview, Terminal, Memory, Recall, Missions, Browser, Reports, Tasks, Skills, Hooks, Agents, Doctor, Audit, Backup, Settings.
- **Deep system inventory** — motherboard, BIOS, CPU per core, GPU/VRAM, RAM modules with vendor/part numbers, all disks, all network interfaces, runtimes, package managers, browsers, displays.
- **Built-in AI tooling** — MCP server with 20+ tools, BrowserAct integration, Superpowers skill repository (14 skills), Camoufox stealth browser.
- **Disk-safe logging** — all log files have built-in rotation (RotatingFileHandler for structured logs, startup + periodic rotation for external captures). Disk usage monitoring with warnings at 80% / 90%. No more disk fill surprises.
- **No external dependencies** beyond `aiohttp` (and optional `psutil`) — uses Python stdlib for everything else (urllib, socket, subprocess, asyncio).
- **One-click uninstall** — `uninstall.bat` on Windows, `uninstall.sh` on Linux/macOS. Clean removal of services and files.

---

## Quick Start

### 1. Get the code

```bash
git clone https://github.com/IvanSkainet/arena-agent.git arena-bridge
cd arena-bridge
```

Or download the [latest release](https://github.com/IvanSkainet/arena-agent/releases) ZIP and extract.

### 2. Run the installer

**Windows (PowerShell or cmd):**
```cmd
install.bat
```

**Linux / macOS:**
```bash
chmod +x install.sh
./install.sh
```

The installer will:
1. Find Python >= 3.10.
2. Install `aiohttp` + `psutil`.
3. Create all required subdirectories inside the repo folder (no files scattered in your home).
4. Generate a fresh auth token (or preserve the existing one).
5. Detect and install optional components: Tailscale, SuperPowers, BrowserAct, Camoufox.
6. Register a background service (NSSM on Windows, Scheduled Task as fallback, systemd-user on Linux, launchd on macOS).
7. Rotate any oversized log files from previous runs.
8. Start the bridge and verify it's healthy.

**Everything stays in one folder.** No files are copied outside the repo directory.

That's it. You now have:

- `http://127.0.0.1:8765/health` — health check (public)
- `http://127.0.0.1:8765/gui` — web dashboard (login with token)
- `https://YOUR-PC.tail-net.ts.net` — public HTTPS (if Funnel enabled)

### 3. Give your AI the URL + token

In your chat:
> *"My bridge is at `https://YOUR-PC.tail-net.ts.net` with token `...`. Please do X."*

Most modern AI chat UIs (Claude.ai, ChatGPT custom GPTs, AnythingLLM, Open WebUI, ...) support custom HTTP tools or MCP servers and can call your endpoints directly.

For a ready-to-use system prompt template, see [`docs/AI_SYSTEM_PROMPT.md`](docs/AI_SYSTEM_PROMPT.md).

### 4. Update

```cmd
cd /d "C:\Users\You\arena-bridge" && git pull && install.bat
```

The installer preserves your existing token by default. Say `N` when asked about regenerating.

### 5. Uninstall

**Windows:**
```cmd
uninstall.bat
```

**Linux / macOS:**
```bash
chmod +x uninstall.sh
./uninstall.sh
```

Removes the service, scheduled task, and deletes all bridge files. Token and memory are gone too — back up first.

---

## Architecture

```
                        ┌──────────────────────────────────────────────┐
                        │       Internet (HTTPS, Let's Encrypt)        │
                        └──────────────────┬───────────────────────────┘
                                           │
                        ┌──────────────────▼───────────────────────────┐
                        │   Tailscale Funnel  →  https://pc.ts.net     │
                        └──────────────────┬───────────────────────────┘
                                           │
        ┌──────────────────────────────────▼─────────────────────────────────┐
        │                                                                    │
        │   localhost:8765   (one Python asyncio process, ~10.8K lines)       │
        │                                                                    │
        │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
        │   │ REST /v1/*   │  │ MCP /mcp     │  │ MCP /ws      │             │
        │   │ 110+ endpoints│  │ Streamable   │  │ WebSocket    │             │
        │   └──────────────┘  └──────────────┘  └──────────────┘             │
        │                                                                    │
        │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
        │   │ /gui         │  │ /sse,        │  │ /gateway     │             │
        │   │ Dashboard    │  │ /messages    │  │ /run, /tool  │             │
        │   └──────────────┘  └──────────────┘  └──────────────┘             │
        │                                                                    │
        │   ┌──────────────┐  ┌──────────────────────────────────────┐       │
        │   │ CDP browser  │  │  Async Task Runner (queue/inbox)      │       │
        │   │ 36 endpoints │  │  + Log Cleanup + Disk Monitor         │       │
        │   └──────────────┘  └──────────────────────────────────────┘       │
        │                                                                    │
        └────────────────────────────────────────────────────────────────────┘
                                           │
                ┌──────────────────────────┼──────────────────────────┐
                ▼                          ▼                          ▼
        ┌──────────────┐         ┌──────────────┐           ┌──────────────┐
        │   memory/    │         │   missions/  │           │   skills/    │
        │ JSONL facts  │         │ scripted     │           │ AI-runnable  │
        │ + recall     │         │ workflows    │           │ playbooks    │
        └──────────────┘         └──────────────┘           └──────────────┘
```

### Endpoints (highlights)

| Method | Path                         | Description                                  |
|--------|------------------------------|----------------------------------------------|
| GET    | `/health`                    | Public health probe                          |
| GET    | `/v1/info`                   | Bridge info (auth)                           |
| GET    | `/v1/sysinfo`                | CPU/RAM/disk + **disk_usage_percent**        |
| GET    | `/v1/hwinfo`                 | Full hardware: mobo, BIOS, GPU, RAM modules  |
| GET    | `/v1/inventory[?section=…]`  | Deep inventory: runtimes, browsers, etc.     |
| POST   | `/v1/exec`                   | Execute a shell command (with safety rules)  |
| POST   | `/v1/kill`                   | Kill a running process                       |
| POST   | `/v1/upload?path=…`          | Upload binary file                           |
| GET    | `/v1/download?path=…`        | Download file                                |
| GET/POST | `/v1/memory`               | Memory facts (key/value/tags JSONL)          |
| GET    | `/v1/recall?q=…&top=5`       | TF-scored fuzzy search + digest              |
| GET    | `/v1/audit?lines=N`          | Tail audit log                               |
| GET    | `/v1/audit/stats`            | Audit statistics                             |
| GET    | `/v1/doctor`                 | 10 self-tests (Python, dirs, network, disk...) |
| GET    | `/v1/browser/{search,read,head,dump,fetch}` | Web fetch helpers      |
| GET/POST/DELETE | `/v1/browser/cdp/*`  | Chrome DevTools Protocol (36 sub-endpoints)  |
| GET    | `/v1/sys/svc`                | Service status (NSSM/Scheduled Task/systemd) |
| GET    | `/v1/service/info`           | Detailed service info + PID                  |
| GET    | `/v1/sys/funnel`             | Tailscale Funnel status                      |
| POST   | `/v1/restart`                | Graceful restart (uses NSSM/systemd respawn) |
| POST   | `/v1/token/regenerate`       | Rotate auth token                            |
| GET    | `/v1/metrics`                | Bridge performance metrics                   |
| GET    | `/v1/logs?level=&lines=`     | Structured log viewer with level filter      |
| GET    | `/v1/skills`                 | List available AI skills                     |
| POST   | `/v1/skills/run`             | Run a skill                                  |
| GET    | `/v1/tasks`                  | List task queue                              |
| POST   | `/v1/tasks`                  | Submit background task                       |
| POST   | `/v1/tasks/clean`            | Clean completed tasks                        |
| GET    | `/v1/backups`                | List existing zip backups                    |
| POST   | `/v1/backup`                 | Create new backup                            |
| POST   | `/v1/beep`                   | Play sound notification (4 types)            |
| GET    | `/v1/ps`                     | List active exec processes                   |
| POST   | `/mcp`                       | MCP 2025-03-26 (initialize, tools/list, ...) |
| DELETE | `/mcp`                       | Close MCP session                            |
| GET    | `/ws`                        | MCP WebSocket                                |
| GET    | `/sse`                       | MCP SSE legacy transport                     |
| GET    | `/gui`                       | Web dashboard (HTML/JS)                      |

Full list: `GET /` returns a JSON catalog of all routes.

---

## Web Dashboard

The dashboard at `/gui` has 15 tabs and works in any modern browser without external dependencies (single self-contained HTML file).

| Tab | What it does |
|-----|--------------|
| **Overview** | Bridge metrics, hardware diagnostics card, full inventory drawer, disk usage |
| **Terminal** | Real shell session with slash-commands (`/shot`, `/read`, `/search`, ...) + arrow history |
| **Memory** | List, search, add, delete key/value/tag facts |
| **Recall** | Fuzzy TF-scored memory search and digest |
| **Missions** | Browse `missions/` directory |
| **Browser** | One-click `search`, `read`, `dump`, `fetch`, `HEAD`, screenshot |
| **Reports** | Browse and download screenshots / reports |
| **Tasks** | Queue inbox / running / done / failed, submit new task, clean |
| **Skills** | 29 skills (SuperPowers 14 + core/cleanup, core/digest, browseract, ...) |
| **Hooks** | List pre/post hooks |
| **Agents** | Sub-agent registry |
| **Doctor** | 10 self-tests + service/Funnel status + disk free check |
| **Audit** | All events, filter by category, stats |
| **Backup** | Create/list/download backups |
| **Settings** | Tokens, sound notifications, Tailscale Funnel toggle, restart, export config |

---

## Chrome DevTools Protocol (CDP)

The bridge exposes 36 CDP endpoints for controlling a real Chromium browser. This goes far beyond simple screenshots — you get full interactive automation.

| Feature | Endpoints | What it does |
|---------|-----------|--------------|
| **Connection** | `/v1/browser/cdp/connect`, `disconnect`, `status`, `diag`, `health` | Launch/connect to Chromium with stealth profile |
| **Navigation** | `/v1/browser/cdp/navigate` | Go to URL, wait for load |
| **Interaction** | `/v1/browser/cdp/click`, `type` | Click elements, type text with events |
| **Screenshots** | `/v1/browser/cdp/screenshot`, `stealth/shot` | Full-page or viewport PNG capture, stealth screenshot |
| **DOM** | `/v1/browser/cdp/dom` | Query DOM elements by CSS selector |
| **JavaScript** | `/v1/browser/cdp/eval` | Execute arbitrary JS in the page |
| **Tabs** | `/v1/browser/cdp/tabs`, `tabs/new`, `tabs/close`, `tabs/activate` | Multi-tab management |
| **Cookies** | `/v1/browser/cdp/cookies` (GET/POST/DELETE), `cookies/clear`, `cookies/profiles` | Cookie management with profile save/load |
| **Network** | `/v1/browser/cdp/network/start`, `network/stop`, `network/requests`, `network/har` | Network request monitoring and HAR export |
| **Intercept** | `/v1/browser/cdp/intercept/start`, `intercept/stop`, `intercept/rule`, `intercept/rules` | Network interception with custom rules |
| **Stealth** | `/v1/browser/cdp/stealth/extract`, `stealth/shot` | Anti-detection browser automation |
| **Session** | `/v1/browser/cdp/session/check`, `raw-info`, `test-launch`, `test-ws` | Session management and diagnostics |

---

## Disk Safety (v2.1.0)

Previous versions could fill the entire disk because aiohttp's default AccessLogger wrote a line to stderr for every HTTP request, and those lines were captured into append-only log files without rotation. This has been fixed in v2.1.0 with multiple layers of protection:

| Layer | Mechanism |
|-------|-----------|
| **Source eliminated** | `access_log=None` in `web.run_app()` — aiohttp no longer writes access logs |
| **Structured logging** | Python `RotatingFileHandler` (5 MB x 5 files) for `bridge.log` |
| **Startup rotation** | `_rotate_all_logs_on_startup()` rotates any oversized file before the server starts |
| **Periodic cleanup** | Background task every 30 min rotates logs over 10 MB |
| **Disk monitor** | Warning at 80% disk usage, critical at 90% |
| **Script-level rotation** | `install.bat` (NSSM `AppRotateFiles`), `install_windows_service.ps1` and `install.sh` all rotate before starting |
| **Cleanup skill** | `core/cleanup` skill covers rotated log files (`.log.1`, `.jsonl.1`, etc.) |

All log files — `bridge.log`, `audit.jsonl` (50 MB cap), `requests.jsonl` (10 MB cap) — are now properly rotated.

---

## Manage the service

### Windows (NSSM or Scheduled Task)
```powershell
# NSSM service
nssm status ArenaUnifiedBridge
nssm restart ArenaUnifiedBridge
nssm stop ArenaUnifiedBridge

# Scheduled Task (used when NSSM is not installed)
schtasks /run /tn "ArenaUnifiedBridge"
schtasks /end /tn "ArenaUnifiedBridge"

# Manual start
start_bridge.bat

# Logs (structured, rotated)
type %USERPROFILE%\arena-bridge\bridge.log
```

### Linux (systemd-user)
```bash
systemctl --user status   arena-bridge
systemctl --user restart  arena-bridge
journalctl  --user -u     arena-bridge -f
```

### macOS (launchd)
```bash
launchctl print           gui/$UID/com.arena.bridge
launchctl kickstart -k    gui/$UID/com.arena.bridge
```

---

## Project layout

```
arena-bridge/
├── unified_bridge.py     ← the entire server (one file, ~10.8K lines)
├── token.txt             ← your auth token (auto-generated)
├── install.bat           ← Windows installer (run this)
├── install.sh            ← Linux/macOS installer (run this; re-run to update)
├── uninstall.bat         ← Windows uninstaller
├── uninstall.sh          ← Linux/macOS uninstaller
├── start.bat             ← Quick start (manual)
├── stop.bat              ← Quick stop
├── status.bat            ← Quick health check
├── _arena_helper.py      ← Installer helper (version detection, token gen)
├── dashboard/
│   └── index.html        ← single-file web dashboard (15 tabs)
├── docs/
│   ├── AI_SYSTEM_PROMPT.md  ← Ready-to-use AI system prompt template
│   ├── AGENT_PROTOCOL.md    ← Agent protocol documentation
│   └── AGENTS.md.template   ← Agent config template
├── bin/                  ← user-facing CLIs (agentctl, bridge-curl, etc.)
├── scripts/              ← background helpers (inventory, hwinfo, CDP, etc.)
├── skills/               ← AI-runnable playbooks
│   ├── superpowers/      ← 14 curated AI skills from obra/superpowers
│   ├── core/             ← cleanup, digest
│   └── browseract/       ← BrowserAct stealth automation
├── memory/               ← key/value/tag facts (JSONL)
├── missions/             ← scripted workflows
├── queue/                ← task queue (inbox/running/done/failed)
├── reports/              ← screenshots, recordings
├── logs/                 ← bridge log files (rotated)
├── backups/              ← zip backups
├── hooks/                ← pre/post skill hooks
├── agents/               ← agent configurations
├── subagents/            ← subagent spawn/track
└── mcp/                  ← MCP configuration
```

---

## Configuration

All knobs are environment variables (set before running `install.*` or starting the service):

| Var                       | Default                            | Purpose                            |
|---------------------------|------------------------------------|------------------------------------|
| `ARENA_HOME`              | repo directory                      | Agent data directory (same as repo) |
| `BRIDGE_HOME`             | repo directory                      | Bridge directory (same as repo)     |
| `ARENA_PORT`              | `8765`                             | Listen port                        |
| `ARENA_PROFILE`           | `owner-shell`                      | Safety profile (rules in code)     |
| `ARENA_TASK_NAME`         | `ArenaUnifiedBridge`               | Windows Scheduled Task / Service   |
| `ARENA_SERVICE_NAME`      | `ArenaUnifiedBridge`               | NSSM service name                  |
| `ARENA_TOKEN_FILE`        | `<repo>/token.txt`                 | Token file                         |
| `ARENA_BRIDGE_TOKEN`      | (none)                             | Override token at runtime          |
| `ARENA_BRIDGE_URL`        | `http://127.0.0.1:8765`            | Base URL for `bridge-curl`/clients |

---

## Tested Platforms

| OS                         | Install method   | Service          | Status           |
|----------------------------|------------------|------------------|------------------|
| Windows 10 LTSC (build 19044) | `install.bat` | Scheduled Task   | daily-driver     |
| Windows 11                 | `install.bat`    | NSSM             | smoke-tested     |
| Debian 13 (trixie)         | `install.sh`     | systemd-user     | smoke-tested     |
| Ubuntu 22.04 / 24.04       | `install.sh`     | systemd-user     | via container    |
| Arch / CachyOS             | `install.sh`     | systemd-user     | pacman-aware     |
| Fedora 40+                 | `install.sh`     | systemd-user     | dnf-aware        |
| macOS 13+ (Apple Silicon)  | `install.sh`     | launchd          | help wanted      |
| FreeBSD 14                 | `install.sh`     | rc.d / nohup     | help wanted      |

Cross-platform installer auto-detects `apt`, `dnf`, `pacman`, `apk`, `zypper`, `nix`, `brew`, `pkg`, `winget`.

---

## Security model

- **Token-only auth** by default. Token is a 256-bit base64-url string stored at `token.txt` in the repo directory (`chmod 600` on Linux).
- **No request is auth-free** except `/health` and `/` index.
- **`/v1/exec` filters commands** via `BLOCKED_COMMANDS` (shutdown, reboot, format, mkfs, `rm -rf /`, `sudo`, `su`, diskpart, bcdedit, reg delete, curl|sh, encoded PowerShell, ...) and `CAUTIOUS_ALLOW` (safe read-only commands) lists baked into `unified_bridge.py`. Customize there.
- **CORS** enabled on all responses (so browser-based AI dashboards can call you).
- **Audit log** records every exec, every upload/download, every token/funnel/restart event with automatic rotation at 50 MB.
- **No telemetry, no analytics, no phone-home.** The only outbound calls are:
  - User-initiated calls from `/v1/browser/*` endpoints
  - MCP tool calls (exec, fs.read, fs.write, browser.search, etc.)
  - Tailscale status checks

When in doubt, read `unified_bridge.py` — it's a single Python file.

---

## Troubleshooting

### Bridge does not come back after restart on Windows
The bridge uses a Scheduled Task (or NSSM if installed). Both auto-restart on failure. Verify:
```powershell
schtasks /query /tn "ArenaUnifiedBridge"
# or, if NSSM:
nssm status ArenaUnifiedBridge
```

### Disk filled up with log files (v2.0.9 and earlier)
Fixed in v2.1.0. The root cause was aiohttp's AccessLogger writing every HTTP request to stderr, captured into append-only log files. Update to v2.1.0 and the bridge will:
- Disable access logging entirely
- Rotate all log files on startup
- Periodically check and rotate oversized logs (every 30 min)
- Warn when disk usage exceeds 80%

### PowerShell windows pop up on every dashboard refresh
Bridge < v1.6.7 spawned `wmic`/`tailscale`/`schtasks` without `CREATE_NO_WINDOW`. Upgrade to v2.1.0.

### Tailscale Funnel keeps dying
Funnel periodically drops if the upstream port stops accepting (e.g. when the bridge restarts). NSSM/Scheduled Task auto-respawns the bridge; re-enable Funnel once:
```powershell
tailscale funnel --bg 8765
```

### "Token rejected (401)" after I clicked Regenerate
The new token is written to disk; existing process keeps the old in memory. Click **Restart Bridge** in Settings or restart the service.

### How to uninstall
Run `uninstall.bat` (Windows) or `uninstall.sh` (Linux/macOS). This stops the service, removes the scheduled task / systemd unit, and deletes all bridge files.

---

## Changelog

### v2.1.0 — Critical disk fill bug fix + log rotation + disk monitoring
- **Fixed:** aiohttp AccessLogger not disabled — was the #1 cause of disk exhaustion (could fill 242 GB in hours)
- **Fixed:** Linux daemon mode redirected stdout/stderr to bridge.log, bypassing RotatingFileHandler rotation
- **Added:** Startup log rotation — `_rotate_all_logs_on_startup()` runs before server starts
- **Added:** Periodic log cleanup — background task every 30 min rotates oversized logs
- **Added:** Disk usage monitoring — warnings at 80%, critical at 90%
- **Added:** `disk_usage_percent` field in `/v1/sysinfo`
- **Added:** NSSM log rotation in `install.bat` (`AppRotateFiles`, 5 MB, 3 backups)
- **Added:** Log rotation in `install_windows_service.ps1` and `install.sh` (rotate at 10 MB)
- **Updated:** Cleanup skill covers rotated log files (`.log.{1,2,3}`, `.jsonl.{1..5}`)

### v2.0.9 — MCP tools fix for Windows
- **Fixed:** MCP tools on Windows no longer depend on `agentctl` binary
- MCP `exec`, `fs.read`, `fs.write`, `fs.list` work natively on all platforms

### v2.0.8 — GUI sysinfo fix, Linux sounds, uninstall scripts
- **Fixed:** GUI Overview now shows Hostname, OS, Platform (via `/v1/sysinfo`)
- **Fixed:** Process counter counts PIDs, not output lines
- **Added:** Unique sound melodies per notification type on Linux
- **Added:** Uninstall scripts (`uninstall.bat`, `uninstall.sh`)
- **Added:** `docs/AI_SYSTEM_PROMPT.md` — AI system prompt template
- **Fixed:** MCP port changed from 8767 to 8765
- **Removed:** 8 deprecated/garbage skills, old docs, duplicate scripts

### v2.0.7 and earlier
- Task API accepts title
- Doctor non-critical fixes
- Security hardening
- 8 new features for release-ready bridge
- MCP Streamable HTTP, SSE, WebSocket support
- Tailscale Funnel integration
- Chrome DevTools Protocol endpoints
- Web Gateway for external tool access

---

## Roadmap

- [ ] **Cloudflare Tunnel** as an alternative to Tailscale Funnel (no account required)
- [ ] **Plugin architecture** for third-party skill install/uninstall
- [ ] **Local semantic RAG memory** via SQLite FTS5
- [ ] **AppContainer sandboxing** on Windows for opt-in command isolation
- [ ] Replace `wmic` (deprecated in Win11) with CIM cmdlets in `_sys_*` helpers
- [ ] Linux Wayland recording in `mission-record` (currently x11grab only)
- [ ] AnythingLLM / Open WebUI integration recipes in `skills/`
- [ ] Multi-user token support
- [ ] Webhook notifications for events

---

## Contributing

Issues and PRs welcome. Please:
- Keep `unified_bridge.py` a **single file** with **stdlib + aiohttp** only.
- Stress-test with `stress-test-v3.sh` before sending PRs.
- Pure-ASCII PowerShell scripts (no unicode dashes/emoji — they break Cyrillic Windows installs).
- Backup before destructive ops.

---

## License

MIT License

Copyright (c) 2025-2026 Ivan / IvanSkainet

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

*Built collaboratively by Ivan and a rotating cast of AI assistants on [arena.ai](https://arena.ai/) — using the bridge to develop the bridge. Recursion of the friendly kind.*

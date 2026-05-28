# Arena Local Agent

> **Cross-platform local automation bridge for AI agents.**
> One process, one port, one Python file — drives your computer from any chat, any AI, any OS.

[![Version](https://img.shields.io/badge/version-v1.9.0-blue.svg)](https://github.com/IvanSkainet/arena-agent/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-green.svg)]()
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](#license)

---

## What is this?

Arena Local Agent is a tiny local HTTP/MCP server that lets any AI (ChatGPT, Claude, Gemini, Grok, GLM, your own scripts, …) safely drive your computer — execute commands, browse the web, save memory, capture screenshots, run skills, manage the queue of background tasks.

It exposes a single secure URL like `https://your-pc.tail328f18.ts.net` (over Tailscale Funnel) and listens to a REST API, MCP protocol, WebSocket and a built-in web dashboard at `/gui`.

**Goal:** *"Unzip the folder, run one installer, your AI has hands."*

---

## Highlights

- 🌍 **Truly cross-platform** — installer auto-detects Windows / Linux / macOS / BSD and picks the right packaging strategy (NSSM Windows Service, systemd user unit, or launchd agent).
- 🔌 **Unified single-process architecture** — REST API, MCP (HTTP/SSE/WebSocket), web gateway, dashboard, async task runner, all on **one port** (default `8765`).
- 🔒 **Token-authenticated** — Bearer token, persistent in `token.txt`, hot-rotatable from the dashboard.
- 🚀 **Auto-restart everywhere** — NSSM on Windows, `Restart=on-failure` on systemd, `KeepAlive` on launchd. Survives crashes, reboots, login/logout.
- 🌐 **Public HTTPS in one click** — Tailscale Funnel integration, no port-forward, no DDNS, real Let's Encrypt cert.
- 🖥️ **Modern web dashboard** at `/gui` — Overview, Terminal (with slash-commands + ↑/↓ history), Memory, Recall, Missions, Browser, Reports, Tasks, Skills, Hooks, Agents, Doctor, Audit, Git, Settings.
- 🧠 **Deep system inventory** — motherboard, BIOS, CPU per core, GPU/VRAM, RAM modules with vendor/part numbers, all disks, all network interfaces, runtimes, package managers, browsers, displays.
- 🧰 **Built-in AI tooling** — MCP server with 20+ tools, BrowserAct integration, Superpowers skill repository, agent-browser stealth mode.
- 📦 **No external dependencies** beyond `aiohttp` — uses Python stdlib for everything else (urllib, socket, subprocess, asyncio).

---

## Quick Start

### 1. Get the code

```bash
git clone https://github.com/IvanSkainet/arena-agent.git arena-bridge
cd arena-bridge
```

### 2. Run the installer

**Windows (PowerShell or cmd, run as admin if you want NSSM service):**
```cmd
install.bat
```

**Linux / macOS / BSD:**
```bash
chmod +x install.sh
./install.sh
```

The installer will:
1. Find Python >= 3.10.
2. Install `aiohttp` + `psutil`.
3. Create all required subdirectories inside the repo folder (no files scattered in your home).
4. Generate a fresh auth token (or preserve the existing one).
5. Register a background service (NSSM on Windows, systemd-user on Linux, launchd on macOS).
6. Start the bridge and verify it's healthy.

**Everything stays in one folder.** No files are copied outside `~/arena-bridge` or anywhere else.

That's it. You now have:

- `http://127.0.0.1:8765/health` — health check (public)
- `http://127.0.0.1:8765/gui` — web dashboard
- `https://YOUR-PC.tail-net.ts.net` — public HTTPS (if Funnel enabled)

### 3. Give your AI the URL + token

In your chat:
> *"My bridge is at `https://YOUR-PC.tail-net.ts.net` with token `…`. Please do X."*

Most modern AI chat UIs (Claude.ai, ChatGPT custom GPTs, AnythingLLM, Open WebUI, …) support custom HTTP tools or MCP servers and can call your endpoints directly.

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
        │   localhost:8765   (one Python asyncio process, ~1500 lines)       │
        │                                                                    │
        │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
        │   │ REST /v1/*   │  │ MCP /mcp     │  │ MCP /ws      │             │
        │   │ 50+ endpoints│  │ Streamable   │  │ WebSocket    │             │
        │   └──────────────┘  └──────────────┘  └──────────────┘             │
        │                                                                    │
        │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
        │   │ /gui         │  │ /sse,        │  │ /gateway     │             │
        │   │ Dashboard    │  │ /messages    │  │ /run, /tool  │             │
        │   └──────────────┘  └──────────────┘  └──────────────┘             │
        │                                                                    │
        │   ┌──────────────────────────────────────────────────────┐         │
        │   │      Async Task Runner (queue/inbox)                 │         │
        │   └──────────────────────────────────────────────────────┘         │
        │                                                                    │
        └────────────────────────────────────────────────────────────────────┘
                                           │
                ┌──────────────────────────┼──────────────────────────┐
                ▼                          ▼                          ▼
        ┌──────────────┐         ┌──────────────┐           ┌──────────────┐
        │ ~/arena-     │         │ ~/arena-     │           │ ~/arena-     │
        │   bridge/    │         │   bridge/    │           │   bridge/    │
        │   memory/    │         │   missions/  │           │   skills/    │
        │ JSONL facts  │         │ scripted     │           │ AI-runnable  │
        │              │         │ workflows    │           │ playbooks    │
        └──────────────┘         └──────────────┘           └──────────────┘
```

### Endpoints (highlights)

| Method | Path                         | Description                                  |
|--------|------------------------------|----------------------------------------------|
| GET    | `/health`                    | Public health probe                          |
| GET    | `/v1/info`                   | Bridge info (auth)                           |
| GET    | `/v1/sysinfo`                | Lightweight CPU/RAM/disk                     |
| GET    | `/v1/hwinfo`                 | Full hardware: mobo, BIOS, GPU, RAM modules  |
| GET    | `/v1/inventory[?section=…]`  | Deep inventory: runtimes, browsers, etc.     |
| POST   | `/v1/exec`                   | Execute a shell command (with safety rules)  |
| POST   | `/v1/upload?path=…`          | Upload binary file                           |
| GET    | `/v1/download?path=…`        | Download file                                |
| GET/POST | `/v1/memory`               | Memory facts (key/value/tags JSONL)          |
| GET    | `/v1/recall?q=…&top=5`       | TF-scored fuzzy search                       |
| GET    | `/v1/audit?lines=N`          | Tail audit log                               |
| GET    | `/v1/doctor`                 | 11 self-tests (Python, dirs, network, …)    |
| GET    | `/v1/browser/{search,read,head,dump,fetch}` | Web fetch helpers      |
| GET    | `/v1/sys/svc`                | Service status (NSSM/Scheduled Task/systemd) |
| GET    | `/v1/sys/funnel`             | Tailscale Funnel status                      |
| POST   | `/v1/restart`                | Graceful restart (uses NSSM/systemd respawn) |
| POST   | `/v1/token/regenerate`       | Rotate auth token                            |
| GET    | `/v1/backups`                | List existing zip backups (deprecated, use Git)  |
| POST   | `/v1/backup`                 | Create new backup (deprecated, use Git)          |
| POST   | `/mcp`                       | MCP 2025-03-26 (initialize, tools/list, …)   |
| GET    | `/ws`                        | MCP WebSocket                                |
| GET    | `/gui`                       | Web dashboard (HTML/JS)                      |

Full list: `GET /` returns a JSON catalog of all routes.

---

## Web Dashboard

The dashboard at `/gui` has 14 tabs and works in any modern browser without external dependencies (single self-contained HTML file).

| Tab | What it does |
|-----|--------------|
| **Overview** | Bridge metrics, hardware diagnostics card, full inventory drawer |
| **Terminal** | Real shell session with slash-commands (`/shot`, `/read`, `/search`, …) + ↑/↓ history |
| **Memory** | List, search, add, delete key/value/tag facts |
| **Recall** | Fuzzy TF-scored memory search and digest |
| **Missions** | Browse `missions/` directory |
| **Browser** | One-click `search`, `read`, `dump`, `fetch`, `HEAD`, screenshot |
| **Reports** | Browse and download screenshots / reports |
| **Tasks** | Queue inbox / running / done / failed, submit new task, clean |
| **Skills** | 26 built-in skills (`core/cleanup`, `web/research`, `system/sys-snapshot`, …) |
| **Hooks** | List pre/post hooks |
| **Agents** | Sub-agent registry |
| **Doctor** | 11 self-tests + NSSM/Funnel status |
| **Audit** | All events, filter by category, stats |
| **Git** | Version control: status, commit, push, pull, branch management |
| **Settings** | Tokens, sound notifications, Tailscale Funnel toggle, restart, export config |

---

## Manage the service

### Windows (NSSM)
```powershell
Get-Service     ArenaUnifiedBridge   # status
Stop-Service    ArenaUnifiedBridge
Start-Service   ArenaUnifiedBridge
Restart-Service ArenaUnifiedBridge
# Logs:
Get-Content "$env:USERPROFILE\arena-bridge\logs\ArenaUnifiedBridge.log" -Tail 50
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
├── unified_bridge.py     ← the entire server (one file, ~5700 lines)
├── token.txt             ← your auth token (auto-generated)
├── install.bat           ← Windows installer (run this)
├── install.sh            ← Linux/macOS installer (run this)
├── update.bat            ← Windows updater (preserves token)
├── update.sh             ← Linux/macOS updater (git pull + restart)
├── dashboard/
│   └── index.html        ← single-file web dashboard
├── bin/                  ← user-facing CLIs
├── scripts/              ← background helpers
├── skills/               ← AI-runnable playbooks
├── memory/               ← key/value/tag facts (JSONL)
├── missions/             ← scripted workflows
├── queue/                ← task queue (inbox/running/done/failed)
├── reports/              ← screenshots, recordings
├── logs/                 ← bridge log files
└── ...
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
| `ARENA_TOKEN_FILE`        | `~/arena-bridge/token.txt`         | Token file                         |
| `ARENA_BRIDGE_TOKEN`      | (none)                             | Override token at runtime          |
| `ARENA_BRIDGE_URL`        | `http://127.0.0.1:8765`            | Base URL for `bridge-curl`/clients |

---

## Tested Platforms

| OS                         | Install method   | Service          | Status           |
|----------------------------|------------------|------------------|------------------|
| Windows 10 LTSC (build 19044) | `install.bat` | NSSM             | ✅ daily-driver  |
| Windows 11                 | `install.bat`    | NSSM             | ✅ smoke-tested  |
| Debian 13 (trixie)         | `install.sh`     | systemd-user     | ✅ smoke-tested  |
| Ubuntu 22.04 / 24.04       | `install.sh`     | systemd-user     | ✅ via container |
| Arch / CachyOS             | `install.sh`     | systemd-user     | ✅ pacman-aware  |
| Fedora 40+                 | `install.sh`     | systemd-user     | ✅ dnf-aware     |
| macOS 13+ (Apple Silicon)  | `install.sh`     | launchd          | ⚠️ help wanted  |
| FreeBSD 14                 | `install.sh`     | rc.d / nohup     | ⚠️ help wanted  |

Cross-platform installer auto-detects `apt`, `dnf`, `pacman`, `apk`, `zypper`, `nix`, `brew`, `pkg`, `winget`.

---

## Security model

- **Token-only auth** by default. Token is a 256-bit base64-url string stored at `token.txt` in the repo directory (`chmod 600`).
- **No request is auth-free** except `/health` and `/` index.
- **`/v1/exec` filters commands** via `BLOCKED_COMMANDS` (shutdown, reboot, format, mkfs, rm -rf, …) and `CAUTIOUS_ALLOW` (sudo, su, killall) lists baked into `unified_bridge.py`. Customize there.
- **CORS** enabled on all responses (so browser-based AI dashboards can call you).
- **Audit log** records every exec, every upload/download, every token/funnel/restart event.
- **No telemetry, no analytics, no phone-home.** The only outbound calls are:
  - `https://nssm.cc` once during install (only Windows, only if not cached)
  - `https://nssm.cc/release/nssm-2.24.zip` (~350 KB)
  - User-initiated calls from `/v1/browser/*` endpoints

When in doubt, read `unified_bridge.py` — it's a single Python file.

---

## Troubleshooting

### Bridge does not come back after restart on Windows
You probably ran an older version that used a fragile Scheduled Task. Re-install via `install.bat`, which will register NSSM. Verify:
```powershell
Get-Service ArenaUnifiedBridge   # should say Running, Automatic
```

### PowerShell windows pop up on every dashboard refresh
Bridge < v1.6.7 spawned `wmic`/`tailscale`/`schtasks` without `CREATE_NO_WINDOW`. Upgrade to ≥ 1.6.9.

### Tailscale Funnel keeps dying
Funnel periodically drops if the upstream port stops accepting (e.g. when the bridge restarts). NSSM auto-respawns the bridge; re-enable Funnel once:
```powershell
tailscale funnel --bg 8765
```

### "Token rejected (401)" after I clicked Regenerate
The new token is written to disk; existing process keeps the old in memory. Click **Restart Bridge** in Settings or run `Restart-Service ArenaUnifiedBridge`.

---

## Roadmap (post-v1.8.1)

- [ ] **Step 2: CDP browser deep dive** — proper click/type/screenshot/auth-flow via Chrome DevTools Protocol
- [ ] **Step 3: Local semantic RAG memory** via SQLite FTS5
- [ ] **Step 4: AppContainer sandboxing** on Windows for opt-in command isolation
- [ ] Replace `wmic` (deprecated in Win11) with CIM cmdlets in `_sys_*` helpers
- [ ] Linux Wayland recording in `mission-record` (currently x11grab only)
- [ ] AnythingLLM / Open WebUI integration recipes in `skills/`

---

## Contributing

Issues and PRs welcome. Please:
- Keep `unified_bridge.py` a **single file** with **stdlib + aiohttp** only.
- Stress-test with `tmp/stress_test.py` before sending PRs.
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

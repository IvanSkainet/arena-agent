<div align="center">

# 🌉 Arena Unified Bridge

**Cross-platform local automation bridge for AI agents.**
One process · One port · One Python file — drives your computer from any chat, any AI, any OS.

[![CI](https://github.com/IvanSkainet/arena-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/IvanSkainet/arena-agent/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-v2.11.4-blue.svg)](https://github.com/IvanSkainet/arena-agent/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-green.svg)]()
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](#license)

</div>

---

## ✨ What is this?

Arena Unified Bridge is a tiny local HTTP/MCP server that lets any AI — ChatGPT, Claude, Gemini, Grok, GLM, your own scripts — **safely drive your computer**. Execute commands, browse the web, save memory, capture screenshots, run skills, manage a queue of background tasks, control a real browser via Chrome DevTools Protocol, and even automate the desktop with clicks, typing, and key presses on Wayland and X11.

It exposes a single secure URL like `https://your-machine.tail-XXXXX.ts.net` (over Tailscale Funnel) and serves a REST API, MCP protocol, WebSocket events, and a built-in web dashboard at `/gui`.

> **The goal:** *Unzip the folder, run one installer, your AI has hands.*

---

## 🚀 Highlights

| Category | Feature |
|----------|---------|
| **Cross-platform** | Installer auto-detects Windows / Linux / macOS and picks the right packaging strategy (NSSM Service, Scheduled Task, systemd user unit, or launchd agent) |
| **Unified architecture** | REST API, MCP (HTTP/SSE/WebSocket), web gateway, dashboard, async task runner — all on **one port** (default `8765`) |
| **236 route registrations** | 130+ handlers covering exec, memory, browser, CDP, desktop, tasks, skills, audit, watchdog, profiles, OpenAPI, and more |
| **36 CDP endpoints** | Full Chrome DevTools Protocol: navigate, click, type, screenshot, cookies, network interception, multi-tab management |
| **6 Desktop endpoints** | Wayland/X11 desktop automation: screenshot (PNG/JPEG/WebP + resize), click, layout-safe type, key press, mouse move, window list |
| **Token-authenticated** | 256-bit Bearer token, persistent in `token.txt`, hot-rotatable from the dashboard |
| **Auto-restart everywhere** | NSSM on Windows, Scheduled Task as fallback, `Restart=on-failure` on systemd, `KeepAlive` on launchd |
| **Public HTTPS in one click** | Tailscale Funnel integration — no port-forward, no DDNS, real Let's Encrypt cert |
| **14-tab dashboard** | Overview, Terminal, Memory, Recall, Missions, Browser, Reports, Tasks, Skills, Hooks, Agents, Doctor, Audit, Settings |
| **Deep system inventory** | Motherboard, BIOS, CPU per core, GPU/VRAM, RAM modules with vendor/part numbers, all disks, all network interfaces, runtimes, package managers, browsers, displays |
| **Built-in AI tooling** | MCP server with 20+ tools, BrowserAct integration, Superpowers skill repository (14 skills), Camoufox stealth browser |
| **Disk-safe logging** | Multiple layers of log rotation and disk monitoring — no more disk fill surprises (see [Disk Safety](#-disk-safety-v210)) |
| **Zero external deps** | Only `aiohttp` (and optional `psutil`) — everything else is Python stdlib |
| **One-click uninstall** | `uninstall.bat` / `uninstall.sh` — clean removal of services and files |

### 🆕 What's new in v2.11.4

- **Windows restart fixed:** `/v1/restart` no longer mistakes a stale stopped Windows service for an active NSSM install, and the Scheduled Task helper now kills the old bridge PID before relaunching to avoid orphaned `python.exe` processes.
- **Capability-aware stress test:** new `dev/stress-test-v4.py` exercises core API, hardware, service, skills, tasks, CDP, desktop endpoints when available, and optional restart without failing unsupported backends.
- **Keeps v2.11.3 stabilization:** installer version detection, Windows UTF-8/CIM date fixes, service diagnostics, and `/v1/capabilities` remain the baseline.

---

## 📦 Quick Start

### 1. Download the latest release

> ⚠️ **Always download from [Releases](https://github.com/IvanSkainet/arena-agent/releases).** The `master` branch is the development branch and may contain unstable or untested changes. Only tagged releases are production-ready.

Go to **[latest release](https://github.com/IvanSkainet/arena-agent/releases/latest)** and download the ZIP archive. Extract it to a folder of your choice, for example `C:\Users\You\arena-bridge` (Windows) or `~/arena-bridge` (Linux/macOS).

<details>
<summary>📦 Alternative: one-liner downloads</summary>

**Windows (PowerShell):**
```powershell
Invoke-WebRequest -Uri "https://github.com/IvanSkainet/arena-agent/releases/latest/download/arena-agent.zip" -OutFile "arena-agent.zip"
Expand-Archive arena-agent.zip -DestinationPath arena-bridge
cd arena-bridge
```

**Linux / macOS:**
```bash
curl -fsSL https://github.com/IvanSkainet/arena-agent/releases/latest/download/arena-agent.zip -o arena-agent.zip
unzip arena-agent.zip -d arena-bridge
cd arena-bridge
```
</details>

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
1. Find Python >= 3.10
2. Install `aiohttp` + `psutil`
3. Create all required subdirectories inside the repo folder (no files scattered in your home)
4. Generate a fresh auth token (or preserve the existing one)
5. Detect and install optional components: Tailscale, SuperPowers, BrowserAct, Camoufox
6. Register a background service (NSSM on Windows, Scheduled Task as fallback, systemd-user on Linux, launchd on macOS)
7. Rotate any oversized log files from previous runs
8. Start the bridge and verify it's healthy

> **Everything stays in one folder.** No files are copied outside the repo directory.

## 🧾 Transparency: background processes are expected (not malware)

Arena Unified Bridge is a **local automation server**. After installation it intentionally runs in the background so your AI tools can keep talking to your machine after you close the terminal.

The installers (`install.bat` and `install.sh`) show this transparency notice and ask for confirmation before registering/updating the background service. Automation can opt in explicitly with `ARENA_ACCEPT_BACKGROUND=1`.

This can look suspicious if you did not expect it — especially on Windows, where Task Manager may show `python.exe` processes. These processes are not hidden and are not meant to be stealthy: they are the bridge service, optional helper servers, and/or legacy helper scripts from older private builds.

### Normal process names you may see

| Process / command line contains | Why it exists |
|---------------------------------|---------------|
| `unified_bridge.py serve` | Current main bridge server (`http://127.0.0.1:8765`) |
| `local_bridge.py serve` | Legacy pre-GitHub bridge name used by older private builds |
| `mcp_ws_server.py` | Legacy MCP/WebSocket helper from older builds |
| `web_gateway.py` | Legacy web gateway helper from older builds |
| `agentctl task-watch` | Background task queue worker / legacy helper |
| `cloudflared` or `tailscale` | Optional tunnel/exposure helper if you enabled remote access |
| `ydotoold` | Linux/Wayland input automation daemon used for desktop control |

### Windows: inspect, stop, and remove it

Inspect Arena-related Python/background processes:

```powershell
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
  Where-Object { $_.CommandLine -match 'arena|bridge|mcp_ws|web_gateway|agentctl|local_bridge' } |
  Select-Object ProcessId, ParentProcessId, CommandLine |
  Format-List
```

Inspect scheduled tasks/services:

```powershell
schtasks /query /fo LIST /v | findstr /i "Arena Bridge arena local_bridge unified_bridge agentctl mcp_ws web_gateway"
sc query ArenaUnifiedBridge
```

Stop the current official install:

```cmd
uninstall.bat
```

If you are cleaning up an **old private/pre-GitHub build** that did not include the uninstaller, stop and remove stale tasks manually:

```powershell
# Stop matching Python helper processes
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
  Where-Object { $_.CommandLine -match 'arena|bridge|mcp_ws|web_gateway|agentctl|local_bridge' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# Remove known scheduled task names (ignore errors if they do not exist)
schtasks /Delete /TN "ArenaUnifiedBridge" /F
schtasks /Delete /TN "ArenaBridge" /F
schtasks /Delete /TN "ArenaLocalBridge" /F
```

### Linux/macOS: inspect and remove

```bash
pgrep -af 'arena|bridge|unified_bridge|local_bridge|mcp_ws|web_gateway|agentctl'
systemctl --user status arena-bridge.service  # Linux systemd user install
./uninstall.sh
```

### Privacy promise

The bridge does **not** install itself silently, does **not** hide its process names, and does **not** phone home. It only exposes the local/API functionality you installed it for. See [Security Model](#-security-model) for auth, safety filters, audit logs, and uninstall details.

That's it. You now have:

| URL | What |
|-----|------|
| `http://127.0.0.1:8765/health` | Health check (public, no auth) |
| `http://127.0.0.1:8765/gui` | Web dashboard (login with token) |
| `https://YOUR-PC.tail-net.ts.net` | Public HTTPS (if Funnel enabled) |

### 3. Give your AI the URL + token

In your chat:

> *"My bridge is at `https://YOUR-PC.tail-net.ts.net` with token `...`. Please do X."*

Most modern AI chat UIs (Claude.ai, ChatGPT custom GPTs, AnythingLLM, Open WebUI, ...) support custom HTTP tools or MCP servers and can call your endpoints directly.

For a ready-to-use system prompt template, see [`docs/AI_SYSTEM_PROMPT.md`](docs/AI_SYSTEM_PROMPT.md).

### 4. Update

Download the [latest release](https://github.com/IvanSkainet/arena-agent/releases/latest) ZIP and extract it over your existing folder (or into a new one). Then re-run the installer:

**Windows:**
```cmd
cd /d "C:\Users\You\arena-bridge"
install.bat
```

**Linux / macOS:**
```bash
cd ~/arena-bridge
./install.sh
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

## 🏗️ Architecture

```
                        ┌──────────────────────────────────────────────┐
                        │       Internet (HTTPS, Let's Encrypt)        │
                        └──────────────────┬───────────────────────────┘
                                           │
                        ┌──────────────────▼───────────────────────────┐
                        │   Tailscale Funnel  →  https://pc.ts.net     │
                        └──────────────────┬───────────────────────────┘
                                           │
        ┌──────────────────────────────────▼──────────────────────────────────┐
        │                                                                     │
        │   localhost:8765   (one Python asyncio process, ~11.7K lines)       │
        │                                                                     │
        │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
        │   │ REST /v1/*   │  │ MCP /mcp     │  │ MCP /ws      │              │
        │   │ 141 routes   │  │ Streamable   │  │ WebSocket    │              │
        │   └──────────────┘  └──────────────┘  └──────────────┘              │
        │                                                                     │
        │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
        │   │ /gui         │  │ /sse,        │  │ /gateway     │              │
        │   │ Dashboard    │  │ /messages    │  │ /run, /tool  │              │
        │   └──────────────┘  └──────────────┘  └──────────────┘              │
        │                                                                     │
        │   ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐      │
        │   │ CDP browser  │  │ Desktop API  │  │  Async Task Runner   │      │
        │   │ 36 endpoints │  │ 6 endpoints  │  │  + Log + Disk Mon.   │      │
        │   └──────────────┘  └──────────────┘  └──────────────────────┘      │
        │                                                                     │
        └─────────────────────────────────────────────────────────────────────┘
                                           │
                ┌──────────────────────────┼──────────────────────────┐
                ▼                          ▼                          ▼
        ┌──────────────┐         ┌──────────────┐           ┌──────────────┐
        │   memory/    │         │   missions/  │           │   skills/    │
        │ JSONL facts  │         │ scripted     │           │ AI-runnable  │
        │ + recall     │         │ workflows    │           │ playbooks    │
        └──────────────┘         └──────────────┘           └──────────────┘
```

---

## 📡 API Reference

### Core Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Public health probe (no auth) |
| `GET` | `/v1/version` | Version info |
| `GET` | `/v1/info` | Bridge info (auth) |
| `GET` | `/v1/status` | Bridge status (auth) |
| `GET` | `/v1/config` | Token-free configuration dump |

### System & Diagnostics

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/sysinfo` | CPU, RAM, disk + **disk_usage_percent** |
| `GET` | `/v1/hardware` | Canonical rich hardware/system inventory (normalized JSON from the unified collector) |
| `GET` | `/v1/hwinfo` | Backward-compatible alias for `/v1/hardware` |
| `GET` | `/v1/inventory[?section=…]` | Deep inventory: runtimes, browsers, displays, env, services, etc. |
| `GET` | `/v1/doctor` | 9 self-tests (Python, dirs, network, disk, sound…) |
| `GET` | `/v1/metrics` | Bridge performance metrics |
| `GET` | `/v1/logs?level=&lines=` | Structured log viewer with level filter |
| `GET/POST` | `/v1/watchdog` | Health watchdog status (memory/CPU/alerts) |
| `GET` | `/v1/ps` | List active exec processes |

### Execution

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/exec` | Execute a shell command. Body: `{"cmd": "..."}` (safety rules; input-injection commands are blocked while desktop control is paused/revoked) |
| `POST` | `/v1/kill` | Kill a running process. Body: `{"pid": N}` |
| `POST` | `/v1/batch` | Batch operations in parallel. Body: `{"operations": [{"method": "GET", "path": "/v1/status"}, ...]}` |
| `POST` | `/v1/restart` | Graceful restart (uses NSSM/systemd respawn) |

### File Operations

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/upload?path=…` | Upload binary file (`--data-binary`, path must be inside user home) |
| `GET` | `/v1/download?path=…` | Download file (path must be inside user home) |

> **Security:** Upload and download paths are restricted to the user's home directory. Path traversal (`..`) is blocked. The bridge binary itself cannot be overwritten.

### Memory & Recall

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/memory` | List memory facts (key/value/tags JSONL, pagination: `?offset=&limit=`) |
| `POST` | `/v1/memory` | Set memory fact. Body: `{"key": "...", "value": "...", "tags": [...]}` |
| `DELETE` | `/v1/memory` | Delete memory fact by key. Body: `{"key": "..."}` |
| `GET` | `/v1/recall?q=…&top=5` | TF-scored fuzzy search + digest |
| `GET` | `/v1/recall/digest` | Memory digest |

### Tasks & Queue

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/tasks` | List task queue |
| `POST` | `/v1/tasks` | Submit background task. Body: `{"cmd": "...", "title": "..."}` |
| `POST` | `/v1/tasks/clean` | Clean completed tasks |

### Skills & Hooks

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/skills` | List available AI skills |
| `POST` | `/v1/skills/run` | Run a skill |
| `POST` | `/v1/skills/reload` | Force reload skills cache |
| `GET` | `/v1/hooks` | List pre/post hooks |
| `GET` | `/v1/agents` | List agent configs |
| `GET` | `/v1/subagents` | List subagents |
| `POST` | `/v1/subagents/spawn` | Spawn subagent |

### Browser & Web

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/browser/search?q=…` | Search DuckDuckGo |
| `GET` | `/v1/browser/read?url=…` | Readability-extract text |
| `GET` | `/v1/browser/dump?url=…` | Full page dump with links |
| `GET` | `/v1/browser/fetch?url=…` | Raw content fetch |
| `GET` | `/v1/browser/head?url=…` | HTTP HEAD request |
| `POST` | `/v1/browser/browse` | Smart browse with rendering (auto-selects CDP or BrowserAct) |

### Chrome DevTools Protocol (36 endpoints + `/v1/cdp/*` aliases)

| Feature | Endpoints | What it does |
|---------|-----------|--------------|
| **Connection** | `/v1/browser/cdp/connect`, `disconnect`, `status`, `diag`, `health`, `raw-info`, `test-launch`, `test-ws` (`/v1/cdp/*` aliases also supported) | Launch/connect to Chromium with stealth profile |
| **Navigation** | `cdp/navigate` | Go to URL, wait for load (30s timeout) |
| **Interaction** | `cdp/click`, `cdp/type` | Click elements, type text with events |
| **Screenshots** | `cdp/screenshot`, `cdp/stealth/shot` | Full-page or viewport PNG capture |
| **DOM** | `cdp/dom` | Query DOM elements by CSS selector |
| **JavaScript** | `cdp/eval` | Execute arbitrary JS in the page (configurable timeout) |
| **Tabs** | `cdp/tabs`, `tabs/new`, `tabs/close`, `tabs/activate` | Multi-tab management |
| **Cookies** | `cdp/cookies` (GET/POST/DELETE), `cookies/clear`, `cookies/profiles` | Cookie management with profile save/load |
| **Network** | `cdp/network/start`, `network/stop`, `network/requests`, `network/har` | Network monitoring and HAR export |
| **Intercept** | `cdp/intercept/start`, `intercept/stop`, `intercept/rule` (POST/DELETE), `intercept/rules` | Network interception with custom rules |
| **Stealth** | `cdp/stealth/extract`, `stealth/shot` | Anti-detection browser automation |
| **Session** | `cdp/session/check` | Session management and diagnostics |

### Desktop Automation (6 endpoints)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/desktop/screenshot` | Take a desktop screenshot. Query: `format=png|jpeg|webp|base64`, `scale`, `max_width`, `quality` |
| `POST` | `/v1/desktop/click` | Click at coordinates. Body: `{"x": N, "y": N, "button": "left"}` |
| `POST` | `/v1/desktop/type` | Type text. Body: `{"text": "...", "ensure_latin": true}` (default: layout-safe typing on KDE) |
| `POST` | `/v1/desktop/key` | Press a key. Body: `{"key": "Return"}` |
| `POST` | `/v1/desktop/mouse` | Move mouse. Body: `{"action": "move", "x": N, "y": N}` |
| `GET` | `/v1/desktop/windows` | List open windows with titles/positions; tries native KWin scripting on KDE Wayland, then wmctrl/xdotool fallbacks |

> **Wayland support:** The installer auto-starts `ydotoold` for Wayland desktop automation. On X11, `xdotool` is used as fallback. Desktop click automatically activates the target window (v2.5.1+). For vision agents, prefer `GET /v1/desktop/screenshot?format=jpeg&scale=0.5&quality=80` or `max_width=1280` to reduce payload size dramatically.

### Audit & Logs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/audit?lines=N` | Tail audit log |
| `GET` | `/v1/audit/stats` | Audit statistics |
| `GET` | `/v1/audit/log?method=&path=&status=` | Request/response log with filters |

### Service & Security

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/sys/svc` | Service status (NSSM/Scheduled Task/systemd) |
| `GET` | `/v1/service/info` | Detailed service info + PID |
| `GET` | `/v1/sys/funnel` | Tailscale Funnel status |
| `POST` | `/v1/tailscale/funnel/{action}` | Start/stop Funnel |
| `POST` | `/v1/token/regenerate` | Rotate auth token |
| `GET/POST/DELETE` | `/v1/users` | User management |
| `GET/POST` | `/v1/profiles` | Safety profiles (cautious / owner-shell) |
| `POST` | `/v1/profiles/{name}/load` | Load a named safety profile |
| `GET/POST` | `/v1/ratelimit` | Rate limiter configuration |

### Observability & Advanced

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/events` | WebSocket real-time event stream |
| `GET/POST` | `/v1/tracing` | OpenTelemetry tracing config |
| `GET/POST` | `/v1/traces/export` | Export traces |
| `GET/POST` | `/v1/alerts` | Alert management |
| `GET` | `/v1/tls` | TLS configuration |
| `GET/POST` | `/v1/sandbox` | Sandbox configuration |
| `GET/POST` | `/v1/cluster` | Cluster status |
| `GET` | `/metrics` | Prometheus-compatible metrics (text format) |

### Reports & Missions

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/reports` | List screenshots and reports |
| `GET` | `/v1/missions` | List scripted missions |
| `GET` | `/v1/mission/show?name=…` | Show mission details |

### MCP Protocol

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/mcp` | MCP Streamable HTTP (2025-03-26 spec) |
| `DELETE` | `/mcp` | Close MCP session |
| `GET` | `/sse` | MCP SSE legacy transport |
| `POST` | `/messages` | MCP SSE peer endpoint |
| `GET` | `/ws` | MCP WebSocket transport |

### Web Gateway

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/gateway` | Web Gateway info |
| `GET` | `/gateway/tools` | Available gateway tools |
| `POST` | `/run` | Run whitelisted command |
| `POST` | `/tool` | Proxy MCP tool call |

### Sound & Notifications

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/beep` | Play sound notification (`success`, `warning`, `error`, `attention`, `melody`) |

### Dashboard & Docs

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/gui` | Web dashboard (single-file HTML/JS) |
| `GET` | `/api-docs` | OpenAPI 3.0 specification (JSON) |
| `GET` | `/openapi.json` | OpenAPI 3.0 alias for tooling that expects this conventional path |

> Full list: `GET /` returns a JSON catalog of all routes.

---

## 🖥️ Web Dashboard

The dashboard at `/gui` has **14 tabs** and works in any modern browser without external dependencies (single self-contained HTML file).

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
| **Skills** | Core skills + Superpowers + BrowserAct |
| **Hooks** | List pre/post hooks |
| **Agents** | Sub-agent registry |
| **Doctor** | 9 self-tests + service/Funnel status + disk free check |
| **Audit** | All events, filter by category, stats |
| **Settings** | Tokens, sound notifications, Tailscale Funnel toggle, restart, export config |

---

## 🛡️ Disk Safety (v2.1.0)

Previous versions could fill the entire disk because aiohttp's default AccessLogger wrote a line to stderr for every HTTP request, and those lines were captured into append-only log files without rotation. **This is fixed in v2.1.0** with multiple layers of protection:

| Layer | Mechanism | Details |
|-------|-----------|---------|
| **Source eliminated** | `access_log=None` | aiohttp no longer writes access logs at all |
| **Structured logging** | `RotatingFileHandler` | 5 MB × 5 files for `bridge.log` |
| **Startup rotation** | `_rotate_all_logs_on_startup()` | Rotates any oversized file before the server starts |
| **Periodic cleanup** | `_log_cleanup_loop()` | Background task every 30 min, rotates logs over 10 MB |
| **Disk monitor** | `disk_usage_percent` | Warning at 80%, critical at 90%, visible in `/v1/sysinfo` |
| **Script-level rotation** | `install.bat`, `install.sh` | Rotate at 10 MB before starting bridge |
| **NSSM rotation** | `AppRotateFiles=1` | 5 MB, 3 rotated copies in Windows service |
| **Cleanup skill** | `core/cleanup` | Covers old sessions, reports, completed tasks |

All log files — `bridge.log`, `audit.jsonl` (50 MB cap), `requests.jsonl` (10 MB cap) — are now properly rotated.

> **Result:** After 50+ test requests, `bridge.log` stayed at **797 bytes**. Previously, it could grow to gigabytes per hour.

---

## 🔧 Manage the Service

### Windows (NSSM or Scheduled Task)

```powershell
# NSSM service
nssm status ArenaUnifiedBridge
nssm restart ArenaUnifiedBridge
nssm stop ArenaUnifiedBridge

# Scheduled Task (used when NSSM is not installed)
schtasks /run /tn "ArenaUnifiedBridge"
schtasks /end /tn "ArenaUnifiedBridge"
schtasks /query /tn "ArenaUnifiedBridge" /fo LIST /v

# Remove stale scheduled task manually (normally uninstall.bat does this)
schtasks /delete /tn "ArenaUnifiedBridge" /f

# Manual start
start_bridge.bat

# View structured logs
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

## 📂 Project Layout

```
arena-bridge/
├── unified_bridge.py     ← the entire server (one file, ~11.7K lines)
├── token.txt             ← your auth token (auto-generated)
├── install.bat           ← Windows installer (run this)
├── install.sh            ← Linux/macOS installer (run this; re-run to update)
├── uninstall.bat         ← Windows uninstaller
├── uninstall.sh          ← Linux/macOS uninstaller
├── start.bat             ← Quick start (manual)
├── stop.bat              ← Quick stop
├── status.bat            ← Quick health check
├── _arena_helper.py      ← Installer helper (version detection, token gen)
│
├── dashboard/
│   └── index.html        ← single-file web dashboard (14 tabs)
│
├── docs/
│   └── AI_PROMPT_TEMPLATE.md ← Ready-to-use AI prompt template
│
├── dev/
│   └── stress-test-v3.sh     ← load/stress test suite (run before PRs)
│
├── bin/                  ← user-facing CLIs (agentctl, bridge-curl, etc.)
├── scripts/              ← background helpers (inventory, hwinfo, CDP, desktop, etc.)
├── skills/               ← AI-runnable playbooks
│   ├── superpowers/      ← 14 curated AI skills from obra/superpowers
│   ├── core/             ← cleanup, digest, health, snapshot
│   ├── dev/              ← auto-fix
│   ├── web/              ← research
│   ├── system/           ← sys-snapshot
│   └── browseract/       ← BrowserAct stealth automation
├── memory/               ← key/value/tag facts (JSONL)
├── missions/             ← scripted workflows
├── queue/                ← task queue (inbox/running/done/failed)
├── reports/              ← screenshots, recordings
├── logs/                 ← bridge log files (rotated)
├── hooks/                ← pre/post skill hooks
├── agents/               ← agent configurations
├── subagents/            ← subagent spawn/track
├── tools/                ← external tools
└── mcp/                  ← MCP configuration
```

---

## ⚙️ Configuration

All knobs are environment variables (set before running `install.*` or starting the service):

| Variable | Default | Purpose |
|----------|---------|---------|
| `ARENA_HOME` | repo directory | Agent data directory (same as repo) |
| `BRIDGE_HOME` | repo directory | Bridge directory (same as repo) |
| `ARENA_PORT` | `8765` | Listen port |
| `ARENA_PROFILE` | `owner-shell` | Safety profile (rules in code) |
| `ARENA_TASK_NAME` | `ArenaUnifiedBridge` | Windows Scheduled Task / Service |
| `ARENA_SERVICE_NAME` | `ArenaUnifiedBridge` | NSSM service name |
| `ARENA_TOKEN_FILE` | `<repo>/token.txt` | Token file |
| `ARENA_BRIDGE_TOKEN` | (none) | Override token at runtime |
| `ARENA_BRIDGE_URL` | `http://127.0.0.1:8765` | Base URL for `bridge-curl`/clients |

---

## 🧪 Tested Platforms

| OS | Install method | Service | Status |
|----|----------------|---------|--------|
| Windows 10 LTSC (build 19044) | `install.bat` | Scheduled Task | daily-driver |
| Windows 11 | `install.bat` | NSSM | smoke-tested |
| Debian 13 (trixie) | `install.sh` | systemd-user | smoke-tested |
| Ubuntu 22.04 / 24.04 | `install.sh` | systemd-user | via container |
| CachyOS (Arch) | `install.sh` | systemd-user | daily-driver |
| Fedora 40+ | `install.sh` | systemd-user | dnf-aware |
| macOS 13+ (Apple Silicon) | `install.sh` | launchd | help wanted |
| FreeBSD 14 | `install.sh` | rc.d / nohup | help wanted |

Cross-platform installer auto-detects `apt`, `dnf`, `pacman`, `apk`, `zypper`, `nix`, `brew`, `pkg`, `winget`.

---

## 🔒 Security Model

- **Token-only auth** by default. Token is a 256-bit base64-url string stored at `token.txt` (`chmod 600` on Linux).
- **No request is auth-free** except `/health` and `/` index.
- **`/v1/exec` filters commands** via blocked patterns (`rm -rf /`, `sudo`, `su`, `format`, `mkfs`, `diskpart`, `bcdedit`, `reg delete`, `curl|sh`, encoded PowerShell, obvious secret reads, reverse shells, ...) and a `CAUTIOUS_ALLOW` allowlist for safe read-only commands. Customize in `unified_bridge.py`.
- **Control lease applies to input injection** — when `/v1/control/pause` or `/v1/control/revoke` is active, desktop endpoints are blocked, and `/v1/exec` also rejects commands that would inject keyboard/mouse input (`ydotool`, `xdotool key/click/type`, `wtype`, etc.). General shell diagnostics remain available to avoid self-lockout.
- **File operations are sandboxed** — upload and download paths must be inside the user's home directory. Path traversal (`..`) is blocked, and the bridge binary itself cannot be overwritten.
- **Browser fetch SSRF guard** — `/v1/browser/read`, `/dump`, `/fetch`, and `/head` only allow HTTP(S) public targets. The validator blocks localhost/private/link-local/reserved/multicast/unspecified addresses, obfuscated IPv4 spellings (`127.1`, octal, hex, integer forms), IPv4-mapped IPv6 loopback, internal/metadata hostnames, and DNS names resolving to internal addresses.
- **Profile system**: `owner-shell` (permissive) and `cautious` (restricted). Switch via `ARENA_PROFILE` env var.
- **Rate limiting**: 300 requests per minute per IP, configurable via `/v1/ratelimit`. Auth failures are rate-limited separately at 10 attempts per minute per IP.
- **CORS** enabled on all responses (browser-based AI dashboards can call you).
- **Audit log** records every exec, every upload/download, every token/funnel/restart event with automatic rotation at 50 MB.
- **No telemetry, no analytics, no phone-home.** The only outbound calls are:
  - User-initiated calls from `/v1/browser/*` endpoints
  - MCP tool calls (exec, fs.read, fs.write, browser.search, etc.)
  - Tailscale status checks
- **Not stealth software.** The bridge runs as a visible service/scheduled task with readable command lines and documented process names. It is designed to be inspectable and removable, not hidden.

When in doubt, read `unified_bridge.py` — it's a single Python file.

---

## 🐛 Troubleshooting

### I see `python.exe`, `local_bridge.py`, `mcp_ws_server.py`, or `web_gateway.py` in Task Manager — is this a virus?
No — these are Arena bridge/background helper processes, especially from older private/pre-GitHub builds. They should be visible in Task Manager/PowerShell, and you can remove them.

Use this to inspect:

```powershell
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
  Where-Object { $_.CommandLine -match 'arena|bridge|mcp_ws|web_gateway|agentctl|local_bridge' } |
  Select-Object ProcessId, ParentProcessId, CommandLine |
  Format-List
```

Then run `uninstall.bat` from the bridge folder. If this was an old build without an uninstaller, stop the processes and remove stale scheduled tasks as shown in [Transparency: background processes are expected](#-transparency-background-processes-are-expected-not-malware).

### Bridge does not come back after restart on Windows
The bridge uses a Scheduled Task (or NSSM if installed). Both auto-restart on failure. Verify:
```powershell
schtasks /query /tn "ArenaUnifiedBridge"
# or, if NSSM:
nssm status ArenaUnifiedBridge
```

### Disk filled up with log files (v2.0.9 and earlier)
**Fixed in v2.1.0.** The root cause was aiohttp's AccessLogger writing every HTTP request to stderr, captured into append-only log files. Update to v2.1.0 and the bridge will:
- Disable access logging entirely
- Rotate all log files on startup
- Periodically check and rotate oversized logs (every 30 min)
- Warn when disk usage exceeds 80%

### CDP WebSocket becomes unstable on heavy pages
**Improved in v2.5.1.** The health probe now uses lightweight `Target.getTargetInfo` instead of `eval_js`, and the WebSocket ping check is tolerant of occasional timeouts. The bridge will reconnect automatically after 3 consecutive failures.

### Desktop click/key not reaching the target window
**Fixed in v2.5.1.** Desktop click now automatically activates the target window (via `kdotool`/`xdotool`) before sending the click event, ensuring the input reaches the correct window.

### PowerShell windows pop up on every dashboard refresh
Bridge < v1.6.7 spawned `wmic`/`tailscale`/`schtasks` without `CREATE_NO_WINDOW`. Fixed in v2.0+ — all subprocess calls use the `_NO_WINDOW_FLAG` on Windows.

### Tailscale Funnel keeps dying
Funnel periodically drops if the upstream port stops accepting (e.g. when the bridge restarts). NSSM/Scheduled Task auto-respawns the bridge; re-enable Funnel once:
```powershell
tailscale funnel --bg 8765
```

### Desktop commands typed as gibberish (e.g. `/time set day` → `.ешьу ыуе вфн`)
This happens when raw keycodes are interpreted through a non-Latin active keyboard layout. **Improved in v2.10.0:** `/v1/desktop/type` uses `ensure_latin: true` by default on KDE, switching to the first/Latin layout before typing.

### Screenshot is too large or slow for vision agents
Use the v2.10.0 screenshot transforms instead of full-size PNG:

```bash
GET /v1/desktop/screenshot?format=jpeg&scale=0.5&quality=80
# or
GET /v1/desktop/screenshot?format=jpeg&max_width=1280&quality=80
```

### "Token rejected (401)" after I clicked Regenerate
The new token is written to disk; existing process keeps the old in memory. Click **Restart Bridge** in Settings or restart the service.

### How to uninstall
Run `uninstall.bat` (Windows) or `uninstall.sh` (Linux/macOS). This stops the service, removes the scheduled task / systemd unit, and deletes all bridge files.

---

## 📋 Changelog

### v2.11.4 — Windows restart lifecycle and stress-test baseline
- **Fixed:** Windows `/v1/restart` now uses the SCM/NSSM branch only when the service is actually running; stale stopped services no longer prevent Scheduled Task relaunch.
- **Fixed:** Scheduled Task restart helper now force-kills the previous bridge PID before relaunching the task, preventing orphaned `python.exe` bridge processes.
- **Added:** `dev/stress-test-v4.py`, a capability-aware cross-platform smoke/stress test runner for REST/core/hardware/service/skills/tasks/CDP/desktop/restart checks.

### v2.11.3 — Windows stabilization and capabilities map
- **Fixed:** `install.bat`/`install.sh` now read the canonical version from `_arena_helper.py` / `arena/constants.py`, avoiding `Bridge vunknown` after the version constant moved out of `unified_bridge.py`.
- **Improved:** Windows installer health verification prints the actual `/health.version`.
- **Improved:** Windows CIM/PowerShell inventory probes force UTF-8 and normalize common CIM date formats.
- **Improved:** Windows service/status endpoints distinguish stale stopped services from active Scheduled Tasks and include process command lines for bridge-related Python processes.
- **Added:** `/v1/capabilities` returns an agent-facing map of available OS/service/browser/desktop/hardware capabilities and selected backends.

### v2.11.2 — Third-party uninstall safe-name polish
- **Fixed:** `/v1/skills/uninstall` now accepts safe third-party skill names beginning with `_`, matching names that `/v1/skills` can list, while retaining traversal/core-skill protections.

### v2.11.1 — Hardware device expansion, KWin journal windows, skill uninstall fix
- **Improved:** `/v1/hardware` now includes `devices.storage`, `devices.pci`, `devices.usb`, and `thermal` sections where available.
- **Fixed:** KDE/KWin window discovery no longer uses `QFile` inside KWin scripts; it now reads a tokenized JSON line from the user journal and falls back safely if unavailable.
- **Fixed:** `/v1/skills/uninstall` now accepts `third_party/<name>` as returned by `/v1/skills`, plus bare third-party names, while rejecting core/category skills and traversal.
- **Removed:** broken test-only `skills/third_party/weather` skill from the production tree.
- **Tests:** Added regression coverage for hardware device normalization and third-party uninstall name normalization.

### v2.11.0 — Unified hardware API, KDE Wayland windows, CDP aliases
- **Added:** `/v1/hardware` as the canonical rich hardware/system inventory endpoint, backed by `scripts/inventory.py`; `/v1/hwinfo` remains a compatibility alias.
- **Improved:** Hardware JSON now merges richer inventory facts, including motherboard/BIOS, NVIDIA VRAM/temperature/utilization, memory modules, disks, displays, network, runtimes, package managers, and browsers.
- **Fixed:** Windows CIM inventory helper no longer silently fails because of an unsupported `_run(..., shell=True)` call; Windows display and logical disk collection were also hardened.
- **Improved:** `/v1/desktop/windows` now tries native KDE/KWin scripting on Plasma Wayland before falling back to `wmctrl` and `xdotool`.
- **Added:** Short `/v1/cdp/*` aliases for the existing `/v1/browser/cdp/*` endpoints to improve agent discoverability.
- **Changed:** `/v1/browser/cdp/session/check` returns HTTP 200 with `connected: false` and actionable details when CDP is disconnected.
- **Polished:** Runtime version probes now handle noisy `lua`/`dotnet` cases more cleanly.

### v2.10.3 — SSRF hardening for browser fetch endpoints
- **Security:** Hardened `_validate_url` for `/v1/browser/read`, `/dump`, `/fetch`, and `/head` against obfuscated internal-address bypasses (`127.1`, octal/hex/integer IPv4, IPv4-mapped IPv6 loopback) and cloud metadata/internal hostnames.
- **Defense in depth:** DNS A/AAAA results are resolved and checked for private/internal addresses before fetch.
- **Tests:** Added regression coverage for the reported SSRF bypasses, including `metadata.google.internal` and `localhost.localdomain`.

### v2.10.2 — CI, security tests, and safe release packaging
- **Security:** Release packaging now ships only git-tracked files plus explicit runtime placeholders and asserts that sensitive files are not included.
- **Tests/CI:** Added GitHub Actions, `tests/test_security.py`, `requirements.txt`, `pyproject.toml`, and repository hygiene updates.

### v2.10.1 — Installer transparency and anti-false-positive release
- **Installers:** `install.bat` and `install.sh` now show a prominent `TRANSPARENCY NOTICE - BACKGROUND SERVICE` before registering/updating any background service, scheduled task, systemd unit, or launchd agent.
- **Consent:** installers now ask for explicit confirmation (`Continue and install/update the background service? [y/N]`) before service registration. Automation can opt in with `ARENA_ACCEPT_BACKGROUND=1` or `ARENA_ASSUME_YES=1`.
- **Docs:** README now documents expected background processes, legacy helper names (`local_bridge.py`, `mcp_ws_server.py`, `web_gateway.py`, `agentctl task-watch`), inspection commands, and cleanup/uninstall commands to avoid the project being mistaken for malware.
- **Version:** bridge runtime version bumped to `2.10.1` so `/health` and `/v1/version` identify this transparency release.

### v2.10.0 — Bridge hardening, screenshot transforms, layout-safe typing & OpenAPI alias
- **Docs:** Added a prominent transparency section explaining expected background processes, Windows scheduled tasks/services, legacy helper names, and manual cleanup commands so the project is not mistaken for malware.
- **Installers:** `install.bat` and `install.sh` now show an explicit background-service transparency notice and require confirmation before installing/updating the service (set `ARENA_ACCEPT_BACKGROUND=1` for automation).
- **Fixed:** `/v1/exec` can no longer bypass `/v1/control/pause` or `/v1/control/revoke` for desktop input injection commands (`ydotool`, `xdotool key/click/type`, `wtype`, etc.).
- **Added:** `/v1/desktop/screenshot` now supports `format=jpeg|jpg|webp|png|base64`, `scale`, `max_width`, and `quality`.
- **Added:** `/v1/desktop/type` now supports `ensure_latin` (default `true`) to avoid non-Latin XKB layout corruption on KDE/Wayland.
- **Hardened:** `/v1/exec` blocks obvious secret reads (`~/.ssh/id_*`, `.netrc`, `.git-credentials`, `.aws/credentials`, `token.txt`, `/etc/shadow`) and common reverse-shell patterns.
- **Added:** `/openapi.json` alias and OpenAPI documentation for the new desktop parameters.

### v2.9.1 — GUI Control Panel, KWin DBus focus & active window improvements
- **Added/Improved:** desktop focus/control APIs and active window handling for KDE/Wayland/XWayland workflows.
- **Improved:** control lease endpoints (`/v1/control/status`, `/pause`, `/resume`, `/revoke`) for safer desktop automation sessions.

### v2.8.0 — Memory DB Integrity Sync, Quality Hardening & Universal Plugins
- **Added:** Local Semantic RAG Memory via SQLite FTS5 with `trigram` tokenizer, fully replacing obsolete `facts.jsonl` in both the bridge and CLI tools (`scripts/memory.py`, `bin/memory_recall.py`)
- **Added:** Cloudflare Quick Tunnels integration (`cloudflared`) managed directly from the dashboard, featuring auto-cleanup of stale daemon processes
- **Added:** Plugin architecture for installing/uninstalling third-party skills from ZIP (with automatic un-nesting and macOS metadata cleaning) or GitHub repositories with flag injection protections
- **Added:** Webhook notifications for bridge events with built-in in-memory caching for zero-I/O background performance
- **Added:** Linux Wayland video recording support via `wf-recorder` or `kmsgrab` fallback to `mission-record`
- **Added:** AppContainer sandboxing on Windows (`scripts/appcontainer_run.ps1`) for isolated command execution
- **Added:** Modern PowerShell CIM-cmdlets (`Get-CimInstance`) replacing deprecated `wmic` across all scripts, including `scripts/hwinfo_lite.py`
- **Added:** Full automated test suite inside `tests/test_unified_bridge.py` running on `pytest` to verify all components natively on any platform
- **Refactored:** 100% eradication of bare `except:` blocks across all Python and Shell scripts in the entire repository, improving maintainability and error diagnostics.

### v2.7.0 — Cloudflare Quick Tunnels, Webhooks, AppContainer Sandbox & Universal Plugins (Pre-release)

### v2.5.2 — Remove backup feature
- **Removed:** Backup feature entirely (`/v1/backup/*` endpoints and `backups/` directory) — it could create oversized archives (44 GB+) and is not reliably fixable. Use external backup tools instead.

### v2.5.1 — CDP resilience, desktop focus, eval fixes, cookie manager
- **Fixed:** `arena-task-runner.service` crash loop — `install.sh` now cleans up old service units before registering new ones
- **Fixed:** CDP WebSocket instability on heavy pages — replaced `eval_js` health probe with `Target.getTargetInfo`, added 3-timeout tolerance before reconnect
- **Fixed:** Desktop click/key not reaching windows — added automatic window activation (via `kdotool`/`xdotool`) before click
- **Fixed:** Heavy `cdp/eval` returning `ok: false` — now uses `Runtime.evaluate` directly with proper error messages and configurable timeout
- **Fixed:** Cookie manager 500 error — `TabCookieManager.set_cookie()` interface fixed to match actual method signature
- **Fixed:** `uninstall.sh` now removes all arena-related service units (including stale ones like `arena-task-runner`)

### v2.5.0 — Cookie manager fallback, bug fixes
- **Fixed:** Cookie manager crash — added `TabCookieManager` fallback when `CDPCookieManager` is unavailable
- **Fixed:** 5 critical bugs found during Arena.ai testing (command execution, response handling, error propagation)

### v2.4.0 — Desktop automation, navigate improvements
- **Added:** Desktop Automation API — 6 new endpoints: `/v1/desktop/screenshot`, `/v1/desktop/click`, `/v1/desktop/type`, `/v1/desktop/key`, `/v1/desktop/mouse`, `/v1/desktop/windows`
- **Added:** Wayland support via `ydotool`/`kdotool` with auto-start of `ydotoold` daemon
- **Added:** X11 fallback via `xdotool`
- **Fixed:** CDP navigate timeout increased to 30s for heavy sites
- **Fixed:** Auto-refresh tab list after navigation

### v2.3.0 — Critical CDP safety fixes
- **Fixed:** CDP commands could freeze the system — added 15s hard timeout to all CDP operations
- **Fixed:** CDP click and type now have coordinate support and timeout protection
- **Added:** Safety timeouts prevent system freezes from unresponsive CDP targets

### v2.2.0 — 14 surgical fixes
- Version bump consolidating 14 bug fixes and improvements verified across all endpoints
- Updated deprecated endpoint `removal_version` targets

### v2.1.1 — Surgical fixes, multi-user auth, memory DELETE, auth rate limit
- **Fixed:** `check_auth()` now checks `users.json` tokens — multi-user auth works on all endpoints, not just `/v1/users`
- **Fixed:** `decode_output()` on Windows uses `errors="replace"` instead of `strict` — one bad byte no longer kills entire output
- **Fixed:** `/v1/doctor` disk check uses 80% threshold (consistent with disk monitoring) instead of hardcoded 1 GB
- **Fixed:** `_load_facts()` logs errors instead of silently swallowing them
- **Fixed:** Cleanup skill docs (SKILL.md, manifest.json) now list `rotated_logs` category
- **Fixed:** `install.bat` header comment updated from v2.0.6 to v2.1.0
- **Fixed:** `_arena_helper.py` replaced from garbage data to working version/token helper
- **Added:** `DELETE /v1/memory` endpoint — delete a specific memory fact by key
- **Added:** `/v1/memory` pagination — `?offset=N&limit=N` params, `total` and `next_offset` in response
- **Added:** Auth-specific rate limiting — 10 failed auth attempts per minute per IP (429 with `Retry-After`)
- **Updated:** Deprecated endpoints `removal_version` bumped from `VERSION` (2.1.0) to `"2.3.0"`
- **Updated:** Roadmap — removed "Multi-user token support" (already implemented)
- **Updated:** `AI_SYSTEM_PROMPT.md` — removed incorrect token query param, added v2.1.0+ endpoints

### v2.1.0 — Critical disk fill bug fix + log rotation + disk monitoring
- **Fixed:** aiohttp AccessLogger not disabled — was the #1 cause of disk exhaustion (could fill 242 GB in hours)
- **Fixed:** Linux daemon mode redirected stdout/stderr to bridge.log, bypassing RotatingFileHandler rotation
- **Added:** Startup log rotation — `_rotate_all_logs_on_startup()` runs before server starts
- **Added:** Periodic log cleanup — background task every 30 min rotates oversized logs
- **Added:** Disk usage monitoring — warnings at 80%, critical at 90%
- **Added:** `disk_usage_percent` field in `/v1/sysinfo`
- **Added:** NSSM log rotation in `install.bat` (`AppRotateFiles`, 5 MB, 3 rotated copies)
- **Added:** Log rotation in `install_windows_service.ps1` and `install.sh` (rotate at 10 MB)
- **Updated:** Cleanup skill covers rotated log files

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

## 🗺️ Roadmap

- [x] **Cloudflare Tunnel** as an alternative to Tailscale Funnel (no account required)
- [x] **Plugin architecture** for third-party skill install/uninstall
- [x] **Local semantic RAG memory** via SQLite FTS5
- [x] **AppContainer sandboxing** on Windows for opt-in command isolation
- [x] Replace `wmic` (deprecated in Win11) with CIM cmdlets in `_sys_*` helpers
- [x] Linux Wayland recording in `mission-record` (currently x11grab only)
- [ ] AnythingLLM / Open WebUI integration recipes in `skills/`
- [x] Webhook notifications for events
- [ ] Code and repository cleanup (remove unused test files, old configs)

---

## 🤝 Contributing

Issues and PRs welcome. Please:
- Keep `unified_bridge.py` a **single file** with **stdlib + aiohttp** only.
- Stress-test with `dev/stress-test-v3.sh` before sending PRs.
- Pure-ASCII PowerShell scripts (no unicode dashes/emoji — they break Cyrillic Windows installs).
- Snapshot before destructive ops (use external backup tools).

---

## 📄 License

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

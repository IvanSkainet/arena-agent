<div align="center">

# 🌉 Arena Unified Bridge

**Cross-platform local automation bridge for AI agents.**
One process · One port · Modular Python architecture — drives your computer from any chat, any AI, any OS.

**🌐 English · [Русский](README.ru.md)**

[![CI](https://github.com/IvanSkainet/arena-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/IvanSkainet/arena-agent/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/release/IvanSkainet/arena-agent?color=blue&label=version)](https://github.com/IvanSkainet/arena-agent/releases)
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
| **200+ method/path routes** | Public REST, MCP, gateway, dashboard, observability, desktop, browser, admin, and compatibility surfaces on one port |
| **36 CDP endpoints** | Full Chrome DevTools Protocol: navigate, click, type, screenshot, cookies, network interception, multi-tab management |
| **15 desktop + 4 control endpoints** | Wayland/X11 desktop automation: screenshot, display/output discovery, OCR, text-target detection, OCR-to-window resolution, high-level text actions, semantic click-by-text, click, layout-safe type, key press, mouse move, window list, active window, focus, window actions, plus control lease pause/resume/revoke/status |
| **Token-authenticated** | 256-bit Bearer token, persistent in `token.txt`, hot-rotatable from the dashboard |
| **Auto-restart everywhere** | NSSM on Windows, Scheduled Task as fallback, `Restart=on-failure` on systemd, `KeepAlive` on launchd |
| **Public HTTPS in one click** | Tailscale Funnel integration — no port-forward, no DDNS, real Let's Encrypt cert |
| **16-tab dashboard** | Overview, Workspace, Terminal, Memory, Recall, Missions, Browser, Reports, Tasks, Skills, Hooks, Agents, Control, Doctor, Audit, Settings |
| **Deep system inventory** | Motherboard, BIOS, CPU per core, GPU/VRAM, RAM modules with vendor/part numbers, all disks, all network interfaces, runtimes, package managers, browsers, displays |
| **Built-in AI tooling** | MCP server with 68 tools, BrowserAct integration, Superpowers skill repository (14 skills), Camoufox stealth browser |
| **Disk-safe logging** | Multiple layers of log rotation and disk monitoring — no more disk fill surprises (see [Disk Safety](#-disk-safety-v210)) |
| **Zero external deps** | Only `aiohttp` (and optional `psutil`) — everything else is Python stdlib |
| **One-click uninstall** | `uninstall.bat` / `uninstall.sh` — clean removal of services and files |

### 🆕 What's new in v3.36.0

- **Readable execution failures** — extension history and inline controls now show failed tool-call output instead of `error: unknown`.
- **Cleaner AI Studio controls** — controls are attached after rendered `Jsonl` code blocks rather than inside the code-block UI.
- **Panel fallback** — if Chrome blocks `sidePanel.open()`, the side panel opens as a normal extension tab.
- Full history in [CHANGELOG.md](CHANGELOG.md).

---

## 📦 Quick Start

### 1. Download the latest release

> ⚠️ **Always download from [Releases](https://github.com/IvanSkainet/arena-agent/releases).** Branches may contain development changes during active releases. Only tagged releases are production-ready.

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
5. Ask before installing each optional component (Tailscale, SuperPowers, BrowserAct, Camoufox) — see [Optional components](#-optional-components-and-where-they-install) for what lands where
6. Register a background service (NSSM on Windows, Scheduled Task as fallback, systemd-user on Linux, launchd on macOS)
7. Rotate any oversized log files from previous runs
8. Start the bridge and verify it's healthy

> **The bridge itself stays in one folder.** Optional components are installed only after explicit consent; some of them (Tailscale, BrowserAct, Camoufox) intentionally land outside the bridge directory because they are system-wide tools. See [Optional components and where they install](#-optional-components-and-where-they-install) for the full picture.

### 3. Updating an existing installation

Re-running the installer on an existing installation is **safe and non-destructive**:

- **Never silently downgrades.** The installer reads your locally-installed version and compares it with the remote tip of your current branch. If your local version is newer than (or equal to) the remote, nothing is changed.
- **Never switches branches.** The updater fast-forwards the *current* branch only. It does not run `git checkout -B` against a hardcoded branch, so users who pinned themselves to a release branch stay on it.
- **Asks before updating.** If the remote version is newer, you get a prompt (or set `ARENA_ASSUME_YES=1` for automation). If `git merge --ff-only` would fail (diverged branches, local commits), your work is preserved and you get instructions to resolve manually.
- **Falls back gracefully.** If GitHub is unreachable, the installer keeps your local code and continues with dependency setup and service registration.

On Windows, `install.bat` additionally queries the GitHub releases API and prints an `[INFO]` line when a newer release is available - it never auto-updates, just informs you.

## 🧩 Optional components and where they install

The installer asks for explicit consent before installing each optional component. Some components are scoped to the bridge directory; others are system-wide by design (they cannot work from inside a single folder).

| Component | Where it installs | Required for | Consent prompt |
|-----------|-------------------|--------------|----------------|
| **Tailscale** | System package (`/usr/bin/tailscale` on Linux, `C:\Program Files\Tailscale` on Windows) | Recommended way to expose the bridge to the internet via Tailscale Funnel (real HTTPS, no port-forward) | Yes — installs via official script (Linux/macOS) or `winget` (Windows); requires sudo/admin |
| **cloudflared** | Inside the bridge directory (`$INSTALL_DIR/cloudflared` or `%BRIDGE_DIR%\cloudflared.exe`) | Alternative to Tailscale Funnel (Cloudflare Quick Tunnels, no account needed) | Yes — downloads ~40MB |
| **SuperPowers** | Inside the bridge directory (`skills/superpowers/`) | 14-skill agentic framework (TDD, debugging, planning) | Yes — clones from GitHub |
| **BrowserAct** | **Globally** via `uv tool` (in `~/.local/bin` or `%USERPROFILE%\.local\bin`, outside the bridge directory) | Browser automation CLI (browse, click, forms, CAPTCHAs) — the bridge calls `browser-act` via PATH | Yes — global install is required for it to work |
| **Camoufox** | **System cache** (`~/.cache/camoufox` on Linux, `%LOCALAPPDATA%\camoufox` on Windows, outside the bridge directory) | Stealth browser engine for BrowserAct (~300MB download) | Yes — required by the camoufox Python package |

### Setting up Tailscale Funnel for internet access

Tailscale Funnel is the recommended way to expose your bridge to the internet. It gives you a real HTTPS URL (like `https://your-pc.tail-XXXXX.ts.net`) with a Let's Encrypt certificate, no port-forwarding, no DDNS, no Cloudflare account.

**If you skipped Tailscale during install**, set it up in three steps:

```bash
# 1. Install Tailscale (Linux/macOS — uses your system package manager)
curl -fsSL https://tailscale.com/install.sh | sh
# On Windows:  winget install --id Tailscale.Tailscale

# 2. Log in (opens a URL in your browser — sign in with Google, GitHub, Microsoft, etc.)
sudo tailscale login         # Linux/macOS
tailscale login              # Windows

# 3. Publish the bridge (exposes http://127.0.0.1:8765 to the internet via HTTPS)
sudo tailscale funnel --bg 8765    # Linux/macOS
tailscale funnel --bg 8765         # Windows
```

After step 3, your public URL will look like `https://your-pc.tail-XXXXX.ts.net`. Use it (with your auth token) in any AI chat to drive your computer remotely.

> **Why Tailscale and not just port-forwarding?** Tailscale Funnel terminates TLS with a real Let's Encrypt cert (no self-signed warnings), works behind any NAT/firewall, and gives you a stable hostname that follows your machine across networks. The bridge's `/v1/sys/funnel` endpoint checks Funnel status; the dashboard Settings tab has a toggle for it.

### Skipping optional components

If you answer "N" to every optional component prompt, the bridge still works fully for:
- Local execution (`POST /v1/exec`)
- Memory and recall (`/v1/memory`, `/v1/recall`)
- Local browser fetch (`/v1/browser/read`, `/dump`, `/fetch`, `/head`)
- Desktop automation (`/v1/desktop/*`) — uses `ydotool`/`xdotool`, not BrowserAct
- Web dashboard at `http://127.0.0.1:8765/gui`

You only need the optional components for: remote internet access (Tailscale/cloudflared), agentic skill playbooks (SuperPowers), or anti-detection browser automation (BrowserAct + Camoufox). You can install any of them later by re-running the installer.

---

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

For a ready-to-use system prompt template, see [`docs/AI_PROMPT_TEMPLATE.md`](docs/AI_PROMPT_TEMPLATE.md).

#### Integration recipes

Ready-to-use recipes for major frontends and IDE agents live in [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md), including:
- Arena Agent Mode
- Claude / generic custom-tools chats
- Cursor
- Cline
- Windsurf
- Open Interpreter
- Local model backends (Ollama / OpenRouter / Groq / Together)

#### Using with Arena Agent Mode

[Arena.ai](https://arena.ai/) Agent Mode gives you free access to frontier AI models (Claude Opus, GPT-5, Grok, etc.) that can call tools. You can use Arena Unified Bridge as the "tool backend" for Arena Agent Mode:

1. Start the bridge: `./install.sh` (or `install.bat`)
2. Note your bridge URL and token (printed at the end of install)
3. In Arena Agent Mode, paste the system prompt from [`docs/AI_PROMPT_TEMPLATE.md`](docs/AI_PROMPT_TEMPLATE.md) with your URL and token filled in
4. The AI agent can now call your bridge endpoints to execute commands, edit files, browse the web, and more

This gives you a **free, unlimited AI agent** that can drive your computer — the bridge handles security (token auth, command firewall, path sandbox), and Arena handles the AI reasoning.

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
        │   localhost:8765   (one modular Python process, thin entrypoint)       │
        │                                                                     │
        │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
        │   │ REST /v1/*   │  │ MCP /mcp     │  │ MCP /ws      │              │
        │   │ 200+ routes  │  │ Streamable   │  │ WebSocket    │              │
        │   └──────────────┘  └──────────────┘  └──────────────┘              │
        │                                                                     │
        │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
        │   │ /gui         │  │ /sse,        │  │ /gateway     │              │
        │   │ Dashboard    │  │ /messages    │  │ /run, /tool  │              │
        │   └──────────────┘  └──────────────┘  └──────────────┘              │
        │                                                                     │
        │   ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐      │
        │   │ CDP browser  │  │ Desktop API   │  │  Async Task Runner   │      │
        │   │ 36 endpoints │  │ 15+4 endpoints │  │  + Log + Disk Mon.  │      │
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
| `PATCH` | `/v1/fs/edit` | Find-and-replace in a text file (surgical edit, no re-upload). Add `"preview": true` for a non-destructive preview/confirm workflow. |
| `POST` | `/v1/fs/edit/apply` | Apply a previously previewed edit. Body: `{"preview_id": "..."}` |
| `POST` | `/v1/fs/edit/rollback` | Roll back a previously applied safe edit. Body: `{"rollback_id": "...", "force": false}` |

> **Security:** Upload, download, and edit paths are restricted to the user's home directory. Path traversal (`..`) is blocked. The bridge binary itself cannot be overwritten. File edit additionally blocks sensitive files (`token.txt`, `.env`, SSH keys, `users.json`, etc.) and requires `old_text` to be unique unless `replace_all=true`.

### Memory & Recall

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/memory` | List memory facts for a profile (default: `default`), pagination: `?profile=&offset=&limit=`; use `profile=all` to query all profiles |
| `POST` | `/v1/memory` | Set memory fact. Body: `{"profile": "default", "key": "...", "value": "...", "tags": [...]}` |
| `DELETE` | `/v1/memory` | Delete memory fact by key within a profile. Body: `{"profile": "default", "key": "..."}` |
| `GET` | `/v1/recall?q=…&top=5&profile=` | TF-scored fuzzy search scoped to a profile (or `profile=all`) |
| `GET` | `/v1/recall/digest?profile=` | Memory digest for a profile (or `profile=all`) |

### Planner

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/plan` | Build a structured execution plan from a goal. Body: `{"goal": "...", "context": "...", "constraints": ["..."], "max_steps": 8, "memory_profile": "projects/<name>"}` |
| `POST` | `/v1/react` | Run a bounded reason → act → observe loop from a goal. Body: `{"goal": "...", "context": "...", "constraints": ["..."], "max_iterations": 4, "memory_profile": "projects/<name>", "url": "https://..."}` |
| `POST` | `/v1/reflect` | Reflect on a prior run and return positives, concerns, missing evidence, confidence, and suggested next steps. |

### File Watchers

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/watch/files` | List active file watchers |
| `POST` | `/v1/watch/files` | Add a watcher. Body: `{"path": "...", "recursive": true, "patterns": ["*.py"], "label": "repo"}` |
| `DELETE` | `/v1/watch/files` | Remove a watcher. Body: `{"id": "..."}` |

> File watcher changes are emitted as `file_watch_change` events over `/v1/events`.

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

### Desktop Automation (15 endpoints + 4 control lease endpoints)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/desktop/screenshot` | Take a desktop screenshot. Query: `format=png|jpeg|webp|base64`, optional `display`, `scale`, `max_width`, `quality` |
| `GET` | `/v1/desktop/displays` | List desktop displays/outputs with global geometry for multi-monitor aware automation |
| `POST` | `/v1/desktop/click` | Click at coordinates. Body: `{"x": N, "y": N, "button": "left"}` |
| `POST` | `/v1/desktop/type` | Type text. Body: `{"text": "...", "ensure_latin": true}` (default: layout-safe typing on KDE) |
| `POST` | `/v1/desktop/key` | Press a key. Body: `{"key": "Return"}` |
| `POST` | `/v1/desktop/mouse` | Move mouse. Body: `{"action": "move", "x": N, "y": N}` |
| `GET` | `/v1/desktop/windows` | List desktop windows with optional filters for title, class, pid, display, and active state; annotates windows with display metadata when available |
| `GET` | `/v1/desktop/active_window` | Get the currently active desktop window |
| `POST` | `/v1/desktop/focus` | Focus a window by id, semantic filters, or OCR text query; supports `dry_run` target resolution before actual focus |
| `POST` | `/v1/desktop/window_action` | Move, resize, center, snap into common tiling positions, move to another display, minimize, maximize, restore, close, or toggle fullscreen on a window resolved by id, semantic filters, or OCR text query; supports `dry_run` |
| `POST` | `/v1/desktop/resolve_text_target` | Resolve OCR text into both a click target and the containing window, with optional display/window filters |
| `POST` | `/v1/desktop/text_action` | High-level OCR → target → action workflow that can resolve, focus, click, or run semantic window actions from visible text |
| `POST` | `/v1/desktop/ocr` | Run OCR on a fresh desktop screenshot and return words, full text, confidence, and bounding boxes; can be scoped to a named display |
| `POST` | `/v1/desktop/find_text` | Find text on the current desktop and return ranked matching bounding boxes plus click-ready center coordinates; can prefer or constrain matches to the active window or a named display |
| `POST` | `/v1/desktop/click_text` | Find text on the current desktop, choose the best ranked match, and click it in one step; supports active-window-aware and display-aware targeting |

> **Wayland support:** The installer auto-starts `ydotoold` for Wayland desktop automation. On X11, `xdotool` is used as fallback. Desktop click automatically activates the target window (v2.5.1+). For vision agents, prefer `GET /v1/desktop/screenshot?format=jpeg&scale=0.5&quality=80` or `max_width=1280` to reduce payload size dramatically. OCR uses the locally installed `tesseract` binary when available.

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
| `GET` | `/v1/mission/templates` | List built-in mission templates available for composition |
| `GET` | `/v1/mission/status?name=…` | Get structured status for a persisted mission |
| `GET` | `/v1/mission/report?name=…` | Read a mission report generated by the mission manager |
| `GET` | `/v1/mission/history?name=…` | Inspect run history and step-log summaries for a persisted mission |
| `GET` | `/v1/mission/lineage?name=…` | Inspect parent/child lineage, ancestors, descendants, and siblings for a persisted mission |
| `GET` | `/v1/mission/family?name=…` | Inspect the full mission family rooted at a mission chain, including members, leaves, and branch summaries |
| `GET` | `/v1/mission/catalog?q=&state=&template=&has_report=&limit=&offset=` | Filter persisted missions by lifecycle metadata and return summary stats |
| `GET` | `/v1/mission/schedules?action=&enabled=&due_only=&limit=` | List recurring mission schedules and due-state summaries |
| `GET` | `/v1/mission/schedules/state` | Read recurring mission schedule worker state |
| `POST` | `/v1/mission/compose` | Compose a planner-backed mission draft from a goal, context, and optional template |
| `POST` | `/v1/mission/propose` | Run a bounded agentic proposal flow and return a mission bundle, with optional create/run |
| `POST` | `/v1/mission/create` | Persist a composed mission draft into the local `missions/` directory |
| `POST` | `/v1/mission/run` | Run a persisted mission by mission id through the built-in mission manager |
| `POST` | `/v1/mission/rerun` | Rerun a mission, optionally only the last failed step or a chosen step |
| `POST` | `/v1/mission/recover` | Build a recovery bundle for a mission, with optional rerun and follow-up mission composition |
| `POST` | `/v1/mission/followup` | Build a next mission from an existing mission's artifacts using agentic analysis |
| `POST` | `/v1/mission/iterate` | Run a mission iteration loop that combines recovery with optional follow-up mission creation and execution |
| `POST` | `/v1/mission/schedules` | Create or update a recurring mission schedule |
| `DELETE` | `/v1/mission/schedules` | Delete a recurring mission schedule by id |
| `POST` | `/v1/mission/schedules/tick` | Manually execute due mission schedules |
| `GET` | `/v1/extension/policies` | Read browser chat extension execution policies, risk classes, and payload examples |
| `POST` | `/v1/extension/preview` | Validate and classify a structured `arena-tool` payload before execution |
| `POST` | `/v1/extension/execute` | Execute an approved `arena-tool` payload through the local bridge |

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

The dashboard at `/gui` has **16 tabs** and works in any modern browser without external dependencies (single self-contained HTML file).

| Tab | What it does |
|-----|--------------|
| **Overview** | Bridge metrics, hardware diagnostics card, full inventory drawer, disk usage |
| **Workspace** | Companion-style surface for active profile context, planner output, bounded ReAct runs, reflection, file watcher management, profile notes, important lessons, recent activity, and a mission loop studio for lineage / family / schedules / schedule-state / follow-up / iterate flows |
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
| **Control** | Desktop control lease status, pause/resume/revoke actions, and active window overview |
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
├── unified_bridge.py     ← thin compatibility/CLI entrypoint (<150 lines)
├── arena/                ← modular bridge implementation
│   ├── app.py            ← aiohttp app factory
│   ├── routes.py         ← route registry facade
│   ├── route_registry/   ← route groups by domain (core, CDP, desktop, v2, MCP)
│   ├── contexts/         ← handler dependency dataclasses grouped by domain
│   ├── wiring/           ← composition/wiring helpers and legacy compatibility setup
│   ├── browser/          ← browser fetch, high-level browse and CDP modules
│   ├── desktop/          ← screenshots, input, windows, KWin/Wayland helpers
│   ├── service/          ← service status, capabilities, restart helpers
│   ├── system/           ← sysinfo, doctor, sound, legacy hwinfo fallback
│   ├── memory/           ← SQLite/FTS memory store and recall handlers
│   ├── skills/           ← skill registry, install/uninstall/run/cache
│   ├── tasks/            ← task queue and background runner
│   ├── observability/    ← metrics, audit, logs, alerts, tracing
│   ├── admin/            ← token, Tailscale Funnel, cloudflared tunnels
│   ├── mcp/              ← MCP tools and transports
│   └── ...               ← gateway, grpc, tls, sandbox, cluster, resources
├── token.txt             ← your auth token (auto-generated)
├── install.bat           ← Windows installer (run this)
├── install.sh            ← Linux/macOS installer (run this; re-run to update)
├── uninstall.bat/.sh     ← clean removal of service + files
├── docs/                 ← architecture notes, stress-test guide, AI prompt template
├── dev/                  ← release/stress tooling (`stress-test-v4.py`)
├── bin/                  ← user-facing CLIs (agentctl, bridge-curl, etc.)
├── scripts/              ← background helpers (inventory, CDP, desktop, etc.)
├── skills/               ← AI-runnable playbooks and BrowserAct integration
├── memory/               ← local memory database/files
├── missions/             ← scripted workflows
├── queue/                ← task queue (inbox/running/done/failed)
├── reports/              ← screenshots, recordings, outputs
├── hooks/                ← pre/post skill hooks
├── agents/               ← agent configurations
├── subagents/            ← subagent spawn/track
├── tools/                ← external tools
└── mcp/                  ← MCP configuration
```

See [`AGENTS.md`](AGENTS.md), [`docs/AI_CODEBASE_NAVIGATION.md`](docs/AI_CODEBASE_NAVIGATION.md), [`docs/V3_MODULAR_ARCHITECTURE.md`](docs/V3_MODULAR_ARCHITECTURE.md), [`docs/MODULE_MAP.md`](docs/MODULE_MAP.md), [`docs/V3_RELEASE_CHECKLIST.md`](docs/V3_RELEASE_CHECKLIST.md), and [`docs/MOBILE_SUPPORT_ROADMAP.md`](docs/MOBILE_SUPPORT_ROADMAP.md) for domain maps, release gates, mobile planning, and guidance for humans and AI coding agents.

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

When in doubt, start with `unified_bridge.py` — it is the thin compatibility entrypoint, and the implementation lives in focused `arena/*` modules.

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

### v2.12.0 — Stable monolith baseline and stress-test gate
- **Changed:** `dev/stress-test-v4.py` is non-persistent by default and no longer submits queue tasks unless `--task-roundtrip` is explicitly requested.
- **Improved:** Task roundtrip now uses `echo stress-test-v4 noop`, which is valid on both Windows cmd and POSIX shells.
- **Added:** `docs/STRESS_TEST_V4.md` documents local/remote, restart, and task-roundtrip stress modes.
- **Validated:** Windows and CachyOS/KDE have both passed v4 stress checks with restart lifecycle coverage.
- **Milestone:** This release is the stable monolith checkpoint before the planned v3 modularization work.

### v2.11.6 — Linux systemd restart fix
- **Fixed:** Linux `/v1/restart` now prefers a transient `systemd-run --user` unit, avoiding cgroup cleanup killing the restart helper together with `arena-bridge.service`.
- **Kept:** Detached `.sh` restart helper remains as fallback for non-systemd Linux environments.

### v2.11.5 — Linux/macOS installer version-read fix
- **Fixed:** `install.sh` no longer references unset `$PYTHON` before Python discovery while reading the bridge version; it now uses a local `VERSION_PY` probe.
- **Improved:** `install.sh` re-executes itself under `bash` when invoked as `sh install.sh`, avoiding shell-mismatch failures.

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
- **Added:** Di
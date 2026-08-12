# arena-bridge (Skainet Bridge Skill)

Skill and protocol specification for AI agents (Arena.ai Agent Mode, Claude Code,
Codex, Cursor, and custom agentic frameworks) interacting with **Skainet Bridge**.

---

## 1. Overview & Purpose

**Skainet Bridge** is an authenticated, local-first bridge that breaks AI agents out
of restrictive sandboxes (such as Arena.ai's 128 MB snapshot cap and GPU/X11 absence)
and connects them directly to the operator's real machine, local tools, file system,
and hardware.

This skill equips agents with the exact operational protocol:
1. Connecting to the bridge (Local loopback, Tailscale Funnel, Cloudflare, ngrok, bore);
2. Bypassing sandbox filesystem limits (persistent storage on host, >128 MB);
3. Offloading heavy compute, game engines (e.g. Godot), and GPU tasks to the host;
4. Executing MCP tools and managing long-running background processes;
5. Structured task execution via Spec-Kit (T0..Tn) and Serena session recall.

---

## 2. Discovery & Connection

### Connection Transports
The bridge exposes an HTTP/REST API and an MCP (Model Context Protocol) endpoint:
- **Local host:** `http://127.0.0.1:8765`
- **Tailscale Funnel:** `https://<node-name>.ts.net`
- **Public Tunnels:** ngrok (`https://<id>.ngrok-free.dev`), Cloudflare Quick Tunnels, or bore.

### Authentication
Every request requires the master token in the Authorization header:
```http
Authorization: Bearer <TOKEN>
```
*Tip:* On first launch, `start.bat` / `start.sh` automatically generates `token.txt`
and copies the token to the clipboard.

### Diagnostics & Handshake
To verify connectivity from inside the agent sandbox:
```bash
python scripts/check_bridge.py
```
Or query endpoints directly:
```bash
# 1. Check health & version
curl -s http://127.0.0.1:8765/health

# 2. Authenticated self-descriptor (profile & active tools)
curl -s -H "Authorization: Bearer $(cat token.txt)" http://127.0.0.1:8765/v1/self

# 3. Active tunnel & external URL status
curl -s -H "Authorization: Bearer $(cat token.txt)" http://127.0.0.1:8765/v1/tunnels/status
```

---

## 3. Sandbox Escape & Large Storage Protocol

In sandboxed environments (like Arena.ai Agent Mode), the root directory `/home/user`
is strictly capped at **128 MB and 10,000 files** between messages. Exceeding this budget
causes catastrophic session truncation.

### The Bridge Storage Solution:
- **Workspace Isolation:** Temporary files during the session are written to `/tmp` (1 GB tmpfs).
- **Persistent Artifacts on Host:** Heavy files (large datasets, media assets, Godot game binaries, APKs)
  are streamed to the host machine via Bridge `/v1/files/*` or MCP filesystem tools.
- **Host Workspace Path:** Default host storage is located under `~/arena-bridge/` on the operator's PC.

```
+---------------------------+             +-------------------------------+
|  Arena.ai Sandbox         |             |  Operator Host Machine        |
|  (128 MB ephemeral snapshot|  HTTP / MCP |  (Unlimited disk, real GPU,   |
|   /tmp for tooling)       | ----------> |   Godot engine, hardware)     |
+---------------------------+             +-------------------------------+
```

---

## 4. Godot Game Production via Bridge

When building games with Godot (e.g. using `godot-game-production-skill`):
1. **Engine Execution:** Godot runs on the host machine where real display/GPU or headless binaries reside.
2. **Headless Harness:** The agent sends GDScript files to the host via Bridge, runs headless unit/smoke tests,
   and collects structured game state.
3. **Visual Frame Verification:** Visual frames and game screenshots are captured via Bridge desktop/window
   probes (`/v1/desktop/screenshot` or `/v1/desktop/window/*`) and returned to the agent.
4. **Asset Management:** 3D models (.gltf), sound banks, and texture packs live entirely on the host
   filesystem under `~/arena-bridge/projects/<game_name>/`, never bloating the 128 MB sandbox.

---

## 5. Agent Workflow & Discipline (Spec-Kit & DoD)

When acting as an autonomous maintainer or feature builder:

1. **Task Board First:** Every task is assigned an identifier from `T0` to `Tn` in `docs/TASK_BOARD.md`.
2. **Strict Definition of Done (DoD):**
   - **Root-Cause Fix:** Never silence errors with `|| true` or blanket suppressions.
   - **Isolated Parity Suite:** Deterministic unit/integration tests with mocks for external processes and sockets.
   - **Zero Mutation Survivors:** Tested against `mutmut` with 0 surviving mutants.
   - **Mandatory Bilateral Sabotage:** Intentionally breaking the fix fails tests; healthy code is 100% green.
   - **Preflight Pass:** `python scripts/preflight.py` (21 local gates) must be completely green before push.
3. **Serena Session Memory:**
   - Use Serena MCP (`serena start-mcp-server`) or session recall (`arena/agentctl_cli/agentctl_memory.py`)
     to persist architectural decisions and context across session boundaries.
   - Read `AGENTS.md` and `docs/TASK_BOARD.md` at the beginning of every turn.

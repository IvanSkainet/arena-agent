# Changelog

## v2.11.3 — 2026-06-10

### Added
- Added `/v1/capabilities`, a stable agent-facing map of available OS/service/browser/desktop/hardware capabilities and selected backends.

### Improved
- Windows installer version detection now uses `_arena_helper.py` / `arena/constants.py`, fixing `Bridge vunknown` after the version constant moved out of `unified_bridge.py`.
- Windows install health verification now prints the actual `/health.version`.
- Windows CIM/PowerShell inventory probes force UTF-8 output and normalize common CIM date formats.
- Windows service/status endpoints distinguish stale stopped services from active Scheduled Tasks and include command lines for bridge-related Python processes.

### Tests
- Added regression coverage for installer helper version detection and `/v1/capabilities` route registration.

## v2.11.2 — 2026-06-10

### Fixed
- `/v1/skills/uninstall` now accepts safe third-party skill basenames beginning with `_`, so it can remove every safe `third_party/<name>` entry that `/v1/skills` can list while still rejecting traversal and core/category skills.

### Tests
- Added regression coverage for underscore-prefixed third-party skill names.

## v2.11.1 — 2026-06-10

### Improved
- `/v1/hardware` now exposes additional read-only device context: physical/block storage devices, PCI/PNP devices, USB devices, and thermal/sensor facts where available.
- KDE Plasma Wayland window discovery no longer depends on `QFile` inside KWin scripting. The script now prints tokenized JSON to the user journal, which the bridge reads back, and still falls back to `wmctrl`/`xdotool`.

### Fixed
- `/v1/skills/uninstall` now accepts the same third-party names returned by `/v1/skills` (`third_party/<name>`) as well as bare third-party names, while rejecting core/category skills and path traversal.

### Removed
- Removed the broken test-only `skills/third_party/weather` skill from the production tree.

### Tests
- Added regression coverage for hardware device sections and third-party skill-name normalization.

## v2.11.0 — 2026-06-10

### Added
- Added `/v1/hardware` as the canonical rich hardware/system inventory endpoint. It is backed by `scripts/inventory.py`, returns normalized JSON for agents and GUI consumers, and keeps `/v1/hwinfo` as a backward-compatible alias.
- Added short `/v1/cdp/*` aliases for the existing `/v1/browser/cdp/*` endpoints to reduce agent/tool 404s when shorter CDP paths are inferred from docs.

### Improved
- Unified the old split hardware collectors: motherboard/BIOS, CPU, memory modules, GPU/NVIDIA telemetry, disks, network, displays, runtimes, package managers, and browsers now come from one inventory source.
- `/v1/desktop/windows` now tries native KDE/KWin scripting on Plasma Wayland before falling back to `wmctrl` and `xdotool`, improving Wayland window discovery without requiring `kdotool`.
- `/v1/browser/cdp/session/check` now returns HTTP 200 with `connected: false` and actionable details when CDP is disconnected, instead of treating the normal disconnected state as a malformed request.
- Runtime version probing is quieter for tools such as `lua` and partial `dotnet` installs.

### Fixed
- Fixed Windows CIM inventory collection: `_get_cim_json()` no longer calls `_run(..., shell=True)` on a helper that did not support `shell`, which previously caused Windows hardware sections to silently return empty data.
- Fixed Windows display inventory (`screens` was referenced before assignment) and expanded Windows logical disk/GPU/RAM CIM property selection.

### Tests
- Added regression coverage for the inventory runner, noisy version filtering, and hardware normalization/NVIDIA merge path.

## v2.10.3 — 2026-06-08

### Security
- Hardened `arena/security.py::_validate_url` against SSRF bypasses in browser fetch endpoints (`/v1/browser/read`, `/dump`, `/fetch`, `/head`).
- Blocked obfuscated internal hosts including `127.1`, octal IPv4 (`0177.0.0.1`), decimal integer IPv4 (`2130706433`), hex IPv4 (`0x7f000001`), IPv4-mapped IPv6 loopback, and `localhost.localdomain`.
- Blocked metadata/internal hostnames such as `metadata.google.internal`, bare `metadata`, `.internal`, and `.local` names.
- Added DNS resolution defense-in-depth: every A/AAAA result is checked for private, loopback, link-local, reserved, multicast, or unspecified addresses before fetch.

### Tests
- Added regression tests for the reported SSRF bypass payloads.

## v2.10.2 — 2026-06-08

First release built with CI, an expanded test suite, and safe-by-construction
release packaging. No runtime feature changes — focused on correctness,
security of the release process, and developer experience.

### Fixed
- `scripts/mcp_stream_server.py`: added missing `import shutil` — the browser
  screenshot tool called `shutil.which()` without importing it, which would
  raise `NameError` when invoked (found by the new lint pass).
- `unified_bridge.py`: import `Dict`/`Optional` from `typing` (referenced in
  annotations but never imported) and removed a redundant local `urlparse`
  import.

### Security
- **Release packaging is now safe by construction.** `scripts/pack_release.py`
  previously could include `token.txt`, `users.json`, `audit.jsonl`,
  `requests.jsonl`, and root-level `bridge.log` in the public release archive.
  It now ships only git-tracked files (sensitive files are git-ignored) plus an
  explicit `cloudflared` bundle and runtime-dir placeholders, and asserts the
  archive contains no sensitive names before finishing.

### Tests / CI
- Added GitHub Actions CI: pytest on Python 3.10–3.13 plus a ruff lint pass
  (critical correctness rules enforced as blocking; full rule set informational).
- Added `tests/test_security.py` (60 tests) covering the safety-critical
  surface: command blocklist, desktop-input-injection guard, SSRF validation,
  audit redaction, token generation, and Bearer auth.

### Developer experience / repository hygiene
- Removed the bundled ~39 MB `cloudflared` binary from version control; the
  installers now fetch the platform-correct binary on demand.
- Added `requirements.txt` and `pyproject.toml` (explicit dependencies, ruff &
  pytest configuration); installers install dependencies from `requirements.txt`.
- Added `.editorconfig` and `CONTRIBUTING.md`.
- Moved `AI_PROMPT_TEMPLATE.md` to `docs/` and `stress-test-v3.sh` to `dev/`;
  corrected the README structure section to match the real layout.

## v2.10.1 — 2026-06-08

### Installer transparency / anti-false-positive
- `install.bat` and `install.sh` now show a prominent background-service transparency notice before registering/updating any background service, scheduled task, systemd unit, or launchd agent.
- Installers now require explicit confirmation before service registration. Use `ARENA_ACCEPT_BACKGROUND=1` or `ARENA_ASSUME_YES=1` for unattended automation.
- README documents expected background processes and legacy helper names (`local_bridge.py`, `mcp_ws_server.py`, `web_gateway.py`, `agentctl task-watch`), plus PowerShell/Linux/macOS inspection and cleanup commands.
- Runtime bridge version bumped to `2.10.1` so `/health` and `/v1/version` identify this release.

## v2.10.0 — 2026-06-08

### Fixed
- Closed the control-lease bypass where `/v1/exec` could still inject desktop input while control was paused/revoked by blocking input-injection tools (`ydotool`, `xdotool` key/mouse/type, `wtype`, `dotool`, etc.) under a paused/revoked lease while keeping non-input shell diagnostics available.
- Made `/v1/desktop/screenshot` honor `format`, `scale`, `max_width`, and `quality` parameters. The endpoint can now return JPEG/WebP/downscaled images instead of always returning full-size PNG.
- Hardened `/v1/exec` safety patterns against obvious secret reads and reverse-shell payloads (`~/.ssh/id_*`, `.netrc`, `.git-credentials`, `.aws/credentials`, `token.txt`, `/etc/shadow`, `/dev/tcp`, `nc -e`, etc.).
- Made `/v1/desktop/type` more reliable on KDE/Wayland with `ensure_latin` (default `true`), switching the keyboard layout to the first/Latin layout before typing to avoid RU/other-layout keycode corruption.
- Added `/openapi.json` as an OpenAPI alias to improve API discoverability, and documented the new desktop screenshot/type parameters.

### Documentation / transparency
- Added a prominent README section explaining expected background processes, Windows scheduled tasks/services, legacy helper names, and manual cleanup commands so the project is not mistaken for malware.
- `install.bat` and `install.sh` now show an explicit background-service transparency notice and require confirmation before installing/updating the service. Set `ARENA_ACCEPT_BACKGROUND=1` or `ARENA_ASSUME_YES=1` for unattended automation.

### Notes
- `owner-shell` remains a trusted/local-owner profile; these safety patterns reduce common foot-guns but are not a substitute for a sandbox or least-privilege deployment.
- For vision agents, recommended screenshot parameters are now `format=jpeg&scale=0.5&quality=80` or `format=jpeg&max_width=1280&quality=80`.

# Arena Agent Codebase Guide for AI Maintainers

This repository is intentionally modular. Do not add new runtime logic to thin
compatibility entrypoints or large catch-all files.

## Hard rules

**Architecture**

- Keep `unified_bridge.py` a thin compatibility/CLI entrypoint.
- Keep wrapper scripts in `scripts/` and `bin/` thin; real logic belongs under `arena/`.
- Product files must stay under the modularity limit enforced by
  `tests/test_project_modularity.py` (**currently 700 lines**). Runtime modules
  under `arena/` have an additional limit in
  `tests/test_architecture_boundaries.py` (**currently 600 lines**).
  Readable code beats squeezed code — if a file is close to the limit,
  split it by responsibility instead of collapsing whitespace.
- Do not import `unified_bridge.py` from `arena/*` modules.
- Every new module in `arena/admin/` (tunnels/network providers) must be
  cross-platform: `platform.system()` branches, no Linux-only assumptions,
  never invoke `sudo` directly.
- Every user-facing installer path (`install.sh`, `install.bat`) must
  **verify** after installing dependencies — never trust a silent
  `pip install ... 2>/dev/null || true`.
- Never store per-release scratch notes in the repository; use `/tmp/` when
  driving `gh release create --notes-file`.

**Security (added v4.46.0 -- these are non-negotiable)**

- **Every change must pass `make security-scan` locally before commit.**
  The same three gates (bandit / semgrep / pip-audit) run in CI and will
  block the push regardless. Local iteration is faster.
- **Never delete a `# nosec` or `# nosemgrep` annotation without also
  verifying the underlying finding is genuinely no longer applicable.**
  Each existing annotation carries a specific-rationale comment; if you
  refactor the line and the annotation is stale, remove it and re-run
  the scan to confirm the rule no longer fires. If it does fire, either
  fix the finding or write a new annotation with a fresh rationale.
- **New `# nosec` / `# nosemgrep` in a PR requires a rationale after
  the marker** in the shape `# nosec B602 -- <who feeds this input,
  why the shell/whatever is safe here>`. Reviewers grep for the
  rationale text; a bare `# nosec` will bounce.
- **Never inline a credential-shape string as a test fixture** (raw
  `ghp_...`, `xoxb-...`, `AKIA...`, etc.). GitHub secret-scanning push
  protection will reject the commit even for legitimate redaction-test
  fixtures. Build the fixture at runtime via concatenation
  (`"ghp" + "_" + suffix`) — this is the pattern in
  `tests/test_observability_redact.py` and
  `tests/test_audit_value_redaction.py`.
- **Never use `tempfile.mktemp()`** — TOCTOU-racy since Python 2.3.
  Use `tempfile.NamedTemporaryFile(delete=False)` for a single file or
  `tempfile.mkdtemp()` (which returns 0o700) when a downstream tool
  needs to create the file itself.
- **Never use bare `zipfile.ZipFile.extractall()`** — route through
  `arena.files.safe_extract.safe_extract_zip()` which does the
  pre-scan for zip-slip / symlinks / zip-bomb.
- **Never use `os.system()`** — always argv-form
  `subprocess.run([...], check=False)`. `shell=True` is allowed only
  for CLI-side helpers (operator-fed input) with a per-line
  `# nosec B602 -- <specific rationale>` naming who feeds the string.
- **Redaction lives in one place**:
  `arena/observability/redact.py`. If you add a new credential shape,
  extend `_VALUE_PATTERNS` there AND add a test in
  `tests/test_observability_redact.py`. Never inline the regex in a
  new emit site.
- **Any new HTTP handler that takes a numeric query/body parameter**
  must use `arena.handler_helpers.safe_float()` or `safe_int()`, not
  raw `float()` / `int()` — that closes the NaN/±Inf-injection class.
- **File-mode discipline** on anything under `~/.arena/`,
  `~/arena-bridge/`, or tempfile paths: `chmod 0o600` on files,
  `chmod 0o700` on directories, and re-apply after `rename()` because
  some filesystems reset the mode across rename (ACL-proof pattern
  established in `arena/agentctl_cli/url_cache.py::save`).

See [SECURITY.md](SECURITY.md) for the full threat model and
env-variable reference. [CONTRIBUTING.md](CONTRIBUTING.md) has the
"Security-sensitive areas" section pointing at every file that carries
one of these invariants.

## Where things live

Core:

- HTTP app and routes: `arena/app.py`, `arena/routes.py`, `arena/route_registry/`
- Request contexts: `arena/contexts/`
- Service lifecycle/status/restart: `arena/service/`
- Runtime composition wiring: `arena/wiring/*`
- Runtime dependency namespace for the facade: `arena/runtime_deps/*`

Domain modules:

- Admin / tunnels / auth: `arena/admin/`
  - `tunnels.py` — unified multi-provider facade
    (`tunnels_status`, `tunnels_active`, `tunnels_start`, `tunnels_stop`)
  - `tailscale.py` — Tailscale Funnel primitives
  - `cloudflared.py` — Cloudflare Quick Tunnel with platform-aware hints
  - `zerotier.py` — cross-platform ZeroTier (HTTP API + CLI fallback)
  - `browseract.py` — cross-platform BrowserAct CLI status
  - `sync_factories.py` — sync-callable factories for handler wiring
  - `handlers.py` — HTTP handlers for `/v1/{sys,tunnels,zerotier,cloudflared,tailscale}/…`
- Capabilities map: `arena/capabilities.py`, `arena/service/capabilities.py`
- Desktop automation: `arena/desktop/`
- Browser / CDP handlers: `arena/browser/cdp/`
- Low-level CDP client: `arena/browser/cdp_client/`
- Inventory / hardware probes: `arena/inventory/`
- Memory and recall: `arena/memory/`
- Skills registry: `arena/skills/`
- MCP transports/tools: `arena/mcp/`
- Dashboard handlers / templates: `arena/gui/`, `dashboard/assets/`
- CLI wrappers / implementations: `bin/*` wrappers and `arena/*_cli/` packages

Skill packages (vendored, cross-platform):

- `skills/superpowers/` — upstream mirror of
  [obra/superpowers](https://github.com/obra/superpowers) (single directory
  serves both Bridge `/v1/skills` and IDE plugin consumers; see
  `docs/SUPERPOWERS.md`)
- `skills/browseract/` — Arena wrapper around `browser-act-cli`
  (cross-platform Python `run.py` + legacy bash shim `run.sh`)

## Validation before pushing meaningful changes

```bash
python -m py_compile scripts/*.py bin/*.py arena/**/*.py
python -m ruff check . --select F821,F811
pytest -q

# NON-NEGOTIABLE: security gate. Same three checks CI enforces on push.
make security-scan
```

Skipping `make security-scan` because "it's just docs" is a common
temptation and always wrong -- the scan is fast (~30 s bandit + ~30 s
semgrep + ~5 s pip-audit on a warm cache) and it catches new nosec
markers that need rationales, plus fresh CVEs in deps that landed
between your last pull and now.

For live bridge changes, also run endpoint smoke and
`dev/stress-test-v4.py --restart`.

For remote-access / provider work, verify the live surface:

```bash
curl -sH "Authorization: Bearer $(cat token.txt)" \
  http://127.0.0.1:8765/v1/tunnels/status | jq
curl -sH "Authorization: Bearer $(cat token.txt)" \
  http://127.0.0.1:8765/v1/capabilities | jq '{network, browser}'
```

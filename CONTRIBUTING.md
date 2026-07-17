# Contributing to Arena Unified Bridge

Thanks for helping improve Arena Unified Bridge.

This project is a local automation bridge. Changes can affect command execution,
file access, browser control, desktop automation, and browser-extension behavior,
so small, well-tested patches are strongly preferred.

## Development setup

```bash
git clone https://github.com/IvanSkainet/arena-agent.git arena-bridge
cd arena-bridge
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"
```

Run the bridge locally:

```bash
python unified_bridge.py serve
# default: http://127.0.0.1:8765
# credential file: token.txt
```

## Tests

Full test suite:

```bash
pytest
```

Targeted checks for browser-extension work:

```bash
pytest -q tests/test_chat_extension_assets.py tests/test_chat_extension_adapter_flow.py tests/test_chat_extension_sidepanel_flow.py tests/test_extension_bridge.py tests/test_project_modularity.py
for f in background content parser adapters insert_strategies insert_history adapter_sites popup settings sidepanel; do
  node --check "chat_extension/$f.js"
done
```

Targeted checks for remote-access / provider work (tunnels facade, ZeroTier,
Cloudflared, BrowserAct, Superpowers layout):

```bash
pytest -q tests/test_tunnels.py tests/test_zerotier.py tests/test_cloudflared.py \
          tests/test_browseract.py tests/test_superpowers_layout.py
```

Installer smoke (both must be syntax-clean before touching a release):

```bash
bash -n install.sh
# On Windows the equivalent is: cmd /c "call install.bat /?" — smoke only, does not install.
```

Python syntax smoke:

```bash
python -m py_compile arena/constants.py unified_bridge.py _arena_helper.py
```

If `ruff` is available:

```bash
ruff check .
```

## Security scan (required before push)

CI enforces three security gates on every push and PR — bandit, semgrep
(9 rule packs), and pip-audit. Run the same three locally before pushing:

```bash
make install-security-tools   # one-time: bandit + semgrep + pip-audit
make security-scan            # umbrella target
# or, for iteration:
make security-bandit
make security-semgrep
make security-pip-audit
```

The gates:

- **bandit**: 0 HIGH and 0 MEDIUM findings required. LOW is tolerated as
  code hygiene (`try/except pass`, `subprocess-without-shell`,
  `partial-path`). If bandit flags a legitimate line as HIGH/MEDIUM, add
  a per-line `# nosec <ID> -- <specific rationale>` comment naming who
  feeds the input and why the check is safe.
- **semgrep**: 0 findings across `p/python`, `p/security-audit`,
  `p/owasp-top-ten`, `p/cwe-top-25`, `p/insecure-transport`,
  `p/command-injection`, `p/xss`, `p/secrets`, `p/gitleaks`. False
  positives get an inline `# nosemgrep: <rule> -- <rationale>`.
- **pip-audit**: 0 CVEs in runtime + `full` extras deps. If a CVE is
  reported, upgrade the pinned dep in `pyproject.toml` before merging.

Because CI and the Makefile both call `scripts/security_gate.py`, "passes
locally" == "passes in CI". If you're touching security-sensitive code
(auth, path validators, subprocess call sites, TLS, redaction rules,
extraction, deserialization), also read [SECURITY.md](SECURITY.md) first
— it lists the threat model each defence covers so you know which
invariant your change must preserve.

## Browser extension workflow

1. Edit files in `chat_extension/`.
2. Keep content script order in `chat_extension/manifest.json` intentional.
3. Run the targeted extension tests and `node --check` commands above.
4. Reload the unpacked extension in Chromium/Chrome.
5. Refresh active chat tabs so MV3 content scripts are not stale.

When changing insertion behavior, smoke-test at least:

- ChatGPT;
- Claude;
- Gemini Web;
- Google AI Studio.

Use sidepanel Scan Page diagnostics to verify adapter, composer type, and active
manifest/content/insert script versions.

## Versioning

Bridge version lives in:

- `arena/constants.py`;
- `pyproject.toml`;
- README/CHANGELOG when relevant.

Extension version lives in:

- `chat_extension/manifest.json`;
- `chat_extension/README.md`;
- tests that assert the manifest/readme version.

If content-script diagnostics change, also update:

- `ARENA_CONTENT_SCRIPT_VERSION` in `chat_extension/content.js`;
- `arenaInsertScriptVersion()` in `chat_extension/insert_strategies.js`.

## Release packaging

See [RELEASE.md](RELEASE.md). Release ZIPs should be built from tracked files and
must not include runtime state, credentials, logs, databases, or keys.

## Security-sensitive areas

Be especially careful with changes touching:

- **Authentication** (`arena/auth/*.py`) — Bearer-credential handling,
  rate-limit, `hmac.compare_digest`, multi-agent token registry.
- **`/v1/exec` and command safety patterns** (`arena/exec/*.py`) —
  guarded command execution, injection blocklist.
- **File upload/download/edit path checks**
  (`arena/files/sandbox.py`) — sensitivity check must run BEFORE
  existence check to close the exists-vs-blocked side channel
  (v4.42.1). New sensitive-file classes go into
  `SENSITIVE_FILE_BASENAMES` (basename) or `SENSITIVE_DIR_PREFIXES`
  (directory tree) with a test in
  `tests/test_files_sandbox_v442_hardening.py`.
- **Archive extraction** (`arena/files/safe_extract.py`) — always
  use `safe_extract_zip()`, never bare `ZipFile.extractall()`.
  `# nosec` around the raw call means an audit finding will be
  reintroduced.
- **TLS + certificate pinning** (`arena/agentctl_cli/tls.py` +
  `arena/agentctl_cli/pinning.py`) — strict-verify is the default;
  any new call site must route through `build_ssl_context()` /
  `build_pinned_opener()`, not construct its own `ssl.SSLContext`.
- **Redaction rules** (`arena/observability/redact.py`) — the
  regex battery is the shared source of truth for audit + request
  log + future sinks. When adding a new credential shape, add its
  regex here plus a test in `tests/test_observability_redact.py`.
- **Desktop automation** pause/resume/revoke controls
  (`arena/desktop/*.py`).
- **Extension auto-execution policy**.
- **Release packaging exclusions** (`scripts/make_release_zip.py`) —
  runtime state, `token.txt`, credentials, logs, databases, keys
  must never be included.
- **Installer pip strategies** (`install.sh` / `install.bat`) — never
  silently swallow `pip install` failures; always **verify**
  `import aiohttp` after the last strategy runs.
- **Tunnel-provider modules**
  (`arena/admin/{tunnels,tailscale,cloudflared,zerotier,ngrok}.py`) —
  never invoke `sudo` directly, keep platform detection explicit,
  degrade gracefully on hosts where a provider is absent.

Every one of these has a corresponding test in `tests/`; if you
change the module, run at least the targeted tests plus
`make security-scan` before opening the PR.

Report security issues privately (see [SECURITY.md](SECURITY.md)) instead
of opening a public issue.

## Pull requests

- Keep each PR focused on one concern.
- Include tests or explain why tests are not practical.
- Update docs when behavior changes.
- Prefer clear, direct commit messages.
- Do not commit local credentials, runtime logs, generated databases, or release ZIPs.

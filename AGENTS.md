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

## Verification doctrine (v4.153.3+)

**GREEN ≠ WORKS.** A passing suite proves only that the tests passed;
a green CI check is a sensor reading, not flight status. Success means
an observer sees the real thing work.

- **Verify by execution, not by reading.** Before claiming "done", run
  the real artifact end-to-end: build the wheel, install it into a
  CLEAN environment, import it, run the thing. A claim without an
  execution transcript is a hypothesis.
- **Fix the root cause, never the symptom.** Silencing a check
  (allowlist entries, `|| true`, weakened gates, dismissed alerts)
  requires a written justification in the commit message of why the
  finding is genuinely a false positive.
- **Beware fail-open.** Pipelines (`cmd | tail`, `|| true`) and missing
  artifacts have repeatedly hidden real failures here. Scripts must
  fail CLOSED: missing lock entry, missing file, unexpected exit code =
  abort, loudly.
- **A gate that is always green is suspicious.** Ratchets and contracts
  exist to be occasionally red. Negative-test the gate itself when you
  build one.
- **Sabotage every new gate before you claim it works.** Deliberately
  reintroduce the bug the gate was written for, confirm the gate fails,
  then restore. A gate that has never been observed failing is a
  decoration. This is mandatory, not a suggestion.
  - Restore with `git checkout --` or a fresh write, then delete
    `__pycache__`: copying a backup file back with `cp` preserves its
    mtime, so Python happily keeps serving the *mutant* `.pyc`. That
    cost an hour once — the source read correctly while the imported
    module was still the sabotaged one.
  - Do not rely on this rule alone. Measured 2026-08-04: 406 test files
    existed, six mentioned sabotage, and this document did not contain
    the word. A rule that depends on remembering is not enforcement,
    which is why `scripts/mutation_gate.py` now checks it mechanically.

- Scanners check *pattern classes*, not *product invariants*. The worst
  historical bugs of this repo (broken `pip install` during a green CI,
  dropped Python-3.10 marker deps) were caught only by end-to-end
  execution on the real environment matrix — that is why the blocking
  `Packaging E2E` CI job and the pre-flight install ritual exist.

## Static analysis before you finish (v4.157.0+)

Both debt gates are at **zero** as of v4.156.0. Zero is a state that has to
be actively kept: the Debt visibility CI job turns red on the FIRST new
finding, so a single unchecked commit undoes the whole cleanup.

Before completing any task that creates or modifies files, run the checks
that apply to what you touched:

```bash
ruff check .                            # must print "All checks passed!"
python scripts/lint_ratchet.py --fail-on-any     # must print LINT DEBT ZERO
python scripts/quality_ratchet.py --fail-on-any  # must print QUALITY DEBT ZERO
python scripts/js_lint_ratchet.py       # only if you touched .js
```

Scope as of v4.157.0: **ruff covers the whole tree** (`TARGETS = (".",)`),
pyrefly covers `arena`, `scripts`, `bin`, and oxlint covers `dashboard/assets`
plus `chat_extension`. Every one of them is at zero.

The scope grew in two steps and the reason is worth keeping: `scripts/` and
`bin/` are shipped by `make_release_zip.py`, and `unified_bridge.py` is the
main entry point — a gate that excludes those is a preference, not a gate.
`"."` rather than a list so a new top-level file lands inside the gate by
default instead of silently outside it.

If anything is reported, fix ALL of it and run again to confirm zero. Do not
finish the task on a non-zero count, and do not buy the number with
`# type: ignore`, `# noqa` or a looser preset — see `docs/pyrefly_debt.md`
for why `preset = "basic"` is forbidden even though it would show fewer
findings.

Adopted from Pyrefly's "Adding Pyrefly Type Checking to Your Agentic Loop"
(2026-08). Their point applies exactly here: the tool being installed is not
the same thing as the habit of running it, and only the second one keeps the
count at zero.

## Ratchets and reproducibility (v4.153.3+)

- **Lint ratchet**: `python scripts/lint_ratchet.py` blocks growth of
  per-rule ruff counts vs `scripts/lint_baseline.json`; after cleanups,
  regenerate the floor with `--write-baseline` in the same commit.
- **Quality ratchet**: `python scripts/quality_ratchet.py` does the
  same for vulture/pyrefly per-kind counts vs
  `scripts/quality_baseline.json`.
- **import-linter contracts** (pyproject) are BLOCKING. Never declare a
  contract that does not already hold — verify with `lint-imports`
  locally first.
- **Never bulk-apply ruff `F401`/`F841` auto-fixes**: imports here
  double as re-exports and monkeypatch-by-name targets. Analyze the
  importers of a name before deleting it.
- **Debt layers are cleared with AST-proven tools, never by hand or by
  blind regex.** `scripts/e702_split_statements.py` is the reference
  shape: it rewrites mechanically, then accepts a file ONLY when
  `ast.dump()` is byte-identical before/after — the proof that behaviour
  cannot have drifted. Its dry run rejected two files on the first pass
  and caught real damage: rows like `else: j(...); sys.exit(1)` (inline
  suite — splitting moves `sys.exit` OUT of the branch) and rows that
  close a multi-line statement (`''').strip()); print(out)`). Rows that
  cannot be proven safe are LEFT AS DEBT, not forced. Write the tool,
  let it reject you, fix the tool.
- **Hash-locked CI installs only**: `requirements-ci.lock` (tests +
  tools), `requirements-lint.lock` (ruff), `requirements-packaging.lock`
  (build/twine/check-wheel-contents). Regenerate with the
  `uv pip compile --universal ...` command documented in each `.in`
  header, then ALWAYS verify: `python scripts/check_ci_lock.py` (uv
  0.12.1 has dropped marker-guarded pins on cold caches) followed by a
  real `pip install --require-hashes -r requirements-ci.lock` in a
  fresh venv on the OLDEST supported Python (3.10). No unpinned
  `pip install` in workflows (Scorecard gate).
- **No system-Python installs** on any machine that runs the bridge —
  isolated venvs only. Bridge connectivity: record ALL transports
  (Tailscale Funnel / cloudflared / bore) and fail over; Tailscale is
  fast but flaky, re-probe periodically.

### Debt visibility (v4.153.3+)

The blocking ratchets gate *growth*, so their green checkmark can
coexist with the full legacy backlog — and people/AI read checkmarks,
not logs. Therefore the backlog owns a dedicated signal:

- CI job **debt-visibility** (`continue-on-error: true`, NON-blocking)
  runs `lint_ratchet.py --fail-on-any` and
  `quality_ratchet.py --fail-on-any`. It is **red BY DESIGN while any
  debt remains** and turns green only at zero. This is the sanctioned
  noise route for the backlog: red there ≠ broken build; red in the
  main pipeline = broken build. Never "fix" this job's redness by
  deleting it — lower the actual debt.
- A green main pipeline therefore never means "debt-free". Check the
  debt-visibility job (or its step summary tables) for backlog numbers.

### Tier-2 E2E (v4.153.3+)

- `tests/e2e/test_bridge_live.py` spawns the REAL server process and
  drives it over HTTP/MCP (auth, health, handshake, tool call, fs
  write→read round-trip, jail refusal, abuse cases, graceful teardown).
- CI job **e2e-installed** (BLOCKING) runs the same tests against the
  built wheel installed in an isolated venv (`ARENA_E2E_SERVER_CMD`),
  i.e. it exercises the shipped artifact, not the source tree. "Unit
  tests green" is not evidence the server boots — this gate is.

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

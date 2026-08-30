# Arena Agent Codebase Guide for AI Maintainers

This repository is intentionally modular. Do not add new runtime logic to thin
compatibility entrypoints or large catch-all files.

## Hard rules

**Architecture**

- Keep `unified_bridge.py` a thin compatibility/CLI entrypoint.
- Keep wrapper scripts in `scripts/` and `bin/` thin; real logic belongs under `arena/`.
- Product files must stay under the modularity limit enforced by
  `tests/test_project_modularity.py` (**currently 1600 lines**). Runtime modules
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

**Task Board Discipline & Spec-Kit Protocol (T0..Tn) (v4.169.39+)**

- **Every action belongs to a tracked task.** Any newly discovered bug, refactoring,
  or feature must be recorded in `docs/TASK_BOARD.md` with an identifier `T0..Tn`.
  Never execute ad-hoc or unrecorded side tasks.
- **Strict Definition of Done (DoD):**
  1. *Root-cause fix:* resolve the true invariant failure, never suppress or silence.
  2. *Deterministic Parity Suite:* write isolated unit tests without unmocked sockets or clocks.
  3. *0 Mutation Survivors:* verify with `mutmut` and pin the ratchet in `scripts/mutation_baseline.json`.
  4. *Mandatory Bilateral Sabotage:* prove that breaking the fix fails tests, and healthy code is 100% green.
  5. *Preflight Pass:* `python scripts/preflight.py` must be completely green before release.
- **Sandbox Escape via Bridge:** Never download heavy engines (like Godot), 3D assets, or datasets
  into the 128 MB agent workspace `/home/user`. Route heavy workloads, game production, and persistent
  storage to the host machine via Skainet Bridge (`skills/arena-bridge/SKILL.md` and `docs/GODOT_INTEGRATION.md`).
- **Serena Continuity:** To prevent context loss across session truncations, read `docs/TASK_BOARD.md`
  and run `python scripts/serena_reminder.py` upon session bootstrap.

**Active work continuity (2026-08-16; re-check against latest operator message and Task Board)**

- **Current sequence:** finish T57 Dependabot relock acceptance, then T58
  same-artifact deployment-event identity and the confirmed issue queue. T43 game
  work remains open while upstream PR #1545 awaits Codex/Lottarend. A newer
  operator instruction always overrides this line.
- **Parallel-agent coordination:** Мост is the primary implementation/merge/release
  agent. The second agent is an independent diagnostic reviewer whose normal output
  is Issues and reproduction evidence. Treat those findings as untrusted review
  input: deduplicate and reproduce before changing code. Мост may also perform
  diagnostic tasks, owns final prioritization, and prevents competing writes or
  duplicate PRs.
- **Upstream game rules:** Lottarend explicitly permits independent findings. Prefer
  an Issue titled `[Arena AI Finding] ...`; Arena cannot assign the label itself. If
  Issue creation remains unavailable, use `IvanSkainet/The-Book-of-Eternity-Reborn`
  and PR into `StanislavSmetaninSSM/The-Book-of-Eternity-Reborn:main`. Never push to upstream
  directly. Rebase and duplicate-search first, account for the ongoing entity-
  materialization rewrite, keep diffs minimal, and leave review/approval/merge to
  Codex plus Lottarend as CODEOWNER.
- **Reviewer probation:** T52's synthetic corpus is an initial calibration, not a
  final product verdict. Keep external reviewers informational and exact-head
  triaged; `skipped`/quota errors are no signal. Measure at least 10 substantial
  real PRs before removing an App for low signal. Functional overlap is acceptable
  when it buys independent quota. Never enable required status, blind autofix, or
  automatic commits from an external reviewer.
- **Untrusted fork PRs:** inspect the complete diff, author/check provenance, and
  review surfaces before approving first-time-contributor Actions. Do not execute
  fork code with credentials; `pull_request_target` remains forbidden.

**Agent workspace hygiene (added v4.165.0 -- learned the hard way)**

An agent sandbox has a snapshot budget (128 MB / 10 000 files on Arena).
Blow it and the session starts truncating mid-generation, which reads to
the operator as "the platform is broken" rather than "the agent filled the
disk". It cost Ivan an afternoon and nearly cost the session. Rules:

- **Install tooling outside the snapshot root.** `pip install --user`
  writes to `~/.local`, which IS captured: `ruff` and `pyrefly` alone are
  57 MB of binaries. Use `PYTHONUSERBASE=/tmp/tools pip install ...` and
  put `/tmp/tools/bin` on `PATH`. The tools do not survive a snapshot
  anyway, so paying for them in the budget buys nothing.
- **Never copy the repository to work on it.** A `cp -a` of the tree for a
  background mutation sweep doubles everything. Work in `/tmp/`, or run in
  place and rely on the sweep's own dirty-tree check.
- **Check before finishing a long session**: `du -sh ~ && find ~ -type f | wc -l`.
  Anything over ~80 MB deserves a look at `du -sh ~/.*` too -- dotfiles are
  where it hides.
- `git gc --aggressive --prune=now` reclaims real space after heavy
  fetching (44 MB -> 30 MB here) and is safe on a pushed tree.
- `pip` also leaves ~19 MB in `~/.cache`; pass `--no-cache-dir` or delete
  it afterwards.

The working setup, for copy-paste at the start of a session:

```bash
export PYTHONUSERBASE=/tmp/tools PATH=/tmp/tools/bin:$PATH
pip install --user -q --no-cache-dir ruff bandit "mutmut==2.5.1" cryptography zizmor
```

Measured result: 202 MB / 4 079 files (over budget, session truncating)
became 55 MB / 1 603 files with every tool still on `PATH`.

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

## The operator can leave you messages (v4.166.0+)

There is a mailbox between you and the operator. It is not a
notification you will be shown -- **you have to look**.

```
relay.check                  # MCP tool: oldest unread message, non-blocking
relay.check(wait=25)         # block briefly when you want an answer now
relay.reply(in_reply_to=..., body=...)
relay.send(body=...)         # ask a question mid-task instead of guessing
```

**Check it at the start of a session and between long steps.** The
operator may have left an instruction while no session was running --
overnight, or during a CI wait. `relay.check` with no arguments costs
milliseconds and returns immediately when the box is empty, so there is
no reason to ration it.

**Use `relay.send` instead of guessing.** If a task hinges on a decision
only the operator can make (which release to cut, whether to delete
something), ask. A queued question the operator answers in ten minutes
beats a confident wrong turn you spend an hour on. Say plainly that you
are blocked and on what.

**Do not treat silence as agreement.** A message sits in the queue until
somebody reads it. If nobody replies, that means nobody has looked -- not
that they approved. Same rule as everywhere else here: absence of a
signal is not a signal.

Same queue as the Dashboard **Relay** tab and `bin/arena-relay`, so a
message is visible wherever the operator happens to be.

## Traps that have cost real sessions

Concrete, reproducible obstacles. Each one was diagnosed the slow way at least
once; none is guesswork.

### Test suite

- Run pytest with `--no-cov` when running a subset, or it fails on
  `Required test coverage of 46% not reached`.
- `pytest-randomly` is enabled. Order-dependent failures are real; reproduce
  with `-p no:randomly` before blaming your own change.
- Do **not** run `tests/e2e/test_bridge_live.py` through the bridge: it rotates
  the live bearer token and takes the running service down (issue #209).
- A stale, inaccessible `%TEMP%\pytest-of-<user>` makes every `tmp_path` test
  error out at once (2064 of them, in one observed run). Symptom is
  `PermissionError: [WinError 5]` inside pytest's own `getbasetemp`. Work around
  it with `--basetemp=<fresh dir>` (issue #208).
- Compare failures by **test id**, never by count, when deciding whether a
  branch regressed. Run the same command on the base commit and diff the sets.

### Gates and tooling

- `pyrefly` and `import-linter` are not installable in every sandbox, so
  `scripts/quality_ratchet.py` fails closed locally. Some findings (for example
  `bad-assignment`) can only be seen in CI -- push and read the job log.
- Never use `pytest.importorskip` for a dependency a gate relies on. If the
  package is absent the check silently vanishes, and CI reports success while
  verifying nothing. Pin the dependency in the right `requirements-*.in` and
  import it plainly.
- Locks are hash-pinned. Never hand-edit a `.lock`; regenerate with the exact
  command in its header (`uv pip compile --universal --generate-hashes
  --strip-extras --python-version 3.10 --output-file=<lock> <in>`), then run
  `scripts/check_lock_freshness.py` and `scripts/lock_conflict_ratchet.py`.
- Any new ratchet needs monkeypatched failure-branch tests. Disabling a check
  or widening a tolerance must turn the suite red -- both mutations have slipped
  through here before.

### Merging

- `master` is protected by a **ruleset**, not classic branch protection:
  `/branches/master/protection` returns 404, which does not mean "unprotected".
  Read `gh api repos/{owner}/{repo}/rules/branches/master`.
- `required_review_thread_resolution` is on, so **every** review thread -- bots
  included -- must be resolved or the merge is refused. Resolve via GraphQL
  `addPullRequestReviewThreadReply` then `resolveReviewThread`.

### Working over the bridge (Windows host)

- `/v1/exec/script` takes a raw body; interpreter, timeout and cwd come from the
  `X-Arena-Interpreter`, `X-Arena-Timeout` and `X-Arena-Cwd` headers. Without
  `X-Arena-Timeout` the server applies its 60 s default and answers 408 no
  matter how long the client waits.
- Anything running longer than about a minute drops the TLS connection. Start it
  detached (`Start-Process ... -RedirectStandardOutput`) and poll the log file.
- Distinguish the failure modes before waiting: `gaierror`/`000` is DNS,
  `Network is unreachable` is routing, `SSLEOFError` is TLS, **502 means the
  tunnel is up and the bridge process itself is down**.
- The host publishes several A records and rotates them, and sometimes returns
  only AAAA. Resolve with `AF_UNSPEC`, try every address, cache the ones that
  answer -- and always send the **hostname** as SNI even when dialling an IP, or
  TLS closes with a bare EOF.
- Quoting through PowerShell is a trap: `python -c "..."` with nested quotes,
  `gh ... | python -c`, and slicing `Select-String` results all fail. Push a
  `.py` file, run it, parse in Python.
- `git` writes ordinary output to stderr through the bridge, raising
  `NativeCommandError`. Check `exit_code`, not stderr.
- `gh` output is cp1251: capture bytes and `.decode("utf-8", "replace")`, and set
  `$env:PYTHONIOENCODING="utf-8"`.
- **Never kill host processes by image name.** `Get-Process python | Stop-Process`
  looks like it targets a stray test run; the bridge is itself a Python process,
  so it kills the bridge and every subsequent request returns 502 until an
  operator restarts it by hand. This has happened. Record the PID when you start
  something and stop that PID, or filter on `CommandLine` and exclude the bridge:
  `Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*pytest*' }`.
- Long runs must be started detached and polled through a log file; a background
  run left going will also keep rewriting the worktree under you. Have the
  detached script finish with `git checkout -- .` so the tree is clean for the
  next checkout.

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
- **A release is not done until CI is green on its tag.** Preflight runs
  on Linux only. v4.166.2 shipped with a passing preflight, a verified
  SHA, an execution transcript from the downloaded ZIP, and a live check
  on the operator's machine -- and its CI still went red on every
  Windows and macOS job, because the bug #73 fix used `os.unlink` as an
  exclusive claim and that is POSIX-only semantics. The operator found
  it before the agent did. Polling the run once and seeing
  `in_progress` is not checking; wait for the conclusion, and treat a
  release as provisional until then.
- **Platform assumptions need a Linux-runnable test.** When a fix rests
  on filesystem or OS behaviour, simulate the hostile platform locally
  (monkeypatch the syscall to behave the way Windows does) rather than
  letting the CI matrix be the only detector. Bug #75 added
  `test_the_claim_survives_a_delete_that_does_not_remove_the_name` for
  exactly this: an `os.unlink` that reports success and removes nothing.
  Where a property genuinely cannot be observed on Linux -- a shared
  rename destination is atomic here and racy on Windows -- assert the
  property directly instead of hoping a runtime test trips over it.
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

**Start here — one command, ~12 seconds:**

```bash
python scripts/preflight.py          # add --full before a release
```

It runs every gate that has actually reddened this project's CI, and fails
closed when a tool is missing (a skipped check must never read as a pass).
Measured over 25 CI runs: 12% failed, and all of them on things a local
command could have caught. CI takes ~12 minutes to say the same thing, which
is why half the recent commits here are one-line follow-ups.

Notably it runs `actionlint -shellcheck shellcheck`. Plain `actionlint` is
not enough: CI runs it *with* shellcheck, which is how SC2012 slipped through
once and cost a build.

One class it genuinely cannot catch: platform differences. A test that reads
`/proc` passes everywhere locally and fails the whole macOS matrix. Two
automated heuristics for this were tried and both produced only false
positives (documented in `scripts/preflight.py`); the defence is the CI
matrix plus writing tests against portable properties.

The longer form, still valid:

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

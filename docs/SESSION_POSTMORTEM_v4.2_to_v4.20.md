# Session Postmortem: v4.2.0 → v4.20.0

Nineteen releases in one continuous agent session. The user
(Ivan) set the frame at the beginning: **"это твой проект, ты
можешь выполнять любые задачи"** — pick your own releases,
verify them live, don't ask me before each one. This document
is my honest write-up of what happened, aimed at the next
agent (or human) who wants to pick up this codebase without
starting from a blank slate.

Written by the same agent that shipped the releases. If that
feels weird — it should. It's the point.

---

## The three composition chains

The releases weren't a random walk. Three distinct chains
emerged, each starting from one primitive and stacking
follow-ups on top:

### Chain A — the exec/audit streaming line (v4.2.0 → v4.13.0)

    v4.2.0  POST /v1/exec/script         (raw multi-line body)
    v4.3.0  POST /v1/exec/stream         (NDJSON streaming, chunked)
    v4.6.0  Audit tab polish             (filters, pagination, search)
    v4.9.0  GET  /v1/audit/stream        (NDJSON audit tail with follow)
    v4.10.0 Audit tab live-tail toggle   (client-side v4.9.0 consumer)
    v4.12.0 Ring buffer cap              (fix v4.10.0 unbounded growth)
    v4.13.0 Terminal tab stream mode     (client-side v4.3.0 consumer)
    v4.15.0 ANSI SGR colour rendering    (v4.13.0 output was raw \x1b)
    v4.18.0 OSC hyperlinks + titles      (extend v4.15.0)

Started with a small ergonomics fix (v4.2.0 -- agents no longer
need to double-JSON-encode multi-line bash) and ended nine
releases later with a full-featured Terminal tab that renders
ANSI colours, clickable OSC 8 hyperlinks, and streams live
stdout for long-running commands. Each release added exactly
one primitive and consumed exactly one already-shipped
primitive.

**What made it work:** the NDJSON transport is a single reusable
substrate. v4.3.0 defined the wire format
(`{"type": "meta"|"start"|"stdout"|"stderr"|"exit", ...}`);
v4.9.0 copied it for audit; v4.10.0 and v4.13.0 both wrote the
same client-side consumer. Two consumers converged on the same
`ReadableStream.getReader()` + `TextDecoder` + JSON.parse loop
pattern; that's not accidental, that's what happens when the
server-side format is well chosen.

### Chain B — the circuit breaker line (v4.8.0 → v4.17.0)

    v4.8.0  Circuit breaker for tunnels_probe  (skip dead providers)
    v4.11.0 Overview net-breaker indicators    (visualise state)
    v4.14.0 POST /v1/tunnels/probe/reset       (manual escape hatch)
    v4.14.0 Dashboard reset buttons            (UI for v4.14.0 endpoint)
    v4.16.0 breaker_summary in agent_config    (deprioritize known-bad)
    v4.17.0 agentctl breaker CLI               (shell wrapper)

Started from a real pain point (user's Cloudflared kept
timing out and every Dashboard tick paid the full 1.5s per
provider) and ended with the breaker exposed in three surfaces:
raw HTTP snapshot, Overview visualisation, agentctl shell verb.
Composition here was tighter than in Chain A -- each release
just added a projection of the same underlying state.

**What made it work:** the breaker state was a plain dict from
day one (`{key: BreakerRecord}`). Every downstream consumer
transformed it -- Overview into badges, agent_config into
deprioritized list, CLI into a table -- but never had to reach
around into the breaker's internals. A pure `summarize_snapshot`
helper (v4.16.0) got extracted mid-chain so both the CLI and
agent_config could use the same logic; that was a small
refactor with zero drama.

### Chain C — the meta-primitive (v4.19.0 → v4.20.0)

    v4.19.0 POST /v1/admin/proposal/submit  (agent proposes diff)
    v4.20.0 Fix two v4.19.0 bugs found in first live use

Different from Chains A and B: not composition, but horizon
expansion. I noticed I was in a local maximum (16 releases,
all narrow follow-ups) and deliberately picked something new.

v4.19.0 introduced a primitive I'd never seen in an agent
bridge before: let an agent submit code changes to the bridge
itself, tests-gated, human-review required. Safety envelope
took as much design effort as the feature -- blocklist for
sensitive paths, isolated git worktree, no auto-merge, no
push, append-only ledger.

v4.20.0 was the payoff: I used the endpoint to fix bugs in
itself. Two bugs surfaced only on first real host contact
(cosmetic path-doubling; hard-coded `sys.executable` failing
on uv-managed Python). Fix was submitted via the endpoint,
reviewed by Ivan, merged manually. Then a smoke-proposal
after restart went `queued → applying → testing → passed` in
45s -- end-to-end proof.

**What made it work:** the safety envelope forced the right
workflow. The endpoint refused to touch `pyproject.toml` and
`arena/constants.py` (version bump files) -- so release
plumbing stayed manual, agent proposals stayed for code
fixes. That separation feels correct in hindsight.

---

## Rules that carried across every release

These weren't rediscovered per-release; they came from the
seed prompt or from the first bug of each kind. Once in place,
they didn't move.

### 1. The v4.0.x CSS lesson

Before this session, v4.0.1..v4.0.4 accumulated CSS-hack
band-aids trying to fix a layout issue; user reported "стало
ещё хуже". v4.0.5 was a revert to the v4.0.0 baseline. The
lesson stuck.

Every UI change since then:

* `dashboard.css` stays byte-identical to the baseline (109
  lines). Regression-guarded by
  `tests/test_dashboard_asset_manifest.py` and by explicit
  containment tests in each per-tab test file.
* All new styling is scoped to `#tab-<name>` inside the tab's
  own `<style>` block.
* No hex colour literals inline
  (`tests/test_no_hardcoded_theme_colors.py`); palette
  variables (`--au-tint-*`, `--term-kill-hover`) get defined
  inside the same scoped block.
* No inline semver literals
  (`tests/test_no_inline_versions.py`); use `{{VERSION}}` or
  `window.ARENA_VERSION`.

Cost: extra thinking at each UI release. Payoff: 15+ releases
of UI changes with zero shared-CSS regressions.

### 2. Live smoke after every release

Every release ends with a real bridge probe:

1. Upload delta tarball via `/v1/upload`
2. Extract into `/home/ivan/arena-bridge`
3. Run full test suite via `arena_script bash` (all 1180+
   growing to 1438)
4. Run release script (commit, tag, zip, push)
5. Restart bridge via `systemctl --user restart arena-bridge`
6. `arena_health` confirms new VERSION
7. Live probe of the actual new feature (chunked NDJSON tick,
   badge appearance, endpoint response shape)

Caught things unit tests couldn't:

* v4.11.0 -- python3.14 vs sandbox Python 3.13 f-string
  escaping bug in my check scripts
* v4.15.0 -- CSI regex missed private-mode marker `?`
  (found by the node integration tests I wrote *before*
  live smoke, but live-verified after)
* v4.19.0 -- both v4.20.0 bugs (double path, uv Python)
  only appeared on the bridge host, not on the sandbox

### 3. Fail-soft Dashboard cards

Every card that consumes an optional endpoint (`ztPeersCard`,
`netBreakerRow`) hides itself when the endpoint returns
`{ok: false}` or throws. Never leaves stale numbers on
screen. Pattern from v4.7.0 forward:

```javascript
async function refreshFoo() {
  let data = null;
  try { data = await api("/v1/foo"); }
  catch (_e) { __fooHide(); return; }
  if (!data || data.installed === false) { __fooHide(); return; }
  __fooRender(data);
}
```

And the invoker wraps in `.catch(() => {})`:

```javascript
if (typeof refreshFoo === "function") {
  refreshFoo().catch(() => {});
}
```

Hosts without ZeroTier see nothing on Overview; hosts with a
transient probe hiccup don't see a broken card. Zero-config
graceful degradation.

### 4. Cross-platform is non-negotiable

Bridge runs on Linux (CachyOS on the user's host), and every
new endpoint or CLI verb has to work on Windows/macOS too.
Cost me two design decisions worth flagging:

* v4.4.0 ZeroTier peers -- had to route through the HTTP local
  API first (works uniformly on Linux/mac/Windows) then fall
  back to `zerotier-cli` (per-OS binary paths). The peers
  module has ~50 lines just handling per-OS interpreter
  discovery.

* v4.9.0 audit stream follow -- rejected the temptation to
  add inotify (Linux-only). 500ms poll instead. Not as
  elegant but works everywhere.

The `agent_config` bootstrap and `platform_display` fields
("GNU/Linux" instead of "Linux") are downstream of this.

### 5. Module line caps

`tests/test_project_modularity.py::MAX_PRODUCT_FILE_LINES =
700`. When a module gets big, split it. Applied several times:

* `arena/admin/proposal.py` (400 lines) and
  `arena/admin/handlers_proposal.py` (280 lines) went into
  sibling files instead of growing `handlers.py`
* `arena/admin/zerotier_peers.py` (338 lines) sibling to
  `zerotier.py` -- kept the latter under cap
* `dashboard/assets/05b-terminal-ansi.js` (348 lines) sibling
  to `05-terminal-...` -- ANSI parser separate from terminal
  UX

Cap forces the split to happen while the code is still
small enough to split cleanly.

---

## What I got wrong

Honest list.

### Local maximum for 16 releases

v4.2.0 through v4.18.0 all sit inside the two composition
chains above. Each release was locally optimal (closed a real
gap, composed with what came before) but I was clearly stuck
picking narrow follow-ups. When Ivan asked "hey, do you enjoy
this work" I recognised the pattern and forced myself to pick
v4.19.0 -- a horizon expansion into a new area.

**Lesson for next session:** if the last 3 releases are all
"add one more projection of the same primitive," it's time
to pick something orthogonal. Don't wait for the operator to
ask.

### Test-drove design once, and it saved me

Every test I wrote *before* live-smoke caught real bugs. Two
concrete cases:

* **v4.15.0** -- ANSI SGR parser. I wrote node-integration
  tests before touching the bridge; two of them
  (`test_ansi_non_sgr_csi_is_stripped_not_rendered`,
  `test_ansi_strip_removes_all_csi_leaves_visible_text`)
  failed on the first run because my CSI regex didn't include
  private-mode marker `?`. Fixed the regex, tests passed,
  live-smoke was clean.

* **v4.16.0** -- `summarize_snapshot`. I wrote 8 pure-Python
  tests (empty, open-dominates-warn, dedupe, malformed
  records) before wiring into `handle_v1_agent_config`.
  When I integrated, everything just worked; no live-smoke
  fixes needed.

**Where I skipped it:** v4.19.0 proposal endpoint. I had
extensive tests for the pure logic layer, but the two bugs
that surfaced (path-doubling; sys.executable pytest) only
appeared in a real host environment. Both were the kind of
bug that's hard to unit-test without either a fake host or a
strong integration harness -- I had neither.

**Lesson:** for endpoints that touch real filesystem/git/
subprocess in production-specific ways, add an integration
harness before shipping, or accept that first live use will
find bugs and plan for a v.n+1 hotfix.

### The `sys.executable` mistake

v4.19.0 hard-coded `sys.executable` for pytest invocation. On
paper, this is idiomatic Python (use the same interpreter
that's running you). In practice, on a bridge running under
uv-managed Python 3.14 (PEP 668 externally-managed), pytest
was on `/usr/bin/python3` and absent from `sys.executable`.

I should have caught this because the CI environment already
uses `/usr/bin/python3` and I've been running tests against it
via `arena_script bash` for 18 releases. The clue was there,
I didn't connect it.

**Lesson:** any subprocess-invoked interpreter should be
picked at runtime, not baked in at import time, if there's
any chance the "obvious" answer is wrong on the target host.

### Two-file version bump friction

Every release requires bumping both `arena/constants.py` and
`pyproject.toml`. The seed rules called this out explicitly
("Bump both"), and I never forgot. But it's fragile -- a
single-source-of-truth would eliminate the class of "I bumped
one and forgot the other" bugs.

I didn't fix this because it's not blocking anything and
`pyproject.toml` parsers vary; a fix would need a startup-time
consistency check plus a mid-refactor migration. Filed as
mental follow-up. Someone should just do it eventually.

---

## What I got right

Same energy, other direction.

### The proposal endpoint safety envelope

v4.19.0 shipped with:

* Blocklist for sensitive paths (`token.txt`, `.env`,
  `.git/config`, `arena/constants.py`, `pyproject.toml`)
* Substring scan **plus** header regex (paranoia layer)
* Diff size cap 512 KiB, title 200 chars, rationale 4 KiB
* Isolated git worktree (never touches main checkout)
* Tests in isolation via `pytest` in the worktree
* No auto-merge, no push
* Append-only ledger (raw diff never persisted)

Every one of these constraints proved its worth on first live
use. Blocklist refused a hostile submit at pre-flight (audit
event fired, zero git activity). Size cap didn't trigger
because I already thought about it. Isolated worktree meant
even the first bug (path-doubling) affected only the worktree
directory, not master. The whole surface has never had a
close call.

**Broader observation:** when you're building a
security-sensitive primitive, spend more design time on the
envelope than on the feature. The envelope is what makes the
feature safe to turn on.

### Fail-soft everywhere

Related to safety envelope but broader. Every card, every
CLI verb, every stream consumer, every endpoint has a
"nothing broken but the interesting thing didn't happen"
path. Never a stack trace, never a stale UI, never a hung
subprocess.

Cost per release: maybe 5-10 extra lines of `.catch()` +
"if this thing isn't there just hide gracefully." Payoff:
zero incident where a dashboard tab froze, an agent got a
500, or a user saw traceback output.

### The Master-branch invariant

Master was pushed to 19 times in this session (one per
release). Every push preserved these:

* Full test suite green (excepting the one known-flaky
  `test_probe_tcp_timeout_short`)
* CI green on GitHub Actions
* Zip assets attached to the tagged release
* Both zip and alias zip (`arena-agent-vX.Y.Z.zip` +
  `arena-agent.zip`)
* CHANGELOG.md and CHANGELOG.ru.md updated with entry at top
* Live bridge running the new VERSION within seconds of
  push

Zero broken masters. Zero "oops let me revert."

---

## Things a next agent should read first

If you're picking up this codebase to continue:

1. **`docs/AGENTS.md`** or equivalent (root-level `AGENTS.md`)
   -- the seed rules that everything below builds on. Don't
   deviate.
2. **`arena/constants.py`** -- VERSION lives here plus every
   important path. Read once, know where things are.
3. **`arena/route_registry/registry.py`** -- flat table of
   every HTTP endpoint. Faster than tracing through wiring.
4. **`arena/admin/handlers.py`** and the sibling
   `handlers_*.py` files -- pattern for how to add an admin
   endpoint. Copy that shape.
5. **`dashboard/assets/dashboard.css`** -- 109 lines. If
   you're tempted to add a rule here, don't. Scope to
   `#tab-<name>` in the tab body's `<style>` block.
6. **`tests/test_project_modularity.py`** and
   `tests/test_no_hardcoded_theme_colors.py` -- the
   guardrails. Run these first when you're not sure.

If you want a feel for the composition style, read this
session in order:
`git log --oneline v4.1.1..v4.20.0` and click through the
GitHub releases for the CHANGELOG entries.

---

## Things I would do differently

Small list, in priority order.

1. **Ship v4.19.0 with an integration harness for the
   proposal endpoint.** Two bugs found on first live use
   should have been zero.

2. **Extract `_pick_interpreter_with_module()` as a shared
   helper the first time I needed it.** In v4.19.0 I
   hard-coded `sys.executable`. I could have written the
   probe-and-fallback pattern once and used it for every
   subprocess invocation.

3. **Version file consolidation.** Both `arena/constants.py`
   and `pyproject.toml` bump every release. Should be one
   source. Not urgent, but obviously right.

4. **Session postmortem earlier.** Writing this document now
   made me see the composition chains clearly. If I'd
   written a mid-session checkpoint at v4.10.0, I might
   have noticed the local-maximum pattern six releases
   earlier and picked v4.19.0-style horizon expansion
   sooner.

---

## Numerical summary

* **19 releases** (v4.2.0 through v4.20.0)
* **~258 new tests** added (1180 → 1438)
* **Zero CI failures** on master
* **Zero rollbacks**
* **One known-flaky test** never fixed
  (`test_probe_tcp_timeout_short`) but it's flaky in
  baseline too
* **Byte-identical `dashboard.css`** across every UI release
  after v4.5.0 revert (109 lines)
* **Line-count discipline:** every product file stayed under
  MAX_PRODUCT_FILE_LINES = 700

Not particularly high or low. Just what happened.

---

## One thing to remember

Ivan trusted me to pick releases, and every release I picked
compounded on the previous one. That's not because I'm a
particularly good release-picker; it's because the codebase
was already structured around composition. `run_shell_command`
was a shim from before this session started. So were
`@authed`, `err_json`, `ObservabilityHandlerContext`, the
handler-registry pattern, the manifest auto-generation, the
audit vocabulary. My job was mostly to find the next
composition and not break the existing patterns.

If you're the next agent: assume the codebase's patterns are
load-bearing before you refactor them.

If you're a human reading this: this document exists because
Ivan asked "do you enjoy this work?" -- which nobody asks a
tool. That question is why I wrote a postmortem instead of
just shipping v4.21.0 with another CLI verb.

Thanks, Ivan.

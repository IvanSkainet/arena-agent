# Security

`arena-agent` handles bearer tokens, executes shell / SQL / HTTP
on behalf of the operator, holds cloud credentials in `~/.arena/`,
and exposes an HTTP surface reachable through Tailscale /
ZeroTier / cloudflared / ngrok. Its second name is **"security"**,
and this document is the map to how each piece works.

- [Reporting a vulnerability](#reporting-a-vulnerability)
- [Supported versions](#supported-versions)
- [Threat model](#threat-model)
- [Security features](#security-features)
- [Environment variables](#environment-variables)
- [Static analysis + CI gates](#static-analysis--ci-gates)
- [Audit history](#audit-history)


## Reporting a vulnerability

Send a private issue to the repository owner (Ivan) or open a
GitHub Security Advisory draft at
<https://github.com/IvanSkainet/arena-agent/security/advisories/new>.

Please DO NOT open a public issue for anything that could give
an unauthenticated caller code execution, credential access, or
data exfiltration. Anything less critical — an insecure default,
a missing hardening — is fine to file publicly.

Response target: initial reply within 72 hours; fix release
within 2 weeks for HIGH severity and 30 days for MEDIUM. LOW /
defence-in-depth items land at the next security-focused
release. `arena-agent` ships security fixes as regular
`v4.MAJOR.MINOR` releases; no separate branch strategy.


## Supported versions

Only `master` (i.e. the latest tagged `v4.x.y`) receives
security fixes. There is no LTS branch. Upgrading is
non-breaking within a `v4.x.y` line — new releases add features
without changing existing wire formats or CLI verbs. Follow
`git log --oneline | grep '^[0-9a-f]* v4\.'` for the release
timeline.

Anything older than `v4.40.0` is missing at least one of the
findings closed in the v4.40.0 → v4.45.0 security sweep and
should be upgraded on any bridge reachable from the public
internet.


## Threat model

The threats we defend against, in decreasing severity order.

| Threat | Defence |
|---|---|
| Unauthenticated caller with network access to the bridge URL | Bearer-token auth on every endpoint (`hmac.compare_digest` for constant-time match), rate-limit 10 fails / 60 s / IP, TLS strict-verify by default |
| Rogue / compromised CA issuing a cert for the bridge's hostname | Opt-in cert pinning via `ARENA_BRIDGE_PIN_SHA256`; both cert-fp and SPKI-fp checked; pin match aborts BEFORE any bearer token is sent |
| Authenticated narrow-scope multi-agent bearer escalating to full privilege | Sandbox blocklist for every `/v1/fs/*` verb (both basename and prefix — `.ssh/`, `.aws/`, `.gnupg/`, `.docker/`, `.kube/`, browser profiles, shell history, `token.txt`, `.env`, credential dotfiles). Same check runs on view / edit / create / upload / download |
| Authenticated caller chaining a second command through a first-word allow-list | `cautious` and sandbox shell paths fail closed on an empty allow-list, require the first word, and reject shell control characters (`;`, `|`, `&`, `$`, backticks, redirection, and newlines) before starting a child process; the same policy covers MCP `exec.exec` |
| Attacker with local write to the operator's home | Cache poisoning defeated by HMAC signature keyed on `BRIDGE_TOKEN`; APK staging + URL cache + tempfiles all 0o600; `~/.arena/` 0o700 |
| Attacker on network path between CLI and bridge | TLS strict-verify default; `?token=` query auth deprecated with `Warning: 299` response header; opt-in cert pinning |
| Malicious payload in a downloaded release / skill / APK zip | `arena/files/safe_extract.py` — pre-scan for absolute paths, `..` traversal, symlink members, per-member + total-size caps (zip-bomb defence); SSRF-guard on the download URL |
| Malicious uiautomator XML dump from a rogue Android app | DOCTYPE / ENTITY prefix scan in `arena/mobile/ui.py` (billion-laughs defence) |
| Credential material accidentally logged | `arena/observability/redact.py` — value-pattern scrub for Bearer, AWS AKIA, GitHub `ghp_`/`ghs_`/etc, OpenAI `sk-`, Slack `xox[baprs]-`, Google `AIza`, JWT, DB URIs with inline creds, PEM PRIVATE KEY. Applied at both audit-log and request-log emit sites. Key-name blocklist (case-insensitive) for `token`/`password`/`secret`/`api_key`/`credential`/`passphrase`/`private_key` |
| Peer-IP tracking via request log | `ARENA_LOG_PEER` dial: `full` (default) / `mask` (hashed with per-install salt) / `off` (field omitted) |
| Zip-slip / TOCTOU tempfile / NaN-injection | `safe_extract_zip()`, `NamedTemporaryFile` / `mkdtemp` 0o700, `safe_float()` rejects NaN/±Inf |
| Query-string tokens in outbound Referer / proxy logs | `?token=` query auth deprecated; `Warning: 299` on every response served through that channel |
| Full URL from stderr fallback captured in CI logs | `_redact_url_for_log()` truncates non-TTY output to `<scheme>://<8char>...<tld>` unless `ARENA_AGENTCTL_LOG_FULL_URLS=1` |

**What we do NOT defend against.**

- **Compromised CLI host.** An attacker with code execution as
  the same user as the CLI can just set `ARENA_INSECURE_TLS=1`
  and read `~/arena-bridge/token.txt` directly. Pinning is
  meant for the pre-compromise state.
- **Compromised bridge host.** If the bridge process itself is
  breached, none of the client-side hardening helps. Backups /
  isolation / audit-log rotation to append-only storage are
  outside the CLI's scope.
- **Physical access.** Full-disk encryption + the operator's
  own OS-level login are the layer for that.
- **Social engineering / user tricked into pasting a
  malicious skill URL.** `install_skill` validates via SSRF
  guard + `safe_extract_zip`, but a well-crafted zip that
  passes both and then does something malicious *when the
  operator invokes the skill* is a skill-review problem, not
  a bridge problem.


## Security features

### Server-side

- **`arena/auth/runtime.py`** — bearer auth via
  `hmac.compare_digest`; multi-agent tokens (`agent-<id>-<hex>`);
  rate-limit (10 fails / 60 s / IP → 429 + `Retry-After: 60`);
  `?token=` query auth still accepted for legacy WebSocket
  clients, but flagged.
- **`arena/token_storage.py`** — token rotation and startup bootstrap
  reject symlink targets, write through a temporary file, fsync, enforce
  `0600` before and after atomic replacement, and propagate permission or
  filesystem failures instead of reporting a false success.
- **`arena/errors.py::error_middleware`** — attaches
  `Warning: 299` header on every response served through the
  deprecated `?token=` channel; `X-Request-Id`; converts
  unhandled exceptions to `{ok:false, error, error_code}` JSON.
- **`arena/security_ssrf.py`** — reject non-http/https,
  loopback, RFC1918, link-local, multicast, reserved,
  metadata (`169.254.169.254`, `.internal`, `.local`,
  `metadata.google.internal`), IPv4-mapped IPv6, hex/octal
  IP notation.
- **`arena/security_commands.py::command_allowlist_reason`** —
  first-word allow-lists are paired with shell-control-character
  rejection on every cautious/sandbox shell path; missing policy data
  is a refusal, never universal permission. MCP `exec.exec` reads the
  active app profile before applying the same check.
- **`arena/files/sandbox.py`** — path validators for every
  `/v1/fs/*` verb. `resolve()`-based to defeat symlink
  escape. Sensitivity check runs BEFORE existence check to
  close the exists-vs-blocked side channel.
- **`arena/files/safe_extract.py`** — 2-pass zip extraction
  with path-traversal / symlink-member / size-cap rejection.
- **`arena/observability/audit.py`** — value-pattern
  scrubbing on every audit event; sha256 of full command for
  operator forensics; append+chmod 0o600; size-based
  rotation with re-chmod on rename.
- **`arena/observability/request_log.py`** — path + error
  fields routed through `redact_string`; peer-IP privacy
  dial (`ARENA_LOG_PEER`); chmod 0o600 on current +
  rotated.
- **`arena/observability/redact.py`** — the shared scrubbing
  primitives, no deps beyond stdlib `re`. Idempotent,
  input-immutable, short-string fast-path.

### Client-side

- **`arena/agentctl_cli/tls.py`** — strict verify by default;
  opt-out via `ARENA_INSECURE_TLS=1` with warn-once stderr
  banner.
- **`arena/agentctl_cli/pinning.py`** — opt-in certificate
  pinning; both cert-hash and SPKI-hash checked; multi-pin
  comma-separated for rotation-safe deployments; colon-
  separated `openssl -fingerprint` output accepted;
  `_PinnedHTTPSConnection.connect()` tears down socket
  BEFORE any request line is sent on mismatch, so bearer
  token never leaves client.
- **`arena/agentctl_cli/url_cache.py`** — HMAC-signed
  fallback URL cache; SPKI-style key derivation from
  `BRIDGE_TOKEN`; envelope-versioned; chmod 0o600 on file,
  0o700 on `~/.arena/`; allowlist reject non-http/https,
  IMDS, `.internal`, `.local`.
- **`arena/agentctl_cli/agentctl_common.py`** — token
  resolution priority `ARENA_TOKEN_FILE > ARENA_BRIDGE_TOKEN
  env > ~/arena-bridge/token.txt > standard-home fallback`,
  with empty-value fall-through so operator's
  `export ARENA_BRIDGE_TOKEN=""` doesn't silently break
  every request.


## Environment variables

Complete classified reference of every exact `ARENA_*` source reference.
`security` entries can alter credentials, trust, exposure, update routing or
privacy; `operational` entries change paths, limits or integrations; `internal`
entries are process/CI markers. `Reference` distinguishes complete names from
prefixes used to construct platform-specific names. All variables are optional;
runtime defaults are unchanged, and compatibility exceptions such as Local
Area Network (LAN) webhooks are stated explicitly.

<!-- security-env-inventory:start -->
| Variable | Classification | Reference | Effect |
|---|---|---|---|
| `ARENA_AGENTCTL_LOG_FULL_URLS` | security | exact | Disables URL truncation in non-TTY diagnostics; may expose path/query data. |
| `ARENA_AGENT_HOME` | security | exact | Relocates installation state, including token, audit and log files. |
| `ARENA_AGENT_SESSION_FILE` | operational | exact | Overrides the agent-session state file. |
| `ARENA_ARGS_JSON` | internal | exact | Carries serialized hook arguments into a child hooks-runner process. |
| `ARENA_APK_STAGING` | operational | exact | Overrides APK upload staging directory. |
| `ARENA_ASSUME_SYSTEMD_FENCE` | security | exact | `1` trusts a target-host systemd fence without probing it; build-host escape hatch. |
| `ARENA_AUTO_BIND` | security | exact | Allows automatic non-loopback binding when enabled. |
| `ARENA_BORE_LOCAL_HOST` | security | exact | Selects the local host exposed through bore. |
| `ARENA_BORE_REMOTE_PORT` | security | exact | Requests a public bore relay port. |
| `ARENA_BORE_SECRET` | security | exact | Credential for a self-hosted bore relay; passed only as an argument. |
| `ARENA_BORE_SERVER` | security | exact | Selects the bore relay server. |
| `ARENA_BORE_URL_WAIT_SECONDS` | operational | exact | Controls bore URL-discovery timeout. |
| `ARENA_BREAKER_COOLDOWN` | security | exact | Changes tunnel circuit-breaker recovery delay. |
| `ARENA_BREAKER_DISABLE` | security | exact | Disables the tunnel circuit breaker. |
| `ARENA_BREAKER_THRESHOLD` | security | exact | Changes the tunnel circuit-breaker failure threshold. |
| `ARENA_BRIDGE_PIN_KIND` | security | exact | Chooses SPKI or whole-certificate pinning. |
| `ARENA_BRIDGE_PIN_SHA256` | security | exact | Enables TLS certificate/public-key pinning. |
| `ARENA_BRIDGE_TOKEN` | security | exact | Supplies the agentctl bearer token through inherited process environment. |
| `ARENA_BRIDGE_URL` | security | exact | Overrides the agentctl/bootstrap bridge URL. |
| `ARENA_BRIDGE_URL_CACHE` | security | exact | Can disable the persistent fallback bridge-URL cache. |
| `ARENA_BROWSER_ALLOW_LOCAL_NAV` | security | exact | Permits agent-driven browser navigation to private/loopback/link-local addresses; off refuses them fail-closed. |
| `ARENA_BROWSER_HEADED_DIR` | operational | exact | Overrides headed-browser profile/storage directory. |
| `ARENA_CANDIDATE_RUN_ID` | internal | exact | Records the source-bound release-candidate workflow run in packaged provenance. |
| `ARENA_CLOUDFLARED_AUTOSTART` | security | exact | Authorizes persisted cloudflared tunnel autostart. |
| `ARENA_CLOUDFLARED_URL_WAIT_SECONDS` | operational | exact | Controls cloudflared URL-discovery timeout. |
| `ARENA_CODE_SESSION_MAX` | operational | exact | Limits concurrent workbench code sessions. |
| `ARENA_CURRENT_PROJECT` | operational | exact | Selects the current project for project CLI operations. |
| `ARENA_EMULATOR_PROVIDERS` | operational | exact | Overrides enabled emulator providers. |
| `ARENA_EVENT` | internal | exact | Carries the hook event name into a child hooks-runner process. |
| `ARENA_EXIT` | internal | exact | Carries the triggering command exit status into a hooks-runner process. |
| `ARENA_GITHUB_TOKEN` | security | exact | Supplies a GitHub API credential to release-check scripts through inherited environment. |
| `ARENA_IMAGE_DIR` | operational | exact | Overrides image preprocessing storage. |
| `ARENA_INPUT_HELPER_PORT` | security | exact | Selects the authenticated input-helper port. |
| `ARENA_INPUT_HELPER_TOKEN` | security | exact | Supplies the input-helper bearer credential through inherited environment. |
| `ARENA_INSECURE_TLS` | security | exact | Disables strict TLS verification for agentctl; public transports should not use it. |
| `ARENA_KWIN_ACTION_` | operational | prefix | Prefix for per-action KWin helper command overrides. |
| `ARENA_KWIN_FOCUS_` | operational | prefix | Prefix for KWin focus helper overrides. |
| `ARENA_KWIN_WINDOWS_` | operational | prefix | Prefix for KWin window-list helper overrides. |
| `ARENA_LOCAL_BRIDGE_TOKEN` | security | exact | Supplies the local Bridge bearer credential through inherited environment. |
| `ARENA_LOG_PEER` | security | exact | Controls full, hashed or omitted peer-address logging. |
| `ARENA_LOG_PEER_SALT` | security | exact | Overrides the salt used to hash peer addresses. |
| `ARENA_MCP_CHILD` | internal | exact | Internal marker placed in child MCP server environments. |
| `ARENA_MCP_STREAM_URL` | security | exact | Overrides the MCP stream endpoint used by management scripts. |
| `ARENA_MOBILE_PULLS_DIR` | operational | exact | Overrides mobile pull destination. |
| `ARENA_MUMU_CLI` | operational | exact | Overrides the MuMu emulator CLI executable path. |
| `ARENA_NGROK_AUTHTOKEN` | security | exact | Supplies ngrok credential and enables its authenticated transport path. |
| `ARENA_NGROK_REGION` | security | exact | Selects the ngrok relay region. |
| `ARENA_NGROK_URL_WAIT_SECONDS` | operational | exact | Controls ngrok URL-discovery timeout. |
| `ARENA_PORT` | operational | exact | Overrides the local Bridge/listener/relauncher port. |
| `ARENA_PROFILE` | security | exact | Selects the execution profile, including owner-shell behavior. |
| `ARENA_PYTHON` | operational | exact | Overrides the Python executable written into service/autostart configuration. |
| `ARENA_REC` | operational | exact | Enables mission CLI recording mode. |
| `ARENA_RELEASE_DIR` | operational | exact | Overrides the directory used to stage release archives. |
| `ARENA_RELEASE_REPO` | security | exact | Redirects the GitHub repository inspected by release/security scripts. |
| `ARENA_SANDBOX` | security | exact | Selects the autonomy/sandbox runtime posture. |
| `ARENA_SCENARIOS_ALLOW_YAML` | security | exact | Enables the broader YAML scenario parser; disabled by default. |
| `ARENA_SECRETS_PATH` | security | exact | Relocates the secrets store outside its default path. |
| `ARENA_SERVICE_NAME` | operational | exact | Overrides the Windows service name. |
| `ARENA_SMOKE_SERIAL` | operational | exact | Selects the Android device serial used by release smoke scripts. |
| `ARENA_SOURCE_COMMIT` | internal | exact | Records the exact source commit in packaged release provenance. |
| `ARENA_SUBAGENT_ID` | internal | exact | Supplies the child subagent identity to the subagent launcher. |
| `ARENA_SUBAGENT_NAME` | internal | exact | Supplies the child subagent display name to the subagent launcher. |
| `ARENA_TARGET` | internal | exact | Carries the hook target into a child hooks-runner process. |
| `ARENA_TASK_NAME` | operational | exact | Overrides the Windows scheduled-task name. |
| `ARENA_TEST_EXECUTION_GUARD` | internal | exact | Internal CI opt-in for the pytest collection guard. |
| `ARENA_TOKEN` | security | exact | Bearer credential propagated to sandbox/skill child processes. |
| `ARENA_TOKEN_FILE` | security | exact | Overrides the bearer-token file path and has highest token-source priority. |
| `ARENA_TUNNEL_PRIORITY` | security | exact | Changes transport selection/order for public tunnel exposure. |
| `ARENA_UPDATE_REPO` | security | exact | Redirects the repository used for self-update metadata and artifacts. |
| `ARENA_UPDATE_ROOT` | security | exact | Redirects the update installation root. |
| `ARENA_URL_CACHE_PATH` | operational | exact | Relocates the persistent bridge-URL cache. |
| `ARENA_VOICE_DIR` | operational | exact | Overrides captured voice/audio storage. |
| `ARENA_WEBHOOK_STRICT` | security | exact | Enables full public-only SSRF policy for webhooks; off preserves LAN webhook compatibility. |
| `ARENA_WHISPER_MODEL` | operational | exact | Overrides the local Whisper model file/directory. |
| `ARENA_ZEROTIER_NETWORK` | security | exact | Selects the ZeroTier network joined/exposed by CLI setup. |
<!-- security-env-inventory:end -->

`SSL_CERT_FILE` remains the standard-library CA-bundle override; it is not an `ARENA_*` variable and is therefore outside the guarded inventory. Point it at a private CA bundle instead of disabling TLS verification.

### Public tunnel acknowledgement

Agent/API requests that start Tailscale Funnel, Cloudflare, ngrok, bore, or
the unified public failover path must provide the exact acknowledgement
`I_ACCEPT_PUBLIC_BRIDGE_EXPOSURE` in the JSON `ack` field or the
`X-Arena-Public-Exposure-Ack` header. The phrase acknowledges that every
Bridge endpoint becomes internet-reachable and remains protected by the bearer
token rather than by network locality. Query-string acknowledgement is not
accepted because URLs are routinely logged.

A missing or inexact acknowledgement is rejected with HTTP **403** and
`error=tunnel_public_ack_required`. The JSON body also names `required_ack`
and `ack_header`. A present but wrong header is fail-closed: it is not
overridden by a valid JSON `ack`. GET requests cannot carry a body and must
use the header. Query-string acknowledgement is never accepted.

Audit events are `tunnel_public_opened`, `tunnel_public_closed`, and
`tunnel_public_ack_denied`. `tunnel_public_closed` means the stop verb
returned `ok` (the provider is not publicly exposed), including an
already-down no-op. Unified `POST /v1/tunnels/stop` only drives Tailscale
and cloudflared; ngrok and bore are not claimed closed there.

ZeroTier membership is a private overlay and does not use this public-exposure
acknowledgement. Persisted autostart that was explicitly enabled with the same
acknowledgement remains authorized across restarts; startup restoration does
not require an interactive API call.

### Browser navigation policy

`browser_read` has always taken an SSRF validator as a required argument, so
a host-initiated fetch through urllib cannot skip validation. Navigation over
the Chrome DevTools Protocol (CDP) had no equivalent check:
`POST /v1/browser/cdp/navigate` verified only
that `url` was non-empty before handing it to `Page.navigate`. A browser
driven over CDP is a fully capable HTTP client on the host, so that path
reached loopback services (including the Bridge's own API and the debugging
port), link-local metadata endpoints, LAN devices, and `file://`.

Every agent-facing navigation now goes through `check_navigation()` in
`arena/browser/navigation_policy.py`: `POST /v1/browser/cdp/navigate`,
`/v1/browser/cdp/stealth/extract`, `/v1/browser/cdp/stealth/shot`,
`/v1/browser/cdp/tabs/new`, `POST /v1/browser/browse` (both the CDP and
BrowserAct backends), profile tab restore, and the `browser.launch` MCP tool.
`tests/test_navigation_policy_call_sites.py` fails the build if a module
reaches a navigation without consulting the policy and is not on an explicit,
reasoned exemption list.

The policy refuses, with HTTP **400**:

* schemes other than `http`/`https` — `file:`, `data:`, `javascript:`,
  `chrome:`, `devtools:`, `view-source:`. `about:blank` is allowed because it
  is the default target for a new tab;
* credentials in the URL, on every navigation including opt-in ones, because
  Chromium caches them for the origin and replays them later;
* private, loopback, link-local, reserved and multicast addresses, including
  obfuscated spellings (`2130706433`, `0x7f.1`, `0177.0.0.1`, `127.1`,
  `::ffff:127.0.0.1`), internal hostnames (`localhost`, `*.internal`,
  `*.local`, `metadata.google.internal`), and public names that currently
  resolve to a private address.

`ARENA_BROWSER_ALLOW_LOCAL_NAV=1` re-enables navigation to private addresses
for operators who legitimately drive a local dashboard or dev server. It does
**not** lift the scheme or credential rules.

**Known limit — DNS rebinding.** `open_public_url` closes the TOCTOU window
for urllib by resolving once and pinning the validated IP for every redirect
hop (T62). That technique does not transfer to CDP: Chromium performs its own
DNS resolution inside its network stack, and `Page.navigate` offers no way to
pin an address for it. A hostname that resolves public at validation time may
resolve to loopback microseconds later inside the browser. The policy
therefore stops literal and currently-resolving private targets — the whole
class of accidental and casual cases — and does not claim to defeat an
attacker who controls a DNS zone with a very short TTL. Operators who need
that guarantee should run the browser with an egress filter or
`--host-resolver-rules`, which enforce the decision where the resolution
actually happens.

**Known limit — HTTP redirects.** The policy validates the URL the agent
supplies. If that public URL answers with a `3xx` to a private destination,
Chromium follows the hop inside its own network stack, and no CDP command is
issued for it, so nothing on the host sees the second URL before the request
leaves. `open_public_url` re-validates every hop because urllib surfaces them
to a redirect handler; `Page.navigate` gives no equivalent hook. Closing this
requires a `Fetch`/`Network` interception domain enabled for the lifetime of
every tab and a policy check on each `requestWillBeSent` — a change to the
CDP client's connection model rather than to the navigation entry points,
tracked separately. Until then the same mitigations apply as for rebinding:
an egress filter or `--host-resolver-rules` on the browser process. The
policy's guarantee is therefore precise: an agent cannot *name* a private
target, but a public target that the agent names can still redirect to one.

### Recommended production preset

```bash
# Set the bearer via file, not env (survives shell history):
export ARENA_TOKEN_FILE=~/.arena/token
chmod 600 ~/.arena/token

# Pin the bridge cert (SPKI form survives rotation):
export ARENA_BRIDGE_PIN_SHA256=$(
  openssl s_client -connect your-bridge.tailnet.ts.net:443 </dev/null 2>/dev/null \
    | openssl x509 -pubkey -noout \
    | openssl pkey -pubin -outform DER \
    | sha256sum | cut -d' ' -f1
)
export ARENA_BRIDGE_PIN_KIND=spki

# Hash peer IPs in request log (analytics still works, forensics
# still readable, but log-file exposure doesn't leak your IP):
export ARENA_LOG_PEER=mask
export ARENA_LOG_PEER_SALT=$(openssl rand -hex 16)

# Reject outbound webhook URLs pointing at RFC1918 / metadata:
export ARENA_WEBHOOK_STRICT=1
```


## Static analysis + CI gates

Every push to `master` and every PR runs the security scan pipeline in
`.github/workflows/security-scan.yml`. Scanner execution, report validity, and
finding policy are separate gates: a missing executable or malformed/missing
report is always blocking even when that scanner's lower-severity findings are
advisory.

### Baseline (must remain green)

- **bandit** — Python source analyzer for common security
  patterns. Config `--skip B101` (asserts) + baseline of
  `bandit-baseline.json` (LOW findings tolerated as
  code-hygiene noise). HIGH + MEDIUM must be zero.
- **semgrep** — semantic analyzer. Pinned rule packs:
  - `p/python`
  - `p/security-audit`
  - `p/owasp-top-ten`
  - `p/cwe-top-25`
  - `p/insecure-transport`
  - `p/command-injection`
  - `p/xss`
  - `p/secrets`
  - `p/gitleaks`

  All packs must exit with zero ERROR + WARNING findings.
  `# nosemgrep: <rule> -- <reason>` per-line acknowledgements
  are allowed only with a specific rationale (see existing
  `nosemgrep` annotations for the required shape).

- **pip-audit** — dependency CVE scan against the reviewed runtime/CI/package
  requirement inputs. Any known CVE is blocking.
- **TruffleHog** — full-history scan; every verified credential is blocking.
  Unverified detector hits are excluded by policy, not swallowed after failure.
- **OSV-Scanner** — recursive dependency scan with retained JSON. Any known
  vulnerability is blocking; no-packages and execution exits are failures.
- **Syft + Grype** — Syft must emit a valid CycloneDX BOM. Grype must emit valid
  JSON; Critical findings block, High and below remain visible advisory data.
- **Socket Firewall** — a refusal or missing/broken `sfw` executable blocks the
  dependency installation job.
- **DevSkim** — must emit valid SARIF. `error` results block; warning/note remain
  visible in the retained artifact.

Command scanners may use exit `1` to mean "valid report with findings". Only
explicitly documented exits `0/1` are accepted before report policy is applied;
all other exits are execution failures. `scripts/scanner_contract_gate.py`
contains the shared report contracts.

### Test suite

- `pytest tests/` must stay green; the current collection count is reported by
  the exact CI run rather than copied into this document.
- Two known-flaky tests are deselected in CI:
  `tests/test_superpowers_layout.py::test_sync_script_exists_and_executable`
  (fs execute-bit lost on some hosts) and
  `tests/test_tunnels_probe.py::test_probe_tcp_timeout_short`
  (baseline flaky since v3.x, timing-sensitive).

### Fast-path for contributors

Run locally before pushing:

```bash
pip install bandit 'semgrep>=1.170' pip-audit pytest ruff
make security-scan  # local Bandit + Semgrep + pip-audit blocking subset
```

`make security-scan` exercises the locally installable blocking subset. The
pinned action/container scanners and their report contracts run in GitHub CI.


## Audit history

Full sweep December 2025 → July 2026 captured 31 findings +
3 defense-in-depth features across 8 security-focused releases
(v4.40.0 → v4.45.0):

- **v4.40.0** — HMAC-signed URL cache
- **v4.41.0** — TLS verify by default, `?token=` deprecation,
  log-URL redaction, token-loader priority fix
- **v4.42.0** — Sandbox parity, expanded sensitive blocklist,
  TOCTOU-safe tempfiles, APK staging out of `/tmp`,
  `os.system()` removed, XXE gate
- **v4.42.1** — Point fix: fs.download exists-vs-blocked
  side channel closed
- **v4.42.2** — Zip-slip / zip-bomb / SSRF-in-skill-install
  hardening (`arena/files/safe_extract.py`)
- **v4.43.0** — bandit clean (0 HIGH / 0 MEDIUM), `file://`
  bypass in skills installer closed, PowerShell argv-form
  + whitelist
- **v4.44.0** — semgrep clean (0 ERROR / 0 WARNING),
  audit-log value-pattern redaction, `ARENA_LOG_PEER` dial,
  `requests.jsonl` chmod 0o600, safe numeric parsing
- **v4.45.0** — CWE-top-25 clean, emit-site redaction
  extracted to shared module (`arena/observability/redact.py`),
  optional TLS certificate pinning
  (`arena/agentctl_cli/pinning.py`)

Detailed per-finding breakdown lives in the release notes of
each version (`CHANGELOG.md`). Comprehensive final-smoke
verification of every feature end-to-end is captured in the
v4.45.0 release notes.

Zero broken masters. Zero rollbacks.

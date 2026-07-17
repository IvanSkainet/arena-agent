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
- **`arena/errors.py::error_middleware`** — attaches
  `Warning: 299` header on every response served through the
  deprecated `?token=` channel; `X-Request-Id`; converts
  unhandled exceptions to `{ok:false, error, error_code}` JSON.
- **`arena/security_ssrf.py`** — reject non-http/https,
  loopback, RFC1918, link-local, multicast, reserved,
  metadata (`169.254.169.254`, `.internal`, `.local`,
  `metadata.google.internal`), IPv4-mapped IPv6, hex/octal
  IP notation.
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

Complete reference of security-relevant env vars. All are
optional; defaults are the safe posture.

| Variable | Default | Effect |
|---|---|---|
| `ARENA_BRIDGE_TOKEN` | (unset) | Bearer token for CLI; wins over `~/arena-bridge/token.txt` since v4.41.0 |
| `ARENA_TOKEN_FILE` | (unset) | Absolute path to a file containing the bearer token; highest priority |
| `ARENA_BRIDGE_URL` | `http://127.0.0.1:8765` | Bootstrap URL used by agentctl |
| `ARENA_INSECURE_TLS` | (unset) | `1`/`true`/`yes`/`on` disables TLS strict-verify; warn-once on stderr. **Only for self-signed bridges** — public transports (Tailscale/CF/Ngrok) always work with default strict-verify |
| `ARENA_BRIDGE_PIN_SHA256` | (unset) | Comma-separated SHA-256 fingerprints; colon-separated `openssl` format accepted. Enables cert pinning |
| `ARENA_BRIDGE_PIN_KIND` | `spki` | `spki` (default, survives cert rotation when key reused) or `cert` (pins whole cert). Both hashes checked on every handshake regardless |
| `ARENA_BRIDGE_URL_CACHE` | enabled | `0`/`false`/`no`/`off` disables the persistent fallback URL cache entirely |
| `ARENA_URL_CACHE_PATH` | `~/.arena/last_urls.json` | Override cache location (e.g. for a shared homeless system) |
| `ARENA_AGENTCTL_LOG_FULL_URLS` | (unset) | `1`/`true`/`yes`/`on` disables the non-TTY URL truncation in stderr diagnostics |
| `ARENA_LOG_PEER` | `full` | `full` records full peer IP in `requests.jsonl`; `mask` hashes with per-install salt; `off` omits the field |
| `ARENA_LOG_PEER_SALT` | fixed derivation | Custom salt for `mask` mode; change to invalidate historical logs |
| `ARENA_WEBHOOK_STRICT` | (unset) | `1`/`true`/`yes`/`on` routes outbound webhook URLs through the full SSRF guard (rejects RFC1918, metadata, etc). Off by default to preserve LAN-webhook use cases |
| `ARENA_APK_STAGING` | `~/.arena/apk-staging` | Override APK upload staging directory (e.g. to point at a larger volume) |
| `ARENA_AGENT_HOME` | `~/arena-bridge` | Bridge installation root; token / audit / logs live here |
| `ARENA_BORE_SERVER` *(v4.47.0)* | `bore.pub` | bore relay host; override to point at a self-hosted `bore server` |
| `ARENA_BORE_SECRET` *(v4.47.0)* | (unset) | Shared secret for self-hosted bore servers; passed as `--secret <value>` only when set, never logged |
| `ARENA_BORE_LOCAL_HOST` *(v4.47.0)* | `localhost` | Loopback host bore should forward to |
| `ARENA_BORE_REMOTE_PORT` *(v4.47.0)* | `0` | Preferred remote port; 0 lets the server pick. Out-of-range / non-numeric values fall back to 0 |
| `ARENA_BORE_URL_WAIT_SECONDS` *(v4.47.0)* | `30` | URL-negotiation wait, clamped 1..300 (same shape as ngrok / cloudflared) |
| `ARENA_BORE_AUTOSTART` *(v4.47.0)* | (unset) | Truthy value autostarts bore on bridge boot (same shape as `ARENA_NGROK_AUTHTOKEN` counterparts) |
| `SSL_CERT_FILE` | (OS default) | Standard stdlib env; point at private CA bundle instead of using `ARENA_INSECURE_TLS` |

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

Every push to `master` and every PR runs the security scan
pipeline in `.github/workflows/security-scan.yml` — three
independent tools, all must exit clean.

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

- **pip-audit** — dependency CVE scan against
  `pyproject.toml` runtime deps + optional `full`/`dev`
  extras. Any known-CVE bumps the build red.

### Test suite

- `pytest tests/` — currently 2319 tests on `master`. Must
  stay green.
- Two known-flaky tests are deselected in CI:
  `tests/test_superpowers_layout.py::test_sync_script_exists_and_executable`
  (fs execute-bit lost on some hosts) and
  `tests/test_tunnels_probe.py::test_probe_tcp_timeout_short`
  (baseline flaky since v3.x, timing-sensitive).

### Fast-path for contributors

Run locally before pushing:

```bash
pip install bandit 'semgrep>=1.170' pip-audit pytest ruff
make security-scan  # runs all four
```

`make security-scan` is defined in the repo `Makefile` and is
what CI runs, so passing locally means passing in CI.


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

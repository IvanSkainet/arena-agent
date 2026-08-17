# Release Process

This document describes how to cut a new Arena Unified Bridge release. It is
aimed at maintainers; end users should read the [Quick Start](README.md#quick-start)
instead.

## TL;DR

```bash
# 0) Be on master with a clean tree
cd arena-bridge
git checkout master
git pull --ff-only
git status -sb    # must be clean

# 1) Run the checks (must be green)
python -m pytest tests/ -q
bash -n install.sh
python -m py_compile arena/**/*.py
# Extension work also runs the targeted JS/asset checks (see README "Development").

# 1b) Security gate (added v4.46.0 -- CI runs the same three checks and will
#     block the tag push if any of them are red)
make security-scan
#   - bandit:   0 HIGH + 0 MEDIUM
#   - semgrep:  0 findings across 9 rule packs
#   - pip-audit: 0 CVEs in runtime + full-extras deps

# 2) Bump the version (one command, since v4.60.7)
python dev/bump_version.py x.y.z
#   Updates in a single AST-verified pass:
#     - arena/constants.py            (VERSION = "x.y.z")
#     - pyproject.toml                (version = "x.y.z")
#     - tests/_version_matrix.py      (appends "x.y.z" to BRIDGE_VERSIONS
#                                      so every version-pin test accepts it)
#   Add --dry-run to preview without touching disk.
#   The bumper does NOT touch CHANGELOG (release notes are hand-written)
#   and does NOT git-commit or tag.

# 2b) Hand-write the release notes
#    - CHANGELOG.md                  (prepend "## vX.Y.Z — YYYY-MM-DD")
#    - CHANGELOG.ru.md               (prepend the matching Russian entry)
#    If the extension runtime changed, also bump chat_extension/manifest.json
#    and the content/insert script versions, then add them to EXT_VERSIONS in
#    tests/_version_matrix.py (by hand — the bumper only handles the bridge chain).

# 3) Commit on a release branch and merge through a green PR.
#    Never bypass the master ruleset for a release.
git add arena/constants.py pyproject.toml tests/_version_matrix.py CHANGELOG.md CHANGELOG.ru.md
git commit -m "vX.Y.Z: <short release summary>"
git push -u origin release/vX.Y.Z
gh pr create --base master --head release/vX.Y.Z --title "vX.Y.Z: <summary>"
# Wait for CI required + Security required + Dependency Review + Zizmor, then merge.

# 4) Build the exact master commit twice and attest the matching bytes.
#    This workflow first runs the pinned The Book of Eternity: Reborn Windows
#    ConPTY/relay/repair contract; candidate attestation waits for that job.
gh workflow run release-candidate.yml --ref master
# Resolve the run whose headSha is the exact intended master commit, wait for success,
# then download its final artifact without renaming or rebuilding the ZIPs or APK.
gh run download <run-id> \
    --name attested-release-candidate-<full-master-sha> \
    --dir /tmp/arena-release-candidate

# 5) Verify provenance and the attached SPDX SBOM before host installation.
#    gh CLI v2.68.0+ is required for --source-digest.
SOURCE_DIGEST=<full-master-sha>
(
  cd /tmp/arena-release-candidate
  test "$(find . -maxdepth 1 -name '*.zip' -type f | wc -l)" -eq 2
  test -f arena-agent-vX.Y.Z.zip && test -f arena-agent.zip
  test -f arena-bridge.apk
  cmp arena-agent-vX.Y.Z.zip arena-agent.zip
  for f in arena-agent-vX.Y.Z.zip arena-agent.zip arena-bridge.apk; do
    gh attestation verify "$f" \
      --repo IvanSkainet/arena-agent \
      --signer-workflow IvanSkainet/arena-agent/.github/workflows/release-candidate.yml \
      --source-digest "$SOURCE_DIGEST" \
      --deny-self-hosted-runners
    gh attestation verify "$f" \
      --repo IvanSkainet/arena-agent \
      --signer-workflow IvanSkainet/arena-agent/.github/workflows/release-candidate.yml \
      --source-digest "$SOURCE_DIGEST" \
      --deny-self-hosted-runners \
      --predicate-type https://spdx.dev/Document/v2.3
  done
  sha256sum -c SHA256SUMS-candidate-vX.Y.Z.txt
)

# 6) Install those exact candidate bytes on the real Windows host and run the
#    release-specific live acceptance. If this fails: do not tag and do not publish.

# 7) Only after candidate acceptance, create the annotated tag on the attested commit.
test "$(git rev-parse HEAD)" = "<full-master-sha>"
git tag -a vX.Y.Z -m "vX.Y.Z: <short release summary>"
git push origin vX.Y.Z

# 8) Stage a DRAFT release with the already-attested ZIPs and APK. Draft first
#    so release:published signing can never race an incomplete asset upload.
gh release create vX.Y.Z \
    /tmp/arena-release-candidate/arena-agent-vX.Y.Z.zip \
    /tmp/arena-release-candidate/arena-agent.zip \
    /tmp/arena-release-candidate/arena-bridge.apk \
    --draft \
    --title "vX.Y.Z — <summary>" \
    --notes-file <path-to-release-notes.md>
gh release edit vX.Y.Z --draft=false --latest

# 9) Wait for sign-release. It re-verifies candidate provenance + SBOM before
#    producing SHA256SUMS and Sigstore signatures.

# 10) Download the PUBLIC artifact anonymously, verify it, install it again on
#     Windows, and repeat installed-artifact timeout/restart/live smoke.
```

## Why two zip assets?

The README's quick-start one-liner can download from:

```
https://github.com/IvanSkainet/arena-agent/releases/latest/download/arena-agent.zip
```

GitHub's `releases/latest/download/` URL serves an asset **by exact name**. If
only `arena-agent-vX.Y.Z.zip` exists, that URL 404s and the install instruction
breaks. So each release ships two byte-identical assets:

- **`arena-agent-vX.Y.Z.zip`** — historical convention and explicit pinning.
- **`arena-agent.zip`** — the version-agnostic alias the README relies on.

## Verifying a download

Every published release is signed automatically by
`.github/workflows/sign-release.yml` using Sigstore keyless signing. Each zip
gets a `.sig` and a `.pem`, and a `SHA256SUMS-vX.Y.Z.txt` is published (and
itself signed) alongside them.

Before cosign signs anything, the publishing workflow requires GitHub build
provenance and an SPDX SBOM attestation from the pinned
`.github/workflows/release-candidate.yml` signer. This closes the old gap where
a workflow-valid signature could be applied to arbitrary bytes uploaded before
the signing job started.

GitHub CLI v2.68.0 or newer is required for the exact-commit check:

```bash
TAG=v4.161.0
SOURCE_DIGEST=$(gh api \
  "repos/IvanSkainet/arena-agent/commits/${TAG}" --jq '.sha')
gh attestation verify arena-agent.zip \
  --repo IvanSkainet/arena-agent \
  --signer-workflow IvanSkainet/arena-agent/.github/workflows/release-candidate.yml \
  --source-digest "$SOURCE_DIGEST" \
  --deny-self-hosted-runners

gh attestation verify arena-agent.zip \
  --repo IvanSkainet/arena-agent \
  --signer-workflow IvanSkainet/arena-agent/.github/workflows/release-candidate.yml \
  --source-digest "$SOURCE_DIGEST" \
  --deny-self-hosted-runners \
  --predicate-type https://spdx.dev/Document/v2.3
```

Cosign remains a second, independently verifiable release signature. Keyless
means there is no private key anywhere: GitHub mints a short-lived OIDC token
for the signing job, and the certificate binds the signature to *this workflow
in this repository*. The certificate is also recorded in a public transparency
log.

**With cosign** (proves signing-workflow origin):

```bash
TAG=v4.161.0
cosign verify-blob arena-agent.zip \
  --signature arena-agent.zip.sig \
  --certificate arena-agent.zip.pem \
  --certificate-identity-regexp \
    '^https://github\.com/IvanSkainet/arena-agent/\.github/workflows/sign-release\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

**Without cosign** (integrity only — use it if you trust the release page but
want to catch a corrupted or truncated download):

```bash
sha256sum -c SHA256SUMS-v4.161.0.txt
```

The digest file is signed too, so the cosign check above can be run against
`SHA256SUMS-vX.Y.Z.txt` first and the plain `sha256sum -c` trusted afterwards.

## What goes into the release zip

`scripts/make_release_zip.py` builds a runnable bridge that a user can extract and
`install.sh` / `install.bat` from. It MUST include:

- `unified_bridge.py`, `_arena_helper.py`;
- `arena/` (the full package);
- `bin/`, `scripts/` (CLI wrappers);
- `dashboard/` (web UI assets);
- `chat_extension/` (the browser extension);
- installers and Windows helpers (`install.*`, `uninstall.*`, `start.bat`, etc.);
- `pyproject.toml`, `requirements.txt`;
- `README.md`, `README.ru.md`, `CHANGELOG.md`, `CHANGELOG.ru.md`, `LICENSE`,
  `CONTRIBUTING.md`, `AGENTS.md`;
- `docs/` (architecture and navigation notes);
- virtual `.arena-release-provenance.json` with the exact source commit,
  strict release tag, and candidate workflow run. It is generated canonically
  by the packer and verified against `GITHUB_SHA` / `GITHUB_RUN_ID`; it does not
  contain the ZIP digest because an archive cannot contain its own hash.

On installation, the updater combines that immutable identity with the verified
ZIP SHA-256 and install time in runtime `DEPLOYED_PROVENANCE.json`. The previous
identified deployment is retained under `backups/deployments/<identity>/` before
replacement starts. `/v1/version` exposes the deployed identity and an explicit
`authenticated` boolean; it is true only when the ZIP digest, asset URL/name,
and tag also match metadata fetched from the official GitHub Release. A digest
supplied only by the update caller is integrity input, not provenance
authentication. Absent or malformed state is reported as unauthenticated, never
inferred from a nested vendored `.git` directory. During a valid repair update,
a malformed old record is preserved under `backups/provenance-quarantine/` and
is not used as authenticated history.

Archive compatibility starts with the first release containing T55 provenance
(planned `v4.169.48`). Once that updater is installed, it rejects older
pre-provenance ZIPs, including `v4.169.45`–`v4.169.47`, with an explicit
`release provenance verification failed` error. They remain independently
verifiable public artifacts, but are not accepted as rollback inputs by the new
updater. Supported rollback uses the retained identified tree under
`backups/deployments/{identity}/`; the first migration from a pre-T55 install
cannot invent the old commit/SHA and therefore reports no identified rollback.

It MUST NOT include (excluded automatically by the script):

- `tests/`, `.github/`, `dev/`, `.git/`;
- caches and generated test reports (`__pycache__/`, `*.pyc`, `.pytest_cache/`,
  `.mypy_cache/`, `node_modules/`, `.coverage*`, `coverage.xml`);
- runtime state: `token.txt`, `audit.jsonl`, `bridge.log`, `requests.jsonl`,
  `queue/{running,done,failed}/*`, `memory/{facts,history}.jsonl`,
  `memory/sessions/`, `missions/*`, `reports/*`;
- `backups/`, `logs/`, editor config (`.vscode/`, `.idea/`).

## Where the version lives

The canonical version is `VERSION` in `arena/constants.py`. It is read at runtime
by `_arena_helper.py version`, which the installers and the `/v1/version` endpoint
use. The same string MUST also appear in:

- `pyproject.toml` → `version = "x.y.z"`;
- the annotated git tag `vX.Y.Z`;
- the top `CHANGELOG.md` and `CHANGELOG.ru.md` entries.

The README's version badge is dynamic
(`shields.io/github/v/release/IvanSkainet/arena-agent`) and auto-updates when a
release is published — do NOT edit it manually. No workflow commits generated
version metadata back to `master`: source consistency is checked by
`version_sync.py`, while `release_published_check.py` verifies that
`releases/latest` neither leads the source tree nor trails it by more than the
single candidate release allowed before publication.

## Extension version bumps

The browser extension has its own version, independent of the bridge. Bump it
**only** when the extension runtime actually changes. When you do:

- `chat_extension/manifest.json` → `"version"`;
- `chat_extension/README.md` → `Current extension version: ...`;
- `tests/test_chat_extension_assets.py` and
  `tests/test_chat_extension_adapter_flow.py` (asserted version strings);
- if content scripts changed:
  - `chat_extension/content.js` → `ARENA_CONTENT_SCRIPT_VERSION`;
  - `chat_extension/insert_strategies.js` → `arenaInsertScriptVersion()`.

If only docs or bridge code changed, leave the extension version as-is.

## CHANGELOG format

Each release gets a section at the top of `CHANGELOG.md` (and a matching one in
`CHANGELOG.ru.md`):

```markdown
## vX.Y.Z — YYYY-MM-DD

### Fixed
- <bullet>

### Documentation
- <bullet>

### Validation
- Targeted tests: PASS.
- JS syntax checks: PASS.
- `python -m py_compile ...`: PASS.
```

Omit a sub-section if it has no entries for this release.

## Android release signing identity

Release candidates use a persistent Android signing identity, not the disposable
debug keystore created by ordinary CI. The private key is stored as the
`ANDROID_RELEASE_KEYSTORE_B64` GitHub Actions secret; alias/store/key passwords
use the three matching `ANDROID_RELEASE_*` secrets. The public certificate
fingerprint is pinned in `android_app/release-signing-cert.sha256` and candidate
verification refuses a technically valid APK signed by any other key.

The operator backup lives outside the repository under
`%USERPROFILE%\.arena\release-keys`; its password backup is DPAPI-protected for
the same Windows account. Never rotate or delete this identity as routine
maintenance: Android treats a new key as a different publisher and installed
users cannot upgrade in place. Ordinary PR CI continues to use an ephemeral
debug key because its APK is a build test, never a release asset.

## Pre-release checklist

- [ ] Full test suite passes (`python -m pytest -q`). Record the collection
      count and coverage printed by that exact run in the release evidence;
      do not copy a historical count forward. The default local coverage floor
      is 46%; CI raises Linux to 51%.
- [ ] Targeted extension checks pass (see README "Development").
- [ ] Targeted remote-access checks pass:
      `pytest -q tests/test_tunnels.py tests/test_zerotier.py tests/test_cloudflared.py tests/test_browseract.py tests/test_superpowers_layout.py`.
- [ ] `bash -n install.sh` — syntax OK.
- [ ] `python -m py_compile` on changed files — no syntax errors.
- [ ] **`make security-scan` clean** — bandit 0 HIGH/MEDIUM, semgrep 0
      findings across 9 packs, pip-audit 0 CVEs. This is the same gate
      the CI workflow enforces on push and tag; a red gate blocks the
      release from being published even if the master push succeeds.
- [ ] `arena/constants.py` `VERSION` matches `pyproject.toml` `version`.
- [ ] `CHANGELOG.md` and `CHANGELOG.ru.md` have a new top entry with today's date.
- [ ] If the release adds or removes a security-relevant env variable,
      update the reference table in `SECURITY.md`.
- [ ] No private tunnel hostnames leaked into tracked files.
- [ ] No credential-shape literals in test fixtures (build at runtime
      via prefix + suffix concat -- see AGENTS.md "Security" hard rules).
- [ ] Working tree clean, on `master`, up to date with `origin/master`.
- [ ] `release-candidate.yml` succeeded on that exact master SHA; independent
      builds A/B matched byte-for-byte and `release-verification.json` is clean.
- [ ] Its reusable pinned **The Book of Eternity: Reborn** Windows contract
      passed on the same SHA with current upstream pin, three correlated
      dispatches, empty relay queues, and no surviving GM bridge process.
- [ ] Both ZIP names and `arena-bridge.apk` pass build-provenance and their
      matching SPDX SBOM verification with the pinned release-candidate signer
      workflow and `--source-digest` equal to the exact intended master commit.
- [ ] From the downloaded candidate directory, the documented unmodified
      `sha256sum -c SHA256SUMS-candidate-vX.Y.Z.txt` command passes for exactly
      the versioned ZIP, `arena-agent.zip`, and `arena-bridge.apk`.
- [ ] The downloaded Actions artifact digest is recorded before it leaves CI.
- [ ] That exact digest passed the real Windows candidate acceptance before the
      annotated tag or public release was created.

## Post-release checklist

- [ ] Running install updated (`git pull --ff-only`, restart if a service).
- [ ] `/health` and `/v1/version` report the new version.
- [ ] `/v1/tunnels/status` reports every configured provider with the correct
      `installed` flag (regression guard for the v3.81.1 fix).
- [ ] `/v1/skills` contains no bogus category entries like `superpowers/assets`
      (regression guard for the v3.81.1 fix).
- [ ] Both ZIP assets and `arena-bridge.apk` are visible on the release page and
      byte-identical to the previously accepted Actions artifact.
- [ ] Public ZIPs and APK still pass `gh attestation verify` for both build
      provenance and their matching SPDX SBOM predicates with the
      release-candidate signer workflow and `--source-digest` resolved from the
      exact release tag commit.
- [ ] The alias URL works:
      `curl -sIL https://github.com/IvanSkainet/arena-agent/releases/latest/download/arena-agent.zip`
      returns HTTP 200.
- [ ] The versioned URL works:
      `curl -sIL https://github.com/IvanSkainet/arena-agent/releases/download/vX.Y.Z/arena-agent-vX.Y.Z.zip`
      returns HTTP 200.
- [ ] The `Security scan` GitHub Actions workflow is green on the tag
      commit (blocks daily-cron regressions from silently accumulating):
      <https://github.com/IvanSkainet/arena-agent/actions/workflows/security-scan.yml>.
- [ ] Live smoke against the running bridge: bearer auth still accepts
      the token, `/v1/agent/config` responds, `agentctl bridge cache show`
      confirms the HMAC-signed cache is unaffected by the upgrade
      (empty cache = OK, populated cache = OK). If the release changed
      any CLI-side security surface (TLS context, pinning, url_cache),
      verify with a targeted smoke script under `dev/`.

## Why the candidate workflow does not publish

The candidate workflow deliberately stops after deterministic build,
verification, SBOM, provenance, and Actions artifact upload. GitHub-hosted CI
cannot observe the maintainer's real Windows installation, restart chain, tunnel,
or game/daemon integrations. Publishing from CI before that observation would
recreate the green-equals-works failure in a more automated form.

The human/agent release driver therefore downloads the attested artifact, installs
those exact bytes on Windows, and only then creates the annotated tag and draft
release. Publication changes visibility, not bytes. `sign-release.yml` resolves the tag
to its exact commit, downloads the successful exact-SHA candidate evidence,
requires exactly the two documented ZIP assets plus `arena-bridge.apk`, checks
all three against the accepted candidate manifest, and verifies source-bound
provenance and per-artifact SBOM attestations before adding independent Sigstore
signatures.

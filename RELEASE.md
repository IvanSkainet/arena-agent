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

# 2) Bump the version:
#    - arena/constants.py            (VERSION = "x.y.z")
#    - pyproject.toml                (version = "x.y.z")
#    - CHANGELOG.md                  (prepend "## vX.Y.Z — YYYY-MM-DD")
#    - CHANGELOG.ru.md               (prepend the matching Russian entry)
#    If the extension runtime changed, also bump chat_extension/manifest.json
#    and the content/insert script versions (see below).

# 3) Commit the bump (list files explicitly — never `git add -A`)
git add arena/constants.py pyproject.toml CHANGELOG.md CHANGELOG.ru.md
git commit -m "vX.Y.Z: <short release summary>"

# 4) Tag the release (annotated)
git tag -a vX.Y.Z -m "vX.Y.Z: <short release summary>"

# 5) Push master + tag
git push origin master
git push origin vX.Y.Z

# 6) Build the release zip (version auto-detected from arena/constants.py)
python3 scripts/make_release_zip.py            # -> /tmp/arena-agent-vX.Y.Z.zip

# 7) Create the GitHub Release with TWO assets (the second is critical!)
#    Use a temporary/untracked notes file (e.g. under /tmp) — do not keep
#    per-release scratch notes in the repository.
gh release create vX.Y.Z \
    --title "vX.Y.Z — <summary>" \
    --notes-file <path-to-release-notes.md> \
    --latest

# 7a) Versioned zip (historical convention / explicit pinning)
gh release upload vX.Y.Z /tmp/arena-agent-vX.Y.Z.zip --clobber

# 7b) Unversioned alias (REQUIRED by the README one-liner URL)
cp /tmp/arena-agent-vX.Y.Z.zip /tmp/arena-agent.zip
gh release upload vX.Y.Z /tmp/arena-agent.zip --clobber

# 8) Update the running install and verify
git pull --ff-only
python3 _arena_helper.py version                # must show the new version
systemctl --user restart arena-bridge.service   # if running as a service
sleep 3
curl -s http://127.0.0.1:8765/health            # must report the new version
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
- `docs/` (architecture and navigation notes).

It MUST NOT include (excluded automatically by the script):

- `tests/`, `.github/`, `dev/`, `.git/`;
- caches (`__pycache__/`, `*.pyc`, `.pytest_cache/`, `.mypy_cache/`, `node_modules/`);
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
release is published — do NOT edit it manually.

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

## Pre-release checklist

- [ ] Targeted tests pass (`python -m pytest tests/ -q`, or the extension subset).
- [ ] `bash -n install.sh` — syntax OK.
- [ ] `python -m py_compile` on changed files — no syntax errors.
- [ ] `arena/constants.py` `VERSION` matches `pyproject.toml` `version`.
- [ ] `CHANGELOG.md` and `CHANGELOG.ru.md` have a new top entry with today's date.
- [ ] No private tunnel hostnames leaked into tracked files.
- [ ] Working tree clean, on `master`, up to date with `origin/master`.

## Post-release checklist

- [ ] Running install updated (`git pull --ff-only`, restart if a service).
- [ ] `/health` and `/v1/version` report the new version.
- [ ] Both zip assets are visible on the release page.
- [ ] The alias URL works:
      `curl -sIL https://github.com/IvanSkainet/arena-agent/releases/latest/download/arena-agent.zip`
      returns HTTP 200.
- [ ] The versioned URL works:
      `curl -sIL https://github.com/IvanSkainet/arena-agent/releases/download/vX.Y.Z/arena-agent-vX.Y.Z.zip`
      returns HTTP 200.

## Why not a GitHub Action?

Today the release is cut manually because the bridge is also installed on the
maintainer's machine — pulling a fresh tag locally is part of validating it — and
the two-zip-asset trick is easier to control from a local script. A tag-triggered
build workflow is a possible future improvement; for now, this document is the
source of truth.

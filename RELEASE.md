# Release Process

This document describes how to cut a new Arena Unified Bridge release. It is
aimed at maintainers; end users should read the [Quick Start](README.md#-quick-start)
instead.

## TL;DR

```bash
# 0) Make sure you are on master with a clean tree
cd ~/Документы/arena-agent-v3-git
git checkout master
git pull --ff-only
git status -sb    # must be clean

# 1) Run the test suite (must be 100% green)
python -m pytest tests/ -q
bash -n install.sh
python -m py_compile arena/**/*.py

# 2) Bump version in three places:
#    - arena/constants.py       (VERSION = "x.y.z")
#    - pyproject.toml           (version = "x.y.z")
#    - CHANGELOG.md             (prepend "## vX.Y.Z — YYYY-MM-DD" entry)
python3 -c 'p="arena/constants.py"; t=open(p).read(); t=t.replace("VERSION = \"OLD\"", "VERSION = \"NEW\""); open(p,"w").write(t)'
# (repeat for pyproject.toml and CHANGELOG.md)

# 3) Commit the bump
git add arena/constants.py pyproject.toml CHANGELOG.md
git commit -m "vX.Y.Z: <short release summary>"

# 4) Tag the release (annotated)
git tag -a vX.Y.Z -m "vX.Y.Z: <short release summary>"

# 5) Push master + tag
git push origin master
git push origin vX.Y.Z

# 6) Build the release zip (see "Building the release zip" below)
python3 scripts/make_release_zip.py    # produces /tmp/arena-agent-vX.Y.Z.zip

# 7) Create the GitHub Release with TWO assets (the second is critical!)
#    Use a temporary/untracked notes file (for example under /tmp) — do not
#    keep per-release scratch notes like release_vXXXX.md in the repository.
gh release create vX.Y.Z \
    --title "vX.Y.Z — <summary>" \
    --notes-file <path-to-release-notes.md> \
    --latest

# 7a) Upload the versioned zip (matches historical convention)
gh release upload vX.Y.Z /tmp/arena-agent-vX.Y.Z.zip --clobber

# 7b) Upload the unversioned alias (REQUIRED for README install instructions)
cp /tmp/arena-agent-vX.Y.Z.zip /tmp/arena-agent.zip
gh release upload vX.Y.Z /tmp/arena-agent.zip --clobber

# 8) Update the production install
cd ~/arena-bridge
git pull --ff-only
python3 _arena_helper.py version    # must show the new version
systemctl --user restart arena-bridge.service
sleep 3
curl -sk https://<your-tailscale-url>/health    # must show the new version
```

## Why two zip assets?

The README's "Quick Start" one-liner downloads from:

```
https://github.com/IvanSkainet/arena-agent/releases/latest/download/arena-agent.zip
```

GitHub's `releases/latest/download/` URL serves the asset **by exact name**.
If only `arena-agent-v3.1.6.zip` exists, that URL 404s and the install
instructions break.

To keep both happy:
- **`arena-agent-vX.Y.Z.zip`** — for historical convention and explicit pinning.
- **`arena-agent.zip`** — for the README's version-agnostic one-liner.

Both files are byte-identical (same content, just different names).

## What to put in the release zip

The zip must contain a runnable bridge that a user can extract and `install.sh`
/ `install.bat` from. Specifically it MUST include:
- `unified_bridge.py`, `_arena_helper.py`
- `arena/` (the full package)
- `bin/`, `scripts/` (CLI wrappers)
- `dashboard/` (the web UI assets)
- `install.sh`, `install.bat`, `uninstall.sh`, `uninstall.bat`
- `start.bat`, `stop.bat`, `status.bat`, `regenerate_token.{sh,bat}` (Windows helpers)
- `pyproject.toml`, `requirements.txt`
- `README.md`, `CHANGELOG.md`, `LICENSE`, `AGENTS.md`, `CONTRIBUTING.md`
- `docs/` (architecture and navigation docs for AI maintainers)
- `.gitignore`, `.editorconfig`

It MUST NOT include (excluded by `scripts/make_release_zip.py`):
- `tests/` (development-only)
- `.github/` (CI workflows)
- `dev/` (development scripts)
- `.git/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`
- runtime state: `token.txt`, `audit.jsonl`, `bridge.log`, `queue/{running,done,failed}/*`,
  `memory/{facts,history}.jsonl`, `memory/sessions/`, `missions/*`, `reports/*`
- `backups/`, `logs/`
- editor config: `.vscode/`, `.idea/`

## Where the version lives

The canonical version is in `arena/constants.py`:

```python
VERSION = "3.1.6"
```

It is read at runtime by `_arena_helper.py version`, which the installers and
`/v1/version` endpoint use. The same string MUST also appear in:
- `pyproject.toml` → `version = "3.1.6"` (for `pip install` metadata, if anyone
  ever packages this)
- The git tag `v3.1.6` (annotated)

The README's version badge is dynamic
(`shields.io/github/v/release/IvanSkainet/arena-agent`) and auto-updates when a
new release is published — do NOT edit it manually.

## CHANGELOG format

Each release gets a section at the top of `CHANGELOG.md`:

```markdown
## vX.Y.Z — YYYY-MM-DD

### Fixed
- <bullet>

### Refactored
- <bullet>

### Tests
- <bullet>

### Documentation
- <bullet>

### Validation
- Local `pytest -q`: PASS, N tests.
- Local `bash -n install.sh`: PASS.
- Bridge `/v1/doctor`: 10/10.
```

Use the same sub-headers as the previous release; omit a section if it has no
entries for this release.

## Pre-release checklist

Before tagging, verify:
- [ ] `python -m pytest tests/ -q` — 100% pass, no skips for non-environmental reasons
- [ ] `bash -n install.sh` — syntax OK
- [ ] `python -m py_compile arena/**/*.py` — no syntax errors
- [ ] No `TODO` / `FIXME` introduced in this release's diff (pre-existing ones are fine)
- [ ] `arena/constants.py` `VERSION` matches `pyproject.toml` `version`
- [ ] `CHANGELOG.md` has a new entry at the top with today's date
- [ ] `webhooks.json` is `{urls: [], events: ["*"]}` (empty default)
- [ ] Working tree is clean (`git status -sb` shows nothing)
- [ ] On `master` branch, up to date with `origin/master`

## Post-release checklist

After the GitHub release is published:
- [ ] Production install updated: `cd ~/arena-bridge && git pull --ff-only`
- [ ] Bridge restarted: `systemctl --user restart arena-bridge.service`
- [ ] `/health` reports the new version
- [ ] `/v1/doctor` returns 10/10
- [ ] Both zip assets are visible on the release page
- [ ] The README's one-liner URL works: `curl -sIL
      https://github.com/IvanSkainet/arena-agent/releases/latest/download/arena-agent.zip`
      returns HTTP 200
- [ ] The versioned URL works: `curl -sIL
      https://github.com/IvanSkainet/arena-agent/releases/download/vX.Y.Z/arena-agent-vX.Y.Z.zip`
      returns HTTP 200

## Why not a GitHub Action?

Today the release is cut manually because:
1. The bridge is also installed on the maintainer's machine — pulling a fresh
   tag locally is part of validating it.
2. The release zip excludes runtime state that only makes sense to exclude
   from a working tree, not from a CI checkout.
3. The two-zip-asset trick (versioned + unversioned) is easier to control
   from a local script than from a workflow.

A GitHub Action that auto-builds the zip on tag push is a future improvement.
For now, this document is the source of truth.

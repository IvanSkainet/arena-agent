# Superpowers

`arena-agent` ships **one** vendored copy of the
[obra/superpowers][upstream] skill library at `skills/superpowers/`.
This single directory serves two consumers:

- **Arena Bridge** discovers skills via `GET /v1/skills`, `install.sh`
  installs from here, and `dev/stress-test-v3.sh` validates them here.
- **Standalone IDE plugins** (Claude Code, Codex, Cursor, Gemini) install
  the same directory as a plugin via the manifests it carries
  (`.claude-plugin/`, `.codex-plugin/`, `.cursor-plugin/`,
  `gemini-extension.json`).

[upstream]: https://github.com/obra/superpowers

This is a deliberate change from earlier releases, which shipped **two**
directories (`skills/superpowers/` — an Arena-adapted fork — and
`tools/superpowers/` — the upstream mirror). The fork drifted from
upstream, forcing agents that read from the bridge to see different text
than agents that installed the plugin into an IDE. That split is now
gone: **agent behaviour is identical whether the skill is served by the
bridge or by an IDE plugin.**

## Layout

```
skills/superpowers/
├── skills/                       ← 14 upstream SKILL.md sets
│   ├── brainstorming/
│   ├── dispatching-parallel-agents/
│   ├── executing-plans/
│   ├── finishing-a-development-branch/
│   ├── receiving-code-review/
│   ├── requesting-code-review/
│   ├── subagent-driven-development/
│   ├── systematic-debugging/
│   ├── test-driven-development/
│   ├── using-git-worktrees/
│   ├── using-superpowers/
│   ├── verification-before-completion/
│   ├── writing-plans/
│   └── writing-skills/
├── assets/                       ← icons/svg used by IDE plugins
├── hooks/                        ← session-start hooks + cross-platform runner
├── scripts/                      ← upstream helpers (bump-version, sync-to-codex)
├── .claude-plugin/               ← Claude Code plugin manifest
├── .codex-plugin/                ← Codex plugin manifest
├── .cursor-plugin/               ← Cursor plugin manifest
├── gemini-extension.json         ← Gemini extension manifest
├── package.json                  ← npm plugin metadata (name/version)
├── LICENSE                       ← upstream MIT license
├── .gitattributes                ← LF line endings for scripts/hooks
├── .gitignore
└── .version-bump.json
```

## Update strategy — always track upstream

Because there is no Arena fork, updating is straightforward:

```bash
# Preview upstream diff
./scripts/sync_superpowers_from_upstream.sh --check

# Actually apply upstream on top of skills/superpowers/
./scripts/sync_superpowers_from_upstream.sh --apply
```

The script rsyncs from a fresh clone of `obra/superpowers` `main` into
`skills/superpowers/` and reports which files changed. Commit the diff
with the upstream short SHA in the message.

**We do not carry Arena-specific patches on top.** If Arena needs a
different behaviour, the correct fix is:

1. Upstream the change to `obra/superpowers` and pin our sync to a later
   revision, **or**
2. Add a new Arena-specific skill under a separate root
   (`skills/arena/…`) that lives beside the upstream copy, **or**
3. Wrap the upstream skill from bridge code without editing the SKILL
   text itself.

Do **not** re-introduce an Arena fork inside `skills/superpowers/`.

## Installer / bridge behaviour

`install.sh` prefers the bundled copy that ships with the repo:

1. If `$INSTALL_DIR/skills/superpowers/skills/` exists → use it.
2. Else if `git` is available → clone `obra/superpowers` into
   `skills/superpowers/`.
3. Else print a manual install command and warn.

`tests/test_installer_version_safety.py` enforces that the installer's
`git pull` scope is limited to `skills/superpowers/` and never targets
the bridge itself.

## Historical note

If you are reading this while debugging an older checkout that still
contains `tools/superpowers/` and Arena-flavoured `SKILL.md` text at
`skills/superpowers/skills/…`, that is pre-consolidation state. Rebase
onto `master` and this document (plus
`scripts/sync_superpowers_from_upstream.sh`) will describe the current
world.

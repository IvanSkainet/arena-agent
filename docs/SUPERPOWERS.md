# Superpowers layout & update strategy

`arena-agent` ships **two vendored copies** of the [obra/superpowers][upstream]
skill library. They look similar but serve different consumers and must be
kept intentionally distinct.

[upstream]: https://github.com/obra/superpowers

## Layout

| Path | Consumer | Contents |
|---|---|---|
| **`skills/superpowers/skills/`** | Arena Bridge (`/v1/skills`, installer, `dev/stress-test-v3.sh`) | 14 Arena-flavoured `SKILL.md` files. Descriptions reference the bridge, `/v1/skills` discovery, our feature-branch workflow. This is what agents talk to when they hit the bridge over HTTP. |
| **`tools/superpowers/`** | Standalone plugin for Claude Code, Codex, Cursor, Gemini | Full upstream mirror (v5.1.0): 14 upstream `SKILL.md` files + `.claude-plugin/`, `.codex-plugin/`, `.cursor-plugin/`, `gemini-extension.json`, `hooks/`, `package.json`, LICENSE, `bump-version.sh`. This is what you install into an IDE **without** running the Arena Bridge. |

### Skill diffs

Common skills carry different text on purpose. `tools/superpowers/` mirrors
upstream verbatim; `skills/superpowers/skills/` is our fork with a few
Arena-specific twists:

| Skill (both dirs) | Notes |
|---|---|
| `writing-skills`, `subagent-driven-development`, `test-driven-development`, `systematic-debugging`, … | Arena copy references `/v1/skills`, our profiles, and our stress-test harness. |
| `finishing-a-feature-branch` (Arena) vs `finishing-a-development-branch` (upstream) | Renamed to match our branching conventions. |
| `using-arena-superpowers` (Arena only) | Introduces Arena tooling. |
| `using-feature-branches` (Arena only) | Our git flow. |
| `using-git-worktrees` (upstream only) | Kept in `tools/` for IDE users. |
| `using-superpowers` (upstream only) | Kept in `tools/` for IDE users. |

## Update flow

### Refreshing `tools/superpowers/` from upstream (safe, no fork drift)

`tools/superpowers/` should track upstream faithfully. To update:

```bash
./scripts/sync_superpowers_from_upstream.sh --check           # show diff summary
./scripts/sync_superpowers_from_upstream.sh --apply           # actually update
```

The script clones upstream into a scratch dir, rsyncs into `tools/superpowers/`,
preserves our `.gitattributes`/`.gitignore`, and prints a per-file diff summary
so you can review before committing.

### Refreshing `skills/superpowers/skills/` (Arena fork — needs review)

Because this directory is intentionally forked, we do **not** auto-overwrite.
Recommended flow when upstream ships something interesting:

1. Run `./scripts/sync_superpowers_from_upstream.sh --into skills/superpowers/skills --check`.
2. Read the diff. For each changed skill:
   - **Prose-only upstream improvement** → cherry-pick into the Arena copy.
   - **Reference to upstream-only concept** (git worktrees, IDE-specific paths) → leave the Arena copy alone.
3. Update the Arena skill text, preserving our `/v1/skills`, profile, and
   feature-branch references.
4. Commit with a message that names both the upstream commit hash and the
   Arena rationale.

### Installer behaviour (recap)

`install.sh` prefers the bundled copy when present:

1. If `$INSTALL_DIR/skills/superpowers/skills/` already exists → use it.
2. Else if the repo ships `skills/superpowers/skills/` (default) → use bundled.
3. Else if `git` is available → clone `obra/superpowers` into `skills/superpowers`.
4. Else warn and print manual install command.

Only case 3 turns `skills/superpowers/` into a real git checkout. In all other
cases it is a plain directory managed by this repo. `tests/test_installer_version_safety.py`
enforces that the installer's `git pull` scope is limited to
`skills/superpowers/` and never targets the bridge itself.

## Do not delete either directory

- Removing `skills/superpowers/` would break `install.sh`, `stress-test-v3.sh`,
  the `/v1/skills` surface, and every agent that reads Arena-flavoured skill text.
- Removing `tools/superpowers/` would break standalone IDE users who install
  the plugin without the bridge.

If you find yourself wanting to consolidate, first prove that no downstream
still consumes the removed path.

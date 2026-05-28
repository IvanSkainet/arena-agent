---
name: finishing-a-feature-branch
description: Complete an issue branch by verifying tests, checking bridge health, merging into the shared Feature branch (not master), pushing to GitHub, and cleaning up. No PRs, no merge to master.
---

# Finishing a Feature Branch

## Purpose

This skill defines the end-of-life process for an issue branch: verification, merge, push, and cleanup. It enforces the rule that all completed work merges into the shared Feature branch (not master), gets pushed to GitHub, and the issue branch is deleted.

## When to Use

- After completing all tasks in an issue
- After code review findings are fully processed
- When an issue branch is ready to be merged

## When NOT to Use

- Mid-issue when tasks remain incomplete
- When the stress test is not 39/39
- When code review has unresolved Critical or Important findings
- When discarding a failed experiment (see Discard option below)

## Core Principles

### 1. Verification Before Merge Is Non-Negotiable

You do not merge until:
- Stress test passes 39/39
- Bridge health endpoint returns OK
- Code review has no unresolved Critical or Important findings
- All new code has corresponding tests

### 2. Merge Into Feature, Not Master

The Feature branch (`feature/vX.Y.Z`) is the target, not master. Master is reserved for releases. Merging to master is done separately, as a deliberate release action.

### 3. Push After Every Merge

After merging into Feature, push Feature to GitHub immediately. This ensures the remote always reflects the latest integrated state.

### 4. Delete Issue Branch After Merge

Issue branches are temporary. Once merged, delete them. This keeps the branch list clean and prevents confusion about which branches contain unmerged work.

## Process

### Step 1: Run Full Verification Suite

Before even thinking about merging, verify everything:

```bash
# 1. Run the stress test — must be 39/39
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && python -m pytest tests/stress/ -v 2>&1"}'

# 2. Check bridge health
curl -s http://localhost:8765/health

# 3. Run bridge doctor for 11 self-tests
curl -s http://localhost:8765/v1/doctor \
  -H "Authorization: Bearer $BRIDGE_TOKEN"

# 4. Check bridge metrics for error rates
curl -s http://localhost:8765/v1/metrics \
  -H "Authorization: Bearer $BRIDGE_TOKEN"

# 5. Verify no uncommitted changes
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git status --porcelain"}'
```

**If any verification fails, STOP. Fix the issue before proceeding.**

### Step 2: Present Options to the User

Before proceeding, confirm the action:

```
## Issue Branch Completion: feature/<issue-name>

### Verification Results
- Stress test: 39/39 ✓
- Bridge health: OK ✓
- Doctor self-tests: 11/11 ✓
- Metrics error rate: 0.2% ✓
- Uncommitted changes: None ✓

### Changes in This Branch
- N commits
- M files changed
- +A/-D lines

### Options
1. **Merge to Feature** — Merge feature/<issue-name> into feature/v1.7.0, push to GitHub, delete issue branch
2. **Push to GitHub only** — Push the issue branch to GitHub for backup, but don't merge yet
3. **Keep** — Leave the branch as-is for now
4. **Discard** — Delete the branch without merging (abandon this work)
```

### Step 3: Create Backup If Significant Changes

If the issue branch contains significant changes (new endpoints, refactored core, changed data structures), create a backup before merging:

```bash
# Create a backup tag on the issue branch
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git tag backup/feature/<issue-name>-$(date +%Y%m%d-%H%M%S) feature/<issue-name>"}'

# Push the backup tag
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git push origin backup/feature/<issue-name>-*"}'
```

**When to create a backup:**
- Changes to bridge core (router, middleware, auth)
- Changes to data structures (memory store, skill format)
- Changes to service configuration (NSSM, systemd)
- More than 200 lines changed
- Any change that could break the stress test on Feature

**When a backup is NOT needed:**
- Minor bug fixes (< 50 lines)
- Documentation-only changes
- Test additions without code changes

### Step 4: Merge into Feature Branch

```bash
# Switch to Feature branch
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git checkout feature/v1.7.0"}'

# Ensure Feature is up to date
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git pull origin feature/v1.7.0"}'

# Merge with a descriptive commit message
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git merge feature/<issue-name> --no-ff -m \"Merge feature/<issue-name> into feature/v1.7.0\n\n<brief description of what was accomplished>\n\nStress test: 39/39\nBridge health: OK\""}'
```

The `--no-ff` flag ensures a merge commit is always created, even if a fast-forward is possible. This preserves the history of which commits belonged to which issue.

### Step 5: Resolve Conflicts (If Any)

If the merge produces conflicts:

```bash
# List conflicted files
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git diff --name-only --diff-filter=U"}'

# For each conflicted file, examine and resolve
# Then:
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git add <resolved-file>"}'

# After all conflicts resolved:
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git commit --no-edit"}'
```

**After resolving conflicts, re-run the full verification suite from Step 1.**

### Step 6: Push Feature Branch to GitHub

```bash
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git push origin feature/v1.7.0"}'
```

### Step 7: Delete Issue Branch

```bash
# Delete local branch
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git branch -d feature/<issue-name>"}'

# Delete remote branch (if it was pushed)
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git push origin --delete feature/<issue-name> 2>/dev/null || true"}'
```

### Step 8: Verify Post-Merge State

```bash
# Run stress test on Feature branch after merge
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && python -m pytest tests/stress/ -v"}'

# Check bridge health
curl -s http://localhost:8765/health

# Run bridge doctor
curl -s http://localhost:8765/v1/doctor \
  -H "Authorization: Bearer $BRIDGE_TOKEN"

# Verify Feature branch is clean
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git status"}'
```

## Handling the "Keep" Option

If the user chooses to keep the issue branch without merging:

1. Confirm the verification results are still good
2. Note that the branch remains unmerged
3. Warn that the longer it stays unmerged, the more likely conflicts will occur when it is eventually merged
4. Optionally push the branch to GitHub for backup:

```bash
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git push origin feature/<issue-name>"}'
```

## Handling the "Discard" Option

If the user chooses to discard the issue branch:

1. Confirm this is intentional
2. Warn that this will permanently lose the work on the branch
3. Suggest creating a backup tag before deleting:

```bash
# Create a safety tag before discarding
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git tag archive/<issue-name>-$(date +%Y%m%d) feature/<issue-name>"}'

# Switch away from the issue branch first
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git checkout feature/v1.7.0"}'

# Delete the branch
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git branch -D feature/<issue-name>"}'
```

## What NEVER to Do

### Do NOT Create a Pull Request

This project does not use PRs. Merge directly into Feature and push. PRs add process overhead without benefit for a project with a single development line.

### Do NOT Merge to Master

Master is for releases. Merging to master is a separate, deliberate action performed when the Feature branch is ready for release. It is NOT part of finishing an issue branch.

### Do NOT Force-Push Feature

The Feature branch is shared. Force-pushing can lose other people's work. Use `git revert` if you need to undo a merge.

### Do NOT Skip Verification

"I'm sure it works" is not verification. Run the tests. Check the health endpoint. Use the doctor. Every time.

### Do NOT Leave Stale Branches

If an issue branch is merged, delete it immediately. Stale branches create confusion about what's been integrated and what hasn't.

## Integration with Arena-Agent Workflow

1. **using-feature-branches**: This skill is the conclusion of the branch lifecycle defined there
2. **requesting-code-review**: Review must be complete (no Critical/Important findings) before finishing
3. **receiving-code-review**: All review findings must be processed before finishing
4. **verification-before-completion**: Full verification is a prerequisite for finishing
5. **dispatching-parallel-agents**: Parallel agents must complete and integrate before the issue branch can be finished

## Quick Reference

```
# 1. Verify everything
python -m pytest tests/stress/ -v  # 39/39
GET /health                         # OK
GET /v1/doctor                      # 11/11
GET /v1/metrics                     # Low error rate
git status --porcelain              # Empty

# 2. Present options to user
Merge / Push only / Keep / Discard

# 3. Backup if significant changes
git tag backup/feature/<name>-<timestamp> feature/<name>

# 4. Merge into Feature
git checkout feature/v1.7.0
git pull origin feature/v1.7.0
git merge feature/<name> --no-ff

# 5. Resolve conflicts if any, then re-verify

# 6. Push Feature to GitHub
git push origin feature/v1.7.0

# 7. Delete issue branch
git branch -d feature/<name>

# 8. Verify post-merge
python -m pytest tests/stress/ -v  # 39/39
GET /health                         # OK
```

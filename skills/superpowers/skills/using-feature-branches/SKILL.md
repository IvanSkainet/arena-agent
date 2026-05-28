---
name: using-feature-branches
description: Manage feature branches for arena-agent development following Ivan's workflow: one shared Feature branch as the main development line, per-issue branches based off Feature (not master), sequential merges, and push after each merge. No PRs, no merging to master.
---

# Using Feature Branches

## Purpose

This skill defines the branching strategy for arena-agent development. It replaces a git-worktree-based workflow with a feature-branch workflow tailored to Ivan's specific requirements: one shared Feature branch as the main development line, per-issue branches that merge back into Feature, and strict rules about what goes where.

## When to Use

- Starting work on a new issue
- Creating a branch for a bug fix or feature
- Merging completed work back into the development line
- Setting up the project for a new development cycle

## When NOT to Use

- For hotfixes to production (those go directly to master, but this project doesn't do that yet)
- For experimental spikes that you plan to throw away (use a scratch branch)

## Core Concepts

### The Three Branch Levels

```
master (stable, release-only)
  │
  └── feature/v1.7.0 (shared Feature branch — main development line)
        │
        ├── feature/exec-timeout-fix (per-issue branch)
        ├── feature/add-doctor-endpoint (per-issue branch)
        └── issue-42-stress-test-flakes (per-issue branch)
```

**master**: The stable branch. Never commit directly to master. Only merge from Feature when a release is ready.

**feature/vX.Y.Z**: The ONE shared Feature branch. This is where all completed work accumulates. It is the base for all new issue branches. It gets pushed to GitHub after each merge.

**feature/<issue-name>** or **issue-<N>-<name>**: Per-issue branches. Created from Feature, merged back into Feature, then deleted.

### The Iron Rule: Feature Branch Is the Base

ALL new work branches off the Feature branch, NOT master. This ensures:
- Every issue branch includes all previously completed work
- Conflicts are caught at the issue level, not at the release level
- The Feature branch is always the single source of truth for in-progress work

## Process

### Step 0: Verify Clean Baseline

Before starting any new work, verify that the current Feature branch passes all tests:

```bash
# Switch to Feature branch
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git checkout feature/v1.7.0"}'

# Pull latest
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git pull origin feature/v1.7.0"}'

# Run stress tests — must be 39/39
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && python -m pytest tests/stress/ -v 2>&1 | tail -5"}'

# Check bridge health
curl -s http://localhost:8765/health
```

If the stress test is NOT 39/39, do not start new work. Fix the Feature branch first.

### Step 1: Create the Issue Branch

```bash
# From Feature branch, create a new issue branch
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git checkout -b feature/exec-timeout-fix feature/v1.7.0"}'
```

**Branch naming conventions:**

| Pattern                | Example                        | When to Use                          |
|------------------------|--------------------------------|--------------------------------------|
| `feature/<descriptive>`| `feature/exec-timeout-fix`     | New features or significant changes  |
| `issue-<N>-<name>`     | `issue-42-stress-test-flakes`  | When referencing a specific issue #  |
| `fix/<descriptive>`    | `fix/bridge-memory-leak`       | Bug fixes                            |

**Branch naming rules:**
- Lowercase, hyphens for spaces
- Descriptive but concise (3-5 words max)
- No issue numbers unless referencing a real tracker issue
- No developer names or dates

### Step 2: Implement on the Issue Branch

All work for the issue happens on the issue branch:

```bash
# Make changes and commit
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git add -A && git commit -m \"fix(exec): add timeout parameter to exec endpoint\""}'
```

**Commit message format:**
```
<type>(<scope>): <description>

[Optional body with details]

[Optional footer with references]
```

**Types:**
- `feat`: New feature or endpoint
- `fix`: Bug fix
- `refactor`: Code restructuring without behavior change
- `test`: Adding or updating tests
- `docs`: Documentation changes
- `chore`: Build, config, or tooling changes

**Scopes:** `exec`, `skills`, `memory`, `subagents`, `auth`, `bridge`, `service`, `stress`, `doctor`

### Step 3: Review and Verify Before Merge

Before merging back to Feature:

1. Run stress test (must be 39/39)
2. Run code review (see `requesting-code-review` skill)
3. Check bridge health

```bash
# Run stress test
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && python -m pytest tests/stress/ -v"}'

# Check bridge health
curl -s http://localhost:8765/health
```

### Step 4: Merge into Feature Branch

```bash
# Switch to Feature branch
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git checkout feature/v1.7.0"}'

# Merge the issue branch
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git merge feature/exec-timeout-fix --no-ff -m \"Merge feature/exec-timeout-fix into feature/v1.7.0\""}'

# Resolve conflicts if any (see Conflict Resolution below)
```

### Step 5: Push Feature Branch to GitHub

```bash
# Push Feature branch to GitHub
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git push origin feature/v1.7.0"}'
```

### Step 6: Delete the Issue Branch

```bash
# Delete local issue branch
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git branch -d feature/exec-timeout-fix"}'

# Optionally delete remote branch if it was pushed
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git push origin --delete feature/exec-timeout-fix 2>/dev/null || true"}'
```

### Step 7: Verify the Merge

```bash
# Run stress test on Feature branch after merge
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && python -m pytest tests/stress/ -v"}'

# Check bridge health
curl -s http://localhost:8765/health
```

## Sequential Merge Discipline

When multiple issues are being worked on, they must be merged into Feature **sequentially**, not in parallel. This is critical because:

1. Each merge changes the Feature branch
2. The next issue branch must be rebased on the updated Feature before merging
3. Conflicts are resolved one at a time, not in a massive merge conflict

**Correct sequence:**
```
1. Complete issue A → merge A into Feature → push Feature
2. Rebase issue B on updated Feature → complete issue B → merge B into Feature → push Feature
3. Rebase issue C on updated Feature → complete issue C → merge C into Feature → push Feature
```

**Incorrect (parallel merges):**
```
1. Start issues A, B, C simultaneously
2. Merge A, B, C into Feature at the same time → CONFLICT HELL
```

If you must work on multiple issues in parallel (see `dispatching-parallel-agents`), they must be in **independent problem domains** that don't touch the same files. Merge them one at a time.

## Conflict Resolution

When merging an issue branch into Feature produces conflicts:

```bash
# The merge will report conflicts
# Check which files are conflicted
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git status | grep both"}'

# For each conflicted file, examine both versions
# Use git diff to see the conflict markers
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git diff --name-only --diff-filter=U"}'

# Resolve each conflict by editing the file, then
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git add <resolved-file> && git commit --no-edit"}'

# After resolving all conflicts, run stress test before proceeding
```

**Conflict resolution rules:**
1. Never blindly accept "ours" or "theirs" — read both versions
2. The Feature branch version takes precedence for shared infrastructure
3. The issue branch version takes precedence for new functionality
4. When in doubt, combine both changes and test
5. Always run stress tests after resolving conflicts

## Project Setup

Before starting work, ensure the project environment is ready:

```bash
# Check Python version (3.9+ required)
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "python --version"}'

# Install dependencies if needed
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && pip install -r requirements.txt"}'

# If aiohttp is missing specifically
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "pip install aiohttp"}'

# Verify bridge is running
curl -s http://localhost:8765/health

# Verify git is configured
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "git config user.name && git config user.email"}'
```

## Cross-Platform Considerations

The arena-agent runs on Windows, Linux, and macOS. Branch operations must account for:

| Concern               | Windows                       | Linux/macOS              |
|-----------------------|-------------------------------|--------------------------|
| Path separators       | Use `pathlib.Path` or `os.path` | Same                     |
| Git bash              | Available via Git for Windows | Native                   |
| NSSM service          | Windows-only service manager  | Use systemd on Linux     |
| Line endings          | May be CRLF                   | LF                       |
| File permissions      | Not preserved in git          | Preserved                |

**Rules:**
- Always use forward slashes in git commands (works on all platforms)
- Use `os.path.join()` or `pathlib.Path` in Python code
- Add `.gitattributes` with `* text=auto` to normalize line endings
- Never assume Unix shell commands are available (use Python equivalents)

## Feature Branch Lifecycle

```
┌─────────────────────────────────────────────────────────┐
│ 1. Verify Feature branch baseline (39/39 stress test)   │
├─────────────────────────────────────────────────────────┤
│ 2. Create issue branch from Feature                     │
│    git checkout -b feature/X feature/v1.7.0             │
├─────────────────────────────────────────────────────────┤
│ 3. Implement changes on issue branch                    │
│    - Write code                                         │
│    - Write/modify tests                                 │
│    - Commit with structured messages                    │
├─────────────────────────────────────────────────────────┤
│ 4. Review and verify                                    │
│    - Code review (requesting-code-review skill)         │
│    - Process review (receiving-code-review skill)       │
│    - Stress test 39/39                                  │
│    - Bridge health OK                                   │
├─────────────────────────────────────────────────────────┤
│ 5. Merge into Feature                                   │
│    git checkout feature/v1.7.0                          │
│    git merge feature/X --no-ff                          │
├─────────────────────────────────────────────────────────┤
│ 6. Push Feature to GitHub                               │
│    git push origin feature/v1.7.0                       │
├─────────────────────────────────────────────────────────┤
│ 7. Delete issue branch                                  │
│    git branch -d feature/X                              │
├─────────────────────────────────────────────────────────┤
│ 8. Verify post-merge baseline (39/39 stress test)       │
└─────────────────────────────────────────────────────────┘
```

## Anti-Patterns to Avoid

### Branching Off Master
New issue branches must be based on Feature, not master. Master is behind Feature and doesn't contain in-progress work.

### Creating PRs
This project does not use pull requests. Merge directly into Feature and push.

### Merging to Master
Master is for releases only. All development work goes into Feature.

### Stale Issue Branches
If an issue branch sits for more than a few days without being merged, rebase it on the current Feature branch to prevent painful conflicts later.

### Multiple Shared Branches
There is exactly ONE shared Feature branch. Do not create `feature/v1.7.0-auth` and `feature/v1.7.0-exec` as separate shared branches. All work goes into one Feature branch.

### Force-Pushing Feature
Never force-push the Feature branch. It's shared. If you need to undo a merge, use `git revert`.

## Quick Reference

```
# Verify baseline
git checkout feature/v1.7.0 && git pull
python -m pytest tests/stress/ -v  # Must be 39/39

# Create issue branch
git checkout -b feature/<name> feature/v1.7.0

# Work and commit
git add -A && git commit -m "type(scope): description"

# Review and verify
python -m pytest tests/stress/ -v  # Must be 39/39
GET /health  # Must return OK

# Merge into Feature
git checkout feature/v1.7.0
git merge feature/<name> --no-ff

# Push Feature
git push origin feature/v1.7.0

# Delete issue branch
git branch -d feature/<name>

# Verify post-merge
python -m pytest tests/stress/ -v  # Must be 39/39
```

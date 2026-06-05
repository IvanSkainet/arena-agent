# Executing Plans

> **Implementation Execution Skill** — Execute an approved plan step-by-step with verification at every checkpoint. Backup first, verify always, stop when blocked.

## Purpose

Take a precise implementation plan (created by the `writing-plans` skill) and execute it faithfully. Every step is executed, verified, and recorded. If anything goes wrong, you stop and report — never push through a failure.

---

## Iron Laws

1. **BACKUP FIRST** — Before making any changes, create a backup via `POST /v1/backup`. No exceptions.
2. **VERIFY EVERY STEP** — After each step, run the step's verification. If it fails, do NOT proceed to the next step.
3. **STOP WHEN BLOCKED** — If a step fails and you can't fix it in 2 attempts, stop and ask Ivan. Do not improvise.
4. **FOLLOW THE PLAN EXACTLY** — The plan was carefully written with exact code. Execute it as written. Do not "improve" it during execution.
5. **STRESS TESTS ARE THE GATE** — After the final step, all 39/39 stress tests must pass. 38/39 = not done.

---

## Pre-Execution Checklist

Before executing the first step:

- [ ] Plan document exists at `docs/plans/YYYY-MM-DD-feature-name.md`
- [ ] Plan is approved by Ivan
- [ ] Design doc is approved by Ivan
- [ ] Current branch is clean:
  ```
  POST /v1/exec {"command": "git status --porcelain"}
  ```
  Expected: empty output
- [ ] Baseline stress tests pass:
  ```
  POST /v1/exec {"command": "python stress_test.py"}
  ```
  Expected: 39/39 PASSED
- [ ] Backup created:
  ```
  POST /v1/backup
  ```
  Expected: `{"status": "ok", "backup_id": "...", "path": "..."}`
- [ ] Record the backup ID and path for rollback

If ANY pre-execution check fails, **stop and fix the issue before proceeding.**

---

## Execution Loop

```
┌──────────────────────────┐
│  Pre-Execution Checklist  │
└────────────┬─────────────┘
             │ All pass
             ▼
┌──────────────────────────┐
│  Read Step N from Plan   │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Execute Step N          │
│  - Modify files          │
│  - Run commands          │
│  - Apply exact code      │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│  Verify Step N           │
│  - Run verification cmd  │
│  - Check expected output │
└────────────┬─────────────┘
             │
      ┌──────┼──────┐
      │      │      │
   Passed  Failed  Error
      │      │      │
      │      ▼      ▼
      │  ┌────────────────┐
      │  │ Fix attempt 1  │
      │  └───────┬────────┘
      │          │
      │     ┌────┼────┐
      │   Fixed  Still
      │          Failing
      │     │       │
      │     │       ▼
      │     │  ┌────────────────┐
      │     │  │ Fix attempt 2  │
      │     │  └───────┬────────┘
      │     │          │
      │     │     ┌────┼────┐
      │     │   Fixed  Still
      │     │          Failing
      │     │     │       │
      │     │     │       ▼
      │     │     │  ┌──────────────┐
      │     │     │  │ STOP. Report │
      │     │     │  │ to Ivan.     │
      │     │     │  └──────────────┘
      │     │     │
      ▼     ▼     │
┌─────────────────┤
│  Mark step DONE │
│  Update memory  │
└────────┬────────┘
         │
         ▼
┌────────────────────┐
│  More steps?       │
└────────┬───────────┘
         │
    ┌────┼────┐
   Yes       No
    │         │
    │         ▼
    │  ┌──────────────────┐
    │  │ Full Stress Test  │
    │  │ python stress_test│
    │  └────────┬─────────┘
    │           │
    │     ┌─────┼─────┐
    │   39/39   <39/39
    │     │       │
    │     │       ▼
    │     │  ┌────────────┐
    │     │  │ Debug and  │
    │     │  │ fix or     │
    │     │  │ STOP       │
    │     │  └────────────┘
    │     │
    ▼     ▼
┌──────────────────┐
│  Commit changes   │
│  Report complete  │
└──────────────────┘
```

---

## Step Execution Protocol

For each step in the plan:

### 1. Read the Step
Re-read the step from the plan document. Confirm you understand:
- What files to modify
- What exact code to write
- What command to run
- What verification to perform

### 2. Execute

Use bridge exec for all operations:

```python
# Modify a file
POST /v1/exec
{
  "command": "python -c \"\ncontent = '''<exact code>'''\nfrom pathlib import Path\nPath('path/to/file.py').write_text(content, encoding='utf-8')\n\""
}

# Or use sed for targeted edits
POST /v1/exec
{
  "command": "python -c \"\nfrom pathlib import Path\np = Path('path/to/file.py')\ntext = p.read_text(encoding='utf-8')\ntext = text.replace('old_line', 'new_line')\np.write_text(text, encoding='utf-8')\n\""
}
```

**Cross-platform note**: Always use Python for file operations rather than `sed`, `awk`, or PowerShell — those are OS-specific. `pathlib.Path` works everywhere.

### 3. Verify

Run the step's verification command:

```python
POST /v1/exec
{
  "command": "python -m pytest tests/test_feature.py::test_specific -v"
}
```

**Check the output exactly**:
- If expected: `PASSED` → output contains "PASSED" → ✅
- If expected: specific value → output matches exactly → ✅
- If expected: no errors → exit code is 0 → ✅
- Otherwise → ❌ → attempt fix

### 4. Record

After successful verification:

```python
# Store progress in memory
POST /v1/memory
{
  "key": "plan:feature-name:progress",
  "value": "Step N of M complete. Verified: <what was verified>",
  "tags": ["plan", "progress", "feature-name"]
}
```

---

## Handling Failures

### Step Verification Failed

1. **Read the error output carefully** — Don't guess. Read the actual error message.
2. **Compare to expected** — What was supposed to happen? What actually happened?
3. **Attempt Fix 1** — Make a targeted correction based on the error
4. **Re-verify** — Run the verification again
5. **If still failing, Attempt Fix 2** — Try a different approach
6. **If still failing, STOP** — Report to Ivan with:
   - What step failed
   - What the error was (exact output)
   - What you tried to fix it
   - What you think the root cause might be

**DO NOT**:
- Skip the step and continue
- Change the plan without Ivan's approval
- Make unrelated changes hoping they'll fix it
- Spend more than 2 attempts on a fix without asking for help

### Unexpected Side Effects

If a step causes an unexpected side effect (e.g., a different test breaks):

1. **Record the side effect** — What changed that wasn't expected?
2. **Check if it's related** — Is the broken test testing related functionality?
3. **Attempt Fix 1** — Adjust the step to avoid the side effect
4. **If still broken, STOP** — Report to Ivan

### Service Crashes

If the bridge service crashes during execution:

1. **DO NOT** use PowerShell `Restart-Service` or `systemctl restart`
2. **DO NOT** use `sc query` directly (Russian locale output issues)
3. **Use the bridge API**: `POST /v1/restart`
4. If the API is down (service crashed), restart via:
   - **Windows**: `POST /v1/exec {"command": "nssm restart arena-bridge"}`
   - **Linux**: `POST /v1/exec {"command": "sudo systemctl restart arena-bridge"}`
   - **macOS**: `POST /v1/exec {"command": "launchctl kickstart -k system/arena-bridge"}`
5. After restart, re-run the verification for the current step

---

## Bridge Service Management

### Restarting the Service

**Preferred method** (always try first):
```
POST /v1/restart
```

**Fallback methods** (only if bridge API is unreachable):

| OS | Command |
|---|---|
| Windows (NSSM) | `nssm restart arena-bridge` |
| Windows (sc) | `sc stop arena-bridge && timeout /t 3 && sc start arena-bridge` |
| Linux (systemd) | `sudo systemctl restart arena-bridge` |
| macOS (launchd) | `launchctl kickstart -k system/arena-bridge` |

**Russian locale warning**: `sc query` on Russian Windows outputs Cyrillic text (e.g., "Работает" instead of "RUNNING"). Parse output by state codes (1=stopped, 2=starting, 3=stopping, 4=running) rather than text.

### Creating Backups

```
POST /v1/backup
```

Returns:
```json
{
  "status": "ok",
  "backup_id": "20250315-143022",
  "path": "/path/to/backups/20250315-143022"
}
```

**When to backup**:
- Before starting execution (mandatory)
- Before any risky step (recommended)
- After every 5 steps (checkpoint)

### Health Checks

```
GET /v1/doctor
```

Returns:
```json
{
  "status": "healthy",
  "checks": {
    "api": "ok",
    "auth": "ok",
    "filesystem": "ok",
    "memory": "ok"
  }
}
```

**Run after**:
- Restarting the service
- Modifying configuration files
- Steps that affect the bridge core

---

## Commit Protocol

After all steps are complete and stress tests pass:

### 1. Stage and Review
```python
POST /v1/exec {"command": "git diff --stat"}
```

Confirm the changed files match the plan.

### 2. Stage
```python
POST /v1/exec {"command": "git add -A"}
```

### 3. Commit
Use the commit message from the plan:
```python
POST /v1/exec {"command": "git commit -m \"feat: <description>\n\n<optional body>\n\nRefs: docs/specs/YYYY-MM-DD-topic-design.md\""}
```

### 4. Verify Commit
```python
POST /v1/exec {"command": "git log -1 --oneline"}
```

Confirm the commit message is correct.

---

## Progress Reporting

After each step (or every 3 steps for long plans), provide Ivan with:

```markdown
## Progress: Step N of M

**Completed**: Steps 1-N
**Current**: Step N+1 — <description>
**Blocked**: No / Yes — <reason>
**Stress tests**: Last run at Step N — 39/39 ✅

### What was done:
- Step 1: <summary> ✅
- Step 2: <summary> ✅
- Step N: <summary> ✅

### Next:
- Step N+1: <what's coming>
```

---

## Rollback Protocol

If execution needs to be abandoned:

### Full Rollback
```python
# Discard all uncommitted changes
POST /v1/exec {"command": "git checkout -- ."}

# Verify clean state
POST /v1/exec {"command": "git status --porcelain"}

# Verify stress tests still pass
POST /v1/exec {"command": "python stress_test.py"}
```

### Partial Rollback (to a checkpoint)
If you created intermediate backups or commits:

```python
# Find the last good commit
POST /v1/exec {"command": "git log --oneline -10"}

# Reset to that commit
POST /v1/exec {"command": "git reset --hard <commit-hash>"}

# Verify stress tests
POST /v1/exec {"command": "python stress_test.py"}
```

---

## Anti-Patterns

### ❌ "I'll Skip This Verification — It's Obviously Fine"
```
No. Verification exists because things that are "obviously fine" often
aren't. Run it. Every time. No exceptions.
```

### ❌ "The Plan Is Wrong, I'll Fix It My Way"
```
If the plan has an error, STOP and ask Ivan. Do not silently "fix" the
plan during execution. The plan was approved; changes need approval too.
```

### ❌ "I'll Batch Multiple Steps Together"
```
No. Execute one step at a time, verify, then proceed. Batching hides
which step caused a failure and makes rollback harder.
```

### ❌ "38/39 Is Close Enough"
```
It's not. One failing test means something is broken. The 39th test
might be testing the exact feature you just implemented. Fix it.
```

---

## Integration with Other Skills

| Before This Skill | Required Output |
|---|---|
| `brainstorming` | Approved design document |
| `writing-plans` | Approved implementation plan |

| After This Skill | Trigger |
|---|---|
| `systematic-debugging` | Step verification fails after 2 attempts |
| `test-driven-development` | Need to write tests for uncovered code |
| `brainstorming` | Execution reveals the design is flawed |

---

## Summary

| Principle | Rule |
|---|---|
| **Backup first** | `POST /v1/backup` before any changes |
| **One step at a time** | Execute → verify → record → next |
| **2 attempts max** | Then stop and ask Ivan |
| **Follow the plan** | No improvisation during execution |
| **Bridge API for management** | `POST /v1/restart`, never direct OS commands first |
| **39/39 stress tests** | Non-negotiable final gate |
| **Progress reporting** | Keep Ivan informed at regular intervals |
| **Rollback ready** | Know how to undo any change |

---
name: verification-before-completion
description: Enforce the Iron Law that no task or issue may be marked complete without FRESH verification evidence. Uses bridge health, stress tests, doctor self-tests, and metrics to provide concrete proof of correctness. Includes rationalization prevention and common failure tables adapted for bridge context.
---

# Verification Before Completion

## Purpose

The Iron Law of arena-agent development: **No task or issue may be marked complete without FRESH verification evidence.** "I think it works" is not evidence. "The test passed three hours ago" is not fresh. This skill defines what constitutes valid verification, how to gather it, and how to resist the rationalizations that lead to false completion claims.

## When to Use

- Before marking any task as complete
- Before merging an issue branch into Feature
- Before claiming a bug is fixed
- Before reporting progress to the user
- Before closing an issue

## When NOT to Use

- During active development (verify after, not during)
- For planning or brainstorming (no code to verify yet)

## The Iron Law

**NO completion claims without FRESH verification evidence.**

Definitions:
- **Completion claim**: Any statement that a task is done, a bug is fixed, or an issue is resolved
- **FRESH**: Verification that was run AFTER the last code change, on the current branch, with the bridge running
- **Verification evidence**: Concrete, reproducible proof that the system works as expected

## Verification Hierarchy

From fastest to most thorough:

### Level 1: Quick Check (10 seconds)

```bash
# Bridge health
curl -s http://localhost:8765/health
# Expected: {"status": "ok"} or similar

# Process running
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "echo bridge-ok"}'
# Expected: {"stdout": "bridge-ok", "returncode": 0}
```

**Use for**: Sanity check between tasks, confirming bridge didn't crash during a change

### Level 2: Targeted Test (30 seconds)

```bash
# Run the specific test that covers the change
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && python -m pytest tests/test_exec.py -v -k test_timeout"}'
```

**Use for**: After fixing a specific bug, after adding a specific feature

### Level 3: Doctor Self-Tests (1 minute)

```bash
# Run all 11 bridge doctor self-tests
curl -s http://localhost:8765/v1/doctor \
  -H "Authorization: Bearer $BRIDGE_TOKEN"
```

The doctor checks:
1. Bridge process is running
2. Health endpoint responds
3. Exec endpoint works
4. Skills endpoint lists skills
5. Memory read/write works
6. Auth token is valid
7. Audit log is accessible
8. Subagent system is functional
9. Configuration is valid
10. File system permissions are correct
11. Network ports are available

**Use for**: After any change that could affect bridge internals, before merging to Feature

### Level 4: Metrics Check (30 seconds)

```bash
# Check bridge metrics for error rates
curl -s http://localhost:8765/v1/metrics \
  -H "Authorization: Bearer $BRIDGE_TOKEN"
```

Look for:
- Error rate < 1% (spikes indicate problems)
- Request latency within normal range
- Memory usage stable (not growing)
- No 500 errors

**Use for**: After any change that could affect performance or reliability

### Level 5: Full Stress Test (5-10 minutes)

```bash
# Run the complete stress test suite
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && python -m pytest tests/stress/ -v 2>&1"}'
```

**Must be 39/39 (or updated count if tests were added/removed).**

**Use for**: Before merging to Feature, after any significant change, before reporting an issue as complete

### Level 6: Cross-Platform Verification (manual)

Test on Windows, Linux, and macOS if the change affects:
- File paths
- Process management
- Service configuration (NSSM/systemd)
- Shell command execution
- Line endings

**Use for**: Changes that touch platform-specific code

## Verification Protocol

For each task completion claim:

| Task Complexity | Required Verification Level |
|-----------------|-----------------------------|
| Comment/doc change | Level 1 (quick check) |
| Single-file fix | Level 2 (targeted test) |
| Multi-file fix | Level 3 (doctor) |
| New endpoint | Level 3 + Level 5 (doctor + stress) |
| Core refactoring | Level 3 + Level 4 + Level 5 |
| Merge to Feature | Level 3 + Level 4 + Level 5 |
| Any task before reporting done | Level 5 (stress test) |

## Rationalization Prevention Table

The mind will try to skip verification. Here are the common rationalizations and their antidotes:

| Rationalization                                  | Why It's Wrong                                          | Required Action                          |
|--------------------------------------------------|---------------------------------------------------------|------------------------------------------|
| "I only changed a comment"                       | Even comments can break doc parsing or string literals  | Level 1 quick check                      |
| "The test passed earlier"                        | Not FRESH — subsequent changes may have broken it       | Re-run the test NOW                      |
| "It works on my machine"                         | Bridge runs on Linux server too; your machine ≠ server  | Run via bridge exec, not locally         |
| "The change is too small to break anything"      | Small changes cause some of the worst bugs              | Run the targeted test at minimum         |
| "I'll verify after I finish the next task"       | If the current task is broken, the next builds on sand  | Verify NOW, then proceed                 |
| "The CI will catch it"                           | There is no CI; you are the CI                          | Run the stress test yourself             |
| "It's just a refactor, no behavior change"       | Refactors can subtly change behavior                    | Run the full test suite                  |
| "I reviewed the code carefully"                  | Code review ≠ runtime verification                      | Run it. Watch it pass.                   |
| "The stress test takes too long"                 | 5-10 minutes is not too long for confidence             | Run it while you plan the next task      |
| "I'm confident it works"                         | Confidence is not evidence                              | Produce evidence                         |
| "The reviewer already checked"                   | Reviewers verify logic, not runtime behavior            | Run the tests yourself                   |
| "It was working before my change"               | That means your change broke it                         | Find and fix the regression              |

## Common Failures Table (Bridge Context)

Specific failure modes that verification must catch:

| Failure Mode                          | Symptom                                          | Verification That Catches It        |
|---------------------------------------|--------------------------------------------------|--------------------------------------|
| Bridge process crashed                | Health endpoint returns connection refused        | Level 1: GET /health                 |
| Token expired                         | 401 Unauthorized on authenticated endpoints      | Level 1: POST /v1/exec               |
| Port conflict                         | Bridge fails to start, 8765 occupied             | Level 1: GET /health                 |
| Exec command injection                | Unexpected command execution                     | Level 5: Stress test security tests   |
| Memory leak in bridge                 | Growing memory usage in metrics                  | Level 4: GET /v1/metrics             |
| Skill loading failure                 | GET /v1/skills returns empty or partial list     | Level 3: Doctor skill check          |
| Audit log not writing                 | GET /v1/audit returns stale data                 | Level 3: Doctor audit check          |
| Subagent spawn failure                | POST /v1/subagents/spawn returns error           | Level 3: Doctor subagent check       |
| Cross-platform path issue             | Windows: file not found with Unix paths          | Level 6: Cross-platform test         |
| NSSM service misconfiguration         | Bridge doesn't start as Windows service          | Level 6: Windows-specific test       |
| Race condition in concurrent requests | Intermittent 500 errors under load               | Level 5: Stress test                 |
| Russian locale error messages         | Cyrillic characters garbled in responses         | Level 5: Stress test locale tests     |
| Stale git branch                      | Merging outdated branch causes conflicts          | Level 1: git status, git log          |
| Uncommitted changes                   | git status shows modifications                   | Level 1: git status --porcelain       |
| Stress test regression                | Previously passing test now fails                | Level 5: Full stress test             |
| Dependency version conflict           | ImportError or ModuleNotFoundError                | Level 2: python -c "import module"    |
| Config file syntax error              | Bridge fails to parse config on startup          | Level 3: Doctor config check         |
| File permission issue                 | Cannot write to log/audit directory              | Level 3: Doctor filesystem check     |

## Verification Checklist Template

Before marking any task as complete, fill out this checklist:

```
## Verification Checklist

**Task**: [task name]
**Branch**: feature/<branch-name>
**Date/Time**: [when verification was run]

### Fresh Evidence
- [ ] Quick check: GET /health returns OK (timestamp: ___)
- [ ] Targeted test: [test name] passes (timestamp: ___)
- [ ] Doctor: 11/11 self-tests pass (timestamp: ___)
- [ ] Metrics: Error rate < 1%, no 500s (timestamp: ___)
- [ ] Stress test: 39/39 pass (timestamp: ___)
- [ ] Cross-platform: Tested on [platforms] (if applicable)

### Change Verification
- [ ] git diff shows only expected changes
- [ ] No unintended file modifications
- [ ] No debug code left in (print statements, TODO hacks)
- [ ] No hardcoded test values in production code

### Integration Verification
- [ ] Bridge starts cleanly after changes
- [ ] Existing endpoints still work (exec, skills, memory, etc.)
- [ ] No new warnings in bridge logs
- [ ] Audit log captures the new behavior (if applicable)

### Rationalization Check
- [ ] I did NOT skip any verification level
- [ ] I did NOT use "it worked earlier" as evidence
- [ ] I ran the stress test AFTER the last code change
- [ ] I am reporting actual test output, not assumed results
```

## Process

### Step 1: Determine Required Verification Level

Based on the task complexity table above, determine which verification levels are required.

### Step 2: Run Verification from Level 1 Up

Always start with the quick check. If Level 1 fails, stop and fix. There's no point running the stress test if the bridge isn't even running.

```bash
# Level 1: Quick check
curl -s http://localhost:8765/health

# If OK, proceed to Level 2+
```

### Step 3: Document Results with Timestamps

For each verification, record:
- What was run
- The result (pass/fail)
- The exact output (or a summary for long outputs)
- The timestamp

```
Level 1: GET /health → {"status": "ok"} → PASS (2024-01-15 14:32:01)
Level 2: pytest test_exec.py::test_timeout → PASSED (2024-01-15 14:32:15)
Level 3: GET /v1/doctor → 11/11 checks pass → PASS (2024-01-15 14:33:02)
Level 4: GET /v1/metrics → error_rate: 0.1%, p99_latency: 45ms → PASS (2024-01-15 14:33:08)
Level 5: pytest tests/stress/ → 39/39 passed → PASS (2024-01-15 14:38:44)
```

### Step 4: If Any Level Fails

1. **STOP**. Do not claim completion.
2. Diagnose the failure.
3. Fix the issue.
4. Re-run ALL verification levels from Level 1 up (not just the one that failed).
5. Document the fix and re-verification.

### Step 5: Claim Completion Only with Evidence

When all required verification levels pass:

```
## Task Complete: [task name]

### Verification Evidence
- Level 1: GET /health OK (14:32:01)
- Level 2: test_timeout PASSED (14:32:15)
- Level 3: Doctor 11/11 (14:33:02)
- Level 4: Metrics error_rate 0.1% (14:33:08)
- Level 5: Stress test 39/39 (14:38:44)

### Changes Made
- process_manager.py: Added timeout parameter to run_command()
- routes/exec.py: Pass timeout from request body
- tests/test_exec.py: Added test_timeout() test case

### Known Limitations
- None
```

## Anti-Patterns to Avoid

### Stale Verification
Running the stress test, then making "one small change" and claiming verification is still valid. It's not. Re-run after every change.

### Selective Verification
Running only the tests you know will pass and skipping the ones that might fail. Run ALL required levels.

### Aspirational Verification
Writing "Level 5: Stress test 39/39" without actually running it. This is lying. Run it.

### Proxy Verification
"Code review passed, so the tests must pass." Code review verifies logic, not runtime behavior. Run the tests.

### Verification Theater
Running `echo "OK"` via exec and calling it a health check. Use the actual health endpoint.

## Integration with Arena-Agent Workflow

1. **requesting-code-review**: Verification happens before review (you need tests to pass to show the reviewer)
2. **receiving-code-review**: After implementing review fixes, re-verify before claiming the fix is done
3. **using-feature-branches**: Verification is a prerequisite for merging into Feature
4. **finishing-a-feature-branch**: Full verification is required at the merge gate
5. **dispatching-parallel-agents**: Each agent must verify its own work before you integrate it

## Quick Reference

```
# Level 1: Quick check (10s)
GET /health → must return OK
POST /v1/exec {"command": "echo ok"} → must return ok

# Level 2: Targeted test (30s)
python -m pytest tests/test_<feature>.py -v

# Level 3: Doctor (1m)
GET /v1/doctor → 11/11 checks

# Level 4: Metrics (30s)
GET /v1/metrics → error_rate < 1%, no 500s

# Level 5: Stress test (5-10m)
python -m pytest tests/stress/ -v → 39/39

# Level 6: Cross-platform (manual)
Test on Windows + Linux + macOS

# IRON LAW: No completion without FRESH evidence.
# If you didn't run it AFTER your last change, it's not evidence.
```

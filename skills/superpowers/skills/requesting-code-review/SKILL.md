---
name: requesting-code-review
description: Request structured code reviews via bridge audit log verification, leveraging subagent reviewer templates and severity-based blocking. Ensures every task output is reviewed before proceeding in the arena-agent development workflow.
---

# Requesting Code Review

## Purpose

Every completed task in arena-agent development must undergo code review before it is considered done. This skill defines the structured process for requesting reviews, gathering evidence from the bridge audit log, and interpreting reviewer feedback with clear severity levels that gate further progress.

## When to Use

- After completing any task in subagent-driven development
- Before merging an issue branch into the Feature branch
- After fixing a bug or implementing a new bridge endpoint
- After modifying stress tests or the bridge core
- When you are uncertain about a change and want a second set of eyes

## When NOT to Use

- During active brainstorming or planning (review happens after implementation)
- For trivial whitespace or comment-only changes (use your judgment)
- When you are the sole reviewer and the change is mechanically correct (e.g., renaming a variable across all references)

## Core Principles

### 1. Review Is a Gate, Not a Suggestion

A task is not complete until it has been reviewed. The review outcome determines whether you can proceed:

| Severity    | Meaning                              | Action                          |
|-------------|--------------------------------------|----------------------------------|
| Critical    | Bug, security hole, data loss risk   | Blocks progress. Fix immediately.|
| Important   | Wrong approach, missing edge case    | Fix before proceeding further.   |
| Minor       | Style, naming, future improvement    | Note for later. Does not block.  |

### 2. Evidence-Based Review

Never review from memory alone. Use the bridge audit log to verify what actually changed:

```bash
# Get the full diff for the current task via bridge exec
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "git diff HEAD~1 --stat"}'

# Get the actual diff content
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "git diff HEAD~1"}'

# Get the commit SHA for precise review scope
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "git rev-parse HEAD"}'
```

### 3. Review After Each Task, Not Each Issue

In subagent-driven development, an issue may contain multiple tasks. Review after each task completes, not just at the end. This prevents cascading failures where one bad task corrupts subsequent tasks that depend on it.

## Process

### Step 1: Prepare Review Context

Before requesting a review, gather the following information:

1. **What changed**: Use bridge exec to get the git diff
2. **Why it changed**: Reference the task description or issue number
3. **What was the baseline**: The commit SHA before your changes
4. **Test results**: Run the stress test and capture the output

```bash
# Capture current state
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "git log --oneline -5"}'

# Run stress test to establish test baseline
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && python -m pytest tests/stress/ -v --tb=short 2>&1 | tail -20"}'
```

### Step 2: Formulate the Review Request

Present a structured review request that includes:

```
## Review Request

**Task**: [Task name or number]
**Issue Branch**: feature/<issue-name>
**Base SHA**: <commit SHA before changes>
**Files Changed**: [list of modified files]
**Lines Changed**: [+N/-M]

### What I Did
[Concise description of the implementation]

### Why I Did It This Way
[Design rationale, alternatives considered]

### What I'm Unsure About
[Specific areas where reviewer attention is needed]

### Test Results
[Stress test output: X/39 passed]

### Bridge Health
[GET /health output]
```

### Step 3: Spawn a Code Reviewer Subagent

Use the bridge subagent API to spawn a dedicated reviewer:

```bash
curl -s -X POST http://localhost:8765/v1/subagents/spawn \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "role": "code-reviewer",
    "prompt": "Review the changes on branch feature/<issue-name> since commit <base-sha>.\n\nFocus areas:\n1. Correctness: Does the code do what it claims?\n2. Edge cases: Are boundary conditions handled?\n3. Bridge compatibility: Does it work with the HTTP API on port 8765?\n4. Cross-platform: Will it work on Windows, Linux, and macOS?\n5. Russian locale: Are error messages and logs properly localized if needed?\n6. Security: Any token handling or injection issues?\n\nSeverity levels:\n- Critical: Blocks further work. Must fix now.\n- Important: Fix before proceeding to next task.\n- Minor: Note for future improvement.\n\nFiles to review:\n- <file1>\n- <file2>\n\nProvide findings with severity, file, line, and reasoning."
  }'
```

### Step 4: Verify Changes Against Audit Log

Cross-reference the review findings with the bridge audit log:

```bash
# Query audit log for recent changes
curl -s http://localhost:8765/v1/audit \
  -H "Authorization: Bearer $BRIDGE_TOKEN"

# Filter for specific time range or operation
curl -s "http://localhost:8765/v1/audit?since=2024-01-01T00:00:00Z" \
  -H "Authorization: Bearer $BRIDGE_TOKEN"
```

The audit log provides an independent record of what the bridge actually did, which can confirm or contradict the git diff. Discrepancies indicate uncommitted changes or side effects.

### Step 5: Process Review Findings

Organize findings by severity and address them in order:

1. **Critical findings**: Fix immediately. Do not proceed with any other work.
2. **Important findings**: Fix before starting the next task in the issue.
3. **Minor findings**: Record in a TODO comment or issue note. Do not fix now.

For each finding, document:
- What the reviewer found
- What you did about it (fixed, deferred, pushed back with reasoning)
- Verification that the fix works

### Step 6: Re-Review After Fixes

If Critical or Important findings were fixed, request a follow-up review of just the fix:

```bash
# Get diff of just the fix commit
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "git diff HEAD~1"}'
```

Minor findings do not require re-review.

## Code Reviewer Subagent Template

When spawning a code reviewer subagent, use this template as the system prompt:

```
You are a code reviewer for the arena-agent project.

## Your Role
Review code changes for correctness, safety, and adherence to project standards.

## Review Checklist
- [ ] Does the code do what the commit message says?
- [ ] Are there unhandled edge cases (empty inputs, None values, network failures)?
- [ ] Does the code work with the bridge HTTP API (POST /v1/exec, etc.)?
- [ ] Is the code cross-platform (Windows/Linux/macOS)?
  - [ ] No Unix-only paths (use pathlib or os.path)
  - [ ] No Unix-only commands without Windows fallback
  - [ ] Proper line ending handling
- [ ] Are error messages locale-aware (Russian support)?
- [ ] Is token/auth handling secure?
- [ ] Are there any injection vulnerabilities in exec commands?
- [ ] Does the code maintain stress test compatibility (39/39)?
- [ ] Is the code consistent with existing patterns in the codebase?
- [ ] Are there magic numbers or hardcoded values that should be constants?

## Severity Definitions
- **Critical**: Bug that causes data loss, security vulnerability, or crash. Blocks all further work.
- **Important**: Logic error, missing edge case, or wrong approach. Fix before next task.
- **Minor**: Style issue, naming concern, or future improvement idea. Note only.

## Output Format
For each finding:
1. **Severity**: Critical / Important / Minor
2. **File**: path/to/file.py
3. **Line**: N (or range N-M)
4. **Issue**: What's wrong
5. **Reasoning**: Why this is a problem
6. **Suggestion**: How to fix it (be specific)

If no issues found, say "No issues found. Changes look correct."
```

## Common Review Scenarios

### Scenario: New Bridge Endpoint

When reviewing a new bridge endpoint, check:
- Route is registered in the router
- Token authentication is enforced
- Request validation with clear error messages
- Response format matches existing endpoints
- Error handling covers malformed input
- Stress test covers the new endpoint
- Cross-platform: no OS-specific assumptions in handler

### Scenario: Bug Fix

When reviewing a bug fix, check:
- The fix addresses the root cause, not just the symptom
- The fix doesn't introduce a new bug
- Edge cases that triggered the original bug are now tested
- The fix is minimal — no unrelated changes bundled in

### Scenario: Refactoring

When reviewing a refactoring, check:
- Behavior is preserved (no functional changes)
- All existing tests still pass
- No dead code introduced
- No performance regression

## Anti-Patterns to Avoid

### Requesting Review Too Late
Don't wait until the entire issue is complete to request a review. Review after each task. Late reviews find more problems that are harder to fix because subsequent work depends on the flawed code.

### Vague Review Requests
"Please review my changes" is useless. Specify what changed, why, and what you're uncertain about.

### Ignoring Audit Log Discrepancies
If the git diff shows one thing but the audit log shows another, investigate. This usually means uncommitted changes, side effects, or a stale working directory.

### Treating All Findings Equally
A Minor finding about variable naming does not justify blocking progress. A Critical finding about an SQL injection does. Apply severity consistently.

### Reviewing Your Own Code
If you wrote it, you can't review it impartially. Use the subagent system to get an independent review. Even if you're working alone, the reviewer subagent provides structured analysis that you might skip.

## Integration with Arena-Agent Workflow

This skill integrates with the broader arena-agent development workflow as follows:

1. **using-feature-branches**: Create issue branch → implement task → request review
2. **receiving-code-review**: Process the review findings from this skill's output
3. **verification-before-completion**: After review fixes, run full verification
4. **finishing-a-feature-branch**: After all tasks reviewed and verified, merge to Feature

## Quick Reference

```
# 1. Gather context
bridge exec: git diff HEAD~1 --stat
bridge exec: git rev-parse HEAD

# 2. Run tests
bridge exec: python -m pytest tests/stress/ -v

# 3. Check bridge health
GET /health

# 4. Spawn reviewer
POST /v1/subagents/spawn { role: "code-reviewer", prompt: <review-template> }

# 5. Cross-reference audit log
GET /v1/audit

# 6. Process findings by severity
Critical → fix now
Important → fix before next task
Minor → note for later

# 7. Re-review if Critical/Important fixes were made
```

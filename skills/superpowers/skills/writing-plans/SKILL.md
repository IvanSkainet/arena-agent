# Writing Plans

> **Implementation Planning Skill** — Transform an approved design into a precise, step-by-step implementation plan with exact code, paths, and commands. Zero placeholders. Zero ambiguity.

## Purpose

An approved design document describes **what** to build. This skill creates the **exact plan** for building it — every file to touch, every line to write, every command to run. The plan must be so precise that any agent (or human) could execute it without making a single design decision.

---

## Iron Laws

1. **NO PLACEHOLDERS** — Every code block, path, and command must be exact. No `...`, no `TODO`, no `<fill in later>`, no `// implementation here`.
2. **BITE-SIZED STEPS** — Each step should take 2-5 minutes to execute. If a step takes longer, split it.
3. **DESIGN MUST BE APPROVED** — Never write a plan for an unapproved design. The brainstorming skill's Hard Gate must be passed first.
4. **SELF-REVIEW BEFORE DELIVERY** — Review your own plan for completeness, correctness, and consistency before presenting it.
5. **EXACT VERIFICATION** — Every step must have a verification method. "It should work" is not verification.

---

## Prerequisites

Before writing a plan, confirm:

- [ ] The design document exists at `docs/specs/YYYY-MM-DD-topic-design.md`
- [ ] Ivan has explicitly approved the design
- [ ] You have read the design document in full
- [ ] You have current project context: `GET /v1/inventory`
- [ ] You have recent change context: `GET /v1/audit`
- [ ] You understand the current test baseline: `python stress_test.py` (all 39 should pass)

If any prerequisite is missing, **stop** and resolve it before proceeding.

---

## Plan Document Template

Save to: `docs/plans/YYYY-MM-DD-feature-name.md`

**Example**: `docs/plans/2025-03-15-websocket-reconnect.md`

```markdown
# Plan: <Feature Name>

**Date**: YYYY-MM-DD
**Design Doc**: docs/specs/YYYY-MM-DD-topic-design.md
**Status**: DRAFT | READY | IN-PROGRESS | COMPLETE
**Ivan Approval**: <pending>

---

## Overview

<1-3 sentences: what this plan implements, referencing the approved design>

## Pre-Flight Checks

- [ ] All 39 stress tests pass (baseline)
- [ ] Design doc is approved by Ivan
- [ ] Current branch is clean (`git status` shows no changes)
- [ ] Backup created (`POST /v1/backup`)

## Steps

### Step 1: <Action Title>
**Time estimate**: 2-5 min

**What**: <Precise description of what to do>

**Files to modify**:
- `path/to/file.py` — <what changes and why>

**Exact code**:
```python
# Full, exact code to write/modify. No placeholders.
```

**Command to execute**:
```
POST /v1/exec {"command": "python -c '...'"}
```

**Verification**:
```
POST /v1/exec {"command": "python -m pytest tests/test_x.py::test_y -v"}
```
Expected output: `<exact expected output or pattern>`

---

### Step 2: <Action Title>
<Same structure as Step 1>

---

## Post-Implementation Verification

- [ ] All 39 stress tests pass
- [ ] Manual check: <specific manual verification>
- [ ] `GET /v1/doctor` returns healthy status
- [ ] No new lint warnings

## Commit Plan

Commit messages follow arena-agent convention:

```
feat: <short description of the feature>

<optional longer description>

Refs: docs/specs/YYYY-MM-DD-topic-design.md
```

If fixing a bug:
```
fix: <short description of the fix>
```

If refactoring:
```
refactor: <short description>
```

## Rollback Plan

If anything goes wrong:
1. `git checkout -- .` (discard uncommitted changes)
2. Or restore from backup: locate most recent backup from `POST /v1/backup`
3. Verify stress tests still pass after rollback
```

---

## Step Granularity Rules

A step is the right size when:

✅ It can be described in one sentence
✅ It touches 1-3 files maximum
✅ It can be verified independently
✅ It takes 2-5 minutes to execute
✅ Reverting it is straightforward

A step is TOO BIG when:

❌ It touches more than 3 files → Split into multiple steps
❌ It combines "add function" + "add test" + "update config" → Split by concern
❌ It says "implement the feature" → That's the whole plan, not a step
❌ It would take more than 5 minutes → Split further

A step is TOO SMALL when:

❌ It's just "open a file" → Combine with the edit
❌ It's just "add a blank line" → Combine with surrounding edits
❌ It doesn't have independent verification → Merge with related step

---

## Exact Code Requirement

### ❌ BAD: Placeholders
```python
def handle_reconnect():
    # TODO: implement reconnection logic
    ...
```

### ❌ BAD: Pseudocode
```python
def handle_reconnect():
    # wait for backoff period
    # attempt connection
    # if fails, retry
```

### ❌ BAD: Partial Code
```python
def handle_reconnect():
    backoff = calculate_backoff(...)
    # ... rest of implementation
```

### ✅ GOOD: Exact, Complete Code
```python
def handle_reconnect(self) -> None:
    """Attempt to reconnect with exponential backoff and jitter."""
    import random
    for attempt in range(self.max_retries):
        backoff = min(
            self.base_delay * (2 ** attempt) + random.uniform(0, 1),
            self.max_delay
        )
        time.sleep(backoff)
        try:
            self._connect()
            logger.info(f"Reconnected on attempt {attempt + 1}")
            return
        except ConnectionError:
            logger.warning(f"Reconnect attempt {attempt + 1} failed")
    raise ConnectionError(f"Failed to reconnect after {self.max_retries} attempts")
```

---

## Verification Methods

Every step MUST include one of these verification methods:

### Method 1: Unit Test
```
POST /v1/exec {"command": "python -m pytest tests/test_reconnect.py::test_backoff_calculation -v"}
```
Expected: `PASSED`

### Method 2: Stress Test Subset
```
POST /v1/exec {"command": "python -m pytest stress_test.py::test_connection_resilience -v"}
```
Expected: `PASSED`

### Method 3: Command Output Check
```
POST /v1/exec {"command": "python -c \"from bridge.reconnect import ReconnectHandler; print(ReconnectHandler.__module__)\""}
```
Expected: `bridge.reconnect`

### Method 4: API Endpoint Check
```
GET /v1/doctor
```
Expected: `{"status": "healthy", ...}`

### Method 5: File Existence Check
```
POST /v1/exec {"command": "python -c \"from pathlib import Path; assert Path('bridge/reconnect.py').exists()\""}
```
Expected: No assertion error

### Method 6: Full Stress Test Suite
```
POST /v1/exec {"command": "python stress_test.py"}
```
Expected: `39/39 PASSED`

**After the last step, Method 6 is MANDATORY.**

---

## Self-Review Checklist

After writing the plan, review it against this checklist BEFORE presenting to Ivan:

### Completeness
- [ ] Every file mentioned in the design doc has a corresponding step
- [ ] Every API change from the design doc is addressed
- [ ] Every cross-platform consideration from the design doc is handled
- [ ] Tests are planned for every new/modified behavior
- [ ] Error handling is addressed for every new code path

### Correctness
- [ ] Every code block is syntactically valid Python (or the appropriate language)
- [ ] Every file path is correct and uses `pathlib.Path` or `/` separators
- [ ] Every command is runnable as-is (no missing dependencies or setup)
- [ ] Import paths match the actual project structure
- [ ] Variable names are consistent across steps

### Consistency
- [ ] Steps are ordered so each step's prerequisites are met by previous steps
- [ ] No circular dependencies between steps
- [ ] Verification commands reference files/functions that exist after the step
- [ ] The plan achieves everything in the design doc, nothing more, nothing less

### Risk Assessment
- [ ] Identified the riskiest step and placed it early (fail fast)
- [ ] Every step has a clear rollback path
- [ ] The plan doesn't leave the system in a broken intermediate state
- [ ] Stress tests are run after risky steps, not just at the end

---

## Commit Format

Arena-agent follows conventional commits with these types:

| Type | Usage |
|---|---|
| `feat:` | New feature or endpoint |
| `fix:` | Bug fix |
| `refactor:` | Code restructuring without behavior change |
| `test:` | Adding or updating tests |
| `docs:` | Documentation changes |
| `chore:` | Build, CI, tooling changes |
| `perf:` | Performance improvements |

**Examples**:
```
feat: add exponential backoff to websocket reconnection

Implements the design from docs/specs/2025-03-15-websocket-reconnect-design.md
with jitter-based backoff, max delay cap, and retry limit.

Refs: docs/specs/2025-03-15-websocket-reconnect-design.md
```

```
fix: handle CP1251 encoding in Russian Windows locale

System command output on Russian Windows may be encoded in CP1251
rather than UTF-8. Added encoding detection and normalization.
```

---

## Execution Handoff

After the plan is written and reviewed, offer Ivan two options for execution:

### Option A: Subagent-Driven (Recommended for Large Plans)
- Use the `subagent-driven-development` skill
- Each step becomes a subagent task
- Parallel execution where possible
- Two-stage review per task
- Best for: 5+ steps, independent subtasks

### Option B: Inline Execution
- Use the `executing-plans` skill
- Execute steps sequentially
- Verify after each step
- Direct control over pace
- Best for: <5 steps, highly sequential work

**Recommend the appropriate option based on the plan's characteristics.** Always explain why.

---

## Integration with Other Skills

| Before This Skill | Required Output |
|---|---|
| `brainstorming` | Approved design document |

| After This Skill | Trigger |
|---|---|
| `executing-plans` | Plan is ready, Ivan chooses inline execution |
| `subagent-driven-development` | Plan is ready, Ivan chooses subagent execution |
| `test-driven-development` | Plan includes significant new code (should be most plans) |

---

## Anti-Patterns

### ❌ "I'll Figure Out the Details During Execution"
```
No. The plan IS the details. If you can't write the exact code in the plan,
you don't understand the design well enough to implement it. Go back to
the design doc.
```

### ❌ "Steps 5-12 Are Similar, I'll Just Write Step 5 and Say 'Repeat for 6-12'"
```
No. Each step might have subtle differences. Write each one explicitly.
Copy-paste with modifications is fine — but each step must be complete.
```

### ❌ "Verification Is Just Running Stress Tests at the End"
```
No. If step 3 breaks something and you only verify at step 12, you have
9 steps of accumulated damage. Verify after every step that changes code.
```

### ❌ "The Plan Doesn't Need Tests — That's a Separate Task"
```
No. Tests are part of the implementation. The plan must include writing
and running tests for every behavior change.
```

---

## Summary

| Principle | Rule |
|---|---|
| **Prerequisites** | Approved design, clean baseline, backup created |
| **No placeholders** | Exact code, exact paths, exact commands |
| **Step size** | 2-5 minutes, 1-3 files, independently verifiable |
| **Verification** | Every step verified; full stress test after last step |
| **Self-review** | Complete the checklist before presenting |
| **Commit format** | Conventional commits with arena-agent conventions |
| **Execution handoff** | Offer subagent-driven or inline execution |

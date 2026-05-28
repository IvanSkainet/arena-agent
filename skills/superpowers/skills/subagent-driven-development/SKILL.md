# Subagent-Driven Development

> **Parallel Execution Skill** — Break implementation plans into subagent tasks, spawn them via the bridge API, and manage two-stage review. Continuous execution without unnecessary pauses.

## Purpose

For large implementation plans, executing steps sequentially is slow. This skill governs the parallelization of work via the arena-agent bridge's subagent system. Each subagent gets a precise, self-contained task with all the context it needs. A two-stage review ensures both spec compliance and code quality.

---

## Iron Laws

1. **EACH SUBAGENT GETS FULL CONTEXT** — Never assume a subagent "knows" the project. Include all relevant code, design docs, and constraints in the task description.
2. **TWO-STAGE REVIEW IS MANDATORY** — Every subagent's output is reviewed for (1) spec compliance, then (2) code quality. No merging without both passes.
3. **CONTINUOUS EXECUTION** — Don't pause between tasks waiting for permission. Spawn the next task as soon as the current one is ready. Only stop for BLOCKED status.
4. **NO ORPHANED SUBAGENTS** — Track every spawned subagent. Know its status at all times. Clean up when done.
5. **SPEC COMPLIANCE > CODE ELEGANCE** — If a subagent's output matches the spec but the code could be "better," it passes review. Refactoring is a separate task.

---

## When to Use Subagent-Driven Development

### ✅ Use When:
- Plan has 5+ steps
- Steps can be partitioned into independent groups
- Multiple files need changes that don't depend on each other
- The project is in a known-good state (39/39 stress tests pass)

### ❌ Don't Use When:
- Plan has <5 steps (use `executing-plans` instead)
- Steps are highly sequential (each depends on the previous)
- The project is in a broken state (fix it first)
- Ivan explicitly requests inline execution

---

## Subagent Lifecycle

```
┌───────────────────┐
│  Plan Decomposed   │
│  into Tasks        │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐
│  Task Queue       │
│  (priority order) │
└─────────┬─────────┘
          │
          ▼
┌───────────────────┐     ┌───────────────────┐
│  Spawn Subagent 1 │     │  Spawn Subagent 2 │  ← parallel
│  POST /v1/        │     │  POST /v1/        │
│  subagents/spawn  │     │  subagents/spawn  │
└─────────┬─────────┘     └─────────┬─────────┘
          │                         │
          ▼                         ▼
┌───────────────────┐     ┌───────────────────┐
│  Subagent works   │     │  Subagent works   │
│  on Task 1        │     │  on Task 2        │
└─────────┬─────────┘     └─────────┬─────────┘
          │                         │
          ▼                         ▼
┌───────────────────┐     ┌───────────────────┐
│  Status: DONE /   │     │  Status: DONE /   │
│  DONE_WITH_       │     │  BLOCKED /        │
│  CONCERNS /       │     │  NEEDS_CONTEXT    │
│  BLOCKED          │     │                   │
└─────────┬─────────┘     └─────────┬─────────┘
          │                         │
          ▼                         ▼
┌───────────────────────────────────────────────┐
│              Two-Stage Review                 │
│  Stage 1: Spec Compliance                     │
│  Stage 2: Code Quality                        │
└──────────────────────┬────────────────────────┘
                       │
                ┌──────┼──────┐
                │      │      │
             Pass   Concerns  Fail
                │      │      │
                ▼      ▼      ▼
             Merge  Address  Rework
                    concerns  task
```

---

## Spawning Subagents

### API Call

```python
POST /v1/subagents/spawn
{
  "task_id": "reconnect-001",
  "name": "Implement ReconnectHandler class",
  "description": "<full task description - see template below>",
  "context": {
    "design_doc": "docs/specs/2025-03-15-websocket-reconnect-design.md",
    "plan_doc": "docs/plans/2025-03-15-websocket-reconnect.md",
    "relevant_files": ["bridge/connection.py", "bridge/reconnect.py"],
    "constraints": ["Must work on Windows/Linux/macOS", "UTF-8 and CP1251 handling"]
  },
  "model": "default"  # or specific model hint
}
```

### Response

```json
{
  "subagent_id": "sa-20250315-001",
  "task_id": "reconnect-001",
  "status": "running",
  "created_at": "2025-03-15T14:30:22Z"
}
```

---

## Task Description Template

Every task description must include these sections:

```markdown
# Task: <Title>

## Objective
<1-2 sentences: what this task accomplishes>

## Context
<Why this task exists, what part of the design/plan it fulfills>

## Design Reference
<Relevant sections from the approved design doc>
- Paste the exact design requirements this task addresses

## Files to Create/Modify
- `path/to/file.py` — <what to create or change>
- `path/to/test_file.py` — <tests to write>

## Exact Code
<Full, exact code from the plan step. No placeholders.>

## Constraints
- <Cross-platform requirement>
- <Encoding requirement>
- <API compatibility requirement>
- <Performance requirement>

## Verification
1. Run: `python -m pytest tests/test_x.py::test_y -v`
   Expected: PASSED
2. Run: `python -c "<verification snippet>"`
   Expected: <expected output>

## Definition of Done
- [ ] All code written exactly as specified
- [ ] All verification commands pass
- [ ] No new lint warnings
- [ ] Code follows project conventions

## Status Reporting
When complete, report one of:
- DONE — All verification passed, no concerns
- DONE_WITH_CONCERNS — Verification passed but <describe concerns>
- NEEDS_CONTEXT — Cannot proceed without <describe what's needed>
- BLOCKED — Cannot proceed because <describe blocker>
```

---

## Task Decomposition Strategy

### Step 1: Identify Dependencies

From the plan, build a dependency graph:

```
Step 1: Create ReconnectHandler class
    ↓
Step 2: Add backoff calculation (depends on Step 1)
    ↓
Step 3: Integrate with ConnectionManager (depends on Step 1)
    ↓
Step 4: Add tests (depends on Steps 2, 3)
    ↓
Step 5: Update configuration (depends on Step 4)
```

### Step 2: Group Independent Tasks

Tasks with no dependencies between them can run in parallel:

```
Group A (parallel): Step 1
Group B (parallel): Step 2, Step 3 (both depend on Step 1, but not on each other)
Group C (sequential): Step 4 (depends on Group B)
Group D (sequential): Step 5 (depends on Step 4)
```

### Step 3: Assign Priorities

- **High priority**: Tasks on the critical path (blocking other tasks)
- **Medium priority**: Tasks that are independent but important
- **Low priority**: Tasks that can be done anytime (docs, cleanup)

### Step 4: Sequence Execution

```
1. Spawn all Group A tasks
2. Wait for Group A completion
3. Review Group A outputs
4. Spawn all Group B tasks
5. Wait for Group B completion
6. Review Group B outputs
7. ... continue until all tasks done
```

**Continuous execution**: As soon as a task in Group A finishes and passes review, if Group B tasks only depend on that specific task, spawn them immediately — don't wait for all of Group A.

---

## Two-Stage Review

### Stage 1: Spec Compliance

**Question**: Does the output match the specification?

Check:
- [ ] All files mentioned in the task were created/modified
- [ ] The exact code from the spec was implemented (no deviations)
- [ ] All verification commands pass
- [ ] All Definition of Done items are met
- [ ] No extra features were added (scope creep check)

**If spec compliance fails** → Return to subagent for rework with specific feedback.

### Stage 2: Code Quality

**Question**: Is the code well-written and maintainable?

Check:
- [ ] Follows project naming conventions
- [ ] Includes docstrings where appropriate
- [ ] Error handling is comprehensive
- [ ] Cross-platform considerations addressed
- [ ] No obvious performance issues
- [ ] No security vulnerabilities
- [ ] Logging is appropriate (not too verbose, not silent)

**If quality fails** → Note concerns. If they're minor, merge and create a cleanup task. If major, return for rework.

---

## Handling Subagent Statuses

### DONE
The subagent completed all work and all verifications pass.

**Action**:
1. Run two-stage review
2. If both stages pass → Merge the changes
3. Update memory: `POST /v1/memory` with completion status
4. Check if this unblocks any dependent tasks → spawn them

### DONE_WITH_CONCERNS
The subagent completed work and verifications pass, but has concerns.

**Action**:
1. Read the concerns carefully
2. Run two-stage review
3. Assess whether concerns are:
   - **Informational** (noted for awareness) → Merge, note concerns in memory
   - **Minor issues** (small quality nits) → Merge, create cleanup task
   - **Significant risks** → Do not merge, address concerns first
4. Never ignore concerns without explicit assessment

### NEEDS_CONTEXT
The subagent cannot proceed because it lacks information.

**Action**:
1. Identify what context is needed
2. Provide the context via `POST /v1/subagents/{id}/context`
3. Resume the subagent
4. If you cannot provide the context → Ask Ivan

### BLOCKED
The subagent cannot proceed due to an external blocker.

**Action**:
1. Identify the blocker
2. Is it a dependency on another task? → Wait for that task to complete
3. Is it a technical issue? → Invoke `systematic-debugging`
4. Is it a design issue? → Invoke `brainstorming` (may need design revision)
5. If unresolvable → Ask Ivan

---

## Model Selection Guidance

Different tasks benefit from different model capabilities:

| Task Type | Recommended Model | Rationale |
|---|---|---|
| Well-specified code implementation | `default` / `fast` | Clear spec, straightforward execution |
| Complex algorithm design | `reasoning` | Needs deeper logical analysis |
| Code review / quality check | `default` | Balanced speed and thoroughness |
| Documentation writing | `fast` | Language generation is straightforward |
| Debugging / investigation | `reasoning` | Requires careful analysis and hypothesis testing |
| Cross-platform edge cases | `reasoning` | Needs to think through OS-specific behavior |

**Note**: Model selection is a hint, not a guarantee. The bridge may route to whatever model is available. Always provide complete context regardless of model choice.

---

## Subagent Prompt Templates

### Implementer Prompt

```markdown
You are an implementer subagent for the arena-agent bridge project.

YOUR TASK: {task_description}

CONTEXT:
- Design doc: {design_doc_summary}
- Plan step: {plan_step_details}
- Relevant existing code: {code_snippets}

CONSTRAINTS:
- Follow the exact specification. No creative deviations.
- Use Python with pathlib.Path for all file operations.
- Handle UTF-8 and CP1251 encoding for Russian Windows.
- Run verification commands after implementation.
- Report status as DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, or BLOCKED.

VERIFICATION:
{verification_commands}

DEFINITION OF DONE:
{dod_items}
```

### Reviewer Prompt

```markdown
You are a reviewer subagent for the arena-agent bridge project.

YOUR TASK: Review the output of subagent {subagent_id} for task {task_id}.

REVIEW STAGES:

Stage 1 - Spec Compliance:
{spec_checklist}

Stage 2 - Code Quality:
{quality_checklist}

OUTPUT FORMAT:
- Stage 1: PASS / FAIL (with specific issues)
- Stage 2: PASS / CONCERNS / FAIL (with specific issues)
- Overall: MERGE / REWORK / BLOCKED
- Specific feedback for the implementer (if any)
```

---

## Continuous Execution Protocol

The key principle: **keep the pipeline full**.

```
Timeline:
─────────────────────────────────────────────────────────►

Task 1: [spawn][work][done][review]──[merge]
Task 2: [spawn][work][done][review]──[merge]
Task 3:       [spawn][work][done][review]──[merge]
Task 4:             [spawn][work][done][review]──[merge]
                   ↑
            As soon as Task 1's review passes,
            if Task 3 only depends on Task 1, spawn it.
```

**Rules**:
1. Spawn a task as soon as its dependencies are satisfied
2. Don't wait for Ivan's permission between tasks (the plan is already approved)
3. DO wait for Ivan if a task returns BLOCKED
4. DO pause for Ivan if review fails (design/spec issue)
5. After all tasks complete, run full stress test suite

---

## Convergence and Integration

After all subagent tasks are complete:

### 1. Integration Check
```python
POST /v1/exec {"command": "python stress_test.py"}
```
Expected: 39/39 PASSED

### 2. Cross-Task Consistency
- Verify that tasks didn't create conflicting changes
- Check for duplicate code or missed integration points
- Run `GET /v1/doctor` for overall health

### 3. Single Commit
```python
POST /v1/exec {"command": "git add -A && git commit -m \"feat: <feature description>\n\n<detail>\n\nRefs: docs/specs/YYYY-MM-DD-topic-design.md\""}
```

Or, if tasks touched separate concerns, consider one commit per logical group.

---

## Error Handling

### Subagent Produces Wrong Code
1. Identify the specific deviation from spec
2. Provide precise feedback: what's wrong, what it should be
3. Re-spawn or continue with a correction task

### Subagent Times Out
1. Check subagent status via API
2. If truly stuck, kill and re-spawn with clearer instructions
3. If the task itself is too large, split it and re-assign

### Merge Conflicts
1. Multiple subagents modifying the same file → shouldn't happen (decomposition should prevent this)
2. If it does happen: manual resolution, then re-run stress tests
3. Adjust task decomposition to prevent recurrence

---

## Anti-Patterns

### ❌ "The Subagent Should Know the Project"
```
No. Subagents start with zero context. You must provide ALL relevant
information in the task description. If you assume knowledge, the
subagent will make incorrect assumptions.
```

### ❌ "I'll Skip the Review — It Looks Fine"
```
Two-stage review is mandatory. "Looks fine" is not a review. Run through
the checklist. Catch issues before they're merged.
```

### ❌ "Let Me Wait for All Tasks to Finish Before Reviewing"
```
No. Review each task as it completes. This catches issues early and
allows dependent tasks to start sooner. Continuous execution.
```

### ❌ "One Giant Task for the Whole Plan"
```
No. Decompose into the smallest possible independent units. Smaller
tasks are faster, easier to review, and less likely to go wrong.
```

---

## Integration with Other Skills

| Before This Skill | Required Output |
|---|---|
| `brainstorming` | Approved design document |
| `writing-plans` | Approved implementation plan |

| After This Skill | Trigger |
|---|---|
| `executing-plans` | Ivan prefers sequential execution |
| `systematic-debugging` | Subagent returns BLOCKED due to technical issue |
| `test-driven-development` | Integration tests needed after merge |

---

## Summary

| Principle | Rule |
|---|---|
| **Full context** | Every subagent gets complete, self-contained task descriptions |
| **Two-stage review** | Spec compliance first, then code quality |
| **Continuous execution** | Keep the pipeline full; don't pause unnecessarily |
| **Status handling** | DONE → review; CONCERNS → assess; BLOCKED → escalate; NEEDS_CONTEXT → provide |
| **Dependency management** | Spawn tasks as soon as dependencies are satisfied |
| **Convergence** | Full stress test after all tasks merge |
| **No orphans** | Track every subagent; know every status |

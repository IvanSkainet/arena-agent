---
name: dispatching-parallel-agents
description: Dispatch multiple subagents via the bridge API to work on independent problems in parallel, then integrate results sequentially. One agent per independent problem domain, parallel for independent failures, sequential for coupled issues.
---

# Dispatching Parallel Agents

## Purpose

This skill defines how to use the bridge's subagent API to dispatch multiple agents for parallel work on independent problems, then integrate their results. It covers when parallelism helps, when it hurts, and how to avoid conflicts between agents working simultaneously.

## When to Use

- Multiple independent bugs need fixing simultaneously
- Unrelated features need implementation in parallel
- Stress test failures in independent subsystems
- Time-critical situations where sequential work is too slow

## When NOT to Use

- Issues are related or coupled (shared state, shared files)
- One issue's output is another issue's input
- The project is in a fragile state (stress test already failing)
- You can't clearly delineate problem domains

## Core Concepts

### One Agent Per Independent Problem Domain

Each subagent should own a single problem domain completely. A "problem domain" is a set of files, tests, and functionality that can be changed independently of other domains.

**Independent problem domains in arena-agent:**
- Exec endpoint (process_manager.py, test_exec.py)
- Skills endpoint (skills_handler.py, test_skills.py)
- Memory endpoint (memory_handler.py, test_memory.py)
- Subagent system (subagent_manager.py, test_subagents.py)
- Auth system (auth.py, test_auth.py)
- Service management (nssm_config.py, test_service.py)
- Bridge core (server.py, middleware.py)

**Coupled problem domains (DO NOT parallelize):**
- Exec endpoint + process_manager (same domain)
- Auth + any endpoint (auth touches everything)
- Server.py + router (core infrastructure)
- Stress tests + the code they test (coupled by definition)

### Parallel for Independent, Sequential for Coupled

```
INDEPENDENT (parallel OK):
  Issue A: Fix exec timeout bug         → Agent 1
  Issue B: Add doctor endpoint          → Agent 2
  Issue C: Fix memory leak in skills    → Agent 3

COUPLED (must be sequential):
  Issue D: Refactor process_manager     → Agent 1 (first)
  Issue E: Add new exec parameter       → Agent 1 (second, after D)
  (Both touch process_manager.py — would conflict)
```

## Process

### Step 1: Analyze the Workload

Before dispatching any agents, analyze the set of issues to determine:

1. **Which issues are independent?** (can be parallelized)
2. **Which issues are coupled?** (must be sequential)
3. **What files does each issue touch?** (detect conflicts)
4. **What's the priority order?** (which issues are more important)

Create a dependency graph:

```
Issue A (exec timeout) ─── touches: process_manager.py, test_exec.py
Issue B (doctor endpoint) ─ touches: doctor_handler.py (new), test_doctor.py (new)
Issue C (memory leak) ───── touches: memory_handler.py, test_memory.py

Dependencies: None (all independent)
Conflict risk: Low (no shared files)

Plan: Dispatch A, B, C in parallel
```

```
Issue D (refactor process_manager) ─── touches: process_manager.py, exec routes
Issue E (add exec timeout param) ────── touches: process_manager.py, exec routes
Issue F (fix skills listing) ────────── touches: skills_handler.py, test_skills.py

Dependencies: D must complete before E (E depends on D's refactored structure)
Conflict risk: D and E share process_manager.py; F is independent

Plan: Dispatch D and F in parallel → After D completes, dispatch E
```

### Step 2: Prepare the Agents

For each agent, prepare a clear, self-contained task specification:

```json
{
  "role": "bug-fixer",
  "prompt": "Fix the exec timeout bug in the arena-agent bridge.\n\nProblem: The POST /v1/exec endpoint hangs indefinitely when a command produces infinite output.\n\nFiles to modify:\n- process_manager.py: Add timeout parameter to run_command()\n- routes/exec.py: Pass timeout from request body\n- tests/test_exec.py: Add test for timeout behavior\n\nConstraints:\n- Do NOT modify any other files\n- Do NOT modify the stress tests\n- Default timeout: 300 seconds\n- Timeout returns 408 status code\n- Maintain backward compatibility (timeout is optional)\n\nVerification:\n- python -m pytest tests/test_exec.py -v\n- python -m pytest tests/stress/ -v  (must be 39/39)\n- curl http://localhost:8765/health\n\nBranch: feature/exec-timeout-fix (based on feature/v1.7.0)",
  "context": {
    "branch": "feature/exec-timeout-fix",
    "base_branch": "feature/v1.7.0",
    "files": ["process_manager.py", "routes/exec.py", "tests/test_exec.py"]
  }
}
```

### Step 3: Dispatch Agents

Use the bridge subagent API to spawn agents:

```bash
# Spawn Agent 1
curl -s -X POST http://localhost:8765/v1/subagents/spawn \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "role": "bug-fixer",
    "prompt": "<task-spec-for-issue-A>",
    "branch": "feature/exec-timeout-fix"
  }'

# Spawn Agent 2
curl -s -X POST http://localhost:8765/v1/subagents/spawn \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "role": "feature-implementer",
    "prompt": "<task-spec-for-issue-B>",
    "branch": "feature/add-doctor-endpoint"
  }'

# Spawn Agent 3
curl -s -X POST http://localhost:8765/v1/subagents/spawn \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "role": "bug-fixer",
    "prompt": "<task-spec-for-issue-C>",
    "branch": "feature/fix-memory-leak"
  }'
```

### Step 4: Monitor Agent Progress

Check agent status periodically:

```bash
# Check all subagent statuses
curl -s http://localhost:8765/v1/subagents \
  -H "Authorization: Bearer $BRIDGE_TOKEN"

# Check specific agent status
curl -s http://localhost:8765/v1/subagents/<agent-id> \
  -H "Authorization: Bearer $BRIDGE_TOKEN"

# Check audit log for agent activity
curl -s "http://localhost:8765/v1/audit?type=subagent" \
  -H "Authorization: Bearer $BRIDGE_TOKEN"
```

### Step 5: Review and Integrate Results

As each agent completes, review its output:

```bash
# Get agent results
curl -s http://localhost:8765/v1/subagents/<agent-id>/result \
  -H "Authorization: Bearer $BRIDGE_TOKEN"

# Review the changes on the agent's branch
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git log feature/<branch-name> --oneline -10"}'

# Check the diff
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git diff feature/v1.7.0...feature/<branch-name> --stat"}'
```

### Step 6: Merge Results Sequentially

Even though agents ran in parallel, merges must be sequential:

```bash
# Merge first completed agent's branch
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git checkout feature/v1.7.0 && git merge feature/exec-timeout-fix --no-ff"}'

# Verify after first merge
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && python -m pytest tests/stress/ -v"}'

# Push after first merge
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git push origin feature/v1.7.0"}'

# Rebase second agent's branch on updated Feature before merging
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git checkout feature/add-doctor-endpoint && git rebase feature/v1.7.0"}'

# Merge second agent's branch
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git checkout feature/v1.7.0 && git merge feature/add-doctor-endpoint --no-ff"}'

# And so on for each agent...
```

### Step 7: Check for Conflicts Between Parallel Results

Even when agents work on independent domains, conflicts can arise in shared infrastructure:

**Common conflict areas:**
- `server.py` (route registration)
- `requirements.txt` (dependency additions)
- `config.py` (configuration changes)
- `tests/stress/` (test count changes)
- `.gitignore` (file pattern additions)

**Conflict detection:**
```bash
# After merging each agent, check for potential conflicts with remaining branches
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git diff feature/v1.7.0...feature/<remaining-branch> --stat"}'

# Look for overlapping file changes
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && git diff feature/v1.7.0...feature/<remaining-branch> --name-only | sort > /tmp/remaining.txt && git log feature/v1.7.0 --oneline -1 && git diff HEAD~1 --name-only | sort > /tmp/last-merge.txt && comm -12 /tmp/remaining.txt /tmp/last-merge.txt"}'
```

If overlapping files are found, resolve them carefully during the rebase step.

## Agent Failure Handling

### Agent Produces Broken Code

If an agent's branch fails the stress test:

1. Do NOT merge the broken branch
2. Diagnose the failure on the agent's branch
3. Either fix it yourself or re-dispatch the agent with more specific instructions
4. If the fix is simple, apply it on the agent's branch before merging

### Agent Goes Out of Scope

If an agent modifies files outside its assigned domain:

1. Review the unexpected changes
2. If they're benign (formatting, comments), accept them
3. If they're problematic (functional changes to shared code), revert them
4. Document the scope violation for future agent prompts

### Agent Fails to Complete

If an agent doesn't finish within a reasonable time:

```bash
# Check agent status
curl -s http://localhost:8765/v1/subagents/<agent-id> \
  -H "Authorization: Bearer $BRIDGE_TOKEN"

# Cancel the agent if stuck
curl -s -X DELETE http://localhost:8765/v1/subagents/<agent-id> \
  -H "Authorization: Bearer $BRIDGE_TOKEN"
```

Salvage whatever work was completed on the branch and finish it manually.

## Parallel Dispatch Decision Matrix

| Scenario                          | Parallel? | Reasoning                                       |
|-----------------------------------|-----------|--------------------------------------------------|
| Two bugs in different endpoints   | Yes       | Independent files, no shared state               |
| Two bugs in the same endpoint     | No        | Same files, will conflict                        |
| Bug fix + new endpoint            | Yes       | Different files unless bug is in core            |
| Bug fix + refactoring             | Maybe     | Depends on overlap; usually sequential           |
| Two new endpoints                 | Yes       | Independent files (but watch server.py)          |
| Feature + its tests               | No        | Tests depend on feature; same agent              |
| Windows fix + Linux fix           | Maybe     | If they touch different platform-specific files  |
| Auth change + endpoint change     | No        | Auth touches all endpoints                       |
| Stress test fix + code change     | No        | Tests are coupled to the code they test          |

## Anti-Patterns to Avoid

### Over-Parallelization
Dispatching 10 agents for 10 issues that touch overlapping files creates more conflicts than it saves time. Stick to truly independent domains.

### Under-Specification
An agent given a vague prompt ("fix the bug") will waste time investigating. Give it specific files, specific problems, and specific constraints.

### Merging Without Reviewing
Each agent's output must be reviewed before merging, just like any other code change. Use the `requesting-code-review` skill.

### Skipping the Rebase
When merging the second agent's branch, always rebase on the updated Feature branch first. Skipping this leads to preventable conflicts.

### Ignoring Test Count Changes
If Agent A adds 2 tests and Agent B adds 3 tests, the stress test count changes from 39 to 44. After merging both, the count should be 44/44, not 39/39. Track the expected count.

## Integration with Arena-Agent Workflow

1. **using-feature-branches**: Each agent works on its own issue branch
2. **requesting-code-review**: Review each agent's output before merging
3. **receiving-code-review**: Process review findings for each agent's work
4. **verification-before-completion**: Full verification after each merge
5. **finishing-a-feature-branch**: Finish each agent's branch individually, merge sequentially

## Quick Reference

```
# 1. Analyze workload
Identify independent vs. coupled issues
Map issues to files they touch
Build dependency graph

# 2. Prepare agent specs
One agent per independent domain
Clear file boundaries
Specific constraints and verification steps

# 3. Dispatch agents
POST /v1/subagents/spawn { role, prompt, branch }
One dispatch per independent issue

# 4. Monitor progress
GET /v1/subagents
GET /v1/audit?type=subagent

# 5. Review results
Check agent output
git diff feature/v1.7.0...feature/<branch> --stat

# 6. Merge sequentially
For each completed agent (in priority order):
  git checkout feature/v1.7.0
  git merge feature/<branch> --no-ff
  python -m pytest tests/stress/ -v
  git push origin feature/v1.7.0

# 7. Check for conflicts between remaining branches
Rebase remaining branches on updated Feature
Resolve conflicts file by file
```

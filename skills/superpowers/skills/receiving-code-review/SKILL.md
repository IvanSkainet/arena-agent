---
name: receiving-code-review
description: Process code review findings with technical rigor, avoiding performative agreement and emotional responses. Verify before implementing, push back when reviewers are wrong, and apply YAGNI to reject unnecessary "professional" additions.
---

# Receiving Code Review

## Purpose

Code review is a technical evaluation of your implementation, not a performance review of you as a developer. This skill defines how to receive, evaluate, and act on review findings with technical rigor — no performative agreement, no emotional responses, and no unnecessary scope expansion.

## When to Use

- When a code reviewer subagent or human reviewer provides feedback
- After requesting a review via the `requesting-code-review` skill
- When processing automated lint or test failure reports

## When NOT to Use

- During the initial implementation (write first, review after)
- When interpreting build/CI failures (those are facts, not opinions)

## Core Principles

### 1. Technical Evaluation, Not Emotional Performance

Review feedback is technical data. Process it the same way you'd process a stack trace or a test failure — analytically, not emotionally.

**FORBIDDEN responses:**
- "You're absolutely right!" (performative agreement)
- "Great point!" (performative agreement)
- "Thanks for catching that!" (performative gratitude)
- "I should have thought of that." (performative self-criticism)
- "Good catch!" (performative praise)

**REQUIRED responses:**
- "The reviewer identified that X fails when Y is None. Verified: the fix adds a None check at line N."
- "The reviewer suggests adding input validation. The bridge's request parser already validates this at the route level. No change needed."
- "Finding #3 claims this is a security issue. Analysis: the token is never exposed to user input. Not a valid finding."

### 2. Verify Before Implementing

Never implement a review finding without first verifying it yourself. The reviewer may be wrong, may have misread the code, or may be operating on outdated information.

**Verification checklist for each finding:**

1. **Read the actual code** at the line the reviewer references
2. **Reproduce the issue** if possible (run the code, send a request)
3. **Check the context** — is the reviewer aware of surrounding code that mitigates the issue?
4. **Consult the spec** — does the project's design intent match what the reviewer expects?

```bash
# Verify finding: check the actual code at the referenced line
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "sed -n \"40,50p\" /path/to/file.py"}'

# Verify finding: reproduce the reported issue
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "python -c \"from module import func; print(func(None))\""}'

# Verify finding: check if existing tests cover this case
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && python -m pytest tests/ -k test_boundary -v"}'
```

### 3. Ask Before Assuming

If a finding is ambiguous, ask for clarification rather than guessing what the reviewer meant. Wrong assumptions lead to wrong fixes.

**Good questions:**
- "Finding #2 says 'this could fail under load.' What specific load scenario are you concerned about?"
- "Finding #4 suggests using a different data structure. What's the expected scale — 10 items or 10 million?"
- "Finding #5 flags a potential race condition. Can you describe the interleaving you're worried about?"

**Bad responses:**
- Silently implementing what you think they meant (often wrong)
- Dismissing the finding because you don't understand it (it might be valid)

### 4. Push Back with Technical Reasoning

Reviewers can be wrong. When they are, push back with specific technical reasoning, not opinions.

**Valid pushback structure:**
```
Finding #N: [reviewer's claim]

Status: DISPUTED

Reasoning:
- [Specific technical reason the finding is incorrect]
- [Evidence from code, tests, or documentation]
- [Context the reviewer may have missed]

Proposed action: No change.
```

**Example pushback:**
```
Finding #7: "This endpoint should validate Content-Type header."

Status: DISPUTED

Reasoning:
- The bridge uses aiohttp's request.json() which already validates Content-Type
- If Content-Type is not application/json, aiohttp raises a 400 before reaching our handler
- Test: sending a request with text/plain returns 400 Unsupported Media Type
- Adding our own validation would be redundant and could conflict with aiohttp's behavior

Proposed action: No change.
```

**Invalid pushback:**
- "I prefer my way." (not technical reasoning)
- "It works on my machine." (not evidence of correctness)
- "That's how I've always done it." (appeal to tradition)

### 5. YAGNI Check for "Professional" Features

Reviewers often suggest adding "professional" features that sound good but aren't needed: logging frameworks, metrics dashboards, configuration systems, retry mechanisms, circuit breakers, etc.

**Before implementing any suggestion that adds new functionality, ask:**

1. **Is this needed for the current requirements?** If the requirement is "return the list of skills" and the suggestion is "add a caching layer," the answer is no.
2. **Does this solve a problem we actually have?** If we've never hit a timeout, adding a retry mechanism is premature.
3. **What's the maintenance cost?** Every new feature is a new thing that can break, needs tests, and must be understood by future contributors.
4. **Is this within scope?** The issue says "fix the exec timeout bug," not "redesign the exec architecture."

**Common YAGNI violations suggested by reviewers:**

| Suggestion                       | When It's YAGNI                          | When It's Valid                          |
|----------------------------------|------------------------------------------|------------------------------------------|
| Add structured logging           | Project uses print() and it works        | Debugging production issues              |
| Add retry logic                  | No failures observed                     | Documented flaky upstream dependency     |
| Add configuration file           | Two settings, both in constants          | 10+ settings that vary by environment    |
| Add type hints everywhere        | Codebase doesn't use them                | New module in a typed codebase           |
| Add abstraction layer            | One implementation exists                | Second implementation planned this sprint |
| Add input sanitization           | aiohttp already validates                | Raw user input reaches code              |
| Add metrics/monitoring           | No operational issues                    | Performance investigation underway       |
| Add circuit breaker              | Single dependency, reliable              | Multiple fallback paths needed           |

## Process

### Step 1: Categorize Findings by Severity

Each finding has a severity level from the `requesting-code-review` skill:

- **Critical**: Bug, security hole, data loss risk → Must fix
- **Important**: Wrong approach, missing edge case → Fix before proceeding
- **Minor**: Style, naming, future improvement → Note for later

### Step 2: Verify Each Finding

For each finding (in severity order):

1. Read the code at the referenced location
2. Understand the reviewer's reasoning
3. Attempt to reproduce the issue
4. Check if existing code already handles this case
5. Determine if the finding is valid, partially valid, or invalid

Record your assessment:

```
Finding #1 [Critical]: "exec endpoint allows command injection via shell=True"
  Verification: Checked exec handler. Commands are passed via subprocess.run with shell=False by default.
  However, one code path in process_manager.py:142 uses shell=True for pip commands.
  Assessment: PARTIALLY VALID. The pip path is a known tradeoff documented in SECURITY.md.
  Action: Add input validation for the pip path specifically.

Finding #2 [Important]: "No timeout on exec commands"
  Verification: Checked subprocess.run calls. Default timeout of 300s is set in config.
  Assessment: INVALID. Reviewer missed the default timeout.
  Action: No change. Document the existing timeout in the endpoint docstring.

Finding #3 [Minor]: "Variable name 'x' is unclear"
  Verification: The variable is a loop counter in a 3-line list comprehension.
  Assessment: VALID but MINOR. Not worth changing now.
  Action: Note for later.
```

### Step 3: Implement Fixes in Order

**Implementation order:**

1. **Blocking fixes** (Critical): Fix these first, immediately
2. **Simple fixes** (Important, <5 lines each): Knock these out quickly
3. **Complex fixes** (Important, >5 lines): These need careful implementation

Do NOT mix fix implementation with new feature work. Fixes first, always.

### Step 4: Verify Each Fix

After implementing a fix:

```bash
# Run the specific test that covers the fix
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && python -m pytest tests/test_exec.py -v"}'

# Run the full stress test
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && python -m pytest tests/stress/ -v"}'

# Check bridge health
curl -s http://localhost:8765/health
```

### Step 5: Summarize Review Outcome

Produce a technical summary:

```
## Review Outcome

**Findings received**: N
**Valid**: X
**Partially valid**: Y
**Invalid**: Z
**Deferred (Minor)**: W

### Fixes Applied
1. [Critical] Added input validation for pip commands in exec handler (process_manager.py:142)
2. [Important] Added None check for config.timeout in exec endpoint

### Disputed Findings
1. [Important] "No timeout on exec commands" — Invalid. Default 300s timeout exists in config.

### Deferred
1. [Minor] Variable naming in list comprehension — noted for later

### Verification
- Stress test: 39/39 passed
- Bridge health: OK
- Audit log: consistent with changes
```

## Anti-Patterns to Avoid

### Performative Agreement
Never agree with a finding you haven't verified. "You're right" is not a technical assessment. Verify, then state your assessment.

### Implementing Without Understanding
If you don't understand why a finding is valid, you'll implement the wrong fix. Ask for clarification first.

### Scope Creep via Review
Review is for evaluating what you wrote, not for adding new features. If a reviewer suggests adding a feature, assess it with YAGNI. If it's genuinely needed, create a new issue — don't bundle it into the current fix.

### Emotional Defensiveness
If a finding is valid, fix it. Don't argue that your code is correct when it isn't. The code is what matters, not your feelings about it.

### Blind Obedience
If a finding is invalid, say so with technical reasoning. Don't implement a fix for something that isn't broken just because a reviewer suggested it.

### Bundling Unrelated Fixes
Each fix should be its own commit with its own verification. Don't bundle three Important fixes into one opaque commit.

## Integration with Arena-Agent Workflow

1. **requesting-code-review**: The output of that skill is the input to this one
2. **verification-before-completion**: After processing all findings, run full verification
3. **using-feature-branches**: Fix commits go on the same issue branch
4. **finishing-a-feature-branch**: Only merge after review is fully processed and verified

## Quick Reference

```
# 1. Categorize findings
Critical → fix now
Important → fix before proceeding
Minor → note for later

# 2. Verify EACH finding before acting
Read code → reproduce → check context → assess

# 3. Push back with technical reasoning when reviewer is wrong
Not opinion. Evidence.

# 4. YAGNI check for every "professional" feature suggestion
Need? Problem? Cost? Scope?

# 5. Implement in order
Blocking → Simple → Complex

# 6. Verify each fix
Run specific test → run stress test → check bridge health

# 7. Summarize outcome
Valid/Invalid counts, fixes applied, disputes, deferrals
```

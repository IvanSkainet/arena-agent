# Systematic Debugging

> **Investigation Skill** — Debug methodically through four phases: Root Cause → Pattern Analysis → Hypothesis → Implementation. No guessing. No shotgun debugging. Use bridge tools to investigate.

## Purpose

When something breaks in the arena-agent bridge, resist the urge to "just try something." Follow a structured investigation that finds the real cause, not just a symptom. This skill ensures bugs are fixed once, correctly, and with a test that prevents recurrence.

---

## Iron Laws

1. **NO GUESSING** — Do not change code based on hunches. Investigate first, understand the cause, then fix.
2. **FOUR PHASES, NO SKIPPING** — Root Cause → Pattern Analysis → Hypothesis → Implementation. Each phase builds on the previous. Jumping ahead means you're guessing.
3. **USE BRIDGE TOOLS** — The bridge provides `GET /v1/audit`, `GET /v1/doctor`, and `POST /v1/exec` for investigation. Use them before changing anything.
4. **WRITE A TEST FIRST** — Before fixing any bug, write a test that reproduces it (RED). Then fix it (GREEN). This prevents regression.
5. **STOP AND ASK IVAN WHEN BLOCKED** — If you can't determine the root cause after thorough investigation, escalate. Don't flail.

---

## The Four Phases

```
┌──────────────────────────────┐
│  Phase 1: ROOT CAUSE         │
│  What changed? What broke?   │
│  When did it last work?      │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Phase 2: PATTERN ANALYSIS   │
│  Is this systematic?         │
│  Does it affect other areas? │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Phase 3: HYPOTHESIS         │
│  What's the most likely      │
│  explanation? Verify it.     │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Phase 4: IMPLEMENTATION     │
│  Write test → Fix → Verify   │
└──────────────────────────────┘
```

---

## Phase 1: Root Cause

**Goal**: Identify exactly what changed and when it broke.

### Step 1.1: Define the Symptom

Write down the exact symptom:

```markdown
## Symptom

**What**: <Exact error message, unexpected behavior, or failing test>
**Where**: <Which endpoint, function, or test>
**When**: <When does it occur? Every time? Intermittent?>
**Expected**: <What should happen instead?>
**Impact**: <What functionality is affected?>
```

Be precise. "It doesn't work" is not a symptom. "POST /v1/exec returns 500 with 'UnicodeDecodeError' when command output contains Cyrillic characters on Windows" is a symptom.

### Step 1.2: Check the Audit Log

```python
GET /v1/audit
```

Review recent changes:
- What files were modified recently?
- What API endpoints changed?
- Were there any recent restarts?
- Were there any recent backups (implying risky changes)?

### Step 1.3: Check Service Health

```python
GET /v1/doctor
```

Review the self-diagnostic:
- Is the API responding?
- Is authentication working?
- Is the filesystem accessible?
- Is memory storage functional?

### Step 1.4: Reproduce the Issue

Use bridge exec to reproduce:

```python
POST /v1/exec
{
  "command": "python -c \"\nimport requests\nr = requests.post('http://localhost:8765/v1/exec', json={'command': 'echo тест'}, headers={'Authorization': 'Bearer <token>'})\nprint(f'Status: {r.status_code}')\nprint(f'Body: {r.text}')\n\""
}
```

**Critical**: If you can't reproduce the issue, you can't fix it. Keep trying different conditions:
- Different inputs
- Different timing
- Different OS conditions
- Different encoding scenarios

### Step 1.5: Bisect to the Change

If the issue wasn't always present:

```python
# Check git history for recent changes to affected files
POST /v1/exec {"command": "git log --oneline -20 -- path/to/affected/file.py"}

# Check when tests last passed
POST /v1/exec {"command": "git log --oneline -10 -- stress_test.py"}

# Try the previous commit
POST /v1/exec {"command": "git stash && git checkout HEAD~1 && python stress_test.py"}
# If tests pass at HEAD~1, the bug was introduced in the last commit
```

**Root cause outcome**: You should now be able to state:
> "The bug was introduced by <commit/change> which modified <file/function>. It causes <symptom> because <reason>."

If you can't state this clearly, continue investigating. Do NOT proceed to Phase 2 with a vague understanding.

---

## Phase 2: Pattern Analysis

**Goal**: Understand whether this is an isolated bug or a systemic issue.

### Step 2.1: Search for Similar Patterns

```python
# Search the codebase for similar patterns
POST /v1/exec
{
  "command": "python -c \"\nfrom pathlib import Path\nfor p in Path('.').rglob('*.py'):\n    text = p.read_text(encoding='utf-8')\n    if '<pattern>' in text:\n        print(f'{p}: line with <pattern>')\n\""
}
```

Look for:
- The same pattern in other files (same bug, different location)
- Similar error handling (or lack thereof)
- Similar assumptions that might be wrong

### Step 2.2: Check Edge Cases

Based on the root cause, check related edge cases:

| Root Cause Category | Edge Cases to Check |
|---|---|
| Encoding issue | Other places where text is decoded/encoded |
| Path handling | Other places where file paths are constructed |
| Race condition | Other places with concurrent access |
| Missing validation | Other endpoints with similar input patterns |
| OS-specific code | Other places with platform checks |
| Service management | Other places that restart/stop the service |

### Step 2.3: Stress Test Analysis

```python
POST /v1/exec {"command": "python stress_test.py -v"}
```

If some stress tests fail:
- Note WHICH tests fail (they may point to the affected area)
- Note the ERROR MESSAGES (they may reveal the pattern)
- Note if failures are consistent or intermittent

### Step 2.4: Memory Check

```python
GET /v1/memory?tags=debug
```

Check if this issue has been encountered before:
- Prior debugging notes
- Known workarounds
- Related design decisions

**Pattern analysis outcome**: You should now be able to state:
> "This is an <isolated/systemic> issue affecting <scope>. The pattern is <description>. It may also affect <other areas>."

---

## Phase 3: Hypothesis

**Goal**: Form a testable hypothesis about the exact cause and fix.

### Step 3.1: Form the Hypothesis

Write a clear, testable hypothesis:

```markdown
## Hypothesis

**Root cause**: <The specific code path or condition causing the bug>

**Why it happens**: <The mechanism by which the root cause produces the symptom>

**Fix**: <The specific change that will resolve the root cause>

**Test to verify**: <A test that will pass after the fix and fail before>
```

### Step 3.2: Verify the Hypothesis

Before writing any fix code, verify your hypothesis:

```python
# Add diagnostic logging
POST /v1/exec
{
  "command": "python -c \"\nimport sys\nsys.path.insert(0, '.')\nfrom bridge.module import suspect_function\nresult = suspect_function(problematic_input)\nprint(f'Result: {result!r}')\nprint(f'Type: {type(result)}')\n\""
}
```

Or check specific conditions:

```python
POST /v1/exec
{
  "command": "python -c \"\nimport platform\nprint(f'OS: {platform.system()}')\nprint(f'Encoding: {sys.getdefaultencoding()}')\nprint(f'FS encoding: {sys.getfilesystemencoding()}')\n\""
}
```

**If the hypothesis is wrong**, go back to Phase 1 or Phase 2. Do NOT proceed with a wrong fix.

**If the hypothesis is confirmed**, proceed to Phase 4.

### Step 3.3: Rank Alternative Hypotheses

If multiple hypotheses are possible, rank them by likelihood:

| Rank | Hypothesis | Likelihood | Test to Disprove |
|---|---|---|---|
| 1 | Most likely explanation | High | <test> |
| 2 | Second most likely | Medium | <test> |
| 3 | Less likely but possible | Low | <test> |

Test the most likely hypothesis first. If disproven, move to the next.

---

## Phase 4: Implementation

**Goal**: Fix the bug with a test that prevents regression.

### Step 4.1: Write a Failing Test (RED)

```python
# tests/unit/test_bug_fix.py
def test_exec_handles_cyrillic_output_on_windows():
    """Verify exec normalizes CP1251 output to UTF-8.

    Regression test for: POST /v1/exec returns 500 with
    UnicodeDecodeError when command output contains Cyrillic
    characters on Windows.
    """
    from bridge.exec_handler import ExecHandler
    handler = ExecHandler()

    # Simulate CP1251 output (Russian Windows)
    cp1251_output = "Служба работает".encode("cp1251")
    result = handler.normalize_output(cp1251_output)
    assert isinstance(result, str)
    assert "работает" in result
```

Run the test:
```python
POST /v1/exec {"command": "python -m pytest tests/unit/test_bug_fix.py::test_exec_handles_cyrillic_output_on_windows -v"}
```

Expected: **FAIL** — the bug exists.

### Step 4.2: Implement the Fix (GREEN)

```python
# bridge/exec_handler.py — add the fix
def normalize_output(self, raw_output: bytes) -> str:
    """Normalize command output to UTF-8 string.

    Handles both UTF-8 and CP1251 (Russian Windows) encodings.
    """
    try:
        return raw_output.decode("utf-8")
    except UnicodeDecodeError:
        # Fallback to CP1251 for Russian Windows locale
        return raw_output.decode("cp1251", errors="replace")
```

Run the test:
```python
POST /v1/exec {"command": "python -m pytest tests/unit/test_bug_fix.py::test_exec_handles_cyrillic_output_on_windows -v"}
```

Expected: **PASS** ✓

### Step 4.3: Refactor if Needed (REFACTOR)

Review the fix:
- Is it clear and maintainable?
- Does it handle all edge cases identified in Phase 2?
- Does it follow project conventions?

### Step 4.4: Run Full Verification

```python
# Run all related unit tests
POST /v1/exec {"command": "python -m pytest tests/unit/test_exec_handler.py -v"}

# Run the full stress test suite
POST /v1/exec {"command": "python stress_test.py"}
```

Expected: All pass, 39/39 stress tests.

### Step 4.5: Store Findings in Memory

```python
POST /v1/memory
{
  "key": "debug:cyrillic-exec-output",
  "value": "Bug: POST /v1/exec returns 500 with UnicodeDecodeError for CP1251 output on Russian Windows. Fix: Added encoding detection with UTF-8 first, CP1251 fallback. Test: test_exec_handles_cyrillic_output_on_windows",
  "tags": ["debug", "encoding", "russian-locale", "windows"]
}
```

### Step 4.6: Commit

```python
POST /v1/exec {"command": "git add -A && git commit -m 'fix: handle CP1251 encoding in exec output on Russian Windows\n\nAdded encoding detection with UTF-8 primary and CP1251 fallback.\nIncludes regression test for Cyrillic command output.'"}
```

---

## Bridge Debugging Tools

### Audit Log: `GET /v1/audit`

Returns recent changes and events:

```json
{
  "entries": [
    {
      "timestamp": "2025-03-15T14:30:22Z",
      "type": "code_change",
      "file": "bridge/exec_handler.py",
      "description": "Modified output handling"
    },
    {
      "timestamp": "2025-03-15T14:25:10Z",
      "type": "service_restart",
      "reason": "manual",
      "initiated_by": "ivan"
    }
  ]
}
```

**Use it to**:
- Find what changed before the bug appeared
- Track service restarts
- Identify the timeline of events

### Doctor: `GET /v1/doctor`

Runs self-diagnostic checks:

```json
{
  "status": "healthy",
  "checks": {
    "api_responding": "ok",
    "auth_working": "ok",
    "filesystem_accessible": "ok",
    "memory_functional": "ok",
    "skills_loadable": "ok",
    "subagents_available": "ok"
  },
  "warnings": []
}
```

**Use it to**:
- Verify the service is healthy before debugging
- Identify which subsystem might be causing the issue
- Quick sanity check after a fix

### Exec: `POST /v1/exec`

Execute arbitrary commands for investigation:

```python
# Check Python version and encoding
POST /v1/exec {"command": "python -c \"import sys; print(sys.version); print(sys.getdefaultencoding())\""}

# Check if a specific module loads correctly
POST /v1/exec {"command": "python -c \"from bridge.module import Class; print('OK')\""}

# Check file contents
POST /v1/exec {"command": "python -c \"from pathlib import Path; print(Path('config.json').read_text())\""}

# Check environment variables
POST /v1/exec {"command": "python -c \"import os; print(os.environ.get('ARENA_BRIDGE_HOME', 'NOT SET'))\""}
```

### Restart: `POST /v1/restart`

Restart the bridge service through the API:

```python
POST /v1/restart
```

**Use it when**:
- Code changes require a service restart
- The service is in an inconsistent state
- After fixing configuration issues

**⚠️ ALWAYS use `POST /v1/restart`, not direct OS commands.**

### Memory: `GET /v1/memory` / `POST /v1/memory`

Store and retrieve debugging context across sessions:

```python
# Store debugging notes
POST /v1/memory
{
  "key": "debug:current-investigation",
  "value": "Investigating intermittent 500 on /v1/exec. Phase 1 complete: symptom is timeout after 30s. Checking audit log next.",
  "tags": ["debug", "active"]
}

# Retrieve prior debugging notes
GET /v1/memory?tags=debug
```

---

## NSSM Service Debugging (Windows)

The arena-agent bridge runs as an NSSM service on Windows. Debugging service issues requires special care.

### ❌ NEVER Do This:
```powershell
# DON'T use PowerShell Restart-Service
Restart-Service arena-bridge

# DON'T use sc query output text directly on Russian Windows
# The output will be in Cyrillic (e.g., "Работает" instead of "RUNNING")
```

### ✅ Correct Approach:

```python
# 1. Restart via bridge API
POST /v1/restart

# 2. If bridge API is down, use NSSM
POST /v1/exec {"command": "nssm restart arena-bridge"}

# 3. Check status via NSSM (parses state codes, not text)
POST /v1/exec
{
  "command": "python -c \"\nimport subprocess\nresult = subprocess.run(['sc', 'query', 'arena-bridge'], capture_output=True, text=True, encoding='cp1251')\nprint(result.stdout)\n# Parse by state code: 1=stopped, 2=starting, 3=stopping, 4=running\nfor line in result.stdout.split('\\n'):\n    if 'STATE' in line.upper() or 'СОСТОЯНИЕ' in line:\n        print(f'Status line: {line.strip()}')\n\""
}
```

### Russian Locale NSSM Parsing

On Russian Windows, `sc query` output looks like:

```
СОСТОЯНИЕ СЛУЖБЫ: 4  WORKING
```

Or:
```
СОСТОЯНИЕ СЛУЖБЫ: 1  STOPPED
```

**Parse by the numeric state code**, not by text:
- `1` = Stopped
- `2` = Start Pending
- `3` = Stop Pending
- `4` = Running
- `5` = Continue Pending
- `6` = Pause Pending
- `7` = Paused

```python
import re

def parse_service_status(sc_output: str) -> int:
    """Parse Windows service status code from sc query output.

    Works regardless of locale (Russian, English, etc.)
    """
    match = re.search(r':\s*(\d)\s', sc_output)
    if match:
        return int(match.group(1))
    raise ValueError(f"Could not parse service status from: {sc_output}")
```

---

## Common Debugging Scenarios

### Scenario 1: Stress Test Failure

```
1. Identify which test(s) fail
   POST /v1/exec {"command": "python stress_test.py -v"}

2. Run the failing test in isolation
   POST /v1/exec {"command": "python -m pytest stress_test.py::TestClassName::test_name -v"}

3. Check if it's a test issue or a real bug
   - Does the test fail consistently?
   - Does the corresponding API endpoint work when called manually?

4. Follow the four phases for the underlying bug
```

### Scenario 2: Bridge Service Unresponsive

```
1. Check if the process is running
   POST /v1/exec {"command": "python -c \"import psutil; [print(p.info) for p in psutil.process_iter(['pid','name']) if 'arena' in p.info['name'].lower()]\""}

2. Check the port
   POST /v1/exec {"command": "python -c \"import socket; s=socket.socket(); result=s.connect_ex(('localhost',8765)); print('Port open' if result==0 else 'Port closed'); s.close()\""}

3. Restart via API or NSSM/systemctl

4. Check doctor endpoint
   GET /v1/doctor

5. If still broken, check logs
   POST /v1/exec {"command": "python -c \"from pathlib import Path; log=Path('logs/arena-bridge.log'); print(log.read_text()[-2000:] if log.exists() else 'No log file')\""}
```

### Scenario 3: Encoding Issues (Russian Locale)

```
1. Identify the encoding at play
   POST /v1/exec {"command": "python -c \"import sys,locale; print(f'default: {sys.getdefaultencoding()}'); print(f'fs: {sys.getfilesystemencoding()}'); print(f'locale: {locale.getpreferredencoding()}')\""}

2. Check the specific problematic output
   POST /v1/exec {"command": "chcp"}  # On Windows, shows current code page

3. Test with explicit encoding
   POST /v1/exec {"command": "python -c \"s='тест'; print(s); print(s.encode('utf-8')); print(s.encode('cp1251'))\""}

4. Follow the four phases with encoding as the root cause hypothesis
```

### Scenario 4: Cross-Platform Failure

```
1. Identify the OS
   POST /v1/exec {"command": "python -c \"import platform; print(platform.system()); print(platform.release())\""}

2. Find OS-specific code paths
   - Search for platform.system() checks
   - Search for os.name checks
   - Search for Windows/Linux/macOS-specific commands

3. Check if the failing code path is OS-specific
4. Follow the four phases with cross-platform as the root cause hypothesis
```

---

## Debugging Session Protocol

### Start of Session

```markdown
## Debugging Session: <Issue Title>

**Started**: <timestamp>
**Symptom**: <exact description>

### Phase 1: Root Cause
- [ ] Symptom defined
- [ ] Audit log checked
- [ ] Doctor check run
- [ ] Issue reproduced
- [ ] Bisect to change (if applicable)

### Phase 2: Pattern Analysis
- [ ] Similar patterns searched
- [ ] Edge cases checked
- [ ] Stress tests analyzed
- [ ] Memory checked for prior occurrences

### Phase 3: Hypothesis
- [ ] Hypothesis formed
- [ ] Hypothesis verified
- [ ] Alternative hypotheses ranked

### Phase 4: Implementation
- [ ] Failing test written (RED)
- [ ] Fix implemented (GREEN)
- [ ] Code refactored (REFACTOR)
- [ ] Full verification (stress tests 39/39)
- [ ] Findings stored in memory
- [ ] Committed
```

### End of Session

Update memory with final findings:

```python
POST /v1/memory
{
  "key": "debug:<issue-name>",
  "value": "RESOLVED. Root cause: <cause>. Fix: <fix>. Test: <test_name>. Affected files: <files>.",
  "tags": ["debug", "resolved", "<category>"]
}
```

---

## Anti-Patterns

### ❌ "Shotgun Debugging" — Change Multiple Things at Once
```
"I'll fix the encoding AND the timeout AND the error handling all at once"

If one of those fixes the bug, you won't know which one. Change one
thing at a time. Verify after each change.
```

### ❌ "Coincidental Fix" — Something Worked, Move On
```
"I added a sleep and now it works. Done!"

The sleep isn't the fix — it's masking a race condition. Find the
actual cause. The sleep will fail again under different timing.
```

### ❌ "Blind Stack Overflow" — Copy-Paste a Solution Without Understanding
```
"Someone on SO said to set PYTHONIOENCODING=utf-8, so I did"

That might work for their situation. Do you understand WHY it works
for yours? If not, you're introducing a fix you can't maintain.
```

### ❌ "Debugging in Production" — Making Changes on the Live System
```
"I'll just add a print statement to the running service"

No. Make changes in a controlled way:
1. Write a test that reproduces the issue
2. Make the fix locally
3. Verify with stress tests
4. Commit and restart the service cleanly
```

### ❌ "Skipping Phases" — Going Straight to Fix
```
"I know what the problem is, let me just fix it"

You think you know. You might be wrong. The four phases ensure you
actually know. Skipping them means you're guessing.
```

---

## Integration with Other Skills

| When to Switch | Target Skill | Reason |
|---|---|---|
| Bug reveals design flaw | `brainstorming` | The fix requires architectural changes |
| Fix is straightforward but needs a plan | `writing-plans` | Multiple steps to fix properly |
| Need to write tests for the fix | `test-driven-development` | TDD for the bug fix |
| Fix needs careful execution | `executing-plans` | Step-by-step verification |

---

## Summary

| Phase | Goal | Key Actions |
|---|---|---|
| **1. Root Cause** | What changed? What broke? | Audit log, doctor, reproduce, bisect |
| **2. Pattern Analysis** | Isolated or systemic? | Search codebase, check edge cases, stress tests |
| **3. Hypothesis** | Testable explanation | Form hypothesis, verify, rank alternatives |
| **4. Implementation** | Fix with regression test | RED test, GREEN fix, REFACTOR, verify 39/39 |

| Principle | Rule |
|---|---|
| **No guessing** | Investigate before changing |
| **Four phases** | No skipping |
| **Bridge tools** | Use audit, doctor, exec, memory |
| **Test first** | RED → GREEN → REFACTOR |
| **Service management** | `POST /v1/restart`, never direct OS commands |
| **Russian locale** | Parse by state codes, not text; handle CP1251 |
| **Escalate when blocked** | Ask Ivan after thorough investigation |

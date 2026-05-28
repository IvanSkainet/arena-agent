# Test-Driven Development

> **Quality-First Skill** — No production code without a failing test first. RED → GREEN → REFACTOR. The arena-agent bridge must always pass 39/39 stress tests.

## Purpose

Ensure every piece of functionality in the arena-agent bridge is verified by tests before it exists. TDD isn't about writing tests — it's about driving design through tests. The test tells you what the code should do before you write the code that does it.

---

## Iron Laws

1. **NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST** — Write a test that fails (RED), then write the minimum code to make it pass (GREEN), then clean up (REFACTOR). This cycle is inviolable.
2. **STRESS TESTS ARE THE FINAL GATE** — After any code change, all 39 stress tests must pass. Individual unit tests verify specific behavior; stress tests verify system integrity.
3. **NO SKIPPING REFACTOR** — The third step is not optional. After GREEN, you MUST review and clean up before moving on.
4. **TESTS MUST BE DETERMINISTIC** — No flaky tests. No time-dependent tests without mocking. No tests that pass "sometimes." A test that isn't reliable isn't a test.

---

## The RED-GREEN-REFACTOR Cycle

```
    ┌─────────────┐
    │    RED       │  Write a failing test
    │              │  that describes the
    │              │  desired behavior
    └──────┬──────┘
           │
           │  Test FAILS ✗
           │
           ▼
    ┌─────────────┐
    │    GREEN     │  Write the MINIMUM
    │              │  production code
    │              │  to make the test pass
    └──────┬──────┘
           │
           │  Test PASSES ✓
           │
           ▼
    ┌─────────────┐
    │   REFACTOR   │  Clean up the code
    │              │  without changing
    │              │  behavior
    └──────┬──────┘
           │
           │  Test STILL PASSES ✓
           │
           ▼
    ┌─────────────┐
    │    Next      │  Write the next
    │    Test      │  failing test
    └─────────────┘
```

### Detailed Cycle Description

#### RED Phase
1. Think about what behavior you want to add
2. Write a test that describes that behavior
3. Run the test — it MUST fail (if it passes, the test is wrong or the behavior already exists)
4. The failure message should clearly indicate what's missing

```python
# Example: We want ReconnectHandler with exponential backoff

# tests/test_reconnect.py
import pytest
from bridge.reconnect import ReconnectHandler

def test_backoff_increases_exponentially():
    handler = ReconnectHandler(base_delay=1.0, max_delay=30.0)
    delays = [handler.calculate_backoff(i) for i in range(5)]
    # Each delay should be roughly double the previous
    assert delays[1] >= delays[0] * 1.9  # allow jitter
    assert delays[2] >= delays[1] * 1.9
    assert delays[3] >= delays[2] * 1.9
    # Should cap at max_delay
    assert all(d <= 30.0 for d in delays)
```

Run: `python -m pytest tests/test_reconnect.py::test_backoff_increases_exponentially -v`
Expected: **FAIL** — `ModuleNotFoundError: No module named 'bridge.reconnect'`

#### GREEN Phase
1. Write the **minimum** code to make the test pass
2. Don't add features the test doesn't require
3. Don't optimize prematurely
4. Don't add error handling the test doesn't check

```python
# bridge/reconnect.py
import random
import time

class ReconnectHandler:
    def __init__(self, base_delay: float = 1.0, max_delay: float = 30.0, max_retries: int = 5):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_retries = max_retries

    def calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff with jitter."""
        backoff = min(
            self.base_delay * (2 ** attempt) + random.uniform(0, 1),
            self.max_delay
        )
        return backoff
```

Run: `python -m pytest tests/test_reconnect.py::test_backoff_increases_exponentially -v`
Expected: **PASSED** ✓

#### REFACTOR Phase
1. Review the code for clarity, DRY, naming
2. Improve structure without changing behavior
3. Run the test again — must still pass
4. This is where you add docstrings, extract constants, simplify

```python
# bridge/reconnect.py (after refactor)
"""Reconnection handler with exponential backoff and jitter."""

import random
from dataclasses import dataclass

@dataclass
class ReconnectHandler:
    """Manages reconnection attempts with configurable exponential backoff.

    Args:
        base_delay: Initial delay in seconds (default: 1.0)
        max_delay: Maximum delay cap in seconds (default: 30.0)
        max_retries: Maximum reconnection attempts (default: 5)
    """
    base_delay: float = 1.0
    max_delay: float = 30.0
    max_retries: int = 5

    def calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff with jitter for given attempt number.

        Uses formula: min(base_delay * 2^attempt + random_jitter, max_delay)

        Args:
            attempt: Zero-indexed attempt number

        Returns:
            Delay in seconds before next reconnection attempt
        """
        raw_backoff = self.base_delay * (2 ** attempt)
        jitter = random.uniform(0, self.base_delay)
        return min(raw_backoff + jitter, self.max_delay)
```

Run: `python -m pytest tests/test_reconnect.py::test_backoff_increases_exponentially -v`
Expected: **PASSED** ✓ (behavior unchanged, code improved)

---

## Test Framework: pytest

The arena-agent bridge uses **pytest** as its test framework.

### Running Tests

```python
# Run a single test
POST /v1/exec {"command": "python -m pytest tests/test_file.py::test_name -v"}

# Run all tests in a file
POST /v1/exec {"command": "python -m pytest tests/test_file.py -v"}

# Run all tests matching a pattern
POST /v1/exec {"command": "python -m pytest tests/ -k 'reconnect' -v"}

# Run the full stress test suite
POST /v1/exec {"command": "python stress_test.py"}

# Run with coverage
POST /v1/exec {"command": "python -m pytest tests/ --cov=bridge --cov-report=term-missing"}
```

### Test File Organization

```
tests/
├── unit/                    # Unit tests (fast, isolated)
│   ├── test_reconnect.py
│   ├── test_auth.py
│   └── test_exec.py
├── integration/             # Integration tests (slower, multi-component)
│   ├── test_api_endpoints.py
│   └── test_subagent_lifecycle.py
├── conftest.py              # Shared fixtures
└── fixtures/                # Test data
    ├── sample_requests/
    └── sample_responses/
```

### Test Naming Convention

```python
# test_<what>_<condition>_<expected_result>
def test_calculate_backoff_attempt_zero_returns_base_delay():
    ...

def test_calculate_backoff_high_attempt_capped_at_max_delay():
    ...

def test_exec_command_missing_token_returns_401():
    ...
```

### Shared Fixtures (conftest.py)

```python
import pytest
from pathlib import Path

@pytest.fixture
def bridge_client():
    """Create a test client for the bridge API."""
    from bridge.app import create_app
    app = create_app(test_mode=True)
    with app.test_client() as client:
        yield client

@pytest.fixture
def auth_token():
    """Provide a valid test auth token."""
    return "test-token-for-arena-bridge"

@pytest.fixture
def auth_headers(auth_token):
    """Provide authentication headers for API requests."""
    return {"Authorization": f"Bearer {auth_token}"}

@pytest.fixture
def temp_directory(tmp_path):
    """Provide a temporary directory for file operations."""
    return tmp_path

@pytest.fixture
def russian_locale_env(monkeypatch):
    """Set up Russian locale environment variables for testing."""
    monkeypatch.setenv("LANG", "ru_RU.UTF-8")
    monkeypatch.setenv("LC_ALL", "ru_RU.UTF-8")
```

---

## Arena-Agent Stress Tests

The project's stress test suite (`stress_test.py`) contains 39 tests that verify the complete bridge functionality. These are the **integration-level gate** that must always pass.

### Stress Test Categories

| Category | Count | What It Tests |
|---|---|---|
| API endpoint availability | ~8 | All endpoints respond correctly |
| Authentication | ~5 | Token validation, rejection of invalid tokens |
| Command execution | ~6 | `/v1/exec` with various commands |
| Memory operations | ~4 | Store and retrieve memories |
| Skill management | ~4 | List, read, and run skills |
| Service lifecycle | ~4 | Restart, health check, backup |
| Subagent management | ~4 | Spawn, status, cleanup |
| Cross-platform | ~4 | Path handling, encoding, service management |

### When to Run Stress Tests

| When | Which Tests |
|---|---|
| After every TDD cycle (RED→GREEN→REFACTOR) | Related unit tests only |
| After completing a feature | Full stress test suite |
| Before committing | Full stress test suite |
| After restarting the service | Full stress test suite |
| When in doubt | Full stress test suite |

### The 39/39 Rule

```
39/39 PASSED → ✅ Code is good
38/39 PASSED → ❌ Something is broken. Fix it.
37/39 PASSED → ❌ Something is very broken. Investigate.
 0/39 PASSED → ❌ Service is down. Check POST /v1/restart.
```

There is no acceptable number of failing stress tests other than zero.

---

## Rationalization Red Flags

Test-driven development is the most commonly rationalized-away discipline. Guard against these patterns:

| # | Rationalization | Why It's Wrong | What To Do Instead |
|---|---|---|---|
| 1 | "I'll write the tests after the code" | You won't. Or they'll test the implementation, not the behavior. | Write the test FIRST. Make it fail. Then write the code. |
| 2 | "This is too simple to test" | Simple code has simple bugs. Simple bugs are the hardest to find. | Write the test. It takes 30 seconds. |
| 3 | "Testing this would require mocking everything" | If it's hard to test, the design is wrong. That's the point of TDD. | Redesign for testability, then write the test. |
| 4 | "The stress tests cover this" | Stress tests verify integration. Unit tests verify behavior. You need both. | Write the unit test. Then run stress tests. |
| 5 | "I don't have time for TDD" | You have time to write it twice? Once without tests, once to fix the bugs? | TDD saves time by preventing bugs. Do it first. |
| 6 | "I'm just refactoring — tests aren't needed" | Refactoring WITHOUT tests is just changing code and hoping. | Tests are the safety net that makes refactoring possible. |
| 7 | "This is a bug fix — just fix the bug" | A bug fix without a test is a promise the bug won't recur. Tests are guarantees. | Write a test that reproduces the bug (RED), then fix the bug (GREEN). |
| 8 | "The existing test covers this change" | Does it? Run the test. Does it fail without your change? If not, it doesn't cover it. | Write a new test that fails without the change, then implement. |
| 9 | "TDD doesn't work for bridge/API code" | TDD works for all code. Test the behavior, not the framework. | Test API contracts: given request → expected response. |
| 10 | "I'll add a quick print to debug instead of a test" | Prints are removed. Tests remain. Tests are documented, reproducible debugging. | Write a test that demonstrates the issue, then fix it. |

---

## Edge Cases to Test

### Cross-Platform Tests

```python
import platform
import pytest

@pytest.mark.skipif(platform.system() != "Windows", reason="Windows-specific")
def test_exec_handles_windows_paths():
    """Verify exec handles Windows-style paths with backslashes."""
    ...

@pytest.mark.skipif(platform.system() != "Linux", reason="Linux-specific")
def test_exec_handles_systemctl_commands():
    """Verify exec properly handles systemctl output."""
    ...

def test_exec_path_normalization():
    """Verify paths are normalized regardless of OS."""
    # This should work on ALL platforms
    ...
```

### Russian Locale Tests

```python
def test_exec_handles_cp1251_output(russian_locale_env):
    """Verify exec normalizes CP1251 output to UTF-8."""
    # Simulate CP1251 output from a Russian Windows command
    cp1251_text = "Служба работает".encode("cp1251")
    ...

def test_memory_stores_cyrillic_keys():
    """Verify memory API handles Cyrillic characters in keys and values."""
    ...

def test_file_paths_with_cyrillic():
    """Verify file operations work with Cyrillic characters in paths."""
    ...
```

### NSSM Service Tests (Windows)

```python
@pytest.mark.skipif(platform.system() != "Windows", reason="Windows NSSM test")
def test_restart_uses_bridge_api_not_sc():
    """Verify restart goes through bridge API, not direct sc commands."""
    ...

def test_service_status_parsing_russian_locale():
    """Verify service status is parsed correctly on Russian Windows."""
    # sc query on Russian Windows outputs "Работает" not "RUNNING"
    # Must parse by state code (4 = running), not by text
    ...
```

### Error Handling Tests

```python
def test_exec_invalid_command_returns_error_not_crash():
    """Verify invalid commands return error responses, not server crashes."""
    ...

def test_memory_stores_large_values():
    """Verify memory API handles large values without issues."""
    ...

def test_concurrent_exec_requests():
    """Verify bridge handles concurrent exec requests safely."""
    ...
```

---

## TDD Workflow with the Bridge

### Starting a New Feature

```
1. Write failing test (RED)
   POST /v1/exec {"command": "python -m pytest tests/unit/test_new_feature.py -v"}
   → FAIL

2. Write minimum code (GREEN)
   POST /v1/exec {"command": "python -m pytest tests/unit/test_new_feature.py -v"}
   → PASS

3. Refactor (REFACTOR)
   POST /v1/exec {"command": "python -m pytest tests/unit/test_new_feature.py -v"}
   → PASS

4. Run stress tests
   POST /v1/exec {"command": "python stress_test.py"}
   → 39/39 PASS

5. Commit
   POST /v1/exec {"command": "git add -A && git commit -m 'test: add tests for new feature'"}
```

### Fixing a Bug

```
1. Write a test that reproduces the bug (RED)
   POST /v1/exec {"command": "python -m pytest tests/unit/test_bug_fix.py -v"}
   → FAIL (bug is present)

2. Fix the bug (GREEN)
   POST /v1/exec {"command": "python -m pytest tests/unit/test_bug_fix.py -v"}
   → PASS

3. Verify no regression (REFACTOR)
   POST /v1/exec {"command": "python stress_test.py"}
   → 39/39 PASS

4. Commit
   POST /v1/exec {"command": "git add -A && git commit -m 'fix: handle edge case in ...'"}
```

### Adding to an Existing Feature

```
1. Write a test for the new behavior (RED)
2. Add the minimum code to pass (GREEN)
3. Refactor if needed (REFACTOR)
4. Run stress tests → 39/39 PASS
5. Commit
```

---

## Test Quality Criteria

### Good Test Characteristics (FIRST)

| Principle | Meaning | Example |
|---|---|---|
| **Fast** | Runs in milliseconds, not seconds | Mock external dependencies |
| **Isolated** | No dependency on other tests or external state | Use fixtures, not shared state |
| **Repeatable** | Same result every time | No random data without seeding |
| **Self-validating** | Pass or fail, no manual inspection | Assert specific values |
| **Timely** | Written at the right time — before the code | TDD: test first |

### Test Coverage Guidelines

| Module | Target Coverage | Rationale |
|---|---|---|
| Core bridge logic | ≥90% | Critical path, must be reliable |
| API endpoint handlers | ≥85% | Security and correctness critical |
| Utility functions | ≥80% | Important for correctness |
| Service management | ≥70% | Harder to test, but critical paths covered |
| Configuration | ≥60% | Static data, lower risk |

**Note**: Coverage is a guide, not a goal. 100% coverage of meaningless tests is worse than 80% coverage of meaningful tests.

---

## Mocking Strategy

### What to Mock
- External services (HTTP calls, database connections)
- Time-dependent behavior (`time.sleep`, `datetime.now`)
- File system operations (for fast tests)
- Random number generation (for determinism)

### What NOT to Mock
- The code being tested (that defeats the purpose)
- Simple data structures (just use real ones)
- Python standard library functions (they're reliable)

### Example Mocking

```python
from unittest.mock import patch, MagicMock

def test_reconnect_with_mocked_time():
    """Test reconnection without actually waiting."""
    with patch('time.sleep') as mock_sleep:
        handler = ReconnectHandler(base_delay=1.0, max_delay=30.0)
        handler.attempt_reconnect()

        # Verify sleep was called with expected delays
        assert mock_sleep.call_count > 0
        # First call should be roughly base_delay
        first_delay = mock_sleep.call_args_list[0][0][0]
        assert 1.0 <= first_delay <= 2.0  # base_delay + jitter
```

---

## Anti-Patterns

### ❌ "Write All Tests at the End"
```
This is not TDD. This is "writing tests" — and you'll skip it, or the
tests will be shaped by your implementation rather than your intent.
```

### ❌ "Test the Implementation, Not the Behavior"
```python
# BAD: Testing implementation details
def test_handler_uses_dictionary_internally():
    handler = ReconnectHandler()
    assert isinstance(handler._attempts, dict)

# GOOD: Testing observable behavior
def test_handler_tracks_attempt_count():
    handler = ReconnectHandler()
    assert handler.attempt_count == 0
    handler.attempt_reconnect()
    assert handler.attempt_count == 1
```

### ❌ "One Giant Test for Everything"
```python
# BAD: One test that tries to test everything
def test_everything():
    handler = ReconnectHandler()
    handler.attempt_reconnect()
    handler.attempt_reconnect()
    # ... 50 more assertions

# GOOD: Focused tests
def test_first_attempt_uses_base_delay():
    ...

def test_subsequent_attempts_increase_delay():
    ...

def test_delay_capped_at_max():
    ...
```

### ❌ "Test Only the Happy Path"
```
Error handling is where the bugs live. Test:
- Invalid inputs
- Missing data
- Network failures
- Permission errors
- Encoding issues
- Concurrent access
```

---

## Integration with Other Skills

| Before This Skill | Trigger |
|---|---|
| `brainstorming` | Design approved, need to start coding |
| `writing-plans` | Plan includes TDD steps |
| `executing-plans` | Execution encounters uncovered code |

| After This Skill | Trigger |
|---|---|
| `executing-plans` | Tests written, ready to implement |
| `systematic-debugging` | Test reveals unexpected behavior |
| `brainstorming` | Test difficulty reveals design flaw |

---

## Summary

| Principle | Rule |
|---|---|
| **RED first** | No production code without a failing test |
| **GREEN minimum** | Write the least code to make the test pass |
| **REFACTOR mandatory** | Clean up after every GREEN |
| **39/39 stress tests** | Final gate after every feature |
| **Deterministic tests** | No flakiness. Pass/fail, every time. |
| **Test behavior** | Not implementation details |
| **FIRST principles** | Fast, Isolated, Repeatable, Self-validating, Timely |
| **No rationalization** | Every reason to skip TDD is wrong |

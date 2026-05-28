# Using Arena Superpowers

> **Bootstrap Skill** — This is the first skill loaded. It teaches you how to discover, evaluate, and invoke all other arena-superpowers skills within the arena-agent bridge environment.

## Purpose

You are operating inside the **arena-agent bridge** — a local HTTP API server (port 8765) that lets any AI control a computer. This skill is your operational manual for the skill system itself. Read it once, internalize it, then follow it always.

---

## The Arena-Agent Bridge Environment

The arena-agent bridge provides these core API endpoints:

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/exec` | POST | Execute shell commands on the host |
| `/v1/skills` | GET | List all available skills |
| `/v1/skills/run` | POST | Invoke a skill by name with parameters |
| `/v1/memory` | GET | Retrieve stored memories/context |
| `/v1/memory` | POST | Store memories/context |
| `/v1/inventory` | GET | Project file inventory and context |
| `/v1/audit` | GET | Recent change audit log |
| `/v1/doctor` | GET | Self-diagnostic health check |
| `/v1/restart` | POST | Restart the bridge service |
| `/v1/backup` | POST | Create a backup before changes |
| `/v1/subagents/spawn` | POST | Spawn a subagent for parallel work |

All endpoints require token authentication via `Authorization: Bearer <token>` header.

The bridge runs as:
- **Windows**: NSSM service (`arena-bridge`)
- **Linux/macOS**: systemd/launchd or foreground process

---

## Skill Discovery

### How to List Available Skills

```
GET /v1/skills
```

Returns a JSON array of skill objects:
```json
[
  {
    "name": "brainstorming",
    "path": "skills/brainstorming/SKILL.md",
    "description": "Design documents with HARD GATE before coding",
    "triggers": ["design", "brainstorm", "architecture", "plan feature"]
  }
]
```

### How to Read a Skill's Content

Skills are Markdown files. Read them directly from the filesystem:
```
POST /v1/exec
{
  "command": "cat /path/to/arena-superpowers/skills/brainstorming/SKILL.md"
}
```

Or use the skills API:
```
POST /v1/skills/run
{
  "skill": "brainstorming",
  "action": "read"
}
```

### How to Invoke a Skill

```
POST /v1/skills/run
{
  "skill": "brainstorming",
  "action": "execute",
  "params": {
    "topic": "websocket reconnection strategy"
  }
}
```

---

## Skill Invocation Rules

### Rule 1: MANDATORY Invocation

If there is even a **1% chance** that a skill is relevant to the current task, you **MUST** invoke it. This is not optional.

**Rationale**: Skills encode hard-won operational knowledge. Skipping them because "I already know how to do this" is the #1 cause of preventable errors.

### Rule 2: Ivan's Instructions Override Everything

Ivan (the project owner) may provide explicit instructions via:
- Direct conversation messages
- Stored in bridge memory (`GET /v1/memory`)
- Embedded in RECOVERY_PROMPT or project rules

These instructions take **highest priority** — above skills, above defaults, above your judgment. If Ivan says "do it this way," you do it that way. Period.

### Rule 3: Skill Content is Law

Once a skill is invoked and its content loaded, follow it exactly. Skills contain:
- **Iron Laws** — absolute rules with no exceptions
- **Hard Gates** — checkpoints that require explicit approval
- **Process flows** — step-by-step procedures

Do not improvise around a skill's requirements. If the skill says "stop and ask," you stop and ask.

---

## Decision Flowchart

```
                        ┌─────────────────────┐
                        │  New task arrives    │
                        └─────────┬───────────┘
                                  │
                        ┌─────────▼───────────┐
                        │ Check Ivan's         │
                        │ explicit instructions│
                        │ (GET /v1/memory)     │
                        └─────────┬───────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
               Has explicit   No explicit    Partial match
               instructions   instructions   (clarify first)
                    │             │             │
                    ▼             ▼             │
              Follow Ivan's  Continue ↓    Ask Ivan ──┐
              instructions                  for clarity │
                    │                         │        │
                    │                         ▼        │
                    │              ┌──────────────────┐│
                    │              │ GET /v1/skills    ││
                    │              │ List all skills   ││
                    │              └────────┬─────────┘│
                    │                       │          │
                    │              ┌────────▼─────────┐│
                    │              │ For each skill:   ││
                    │              │ Is this even 1%   ││
                    │              │ relevant?         ││
                    │              └────────┬─────────┘│
                    │                  ┌─────┼─────┐   │
                    │              Yes │     │ No  │   │
                    │                  │     │     │   │
                    │                  ▼     │     │   │
                    │          ┌────────────┐│     │   │
                    │          │ READ the   ││     │   │
                    │          │ SKILL.md   ││     │   │
                    │          │ fully      ││     │   │
                    │          └─────┬──────┘│     │   │
                    │                │       │     │   │
                    │                ▼       │     │   │
                    │          ┌────────────┐│     │   │
                    │          │ FOLLOW the ││     │   │
                    │          │ skill      ││     │   │
                    │          │ exactly    ││     │   │
                    │          └─────┬──────┘│     │   │
                    │                │       │     │   │
                    │                ▼       │     │   │
                    │        ┌──────────────┐│     │   │
                    │        │Any conflicts ││     │   │
                    │        │with Ivan's   ││     │   │
                    │        │instructions? ││     │   │
                    │        └──────┬───────┘│     │   │
                    │          ┌────┴────┐   │     │   │
                    │        Yes│       │No  │     │   │
                    │           │       │    │     │   │
                    │           ▼       │    │     │   │
                    │    Ivan wins.     │    │     │   │
                    │    Override skill.│    │     │   │
                    │           │       │    │     │   │
                    │           └───┬───┘    │     │   │
                    │               │        │     │   │
                    │               ▼        │     │   │
                    │         Execute task   │     │   │
                    │         per combined   │     │   │
                    │         instructions   │     │   │
                    │                        │     │   │
                    └────────────────────────┘◄────┘   │
                                                   │   │
                                                   └───┘
```

---

## Red Flags: Rationalization Patterns

You MUST actively guard against these rationalization patterns. If you catch yourself thinking any of the following, **STOP** and invoke the relevant skill anyway:

| # | Rationalization | Why It's Wrong | What To Do Instead |
|---|---|---|---|
| 1 | "I already know how to do this" | Skills encode project-specific conventions, not generic knowledge | Read the skill. Follow it. |
| 2 | "This is too simple for a skill" | Simple tasks gone wrong cause the worst bugs | Invoke the skill regardless of perceived complexity |
| 3 | "The skill would slow me down" | Skipping skills slows you down when you hit the edge case the skill was designed for | The skill IS the fast path |
| 4 | "I'll just write the code directly" | Code without design = design by accident | Invoke brainstorming → writing-plans → executing-plans |
| 5 | "The user wants results, not process" | The user wants CORRECT results. Process ensures correctness | Follow the process. Ship correct results. |
| 6 | "I can skip the test — it's obvious" | "Obvious" code has the most subtle bugs | Invoke TDD. Write the test first. |
| 7 | "I don't need to read the skill — I remember it" | Memory is lossy. Skills are precise. | Read the skill fresh every time. |
| 8 | "This is an emergency, skip the process" | Emergencies are when you need process MOST — panic causes mistakes | Follow the skill. Slow is smooth. Smooth is fast. |
| 9 | "I'll just fix this one thing without a plan" | "One thing" becomes ten things becomes a broken system | Write a plan. Execute the plan. |
| 10 | "The skill doesn't cover my exact situation" | Skills provide principles, not just recipes. Apply the principle. | Read the skill for the underlying principle, then adapt. |

---

## Skill Categories

### Meta-Skills (Operational)
| Skill | Trigger Words | Iron Law |
|---|---|---|
| **using-arena-superpowers** | bootstrap, how to use skills, start | Read this first, always |
| **brainstorming** | design, brainstorm, architecture, spec | NO CODE until Ivan approves design |
| **writing-plans** | plan, roadmap, step-by-step, implementation plan | No placeholders — exact code, paths, commands |
| **executing-plans** | execute, implement, do the plan, carry out | Backup first. Verify after each step. |
| **subagent-driven-development** | subagent, parallel, spawn, delegate | Two-stage review: spec → quality |

### Quality Skills
| Skill | Trigger Words | Iron Law |
|---|---|---|
| **test-driven-development** | test, TDD, verify, pytest, stress test | No production code without a failing test first |
| **systematic-debugging** | debug, investigate, broken, error, fix | Four phases. No skipping. No guessing. |

---

## Cross-Platform Awareness

The arena-agent bridge runs on **Windows, Linux, and macOS**. When a skill or your own code touches the filesystem, process management, or OS-level APIs, you MUST:

1. **Paths**: Use `pathlib.Path` or `os.path.join()` — never hardcoded separators
2. **Commands**: Check `platform.system()` before running OS-specific commands
3. **Service management**: Use bridge API (`POST /v1/restart`), never direct `Restart-Service` or `systemctl`
4. **Encoding**: Default to UTF-8. For Russian locale, handle both UTF-8 and Windows-1251
5. **Line endings**: Be aware of CRLF (Windows) vs LF (Linux/macOS)

### Russian Locale Specifics

- Windows Russian locale may use CP1251 encoding for some system commands
- `sc query` output on Russian Windows uses Cyrillic status names (e.g., "Работает" instead of "RUNNING")
- File paths may contain Cyrillic characters — always use Unicode-aware APIs
- `POST /v1/exec` handles encoding normalization, but be aware when parsing raw output

---

## Memory Integration

The bridge provides persistent memory for cross-session context:

```python
# Store a memory
POST /v1/memory
{
  "key": "design:websocket-reconnect",
  "value": "Exponential backoff with jitter, max 30s",
  "tags": ["design", "websocket"]
}

# Retrieve memories
GET /v1/memory?key=design:websocket-reconnect
GET /v1/memory?tags=design
```

**Use memory to**:
- Store Ivan's instructions for future sessions
- Record design decisions and their rationale
- Track in-progress work state
- Save debugging findings across investigation steps

---

## Stress Test Awareness

The arena-agent project has a comprehensive stress test suite (39/39 must pass). After ANY change to the bridge code:

1. Run stress tests: `POST /v1/exec {"command": "python stress_test.py"}`
2. All 39 must pass
3. If any fail, the change is NOT complete — do not proceed

This is non-negotiable. Stress tests are the gatekeeper for quality.

---

## Quick Reference: Skill Invocation Checklist

Before starting ANY task, run through this checklist:

- [ ] **Check memory**: `GET /v1/memory` — any instructions from Ivan?
- [ ] **List skills**: `GET /v1/skills` — what's available?
- [ ] **Evaluate relevance**: For each skill, is there even 1% chance it's relevant?
- [ ] **Read relevant skills**: Full content, no skimming
- [ ] **Follow skill instructions**: Exactly, no shortcuts
- [ ] **Handle conflicts**: Ivan's instructions > skill > defaults
- [ ] **Verify after action**: Run stress tests after code changes

---

## Anti-Patterns

### ❌ The "I'll Just" Pattern
```
"I'll just fix this typo" → changes 3 files → breaks stress tests
"I'll just add a log" → introduces encoding bug → Russian paths break
"I'll just refactor" → changes API contract → clients fail
```

### ✅ The Correct Pattern
```
1. Identify the task
2. Check for relevant skills
3. Read the skill fully
4. Follow the skill's process
5. Verify (stress tests)
6. Report results
```

### ❌ The "Good Enough" Pattern
```
"95% of tests pass, that's good enough" → it's not
"I think this works" → you don't know until you verify
"Probably fine" → definitely not fine
```

### ✅ The Correct Pattern
```
1. 39/39 stress tests pass OR the change is not complete
2. Verified by execution, not by reasoning
3. "Confirmed working" = tests green + manual check
```

---

## Summary

| Principle | Rule |
|---|---|
| **Skill invocation** | If ≥1% relevant, invoke. No exceptions. |
| **Ivan's instructions** | Highest priority. Overrides everything. |
| **Skill compliance** | Follow skill content exactly. No improvising. |
| **Verification** | Stress tests must pass 39/39 after any change. |
| **Cross-platform** | Always handle Windows/Linux/macOS differences. |
| **Memory** | Use bridge memory for cross-session context. |
| **Anti-rationalization** | Watch for red flags. Stop and invoke the skill. |

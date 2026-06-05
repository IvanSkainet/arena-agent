# Brainstorming

> **Design-First Skill** — No code is written until Ivan approves the design document. This skill governs the creation of design documents that capture requirements, constraints, and architectural decisions for the arena-agent bridge.

## Purpose

Transform a vague idea or feature request into a precise, reviewable design document. This document becomes the contract between Ivan's intent and the implementation. **No implementation work begins until Ivan explicitly approves the design.**

---

## Iron Laws

1. **NO CODE UNTIL APPROVED** — Writing implementation code before Ivan approves the design is forbidden. This includes "exploratory" code, "quick prototypes," and "just to see if it works."
2. **DESIGN DOCS ARE MANDATORY** — Every feature, every change that affects more than one file, every API modification MUST have a design document first.
3. **APPROVAL IS EXPLICIT** — Ivan must say "approved" or equivalent. Silence is not approval. "Looks good" might be approval — confirm explicitly.
4. **YAGNI REIGNS** — You Ain't Gonna Need It. Design for the current requirement. Future features are noted but not designed.

---

## Hard Gate: Ivan Approval

```
    ┌─────────────────┐
    │  Design Doc      │
    │  Written          │
    └────────┬────────┘
             │
             ▼
    ┌─────────────────┐
    │  Present to Ivan │
    │  with summary    │
    └────────┬────────┘
             │
      ┌──────┼──────┐
      │      │      │
   Approved  Needs  Rejected
      │    Changes   │
      │      │      │
      ▼      ▼      ▼
   PROCEED  Revise  Stop.
   to plan  doc     Rethink.
```

**Do NOT proceed to `writing-plans` or any implementation until the gate is passed.**

---

## When to Invoke This Skill

Invoke this skill when ANY of the following are true:

- Ivan requests a new feature
- A bug fix requires architectural changes (affects >1 file)
- An API endpoint is being added or modified
- A new dependency is being introduced
- Performance characteristics are changing
- Security-relevant changes are being made
- Cross-platform behavior needs to be defined
- The word "design," "architecture," "brainstorm," or "spec" appears

---

## Process

### Phase 1: Gather Context

Before writing anything, collect all relevant information:

```python
# 1. Get project inventory
GET /v1/inventory
# → Understand current file structure, dependencies, configuration

# 2. Get existing memories for this topic
GET /v1/memory?tags=design
# → Check if there are prior decisions or partial designs

# 3. Read relevant existing code
POST /v1/exec
{
  "command": "python -c \"import pathlib; [print(p) for p in pathlib.Path('.').rglob('*.py') if 'bridge' in str(p).lower()]\""
}
# → Understand the current implementation

# 4. Check audit log for recent changes
GET /v1/audit
# → Understand what's been changing recently
```

**Context checklist**:
- [ ] Current project structure understood
- [ ] Existing code for the relevant area read and understood
- [ ] Prior design decisions from memory retrieved
- [ ] Recent changes from audit log reviewed
- [ ] Cross-platform implications identified
- [ ] Russian locale considerations identified (if relevant)

### Phase 2: Define the Problem

Write a clear, concise problem statement:

```markdown
## Problem

<What is the current situation?>
<What is the desired situation?>
<What is the gap between them?>
```

**Quality checks**:
- Can you explain the problem to someone who's never seen the project? → If not, it's too vague.
- Is the problem statement free of solution language? → If it mentions "using WebSocket" it's a solution, not a problem.
- Does Ivan agree this is the actual problem? → If not, you're solving the wrong thing.

### Phase 3: Explore Solutions

Generate at least **two** candidate solutions. For each:

```markdown
### Option A: <Name>

**Approach**: <1-2 sentence description>

**Pros**:
- ...

**Cons**:
- ...

**Complexity**: <Low/Medium/High>

**Cross-platform notes**: <Any OS-specific considerations>

**Risk**: <What could go wrong?>
```

**YAGNI Filter**: For each option, ask:
- Does this solve ONLY the stated problem? → If it also solves hypothetical future problems, it's over-engineered.
- Are there parts that are "nice to have" but not required? → Mark them clearly as future scope.
- Is the simplest option that fully solves the problem included? → If not, add it.

### Phase 4: Recommend

After exploring options, make a clear recommendation:

```markdown
## Recommendation

**Option <X>** because <reason>.

This is the simplest approach that fully addresses the problem statement
without introducing unnecessary complexity or future commitments.
```

**Your recommendation should be the simplest option that works.** Complexity is a cost. Only pay it when the problem demands it.

### Phase 5: Write the Design Document

Save to: `docs/specs/YYYY-MM-DD-topic-design.md`

Path must be relative to the project root. Use the current date. Use a short, hyphenated topic name.

**Example**: `docs/specs/2025-03-15-websocket-reconnect-design.md`

#### Design Document Template

```markdown
# Design: <Topic>

**Date**: YYYY-MM-DD
**Author**: Arena Agent
**Status**: DRAFT | APPROVED | REJECTED | SUPERSEDED
**Ivan Approval**: <pending>

---

## Problem

<Clear, concise problem statement free of solution language>

## Context

<Current state of the system relevant to this problem>
- Current architecture: ...
- Relevant code paths: ...
- Constraints: ...

## Requirements

### Must Have
- <Requirement 1>
- <Requirement 2>

### Should Have
- <Requirement 3> (not blocking)

### Won't Have (This Iteration)
- <Explicitly out of scope>

## Options Considered

### Option A: <Name>
<Full description from Phase 3>

### Option B: <Name>
<Full description from Phase 3>

## Recommendation

<Option X> because <reasoning>

## Detailed Design

### API Changes
<New/modified endpoints, request/response schemas>

### Data Model Changes
<New/modified data structures, storage>

### Cross-Platform Considerations
- Windows: ...
- Linux: ...
- macOS: ...

### Russian Locale Considerations
- Encoding: ...
- UI text: ...
- Path handling: ...

### Security Considerations
<Auth, token handling, input validation>

### Error Handling
<Expected failure modes and recovery>

### Backward Compatibility
<Breaking changes, migration path>

## Testing Strategy

- Unit tests: <what to test at the function level>
- Integration tests: <what to test across components>
- Stress test impact: <which of the 39 tests are affected>
- Manual verification: <what to check by hand>

## Open Questions

- <Question 1> — needs Ivan's input
- <Question 2> — needs investigation

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| YYYY-MM-DD | <decision> | <why> |
```

### Phase 6: Store Decisions in Memory

```python
POST /v1/memory
{
  "key": f"design:{topic}",
  "value": "<summary of the design and key decisions>",
  "tags": ["design", topic]
}
```

This ensures the design context survives across sessions.

### Phase 7: Present to Ivan

Present the design with:
1. **One-paragraph summary** — The problem and recommended solution
2. **Key trade-offs** — What was considered and why the recommendation was chosen
3. **Open questions** — Anything that needs Ivan's explicit input
4. **The full document** — Link or paste the design doc

Then **WAIT**. Do not proceed until Ivan responds with approval.

If Ivan requests changes:
1. Update the design document
2. Update memory
3. Re-present for approval

---

## YAGNI Principles

| Principle | Rule | Example |
|---|---|---|
| **No speculative features** | Don't design for "we might need this later" | Don't add a plugin system for a single handler |
| **No premature abstraction** | Don't create abstractions until you have 3+ instances | Don't make a HandlerFactory for one handler |
| **No future-proofing** | Design for today's requirements | Don't use 256-bit keys "for future crypto" |
| **No configuration for everything** | Hard-code sensible defaults | Don't add config for things that won't change |
| **No generalization without evidence** | Solve the specific case first | Don't make a generic serializer for one data type |

**Exception**: When Ivan explicitly requests a general solution, provide it. YAGNI yields to Ivan's instructions.

---

## Cross-Platform Design Checklist

When designing a feature, explicitly address:

- [ ] **File paths**: Does the feature interact with the filesystem? → Use `pathlib.Path`
- [ ] **Process management**: Does it start/stop/manage processes? → Use bridge API, not OS commands
- [ ] **Network**: Does it bind ports or make connections? → Document port behavior
- [ ] **Encoding**: Does it read/write text? → Default UTF-8, handle CP1251 on Russian Windows
- [ ] **Permissions**: Does it need elevated access? → Document requirements per OS
- [ ] **Service integration**: Does it affect NSSM/systemd? → Use `POST /v1/restart`
- [ ] **Temporary files**: Does it create temp files? → Use `tempfile` module, not hardcoded paths
- [ ] **Environment variables**: Does it read env vars? → Document required vars per OS
- [ ] **Shell commands**: Does it execute shell commands? → Use `POST /v1/exec`, handle OS differences

---

## Anti-Patterns

### ❌ "Let Me Just Code a Quick Prototype"
```
This is the #1 violation of this skill. There is no such thing as a
"quick prototype" — it becomes the implementation, and it was never
designed. Write the design doc first.
```

### ❌ "The Design Is Obvious"
```
If the design were truly obvious, writing the doc would take 5 minutes.
If writing the doc takes longer than 5 minutes, the design wasn't obvious.
Either way, write the doc.
```

### ❌ "I'll Design While I Code"
```
Design-by-coding produces code that reflects the path of least resistance,
not the best architecture. The code becomes a record of your exploration,
not a clean solution.
```

### ❌ "YAGNI Doesn't Apply Here — This Is Clearly Needed"
```
If you can't articulate a concrete, current requirement that demands the
feature, it's YAGNI. "Clearly needed" is not a requirement. "Ivan asked
for it" is a requirement.
```

---

## Rationalization Red Flags

| Rationalization | Reality |
|---|---|
| "It's just a small change, no design needed" | Small changes in a bridge API can break every client |
| "I'll write the design after I prototype" | You won't. The prototype becomes the design. Badly. |
| "The feature is too simple for a design doc" | Simple features have simple designs — 5 minutes to write |
| "Ivan wants this done fast, skip the design" | Ivan wants this done RIGHT. Design catches mistakes early. |
| "I can see the whole thing in my head" | If you can see it, you can write it down. Write it down. |

---

## Integration with Other Skills

| After This Skill | Next Skill | Trigger |
|---|---|---|
| Design approved | `writing-plans` | Ivan says "approved" or "go ahead" |
| Design needs revision | `brainstorming` (loop) | Ivan requests changes |
| Design rejected | `brainstorming` (restart) | Ivan says "no" or "different direction" |
| Discovery of technical constraint | `systematic-debugging` | Design reveals an unknown |

---

## Summary

| Step | Action | Output |
|---|---|---|
| 1 | Gather context | Understanding of current system |
| 2 | Define the problem | Clear problem statement |
| 3 | Explore solutions | ≥2 options with trade-offs |
| 4 | Recommend | Simplest option that works |
| 5 | Write design doc | `docs/specs/YYYY-MM-DD-topic-design.md` |
| 6 | Store in memory | `POST /v1/memory` |
| 7 | Present to Ivan | Wait for explicit approval |
| **GATE** | **Ivan approves** | **Only then proceed to writing-plans** |

# Arena Unified Bridge — Experiments

Date: 2026-06-19

This file is for ideas worth exploring but not safe enough to treat as core roadmap commitments.

---

## 1. Arena Agent Mode as backend/model proxy

### Idea
Drive a third-party agent/chat frontend session and use it as an indirect model backend.

### Why it is attractive
- potentially strong/free models
- quick experimentation
- low immediate API cost

### Why it is risky
- likely ToS fragility
- anti-bot / auth / frontend changes can break it anytime
- not raw API semantics
- hidden system prompting and behavioral constraints
- weak production foundation

### Recommendation
If explored, keep it behind an explicit provider abstraction and treat it as experimental only.

---

## 2. Other experimental provider adapters

Possible future experiments:
- browser-driven provider sessions
- unofficial wrappers around cloud UIs
- hybrid provider multiplexing with fallback heuristics

These should never become invisible core dependencies.

---

## 3. Rule for experiments

Experiments may be:
- prototyped
- benchmarked
- documented

But should not be promoted into the main roadmap until they are:
- operationally stable
- legally acceptable
- testable
- replaceable behind a clean interface

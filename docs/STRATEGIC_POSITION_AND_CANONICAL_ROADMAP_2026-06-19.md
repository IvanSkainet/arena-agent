# Arena Unified Bridge — strategic position + canonical roadmap

> **📎 Historical document.** This is a point-in-time snapshot kept for context. For the current state, see the [README](../README.md) and [CHANGELOG](../CHANGELOG.md).

Date: 2026-06-19
Baseline observed state in this workspace/live cycle: `v3.2.12`

---

## 1. Why AutoClaw felt attractive

From the screenshots and chat context, the interesting part of AutoClaw is **not** primarily its pricing or credits model. The attraction is product feeling:

- softer, less overbearing assistant behavior
- persistent workspace vibe instead of "just a tool runner"
- visible notes / memory / lessons / profile panes
- assistant identity feels less constrained by a strong product-owned system prompt
- chat-centric experience with traces like `Read 1 files`
- a sense of "companion agent" rather than only "automation backend"

This means the real opportunity for Arena is **not** "copy AutoClaw", but:

> keep Arena's strong engineering / bridge architecture and add more companion-like, agentic, workspace-oriented UX.

---

## 2. Product positioning: Arena vs AutoClaw vs Hermes vs OpenClaw

### Arena Unified Bridge
Strongest at:
- local automation substrate
- broad tool surface (REST + MCP + WS)
- filesystem / exec / browser / desktop / memory primitives
- modular Python architecture
- testing and release discipline
- self-hosted control

Weakest at:
- companion / persona / workspace UX
- high-level planning loop built into core
- "living assistant" feeling
- explicit long-horizon memory model

### AutoClaw
Strongest at:
- workspace UX
- assistant-like feel
- onboarding / identity / notes / lessons panels
- chat-first experience

Weakest / risky areas:
- cloud dependency
- pricing / credits dependency
- likely weaker local sovereignty than Arena
- less confidence in stable raw model access
- unclear long-term backend openness/control

### Hermes
Strongest at:
- larger ecosystem / buzz / breadth
- agent framework vibe
- broader "agent platform" direction

Weaknesses for your case:
- different architecture and much bigger moving parts surface
- forking/integrating it deeply would likely dilute Arena rather than strengthen it
- not the cleanest path to preserving Arena's current strengths

### OpenClaw / related local agents
Strongest at:
- local-agent vibe
- assistant framing
- potentially easier to reason about as a user-facing agent

Weaknesses vs Arena:
- Arena's tool/backend surface is already stronger and more structured
- less clear engineering discipline / modular boundary story

---

## 3. Strategic conclusion

The most valuable direction is **not**:
- replacing Arena with Hermes/OpenClaw
- or building Arena around a fragile model proxy hack

The most valuable direction is:

### "Arena Companion Mode"
A product direction where Arena keeps its existing bridge core, but gains:
- identity/persona
- scoped memory
- visible notes and lessons
- recurring tasks/plans
- better agent loop behavior
- workspace UX

That gives you the thing AutoClaw emotionally suggested, without giving up the reliability and control Arena already has.

---

## 4. About the "Arena Agent Mode as model proxy" idea

This should be treated as a **separate experimental adapter idea**, not as core architecture.

### Potential upside
- access to strong models with generous limits
- fast experimentation
- cheap/free prototyping

### Structural risks
- likely ToS fragility
- auth / anti-bot / frontend changes can break it anytime
- not raw API semantics
- unpredictable system-prompting / server-side steering
- weak foundation for a serious self-hosted product

### Recommendation
- OK as a research experiment / optional provider adapter prototype
- NOT OK as the main long-term model backend story

If explored at all, it should live behind an explicit **provider abstraction**, not as a hidden dependency in core behavior.

---

## 5. Canonical reality check: current state vs roadmap claims

The three roadmap files are useful for ideas, but they are **not a reliable source of truth anymore**.

### Current observed state (this cycle)
- Version: `3.2.12`
- Tests: `553 passed`
- MCP tools: `33`
- Route objects in aiohttp app: `296`
- Distinct method/path routes excluding auto-HEAD: `194`

### Major roadmap drift points

#### 1. Version drift
Roadmaps talk about `3.2.2`, `3.2.4`, `3.2.6`, but the actual project has already moved beyond them.

#### 2. Test-count drift
Roadmaps mention values like `528` and `565` tests. Actual current observed state is `553` tests.

#### 3. Backup status is inconsistent
One roadmap marks **S4 Automatic Backups** as complete. But the code/docs history says backup functionality had previously been removed from the product surface as unsafe.

Concrete inconsistency found in the current tree:
- `README.md` says backup feature was removed in the product
- `arena/agentctl_cli/agentctl_misc.py` still contains `backup_run(...)` calling `/v1/backup`

This is a stale surface / cleanup candidate and a strong sign that roadmap claims around backups are not trustworthy without code verification.

#### 4. Git Integration status is stale in older roadmap files
Older files still list F6 as pending; current project already has MCP git tools.

#### 5. Metrics like "190+ endpoints / 37 MCP tools / 565 tests" are not canonical
They are planning snapshots, not durable product truth.

---

## 6. What is actually the highest-value roadmap direction now?

There are two fundamentally different goals:

### Goal A — better model access
"How do we get stronger/free models with good limits?"

This is important, but mostly a backend/provider problem.

### Goal B — better agent product
"How do we make Arena feel like a real long-lived assistant / companion / workspace agent?"

This is more important strategically, because it compounds with every model.

### Recommendation
Prioritize **Goal B first**.

Reason:
- model backends will change repeatedly
- a strong product shell (memory, planning, persona, workspace UX) is durable
- Arena already has a serious core; it needs more high-level agent shape, not less

---

## 7. Re-prioritized roadmap for *your actual goal*

Below is a normalized roadmap ordered not by theoretical "10/10 score" alone, but by fit with the product direction suggested by AutoClaw.

---

## Phase A — Companion foundation (highest leverage)

### A1. M3 — Memory Profiles
Why first:
- separates personal/project/code/browser memory cleanly
- avoids context soup
- directly supports "assistant companion" behavior
- enables notes/identity/workspace panes later

Definition of done:
- profile-aware storage + recall
- switch profile via API/MCP
- UI surface exposes current memory space

### A2. Recurring tasks / scheduler clarity
This is only partially implied by the chat context, but it matters a lot.
The recurring-task experience should be clear and first-class.

Definition of done:
- documented recurring task setup
- visible schedule list
- easy create/edit/delete
- task history surfaced cleanly

### A3. User/assistant profile state
Inspired by AutoClaw side-panels.

Minimal target:
- user profile store
- assistant display name / persona mode
- timezone / focus / notes
- important lessons store

This does not need to be a huge LLM feature first; it can begin as structured state.

---

## Phase B — Agentic behavior

### B1. A1 — Built-in Planner
A `/v1/plan` surface or equivalent MCP tool is high leverage.

### B2. A2 — ReAct loop
This is where Arena stops being only a toolbox and becomes a real agent runtime.

### B3. A3 — Reflection
Very important if you want long-lived assistant quality instead of brittle tool chaining.

These three together are more strategically important than many lower-level feature additions.

---

## Phase C — Workspace and UX

### C1. DX2 — Integration recipes
This is underrated and likely cheap compared to its value.

Should include:
- Arena Agent Mode prompt/backend recipe
- Claude / Cursor / Cline / Open Interpreter / Windsurf examples
- local model provider examples

### C2. Memory Browser / Notes panes
A very direct way to absorb what felt good in AutoClaw.

### C3. Lessons / profile / context sidebars
This is product UX, but it strongly changes how people perceive the assistant.

---

## Phase D — Filesystem and awareness polish

### D1. F5 — File Watchers
Very compatible with companion/workspace direction.

### D2. F4 — Safe editor with preview/confirm/rollback
Good trust feature, especially if Arena is meant to feel like a persistent assistant rather than a raw tool bot.

---

## Phase E — Model/provider abstraction

If the "free strong model" problem is still important, solve it **cleanly**:

### E1. Provider abstraction layer
Support explicit providers such as:
- OpenRouter
- Together
- Groq
- Ollama
- local OpenAI-compatible endpoints

### E2. Optional experimental adapters
Only *after* provider abstraction exists, consider experimental adapters like browser/session-driven access to third-party agent frontends.

This keeps risky ideas quarantined away from the core architecture.

---

## 8. Concrete roadmap corrections

### Mark as definitely stale / misleading in old roadmap files
- backup marked as "done" without verifying live product surface
- test count `565`
- MCP tool count `37`
- old version baselines
- some endpoint counts as product truth

### Keep as still valid ideas
- M1 / M2 / M3 / M4 / M6
- A1 / A2 / A3 / A5
- B3
- D1 / D3
- DX2 / DX5
- F4 / F5

### Reclassify
- E1 (Arena Agent Mode integration) should be considered **experimental / strategic discussion**, not a straightforward roadmap deliverable
- S4 backups should be re-audited before being treated as a completed capability

---

## 9. Practical next four tasks I would choose

If we want maximum value with minimum architectural regret, my recommended next four tasks are:

### 1. M3 — Memory Profiles
Best balance of impact and complexity.

### 2. DX2 — Integration recipes
Low-risk, high-value, improves usability immediately.

### 3. A1 — Built-in Planner
Strong step toward genuine agent behavior.

### 4. F5 — File Watchers
Good workspace-awareness feature; complements the companion direction.

If you want a more "safety/trust" oriented path, swap F5 with F4.

---

## 10. Small surgical cleanup candidates discovered during analysis

These are not the main roadmap, but they are worth tracking:

1. `agentctl` still appears to contain a stale backup path calling `/v1/backup`
2. roadmap metrics and release counters are stale and should not be copied forward blindly
3. a single canonical roadmap file should replace the current fragmented planning set

---

## 11. Recommended canonical planning structure going forward

Instead of three drifting roadmap files, keep:

### `docs/ROADMAP_CANONICAL.md`
Contains:
- current validated project state
- done / partial / planned
- next recommended priorities
- no guessed metrics without verification

### `docs/EXPERIMENTS.md`
Contains:
- Arena Agent Mode proxy idea
- provider experiments
- risky integrations
- anything intentionally speculative

### `docs/PRODUCT_DIRECTION.md`
Contains:
- Arena Companion Mode concept
- UX / persona / memory / workspace direction
- competitive positioning notes

---

## 12. Bottom line

The strongest interpretation of all the context is this:

- AutoClaw surfaced a **product desire**
- Hermes/OpenClaw surfaced **ecosystem alternatives**
- the model-proxy idea surfaced a **backend pain point**

But Arena's best future is:

> become a self-hosted, agentic, companion-like automation workspace built on a strong local bridge core.

That means the priority is not "copy someone else's frontend" and not "bet the whole product on a fragile model proxy".

The priority is:
- scoped memory
- planning/reflection
- workspace UX
- trustworthy automation
- clean provider abstraction

That is the path most likely to turn Arena from a powerful bridge into a genuinely compelling assistant platform.

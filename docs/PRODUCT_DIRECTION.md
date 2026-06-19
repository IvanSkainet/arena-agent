# Arena Unified Bridge — Product Direction

Date: 2026-06-19

---

## 1. Core thesis

Arena already has a strong bridge core:
- local automation
- broad tool surface
- modular architecture
- strong testing discipline

What it lacks compared with products like AutoClaw is not raw capability so much as:
- assistant feeling
- workspace continuity
- visible memory/persona/state
- high-level agent loop behavior

The goal is to move Arena toward:

> a self-hosted companion-like automation workspace

without sacrificing the engineering reliability of the bridge.

---

## 2. Arena Companion Mode

### Desired characteristics
- persistent assistant identity
- user profile + assistant profile
- scoped memory spaces
- notes and lessons panels
- recurring tasks and schedules
- planning + reflection loop
- visible activity traces
- controllable local tools

### Non-goals
- replacing Arena with a giant foreign framework
- hard-coding the product around one cloud provider or one web UI
- making the assistant feel magical at the cost of trust/debuggability

---

## 3. Product pillars

## Pillar A — Trustworthy local power
Arena must remain excellent at:
- exec
- files
- browser
- desktop
- tasks
- memory
- MCP

This is the foundation.

## Pillar B — Context and continuity
Arena should gain:
- memory profiles
- notes
- lessons
- project-specific context
- user profile / preferences

## Pillar C — Agent behavior
Arena should gain:
- planner
- multi-step execution loops
- reflection / critique
- mission dependency handling

## Pillar D — Workspace UX
Arena should surface state visibly:
- what the assistant knows
- what it is doing
- what profile it is in
- what tasks are scheduled
- what lessons it has learned

---

## 4. Why this is better than chasing only model access

Strong/free model access is useful, but provider advantages are unstable.

A durable advantage comes from:
- better memory structure
- better planning behavior
- better assistant UX
- better local tool integration

Any model can benefit from that shell.

---

## 5. Immediate product opportunities

### 1. Memory Profiles
Most direct path toward "assistant that understands context boundaries".

### 2. Recurring task UX
AutoClaw-like value signal: scheduled work that feels first-class.

### 3. Planner
Transforms Arena from substrate toward agent runtime.

### 4. Notes / lessons / profile panes
High product impact even before deeper LLM features.

---

## 6. Positioning statement

If AutoClaw feels like a cloud-first AI workspace and Hermes feels like a large agent framework, Arena should aim to be:

> the most reliable self-hosted local agent bridge that also feels like a real long-lived assistant.

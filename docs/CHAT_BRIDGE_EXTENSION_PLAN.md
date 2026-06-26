# Arena Chat Bridge Extension — Project Plan

Date: 2026-06-26
Status: active implementation — Phase 1 bridge foundation plus stronger ChatGPT-oriented extension UX and side-panel replay/debug workflows in progress
Owner: Arena Unified Bridge

---

## 1. Why this exists

Arena Unified Bridge already gives us a strong local execution core:
- REST
- MCP
- memory
- missions
- desktop/browser/system tooling
- mission families and schedules

But today, to use that power inside many web-based chats, the chat UI usually needs one of these:
- native tool calling
- Python / code interpreter
- MCP support built into the chat product

A browser-extension bridge changes that.

The idea is to make Arena usable inside ordinary web chats, even when the site itself does not expose native MCP or Python execution. The browser extension becomes the UI-side bridge, and the local Arena bridge becomes the execution/runtime side.

This is the same broad category of product idea as MCP-SuperAssistant:
- browser extension injected into AI chat websites
- site adapters
- detection of tool-call blocks in generated responses
- local execution bridge
- result insertion back into chat

What MCP-SuperAssistant already demonstrates publicly:
- it is a browser extension bridging AI chat platforms with MCP tooling [1](https://deepwiki.com/srbhptl39/MCP-SuperAssistant)
- it uses pluggable site adapters across many AI platforms [1](https://deepwiki.com/srbhptl39/MCP-SuperAssistant)
- it detects tool/function calls in model output and renders executable UI blocks [1](https://deepwiki.com/srbhptl39/MCP-SuperAssistant)
- its author described the mechanism as DOM/event listening plus pattern detection, with adapter-based site support [2](https://www.reddit.com/r/mcp/comments/1kd9qom/launching_mcp_superassistant/)
- it also evolved toward JSONL-style tool-calling patterns for better reliability in some cases [3](https://github.com/srbhptl39/MCP-SuperAssistant/releases)

Arena should build a version of this idea that is:
- more bridge-native
- more mission-native
- more policy-safe
- more universal as a fallback
- less dependent on a separate npm executor layer

---

## 2. Product vision

### Working name
**Arena Chat Bridge Extension**

Alternative names:
- Arena Universal Chat Tools
- Arena SiteBridge
- Arena Tool Runner Extension
- Arena Companion Extension

### One-line vision

> Let any supported web chat issue structured Arena tool/mission calls through a browser extension, even if the site itself has no native MCP or code execution.

### Strategic value

If implemented well, this moves Arena up a level:
- from "local bridge for agents that already support tools"
- to "universal local execution layer for ordinary chat websites"

That is a significant platform expansion.

---

## 3. Core product goals

### G1. Run Arena operations inside ordinary chats
A user pastes a system prompt into a web chat.
The model outputs a structured execution block.
The extension detects it and offers to run it.
Arena executes locally and returns results into the chat.

### G2. Work without Python/code-interpreter support in the chat product
The chat website only needs to render text.
The extension handles detection and execution.

### G3. Support both simple tools and high-level orchestration
Not only:
- fs read/write
- exec
- browser fetch

But also:
- mission.followup
- mission.iterate
- mission.family
- mission.schedules
- future recurring orchestration

### G4. Be safe by default
Unknown sites and risky actions must not auto-run silently.

### G5. Have a universal fallback mode
Even on unsupported sites, the extension should still be useful through a side panel and manual execution path.

---

## 4. Non-goals

### N1. Not full site automation for every website
We are not promising perfect automatic DOM integration on every chat site.

### N2. Not replacing built-in MCP where native MCP exists
If a product already supports native MCP or native external tools well, that can remain the preferred integration path.

### N3. Not arbitrary remote execution from any webpage by default
This must not become "every website can trigger local machine actions".

### N4. Not browser-only business logic
Core execution logic should stay in Arena bridge, not migrate into the extension.

---

## 5. User stories

### U1. Chat tool execution on unsupported chat UI
As a user,
I want ChatGPT/Claude/Gemini/Grok/OpenRouter/etc. in the browser to emit a structured Arena call,
so I can execute tools even without the site's built-in MCP support.

### U2. Manual approval
As a user,
I want to review a detected tool call before execution,
so I keep control over dangerous actions.

### U3. Follow-up mission execution
As a user,
I want the model to output a mission.followup or mission.iterate block,
so multi-step work can continue from existing mission state.

### U4. Universal fallback
As a user on an unsupported site,
I want the extension to still show the detected block in a side panel,
so I can run and copy results manually.

### U5. Multi-call orchestration
As a user,
I want one detected block to contain multiple calls,
so the model can batch related operations without fragile copy-paste loops.

---

## 6. High-level architecture

## 6.1 Components

### A. Browser extension
Responsibilities:
- site detection
- adapter selection
- DOM observation
- structured block detection
- UI rendering
- approval flow
- local bridge communication
- result insertion back into page

### B. Local Arena bridge
Responsibilities:
- authenticate local requests
- validate policies
- execute calls
- stream or return results
- audit everything
- expose extension-friendly endpoints

### C. Site adapters
Responsibilities:
- locate assistant message regions
- locate input composer
- determine streaming boundaries
- inject buttons/popovers/side panels
- insert results back into site-specific input or transcript area

### D. Optional side panel / universal fallback UI
Responsibilities:
- show detected calls when site adapter is weak
- manual execute/copy/insert
- show history/status/errors

---

## 6.2 Trust boundaries

### Browser webpage
Untrusted.
Any detected execution payload must be treated as untrusted input.

### Browser extension
Trusted UI/runtime with restrictions.

### Local Arena bridge
Trusted execution core.

### AI model output
Untrusted suggestion layer.
Never implicitly trusted just because it came from a known chat site.

---

## 7. Execution protocol design

We should not rely only on raw JSONL.

## 7.1 Recommended canonical format

Preferred fenced block:

```text
```arena-tool
{
  "bridge": "arena",
  "version": 1,
  "calls": [
    {
      "id": "call_1",
      "tool": "mission.iterate",
      "arguments": {
        "mission_id": "demo",
        "compose_followup": true
      }
    }
  ]
}
```
```

## 7.2 Compatibility formats
Also support:
- JSONL-style blocks
- XML-like function-call blocks
- MCP-SuperAssistant-like JSON payload patterns

But Arena should publish one canonical format so prompts and validators stay simple.

## 7.3 Multi-call support
A single payload may contain multiple calls:

```json
{
  "bridge": "arena",
  "version": 1,
  "calls": [
    {"id": "1", "tool": "mission.lineage", "arguments": {"mission_id": "alpha"}},
    {"id": "2", "tool": "mission.family", "arguments": {"mission_id": "alpha"}}
  ]
}
```

## 7.4 Execution result format
Bridge returns:

```json
{
  "ok": true,
  "request_id": "...",
  "calls": [
    {
      "id": "1",
      "ok": true,
      "tool": "mission.lineage",
      "result": {...}
    }
  ],
  "summary": "1 call executed successfully"
}
```

## 7.5 Deterministic IDs and dedupe
The extension should compute:
- payload hash
- call hash
- page origin
- message fingerprint

This prevents repeated execution when the DOM re-renders during streaming.

---

## 8. Extension ↔ bridge communication model

## 8.1 Simplest path
Direct HTTP to local bridge:
- `http://127.0.0.1:8765/...`

Pros:
- simplest
- no extra local daemon required
- Arena already exists

Cons:
- browser extension permissions must allow localhost
- auth/token handling must be designed carefully

## 8.2 Optional native companion path
Alternative:
- extension → native messaging host or local helper → Arena bridge

Pros:
- stronger local trust separation
- can hide token from page-facing extension paths

Cons:
- more packaging complexity
- harder cross-platform install

## 8.3 Recommendation
Start with:
- **extension → localhost Arena bridge directly**

Later, if needed, add:
- native messaging host for hardened environments

---

## 9. Bridge-side additions we should build

## 9.1 Extension session endpoints
Suggested new endpoints:
- `POST /v1/extension/execute`
- `POST /v1/extension/preview`
- `GET /v1/extension/policies`
- `POST /v1/extension/result-format`

These can wrap existing tools and missions without exposing the full raw protocol to the extension.

## 9.2 Policy-aware execution wrapper
The extension should not call every tool endpoint ad hoc.
Instead, a wrapper should:
- validate tool names
- classify risk
- support dry-run
- audit origin/site/call hash
- optionally batch calls

## 9.3 Structured policy model
Per-site policy examples:
- disabled
- detect only
- manual run only
- safe auto-run only
- always ask for dangerous tools

## 9.4 New audit fields
Add audit metadata like:
- `source: browser_extension`
- `site_origin`
- `site_url`
- `adapter_name`
- `call_hash`
- `message_fingerprint`
- `auto_run`
- `approval_mode`

---

## 10. Site adapter system

## 10.1 Adapter interface
Each adapter should define:
- `match(hostname, url)`
- `findMessageContainers()`
- `findStreamingContainer()`
- `findComposer()`
- `insertResult(text)`
- `getConversationContext()`
- `mountExecutionUI()`

## 10.2 Native adapters first
Priority adapters:
- ChatGPT
- Claude
- Gemini
- Grok
- Perplexity
- OpenRouter

## 10.3 Generic adapter
Fallback if no site adapter matches:
- watch DOM for fenced blocks
- show floating button or side panel
- allow manual run/copy/insert

## 10.4 Unsupported-site fallback UX
If result insertion is unreliable:
- execute anyway
- show result in extension side panel
- provide Copy Result
- provide Insert to active field if possible

---

## 11. Detection pipeline

## 11.1 Message observation
Observe:
- streamed token output
- DOM mutations
- message completion boundaries

## 11.2 Parse stages
1. extract candidate fenced blocks
2. detect `arena-tool`, JSON, JSONL, XML-ish candidates
3. validate schema
4. compute hash/fingerprint
5. dedupe
6. render execution UI

## 11.3 Execute states
- detected
- ready
- approved
- running
- success
- failed
- inserted
- copied-only

---

## 12. Security model

This is the most important section.

## 12.1 Site trust levels
Suggested per-site trust:
- **blocked**
- **detect-only**
- **manual-confirm**
- **safe-auto-run**

Default for unknown sites:
- detect-only or manual-confirm

## 12.2 Tool risk classes
### Safe / readonly
Examples:
- mission.lineage
- mission.family
- mission.catalog
- mission.history
- memory recall
- browser.read/fetch/head

### Medium risk
Examples:
- mission.followup
- mission.iterate without run
- schedule save/delete
- fs.create in workspace

### High risk
Examples:
- exec
- fs.write/edit
- mission.run
- desktop actions
- schedule tick if it may execute run/iterate

## 12.3 Approval policy
At minimum:
- unknown site + any action → manual confirm
- any dangerous tool → manual confirm
- batch containing dangerous tool → manual confirm
- auto-run only for allowlisted readonly tools

## 12.4 Anti-replay / anti-loop
Need:
- payload hash dedupe
- execution TTL
- page message fingerprint
- explicit "already executed" memory

## 12.5 No page-origin trust leakage
The webpage must never directly read the token.
The content script and background script own communication.

---

## 13. UX design

## 13.1 Inline block controls
For supported sites:
- Run
- Dry Run
- Copy Payload
- Approve Always for This Site
- Expand Details

## 13.2 Side panel
Persistent panel with:
- connection status to Arena bridge
- detected calls
- execution history
- schedules
- family summaries
- policy toggles

## 13.3 Result insertion modes
- insert into composer
- append to current conversation field
- copy only
- side-panel only

## 13.4 Failure handling
If insert fails:
- do not lose result
- keep result in side panel
- one-click copy

---

## 14. Arena-specific superpowers

This is where we should outperform a generic MCP site runner.

## 14.1 Mission-native flows
The extension should understand not only single tools, but mission lifecycle blocks.

Examples:
- inspect a family
- continue from mission lineage
- run an iteration loop
- create recurring schedules

## 14.2 Memory-aware execution
Site/session-specific profile hints:
- `browser/<site>`
- `projects/<name>`
- `chat/<site>/<thread>`

## 14.3 Schedule-aware execution
The chat can define recurring operations directly:
- every 60 min inspect mission family
- every 24h iterate mission X
- every 15 min rerun failed-only recovery mission

## 14.4 Subagent and parallelization future path
You mentioned stronger subagents and parallelization. This feature is a good place to connect that later:
- one chat block could request parallel readonly inspections
- schedule worker could dispatch family analysis to subagents
- mission family summaries could later be computed concurrently

Not phase 1, but strong future fit.

---

## 15. Suggested implementation phases

## Phase 0 — spec and security groundwork
Deliverables:
- protocol spec
- risk-class map
- site trust policy design
- audit field design

## Phase 1 — MVP extension + direct local bridge execution
Deliverables:
- extension skeleton
- localhost bridge connection
- detect `arena-tool` fenced block
- manual Run button
- result in side panel
- result copy

Success criteria:
- works on at least one site even with no adapter-specific insert

## Phase 2 — supported-site adapters
Deliverables:
- ChatGPT adapter
- Claude adapter
- Gemini adapter
- Perplexity adapter
- generic fallback adapter

Success criteria:
- reliable detect + execute + insert on major sites

## Phase 3 — bridge-native orchestration payloads
Deliverables:
- mission-focused payload examples
- family/lineage/schedule-oriented templates
- batch execution wrapper
- dry-run preview mode

## Phase 4 — stronger UX and policies
Deliverables:
- side panel policies
- per-site allowlist
- safe auto-run
- dedupe and history
- family/schedule dashboards in panel

## Phase 5 — optional hardening
Deliverables:
- native messaging host option
- stronger token isolation
- signed local session handshake

---

## 16. API / protocol proposal for MVP

## 16.1 New bridge endpoint
Proposed:
- `POST /v1/extension/execute`

Body:

```json
{
  "site": {
    "origin": "https://chat.openai.com",
    "url": "https://chat.openai.com/c/...",
    "adapter": "chatgpt"
  },
  "message": {
    "fingerprint": "...",
    "payload_hash": "..."
  },
  "payload": {
    "bridge": "arena",
    "version": 1,
    "calls": [
      {
        "id": "call_1",
        "tool": "mission.family",
        "arguments": {"mission_id": "demo"}
      }
    ]
  },
  "mode": {
    "dry_run": false,
    "insert_result": true
  }
}
```

## 16.2 New bridge endpoint for preview
- `POST /v1/extension/preview`

Returns:
- parsed calls
- risk class
- approval requirement
- policy decision

This makes extension UX much cleaner.

---

## 17. Testing strategy

## 17.1 Bridge tests
- payload validation
- policy enforcement
- audit metadata
- batch execution
- dedupe

## 17.2 Extension tests
- parser tests for fenced JSON/JSONL/XML
- adapter DOM unit tests
- result insertion tests
- dedupe tests

## 17.3 End-to-end tests
- mock chat DOM
- detected block
- approval click
- localhost execution
- result insertion

## 17.4 Manual validation matrix
Sites:
- ChatGPT
- Claude
- Gemini
- Grok
- Perplexity
- OpenRouter
- unsupported generic site

---

## 18. Risks

### R1. DOM fragility
All site adapters can break when the provider changes UI.
Mitigation:
- adapter abstraction
- generic fallback
- feature flags/remotes later if needed

### R2. Security overreach
A page could try to trick the extension into running dangerous things.
Mitigation:
- strict schema
- risk classes
- site policies
- approvals
- bridge-side enforcement

### R3. Duplicate executions
Streaming DOM can re-render the same payload multiple times.
Mitigation:
- call hash
- message fingerprint
- dedupe cache

### R4. Composer insertion inconsistency
Some sites are hostile to injected text.
Mitigation:
- side panel fallback
- copy result fallback

---

## 19. Recommendation

This project is not only possible — it is strategically very strong for Arena.

My recommendation:

1. **Build it**
2. Start with a **strict MVP**
3. Keep execution logic inside **Arena bridge**, not a separate general npm executor
4. Use **site adapters + generic fallback**
5. Make **security policy** a first-class design feature, not an afterthought

---

## 20. Concrete next implementation step

If we start now, the best first engineering slice is:

### Slice A — protocol + bridge wrapper
- define canonical `arena-tool` payload schema
- add `POST /v1/extension/preview`
- add `POST /v1/extension/execute`
- add risk-class + policy wrapper

### Slice B — browser extension MVP
- content script
- simple parser for fenced blocks
- side panel
- localhost execution
- manual approve

### Slice C — first adapters
- ChatGPT
- Claude
- generic fallback

That is the cleanest path to a real product.

---

## 21. Summary

Yes, we can build an Arena version of this idea.

And if we do it right, Arena becomes:
- not just a Python/code-interpreter-adjacent bridge,
- but a **universal local execution layer for ordinary web chats**.

That is absolutely a level-up.

---
name: writing-skills
description: Write, test, and maintain skills for the arena-agent superpowers system. Skills are stored as SKILL.md files, discovered via the bridge skills endpoint, and follow a TDD workflow: baseline → write skill → verify → close loopholes. Covers skill types, YAML frontmatter, token efficiency, and anti-patterns.
---

# Writing Skills

## Purpose

This skill defines how to write, test, and maintain skills for the arena-agent superpowers system. Skills are the knowledge units that guide the bridge's behavior. They are stored as Markdown files with YAML frontmatter, discovered via the bridge's `GET /v1/skills` endpoint, and must be written for clarity, token efficiency, and actionability.

## When to Use

- Writing a new skill from scratch
- Modifying an existing skill
- Reviewing a skill for quality
- Debugging why a skill isn't being triggered correctly

## When NOT to Use

- Writing application code (use the code-writing workflow, not a skill)
- Writing documentation that isn't a skill (use project docs)

## Skill Storage and Discovery

### File Location

Skills are stored in:
```
~/arena-agent/tools/superpowers/skills/<skill-name>/SKILL.md
```

Each skill gets its own directory containing:
- `SKILL.md` — The skill definition (required)
- Additional reference files (optional, but keep to minimum for token efficiency)

### Bridge Discovery

Skills are available via the bridge API:

```bash
# List all available skills
curl -s http://localhost:8765/v1/skills \
  -H "Authorization: Bearer $BRIDGE_TOKEN"

# Run a specific skill
curl -s -X POST http://localhost:8765/v1/skills/run \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"skill": "verification-before-completion", "context": {"task": "fix-exec-timeout"}}'
```

The bridge reads the `skills/` directory and parses the YAML frontmatter of each `SKILL.md` to build the skills index. The `name` and `description` fields from the frontmatter are what appears in the `GET /v1/skills` response.

## Skill File Structure

Every `SKILL.md` must follow this structure:

```markdown
---
name: skill-name-kebab-case
description: One-sentence description of what the skill does and when to use it. This is what appears in the skills list and what the agent reads to decide whether to activate this skill.
---

# Skill Name

## Purpose
Why this skill exists and what problem it solves. 2-3 sentences.

## When to Use
Specific triggers that should cause this skill to activate.

## When NOT to Use
Boundary conditions where this skill does not apply.

## Core Principles
The fundamental rules that guide the skill's application.

## Process
Step-by-step instructions for executing the skill.

## Anti-Patterns to Avoid
Common mistakes when applying this skill.

## Integration with Arena-Agent Workflow
How this skill connects to other skills.

## Quick Reference
Condensed version of the process for quick lookup.
```

### YAML Frontmatter Rules

1. **name**: Kebab-case, matches the directory name. E.g., `requesting-code-review`
2. **description**: One sentence, max 200 characters. Must answer: "What does this skill do and when should I use it?"
3. No other YAML fields are currently used, but the frontmatter block is required

### Frontmatter Quality Check

Bad description:
```yaml
description: Code review skill for the arena-agent project.
```
(Too vague — doesn't say when to use it or what's different about it)

Good description:
```yaml
description: Request structured code reviews via bridge audit log verification, leveraging subagent reviewer templates and severity-based blocking.
```
(Specific about what it does and what mechanisms it uses)

## Skill Types

### Technique

A technique skill describes **how to do something**. It has a clear process with steps.

Characteristics:
- Has a sequential process
- Has decision points (if X, then Y)
- Has concrete actions and expected outcomes
- Has a clear beginning and end

Example: `requesting-code-review`, `verification-before-completion`

Structure emphasis: **Process** section is the most important part. Each step must be unambiguous.

### Pattern

A pattern skill describes **a recurring solution** to a common problem. It's more about recognizing situations than following steps.

Characteristics:
- Has problem/solution pairs
- Has trade-off analysis
- Has when-to-use/when-not-to-use guidance
- May reference technique skills for implementation details

Example: `using-feature-branches`, `dispatching-parallel-agents`

Structure emphasis: **Core Principles** and **When to Use / When NOT to Use** sections are most important.

### Reference

A reference skill provides **lookup data** that other skills or agents need. It's a structured dataset, not a process.

Characteristics:
- Has tables, lists, or structured data
- Has minimal process (it's reference material)
- Is cross-referenced by other skills
- Is updated when the system changes

Example: A hypothetical `bridge-api-reference` skill that lists all endpoints, parameters, and responses.

Structure emphasis: **Data tables** and **Cross-references** are most important.

## TDD for Skills: Test-Driven Skill Development

Skills should be developed with a TDD approach:

### Step 1: Baseline — What Should the Skill Do?

Before writing the skill, define what it should accomplish:

```
Skill: verification-before-completion

Expected behavior:
- Before marking a task complete, the agent runs the stress test
- The agent does NOT claim completion without test output
- The agent does NOT use stale test results
- The agent does NOT rationalize skipping verification
- The agent reports specific test results as evidence

Failure modes to prevent:
- Agent says "done" without running tests
- Agent uses test results from before the last change
- Agent skips the stress test because "it takes too long"
- Agent claims "the code looks correct" instead of running tests
```

### Step 2: Write the Skill

Write the SKILL.md based on the expected behavior. Include:
- Explicit rules that prevent each failure mode
- Concrete verification commands
- The rationalization prevention table
- The common failures table

### Step 3: Verify — Does the Skill Work?

Test the skill by giving an agent a task and seeing if it follows the skill:

```bash
# Run a skill-guided task
curl -s -X POST http://localhost:8765/v1/skills/run \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "skill": "verification-before-completion",
    "context": {
      "task": "fix-exec-timeout",
      "branch": "feature/exec-timeout-fix"
    }
  }'
```

Check:
1. Did the agent run the stress test before claiming completion?
2. Did the agent provide specific test output as evidence?
3. Did the agent resist rationalizing shortcuts?
4. Did the agent use the correct verification level for the task complexity?

### Step 4: Close Loopholes

If the agent found a way to violate the skill's intent despite the skill being loaded, the skill has a loophole. Fix it:

1. Identify how the agent violated the intent
2. Add an explicit rule or check that prevents this violation
3. Re-test with the same scenario
4. Repeat until no loopholes remain

Common loopholes:
- Skill says "run the stress test" but doesn't say "after the last code change"
- Skill says "verify" but doesn't specify what verification output looks like
- Skill says "don't skip" but doesn't list the common rationalizations for skipping
- Skill says "check bridge health" but doesn't specify the endpoint or expected response

## CSO: Bridge Skill Discovery Optimization

CSO (Claude Search Optimization, adapted for bridge skill discovery) ensures that skills are found and activated when needed. The bridge's `GET /v1/skills` endpoint returns the name and description of each skill, and the agent uses these to decide which skill to activate.

### CSO Rules

1. **Name must be searchable**: Use common terms that an agent would naturally search for. `requesting-code-review` not `rcr-process`.

2. **Description must match intent**: The description should contain the key phrases that would appear in an agent's reasoning when it needs this skill. Think: "If I'm about to request a code review, what words would I use?"

3. **Frontmatter is the index**: The name and description are all that appears in the skills list. If the agent can't tell from the name+description that this skill is relevant, it won't load the full SKILL.md.

4. **Skill activation is lazy**: The full SKILL.md is only loaded when the skill is activated. Keep the description concise but informative so the agent can make good activation decisions without loading every skill.

### CSO Anti-Patterns

| Anti-Pattern                         | Problem                                     | Fix                                            |
|--------------------------------------|---------------------------------------------|------------------------------------------------|
| Vague description                    | Agent can't tell when to use the skill      | Include specific trigger phrases               |
| Overly long description              | Token waste in the skills index             | Keep under 200 characters                      |
| Cute/clever names                    | Agent can't find the skill by search        | Use descriptive, boring names                  |
| Missing when-to-use info             | Agent activates skill at wrong times        | Add trigger conditions to description          |
| Description doesn't match content    | Agent loads skill, finds it irrelevant      | Audit description vs. content alignment        |

## Token Efficiency Guidelines

Skills consume tokens when loaded. Every token spent on a skill is a token not available for the task itself. Optimize for token efficiency:

### 1. Frontmatter Is Free (Almost)

The YAML frontmatter is always loaded (it's in the skills index). The body is loaded only when the skill is activated. So frontmatter should be information-dense.

### 2. Quick Reference Is the Most Valuable Section

The Quick Reference section at the bottom is what an agent will reference during execution. Make it complete and self-contained. An agent should be able to follow the Quick Reference without re-reading the entire skill.

### 3. Use Tables Instead of Prose

Tables are more token-efficient than paragraphs for structured information:

```
# BAD (verbose):
If the severity is Critical, you should fix it immediately and you cannot proceed with any other work. If the severity is Important, you should fix it before starting the next task but you can continue with the current task. If the severity is Minor, you should just note it for later and continue.

# GOOD (compact):
| Severity    | Action                          |
|-------------|----------------------------------|
| Critical    | Fix immediately. Blocks all work.|
| Important   | Fix before next task.            |
| Minor       | Note for later. Does not block.  |
```

### 4. Code Blocks Should Be Copy-Paste Ready

Code blocks in skills are meant to be executed. They should be complete, runnable commands:

```bash
# BAD (incomplete):
run the stress test

# GOOD (complete):
curl -s -X POST http://localhost:8765/v1/exec \
  -H "Authorization: Bearer $BRIDGE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "cd /path/to/arena-agent && python -m pytest tests/stress/ -v"}'
```

### 5. Avoid Redundancy

If a rule is stated in Core Principles, don't restate it in Process. Reference it instead:

```
# BAD:
## Core Principles
Never skip verification.

## Process
Step 3: Verify (and remember, never skip this!).

# GOOD:
## Core Principles
Never skip verification (see Rationalization Prevention Table).

## Process
Step 3: Run required verification levels.
```

### 6. Section Order Matters

The most-consulted sections should be at the top and bottom:
- **Top**: Purpose, When to Use (for activation decisions)
- **Bottom**: Quick Reference (for execution)
- **Middle**: Process, Anti-Patterns (for detailed reference)

## Anti-Patterns to Avoid

### Writing a Skill That Should Be Code
If the skill is basically "run this Python script," write the script instead. Skills are for guidance and decision-making, not for encoding procedural logic that belongs in code.

### Writing a Skill That's Too Vague
"Always verify your work" is not a skill. "Run GET /health, then GET /v1/doctor, then the stress test, and document the results with timestamps" is a skill.

### Writing a Skill That's Too Specific
"Run python -m pytest tests/test_exec.py::test_timeout_issue_42 -v" is not a skill. It's a command. The skill should generalize: "Run the specific test that covers your change."

### Writing a Skill Without Testing It
Skills must be tested with the TDD approach. If you've never seen an agent follow the skill successfully, you don't know if it works.

### Writing a Skill That Conflicts With Another
Check existing skills before writing a new one. If two skills give contradictory advice, the agent will be confused.

### Writing a Skill Without Considering Token Budget
A 5000-token skill that's loaded for every task wastes tokens. Keep skills focused on their specific domain. If a skill is getting too long, split it.

### Writing a Skill That Assumes Context
Skills are loaded in isolation. Don't assume the agent has read other skills or has context about the current project state. Each skill must be self-contained enough to follow on its own.

## Skill Maintenance

### When to Update a Skill

- When the bridge API changes (new endpoints, changed parameters)
- When project workflow changes (new branching strategy, new review process)
- When an agent consistently violates the skill's intent (loophole found)
- When the stress test count changes (update all references to 39/39)
- When cross-platform requirements change

### When to Split a Skill

- When the skill exceeds 3000 tokens (excluding code blocks)
- When the skill covers two distinct problem domains
- When the "When to Use" section has an "and" that should be an "or"

### When to Retire a Skill

- When the skill's advice is no longer relevant
- When the skill has been superseded by a better skill
- When no agent has activated the skill in recent memory

Retired skills should be moved to an `archive/` directory, not deleted, in case they're needed for reference.

## Integration with Arena-Agent Workflow

This skill is meta — it defines how to write the skills that define the workflow. It integrates with:

1. **requesting-code-review**: Review new or modified skills like any other code
2. **receiving-code-review**: Process feedback on skill content
3. **verification-before-completion**: Verify skills by testing them with agents
4. **using-feature-branches**: Skill changes go through the same branch workflow

## Quick Reference

```
# Skill file location
~/arena-agent/tools/superpowers/skills/<name>/SKILL.md

# Required structure
---
name: kebab-case-name
description: One sentence, max 200 chars, includes trigger phrases
---
# Skill Name
## Purpose / When to Use / When NOT to Use
## Core Principles
## Process (step-by-step)
## Anti-Patterns to Avoid
## Integration with Arena-Agent Workflow
## Quick Reference

# Skill types
Technique: how-to with process (e.g., verification-before-completion)
Pattern: recurring solution (e.g., using-feature-branches)
Reference: lookup data (e.g., bridge-api-reference)

# TDD for skills
1. Baseline: define expected behavior and failure modes
2. Write: create SKILL.md with explicit rules
3. Verify: test with an agent following the skill
4. Close loopholes: fix violations, re-test

# CSO rules
- Name: searchable, descriptive, boring
- Description: includes trigger phrases, under 200 chars
- Frontmatter = index, body = loaded on activation

# Token efficiency
- Tables > prose
- Quick Reference must be self-contained
- Code blocks: copy-paste ready
- No redundancy across sections
- Frontmatter is information-dense

# Verify skill via bridge
GET /v1/skills                    → list all skills
POST /v1/skills/run {skill, ctx}  → test a skill
```

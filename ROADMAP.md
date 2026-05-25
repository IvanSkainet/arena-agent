# Arena Agent Roadmap

## Principles
- Core first: bridge, clients, recovery, backup, dashboard, task queue.
- Short commands: prefer `./a 'agentctl ns cmd'` and agentctl namespaces.
- Scenario-driven development: every new feature should map to a mission template.
- Verification discipline: test, memory fact, recovery-update, backup.

## Near-term
1. Dashboard v3/v4: control center for services, MCP, tasks, reports, projects, RAG, terminal.
2. Client/UPS layer: generate/test bash, Python, PowerShell, curl, wget clients.
3. Mission framework: templates, stress tests, artifacts, reports.
4. MCP: real top MCP servers, tool filtering, permissions, Streamable HTTP hardening.
5. Browser/desktop: browser-act adapter, native desktop scenarios, screenshots/OCR.

## Mid-term
- GitLab-like project board/issues/MR dashboards.
- RAG-backed memory and searchable artifacts.
- Multi-agent roles: planner, executor, verifier, browser operator.
- Cross-platform Linux/Windows service parity.

## Scenario templates
- tabs-game
- browser-real-user
- cli-agent-core
- lan-service
- code-tdd
- mcp-integration
- recovery-drill

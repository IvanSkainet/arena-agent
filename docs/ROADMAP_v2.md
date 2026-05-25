# Arena Agent — Roadmap v2 (на основе анализа лидеров)

Сгенерировано: 2026-05-24. Опирается на research:
- **MCP-SuperAssistant** — Chrome extension, прокидывает MCP в ChatGPT/Perplexity/Gemini/Grok
- **Gemini CLI** — open-source ReAct loop, built-in tools + remote MCP, subagents
- **OpenCode** — read-only research agent, MCP, cheatsheet с slash-командами
- **Claude Code** — MCP, CLAUDE.md, slash commands, subagents, hooks, plugins, skills
- **Codex CLI** — Agent Skills (skills.sh), AGENTS.md project context
- **Hermes Agent** — TUI с multiline, slash autocomplete, history, persistent memory, self-skills

## Уже есть у нас ✅

- Bridge с auth + Tailscale Funnel + X25519
- agentctl с 16 namespaces
- MCP Streamable HTTP + SSE legacy + **WebSocket** (3 транспорта, 12 real tools)
- sd-exec — выход из cgroup для GUI/chromium
- py_browser — pure-Python ИБП-fallback
- Dashboard v4 — Terminal/MCP/Browser/Missions/Reports/Memory tabs
- mission templates (включая tabs-game)
- Cross-platform check + installers (linux/windows/macos)
- Memory facts + recovery prompt
- Task queue + audit + backup

## Что взять у лидеров (приоритеты)

### P0 — фундамент (1-2 чата)

1. **AGENTS.md / SKILLS** (от Codex+Claude Code): декларативные «скиллы» как md-файлы.
   Уже есть `agentctl skill ls|show|run`, но без формата. Нужно: `~/arena-agent/skills/<name>/SKILL.md`
   с фронт-маттером (name/desc/triggers) и опциональным `run.sh`. Дать `agentctl skill new`.

2. **Slash-команды для dashboard terminal** (от OpenCode/Claude):
   `/sys`, `/shot`, `/search`, `/mem`, `/help` — автодополнение в input.

3. **Hooks** (от Claude Code): user-defined скрипты на события `pre_exec`, `post_exec`, `pre_mission`.
   Реализация: `~/arena-agent/hooks/<event>.sh`, вызываются bridge'ом до/после `/v1/exec`.

### P1 — UX (2-4 чата)

4. **Subagents** (от Gemini CLI/Claude): запуск изолированного agentctl-runner в отдельном
   контексте через `agentctl sub <task>` → возвращает только summary. Снимает нагрузку с LLM-контекста.

5. **Persistent memory с поиском по векторам** (от Hermes): RAG уже есть, добавить
   автозапись summary каждого чата + auto-retrieve по новому запросу.

6. **TUI клиент** (от Hermes): `agentctl tui` — текстовый интерфейс с multiline,
   slash autocomplete, history, streaming output. Pure Python `prompt_toolkit`.

7. **Project context AGENTS.md** (от Codex): в каждом `~/arena-agent/projects/<name>/`
   класть `AGENTS.md` с правилами для агента → подхватывается автоматически.

### P2 — рост возможностей (4+ чата)

8. **Plugin marketplace** (от Claude/MCP-SA): `agentctl mcp install <name>` берёт MCP-сервер
   из реестра, регистрирует в mcp.json, перезапускает сервис.

9. **Web Bridge для chat-платформ** (от MCP-SA): не Chrome-extension, а простой
   `agentctl gateway` — endpoint, который ChatGPT/Gemini могут дёргать через user-prompt.

10. **Self-skills generation** (от Hermes): после успешной автономной миссии — записать
    последовательность действий как skill автоматически. `agentctl skill from-mission <id>`.

11. **Видеозапись missions** (новое): запись экрана при mission run через ffmpeg+sd-exec,
    сохранение в `~/arena-agent/reports/missions/<id>/recording.mp4`.

12. **WebSocket-only push** (расширение MCP): сейчас WS принимает запросы, но не пушит
    события. Добавить `subscribe(topic)` для notifications/progress.

## Не брать (анти-паттерны)

- ❌ Chrome extension — слишком хрупко, привязка к UI чужих сервисов
- ❌ Гигантские JSON-схемы tools — у нас уже компактно
- ❌ Скрытые/телеметрия — наш bridge owner-shell, всё локально

## Метрики успеха

- Любой новый чат может начать работу за ≤2 вызова `a '...'`
- Команды в среднем ≤80 символов
- MCP tools/call latency p50 < 100ms (без exec/chromium)
- Browser fallback срабатывает без вмешательства пользователя
- Recovery prompt ≤100 строк

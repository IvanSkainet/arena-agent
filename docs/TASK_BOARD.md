# Arena Bridge — Maintainer Task Board (Spec-Driven T0..Tn)

Этот документ фиксирует актуальное состояние задач, приоритеты и строгие критерии приёмки (Definition of Done) для автономных сессий.

---

## Актуальное состояние (на 2026-08-12)

- **Текущая версия:** `v4.169.41` (опубликована, 10 ассетов подписаны Sigstore).
- **CI:** 36/36 зелёных задач (Linux, Windows, macOS, Android, Scorecard, Zizmor, Security scan).
- **Security Alerts:** 0 открытых во всех трёх лентах (CodeQL, Secret Scanning, Dependabot).
- **Мутационный храповик:** 15 модулей зафиксированы на уровне **0 выживших мутантов**.

---

## Завершённые задачи (Done)

- [x] **T1 [MUTATION]** `arena/files/sandbox.py`: 89 выживших → **0** (208 убито, `test_files_sandbox_parity_v4_169_33.py`).
- [x] **T2 [SECURITY]** Аудит 85 отклонённых алертов: закрыты 2 реальных бага (веб-шлюз `web_gateway.py` + XSS тулбаров дашборда) (`v4.169.33`).
- [x] **T3 [MUTATION]** `arena/admin/browseract.py`: 155 выживших → **0** (192 убито, `test_browseract_parity_v4_169_34.py`).
- [x] **T4 [BUGFIX]** Проброс `subprocess_kwargs` (`CREATE_NO_WINDOW`) в `browseract.py` (`v4.169.34`).
- [x] **T5 [MUTATION]** `arena/admin/bore.py`: 141 выживший → **0** (306 убито, `test_bore_parity_v4_169_35.py`).
- [x] **T6 [MUTATION]** `arena/agent_helpers/files.py`: 84 выживших → **0** (99 убито, `test_agent_helpers_files_parity_v4_169_35.py`).
- [x] **T7 [MUTATION]** `arena/agentctl_cli/agentctl_memory.py`: 83 выживших → **0** (116 убито, `test_agentctl_memory_parity_v4_169_35.py`).
  - *Фикс бага:* `mem_set` безопасно валидирует флаги до индексации (предотвращён `IndexError`).
- [x] **T8 [MUTATION]** `arena/agentic/handlers.py`: 71 выживший → **0** (67 убито, `test_agentic_handlers_parity_v4_169_35.py`).
  - *Фикс бага:* `handle_v1_react` безопасно обрабатывает `null` вместо превращения в строку `"None"`.
- [x] **T9 [MUTATION]** `arena/browser/cdp_client/tabs_http.py`: 25 выживших → **0** (49 убито, `test_cdp_tabs_http_parity_v4_169_36.py`).
  - *Фикс race-condition:* устранён сокетный слип в `test_cdp_websocket_url_is_loopback.py`.
- [x] **T10 [MUTATION]** `arena/admin/auto_update_fetch.py`: 32 выживших → **0** (70 убито, `test_auto_update_fetch_parity_v4_169_36.py`).
  - *Оптимизация:* граничные тесты лимита размера 512 MiB без расхода диска tmpfs.
- [x] **T13 [MUTATION]** `arena/mobile/apk_paths.py`: 0 выживших (63/63 убито, `test_mobile_apk_paths_parity_v4_169_37.py`).
- [x] **T14 [MUTATION]** `arena/exec/interpreters.py` (65/65 убито, `test_exec_interpreters_parity_v4_169_37.py`) & `arena/workbench/runtime_fetch.py` (48/48 убито, `test_workbench_runtime_fetch_parity_v4_169_37.py`).
- [x] **T11 [MUTATION]** `arena/observability/live_metrics.py` (паритетный набор + фикс причины сбоя CPU, `test_live_metrics_parity_v4_169_37.py`).
- [x] **T18 [LIFECYCLE]** Безопасные батники `start.bat` / `stop.bat` / `status.bat` (`v4.169.38`):
  - `start.bat`: автопоиск Python по 15 путям, автоустановка зависимостей, автокопирование токена в буфер обмена (`clip`).
  - `stop.bat`: чистое выключение Tailscale Funnel / Serve, остановка туннелей, защита от закрытия браузера пользователя (`findstr /I "LISTENING"`).
  - `status.bat`: сквозной инструмент `scripts/check_bridge.py` с реальным внешним зондом доступности.
- [x] **T12 [MUTATION]** `arena/mcp_client/client.py`: быстрый паритетный набор с мок-процессами (`test_mcp_client_parity_v4_169_39.py`, 42 теста) + кроссплатформенная нормализация `\` в путях команд.
- [x] **T15 [MUTATION]** `arena/admin/handlers_update.py`: паритетный набор `test_handlers_update_parity_v4_169_39.py` (36 тестов, 0 выживших) + устранение эквивалентных мутантов парсинга JSON и fallback platform_display.
- [x] **T17 [MUTATION]** `arena/mobile/mirror.py`: паритетный набор `test_mobile_mirror_parity_v4_169_39.py` (33 теста, 0 выживших), полный охват валидации параметров, пайплайна, broadcast и HTTP/WS хэндлеров.
- [x] **T19 [SKILL]** `skills/arena-bridge/SKILL.md`: официальный агентский скилл Skainet Bridge (протокол подключения, обход лимита 128 MB, вынос тяжелых ассетов/вычислений на хост, MCP инструменты).
- [x] **T20 [INTEGRATION]** `docs/GODOT_INTEGRATION.md`: архитектурный гайд по разработке игр на Godot Engine через Skainet Bridge и скилл `godot-game-production-skill` в бездисковой/без-GPU песочнице Arena.ai.
- [x] **T21 [GOVERNANCE]** `AGENTS.md` + `scripts/serena_reminder.py`: фиксация жестких правил Spec-Kit (T0..Tn), напоминания о Serena и защите от потери контекста при сжатии.
- [x] **T22 [INTEGRATION]** Book of Eternity (BoE) GM Relay Subsystem:
  - `arena/game/boe_relay.py`: протокол сессии, защита путей, атомарная запись JSON, inbox long-poll, сигналы `complete_turn` / `fail_turn` / `repair_ready`.
  - `arena/game/boe_handlers.py`: 7 аутентифицированных хэндлеров `boe.*` для Arena Agent Mode.
  - `arena/game/boe_cli.py` & `bin/boe-arena-relay`: ConPTY pseudo-CLI для демона `game_master_daemon.ps1`.
  - `skills/book-of-eternity/SKILL.md`: агентский скилл автономного ГМа Book of Eternity.
  - `tests/test_boe_relay_parity.py`: паритетный набор из 27 тестов с проверкой path traversal и аутентификации.
- [x] **T23 [TYPES / PYRIGHT]** Ликвидация всех 95 ошибок Pyright до **0**, создание `scripts/pyright_ratchet.py` и `scripts/pyright_baseline.json` (зафиксирован на уровне 0).
- [x] **T24 [SECURITY / ALERTS]** Блокирующий шаг `security-alerts` в `.github/workflows/security-scan.yml` (автоматическое падение при незакрытых алертах).
- [x] **T25 [SECURITY / GITLEAKS]** Блокирующий режим Gitleaks в CI с `.gitleaks.toml`.
- [x] **T26 [SUPPLY-CHAIN]** Расширенный аудит зависимостей тулчейна (`requirements-ci.in`, `requirements-packaging.in`).
- [x] **T28 [LIFECYCLE / BATCH]** Храповик синтаксиса батников `scripts/batch_syntax_ratchet.py` (контроль CRLF и защиты браузера).
- [x] **T29 [RELEASE / VERIFY]** Автоматическая сквозная верификация релиза в `sign-release.yml`.

---

## Очередь задач (Queue)

*Все запланированные задачи Фазы 1, 2 и инфраструктурных ворот полностью выполнены (29/29 Done)!*

---

## Definition of Done (DoD) для любой задачи

1. **Root-cause fix:** чинится первопричина, а не глушится симптом.
2. **Parity Suite:** написан изолированный паритетный тест без недетерминированных зависимостей (monkeypatch хоста, времени и сокетов).
3. **0 Survivors:** запуск `mutmut` по модулю даёт ровно 0 выживших мутантов.
4. **Mandatory Sabotage:** умышленное внесение бага делает тесты красными; немутированный код — 100% зелёный.
5. **Ratchets & Lints:** `ruff check .`, `lint_ratchet.py`, `quality_ratchet.py`, `preflight.py --full` — всё зелёное.
6. **Clean Release:** чистый клон тега, сборка ZIP + APK, проверка SHA, публикация через GitHub API, ожидание зелёного CI на 36 задач.

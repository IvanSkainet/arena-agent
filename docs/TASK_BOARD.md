# Arena Bridge — Maintainer Task Board (Spec-Driven T0..Tn)

Этот документ фиксирует актуальное состояние задач, приоритеты и строгие критерии приёмки (Definition of Done) для автономных сессий.

---

## Актуальное состояние (на 2026-08-11)

- **Текущая версия:** `v4.169.36` (опубликована, 10 ассетов подписаны Sigstore).
- **CI:** 36/36 зелёных задач (Linux, Windows, macOS, Android, Scorecard, Zizmor, Security scan).
- **Security Alerts:** 0 открытых во всех трёх лентах (CodeQL, Secret Scanning, Dependabot).
- **Мутационный храповик:** 8 модулей зафиксированы на уровне **0 выживших мутантов**.

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

---

## Очередь задач (Queue)

### Фаза 1: Мутационная карта (оставшиеся модули TARGETS)
- [ ] **T12 [MUTATION]** `arena/mcp_client/client.py` (изоляция timeouts/stdio).
- [ ] **T15 [MUTATION]** `arena/admin/handlers_update.py` (завершение остатка после .24).
- [ ] **T17 [MUTATION]** `arena/mobile/mirror.py`.

### Фаза 2: Статический анализ и типизация
- [ ] **T16 [PYRIGHT]** Разбор ~95 находок Pyright (`reportOptionalMemberAccess`, `reportArgumentType`, `reportInvalidTypeForm`).

---

## Definition of Done (DoD) для любой задачи

1. **Root-cause fix:** чинится первопричина, а не глушится симптом.
2. **Parity Suite:** написан изолированный паритетный тест без недетерминированных зависимостей (monkeypatch хоста, времени и сокетов).
3. **0 Survivors:** запуск `mutmut` по модулю даёт ровно 0 выживших мутантов.
4. **Mandatory Sabotage:** умышленное внесение бага делает тесты красными; немутированный код — 100% зелёный.
5. **Ratchets & Lints:** `ruff check .`, `lint_ratchet.py`, `quality_ratchet.py`, `preflight.py --full` — всё зелёное.
6. **Clean Release:** чистый клон тега, сборка ZIP + APK, проверка SHA, публикация через GitHub API, ожидание зелёного CI на 36 задач.

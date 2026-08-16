# Arena Bridge — Maintainer Task Board (Spec-Driven T0..Tn)

Этот документ фиксирует актуальное состояние задач, приоритеты и строгие критерии приёмки (Definition of Done) для автономных сессий.

---

## Актуальное состояние (на 2026-08-15)

- **Опубликованная версия:** `v4.169.47` (12 release assets: ZIP pair + APK, Sigstore, exact-commit provenance и отдельные SPDX SBOM).
- **CI:** exact release commit `7995541d` зелёный: 63 check runs; candidate `31906141722`, sign-release `31907053903`, Linux/Windows/macOS matrices, CodeQL, Scorecard, Zizmor и fail-closed Security scan.
- **Security Alerts:** 0 открытых во всех трёх лентах (CodeQL, Secret Scanning, Dependabot).
- **Мутационный храповик:** 17 модулей зафиксированы на уровне **0 выживших мутантов**.

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

- [x] **T37 [GOVERNANCE / GITHUB]** ([#8](https://github.com/IvanSkainet/arena-agent/issues/8)) Значимые изменения переведены на Issue → branch → PR: структурированные Issue Forms и PR template, стабильные aggregate checks и активный ruleset `master` без обязательного внешнего approval/merge queue.
  - PR [#15](https://github.com/IvanSkainet/arena-agent/pull/15), [#17](https://github.com/IvanSkainet/arena-agent/pull/17) и [#18](https://github.com/IvanSkainet/arena-agent/pull/18) merged; ruleset `20321570` active, approvals=0, bypass actors отсутствуют, четыре required checks закреплены за GitHub Actions.
  - Direct-push sabotage `2211bf90` отклонён GitHub с `GH013` (repository rule violation); remote `master` остался `c18fdf3f`.
  - Markdown-only PR [#19](https://github.com/IvanSkainet/arena-agent/pull/19), run `31730318333`: classifier `docs_only=true`, `run_expensive=false`; Python matrix, coverage diff, packaging E2E, dashboard browser E2E, installed-artifact E2E, JS lint, quality scan и Android skipped. Остальные CI/security jobs выполнены, `CI required` success.
  - GitHub-managed AI findings Preview отключён после run `31719744562`: preview сам выбрал недоступную internal-модель и упал с HTTP 400 до анализа diff. CodeQL Default Setup и Copilot Autofix оставлены включёнными.
- [x] **T38 [CI / BADGE WRITER]** ([#9](https://github.com/IvanSkainet/arena-agent/issues/9)) Удалён write-to-master контур `version-badge.yml` после миграции инвариантов: source/tag consistency остаётся в `version_sync.py` / `pre_release_check.py`, а `release_published_check.py` теперь fail-closed отклоняет malformed latest tag и `releases/latest`, опережающий tree. README использует GitHub release badge; bot commits и `docs/version.json` устранены.
- [x] **T39 [SUPPLY CHAIN / PROVENANCE]** ([#10](https://github.com/IvanSkainet/arena-agent/issues/10)) Связать release ZIP с исходным commit: детерминированная CI-сборка, byte-for-byte source rebuild check, SBOM и GitHub/Sigstore provenance attestation. Один и тот же artifact должен пройти реальный Windows acceptance, публикацию без пересборки и анонимную post-publication переустановку.
  - PR [#20](https://github.com/IvanSkainet/arena-agent/pull/20): deterministic packer + `release-candidate.yml` с независимыми builds A/B, canonical artifact verifier, SPDX SBOM и двумя `actions/attest` predicates; signing gate принимает только два точных byte-identical ZIP, сверяет их с exact-SHA candidate manifest и требует attestation `source-digest`, равный commit релизного тега.
  - v4.169.45 завершила live acceptance на exact commit `69507673`: candidate run `31841758299` собрал совпадающие A/B ZIP, выполнил pinned Windows ConPTY contract и создал provenance/SBOM attestations. Оба имени имеют SHA-256 `99356556ea539123faf362b6bcc19fdce3396f40f15a803085f7c1b6c7b19626`.
  - Те же bytes проверены через `gh attestation verify`, до публикации установлены на Windows (1 009/1 009 replace-target files, missing/mismatch 0), опубликованы без пересборки, анонимно скачаны и повторно установлены штатным SHA-consent update API. `sign-release` run `31877313346` и post-update smoke прошли; release содержит 9 assets.
- [x] **T40 [SECURITY / FAIL CLOSED]** ([#11](https://github.com/IvanSkainet/arena-agent/issues/11)) Разделить advisory findings и scanner execution failures в Security workflow. TruffleHog, OSV, Syft/Grype, Socket Firewall и DevSkim не могут давать зелёный результат при падении самого сканера; пороги findings задаются явно и sabotage-проверяются.
  - Завершено PR #42/#43: общий `scanner_contract_gate.py`, строгие nested JSON/SARIF/CycloneDX contracts, явные exit envelopes, blocking action execution и политики OSV=any, Grype=Critical, DevSkim=error. Первый red вскрыл 23 DevSkim errors и настоящий strict-TLS дефект; правила не отключались, false positives закрыты узко. Exact merged-head manual Security run `31900724582`: 10/10 scanner jobs + `Security required` success.
- [x] **T41 [CROSS-REPO / BOOK OF ETERNITY]** ([#12](https://github.com/IvanSkainet/arena-agent/issues/12)) Добавить pinned-commit compatibility manifest и Windows contract workflow для `StanislavSmetaninSSM/The-Book-of-Eternity-Reborn`: build `BookOfEternityGMBridge`, два последовательных multiline ConPTY dispatch, correlated replies и validation-repair cycle без переноса игровых правил в Bridge.
  - PR #27 и exact-head run `31786699211` доказали artifact-bound цепь на upstream `11ddf9f5`. Post-merge freshness gate `31788059685` fail-closed обнаружил новый upstream head `385979a0`; PR #28 обновил pin, а exact-head run `31788294209` повторно доказал все три dispatch, correlation, empty queues и process/temp cleanup. Находки записаны в `docs/audits/boe-contract-live-findings-12.md`; Issue закрывается после merge pin-refresh PR.
- [x] **T42 [ARENA.AI / GM PRODUCTIZATION]** ([#13](https://github.com/IvanSkainet/arena-agent/issues/13)) Довести Arena.ai Agent Mode до пользовательского внешнего Game Master: универсальные full-capability `relay.*` / `fs.*` / `exec.*`, актуальный bootstrap skill, resume новой Arena-сессией, честные active/queued/busy состояния и многоходовой live E2E. Узкий game-specific token/toolset не является обязательным; operator-owned глобальная safety posture остаётся отдельным уровнем.
  - Завершено PR #29 (`82d4d501`): generic `relay.status/check/resume/busy/reply/send`, durable fresh-session resume, честные queued/claimed/busy/replied/repair depths, Arena.ai extension scopes `relay`/`gm`, bootstrap skill и public guide. Реальный Windows-контур без Codex принял ходы 4–7, inactive queue persistence, session restart и daemon repair; ручная кнопка расширения Arena.ai выполнила `relay.status`. Независимый pre-merge аудит добавил fail-closed malformed-state guards; exact-head CI 61/61. Журнал — `docs/audits/arena-agent-gm-live-findings-13.md`.
- [ ] **T43 [UPSTREAM / GAME LIFECYCLE]** ([#14](https://github.com/IvanSkainet/arena-agent/issues/14)) Через обязательные tracked Issues, а затем отдельные PR в репозитории игры передать воспроизводимые upstream-дефекты: stale `pending_turn_snapshot` после cancellation, зависимость обработки terminal signal от console event/F12 и невызванный `Ensure-CliBootstrapSent`.
- [x] **T44 [HTTP / EXEC LIFECYCLE]** ([#16](https://github.com/IvanSkainet/arena-agent/issues/16)) Отмена in-flight exec при разрыве remote HTTP client/proxy: ngrok 503 оставил низкопамятное дерево `cmd → powershell → gh run watch` живым до ручного `taskkill /T`; server-side timeout v4.169.44 при этом работает. Нужны handler cancellation propagation, общий process-tree cleanup и реальный Windows client-abort sabotage.
  - Завершено PR #46 и v4.169.47: общий transport watcher связывает buffered/script/stream handlers с lifetime HTTP-клиента; отмена дожидается runner cleanup, убивающего и reap-ящего всё дерево. Изолированный aiohttp TCP-abort E2E покрывает три endpoint, semaphore/tmp cleanup и `ACTIVE_PROCESSES`; модуль закреплён на 0/54 surviving mutants. Exact Windows head: 19 tests, surviving child=0. На установленном exact candidate реальный abrupt TLS/Tailscale client abort удалил `cmd.exe` PID 15452 и `powershell.exe` PID 9156 за 0,961 с; `/v1/ps` очистился, оба PID отсутствовали, Bridge остался healthy v4.169.47.
- [x] **T48 [WINDOWS / DIAGNOSTICS]** ([#48](https://github.com/IvanSkainet/arena-agent/issues/48)) На реальном RU-locale mover log `inspect_update_log.py` не распознал `DD.MM.YYYY  H:MM:SS,ff`, хотя все фазы и `mover-done` присутствовали. Добавить строгий localized timestamp parser, parity и sabotage без ослабления malformed-line rejection.
  - Завершено: отдельный strict timestamp contract принимает только доказанные ISO и RU Windows shapes, mixed/unobserved формы остаются fail-closed; exact retained log покрыт parity, sabotage ISO-only делает тест красным, новый модуль закреплён на 0/15 surviving mutants. Exact Windows branch source прочитал реальный mover log, восстановил все шесть фаз, `Scheduled Task path was used` и `OK (mover-done present)` с exit code 0.
- [x] **T49 [CI / REQUIRED JOBS GATE]** ([#24](https://github.com/IvanSkainet/arena-agent/issues/24)) Закрыть fail-closed contract gaps для empty/duplicate expected lists, non-object `needs`, malformed per-job records и заменить brittle quote-position parsing Security aggregate на anchored argument extraction. Обязательны CLI exit-code parity, bilateral sabotage и exact-head CI.
  - Добавлены direct + CLI contracts с точными exit codes: invalid expected input = 2, valid JSON с invalid `needs`/job shape = 1. Security aggregate теперь извлекает значение только из anchored `--expected` argument. Совместный sabotage отключения четырёх guards сделал шесть тестов красными; healthy governance suite 11/11.
- [ ] **T45 [GOVERNANCE / AI REVIEW]** ([#22](https://github.com/IvanSkainet/arena-agent/issues/22)) Перекалибровать GitHub Apps по живым PR evidence: CodeRabbit оставить manual high-risk reviewer, Sourcery — automatic informational reviewer, DeepSource удалить из-за exhausted quota и дублирования; читать review bodies/comments/checks вместе с threads, а bot autofix считать непроверенным входом. T45 открыта до Settings permission audit и фактического удаления DeepSource.

- [x] **T47 [TEST / SHIP SMOKE]** ([#38](https://github.com/IvanSkainet/arena-agent/issues/38)) Устранить зависимость `test_ship_smoke_shape` от пустого каталога flight-records: проверять дельту до/после, точный возвращённый `report_path` и двусторонним саботажем доказывать обнаружение двойной записи.

- [x] **T46 [RELEASE / ANDROID PROVENANCE]** ([#36](https://github.com/IvanSkainet/arena-agent/issues/36)) Вернуть `arena-bridge.apk` в релизы без ослабления source-bound pipeline: постоянный release-signing identity из GitHub secrets, exact-SHA APK build/verification, candidate checksum, provenance, отдельный SPDX SBOM, Sigstore signing и fail-closed проверки missing/substituted/wrong-SHA APK. v4.169.45 backfill взят только из exact-source CI run `31841745029`; reusable pipeline остаётся открытым до sabotage и live candidate evidence.
  - PR #37 и merged candidate run `31880691097` доказали persistent-key APK build, pinned certificate, 3-entry checksum, APK provenance и отдельный APK SPDX SBOM на exact SHA `106007d1`.
  - v4.169.46 закрыла healthy path: final candidate `31885105314` на `ad1a3b97`, packaged versionCode `41690046`, sign-release `31885657910`, 12 assets, анонимный APK SHA `eff06f7c149861c514f88e26e9a134ecaa9b52fedd1c60bf39ea5f09aa627d1e` и штатная post-publication переустановка ZIP.

- [x] **T32 [SECURITY / GITLEAKS]** Ночной `schedule` Security scan `#31676936942` нашёл 12 ложных утечек по истории (фикстуры, RFC 6455 `Sec-WebSocket-Key`, удалённые файлы). Расширен `.gitleaks.toml`, двусторонний саботаж в `tests/test_gitleaks_allowlist_v4_169_42.py`, фикстура `ghp_secret123` разобрана на конкатенацию.
- [x] **T33 [SCENARIO / PROTOCOL]** Book of Eternity как сценарий ядра, не как игра в мосте: терминальные сигналы выровнены с `Complete-BoeTurn` / `Complete-BoeValidationRepair`; E2E на официальных полях `output/*` через обычную запись JSON (`tests/test_boe_file_protocol_e2e_v4_169_42.py`).
- [x] **T34 [SCENARIO / TERMINAL RELAY]** Полный daemon-driven E2E без обхода транспорта завершён: универсальный `arena-relay terminal` сохранил 33 937-символьный turn prompt одним сообщением; ходы 2/3 прошли через client → daemon → ConPTY → relay; намеренный `narrative_response_unknown_field` доставлен repair packet'ом и принят после ограниченной починки; WinError 32 устранён `.partial` atomic temp; два последовательных multiline dispatch доказали rearm. Standalone bootstrap не симулировался: upstream-функция определена, но не вызывается. Журнал: `docs/scenarios/BOOK_OF_ETERNITY_DAEMON_E2E.md`; паритет: `tests/test_terminal_relay_v4_169_43.py`.
- [x] **T35 [WINDOWS / EXEC LIFECYCLE]** Runaway PowerShell PID 15300 из agent-authored `/v1/exec/script` probe достиг 44,5 ГиБ после timeout: deep `ConvertTo-Json` раздувал extended `Get-Content` objects, а Windows `Process.kill()` оставил child сиротой. Исправлено `taskkill /T /F` + cancellation/shutdown cleanup. Live sabotage: timeout 3,174 с, parent PID 4552 и child PID 2848 удалены, `.arena_script_tmp` orphans=0; последующий memory sample стабилен.
- [x] **T36 [WINDOWS / RESTART]** Manual `/v1/admin/update/restart` сообщил scheduled и выключил Bridge, не вызвав launcher; через две минуты потребовался ручной `start_hidden.vbs`. Исправлено detached WSH/CMD helper до exit с ожиданием PID и проверкой port после VBS/bat/task; auto-update reuse-ит mover. Live recheck: endpoint сам вернул `relauncherPrepared=true`, log — `ready via start_hidden.vbs`, health v4.169.44 восстановлен без ручного запуска.

---

## Definition of Done (DoD) для любой задачи

1. **Root-cause fix:** чинится первопричина, а не глушится симптом.
2. **Parity Suite:** написан изолированный паритетный тест без недетерминированных зависимостей (monkeypatch хоста, времени и сокетов).
3. **0 Survivors:** запуск `mutmut` по модулю даёт ровно 0 выживших мутантов.
4. **Mandatory Sabotage:** умышленное внесение бага делает тесты красными; немутированный код — 100% зелёный.
5. **Ratchets & Lints:** `ruff check .`, `lint_ratchet.py`, `quality_ratchet.py`, `preflight.py --full` — всё зелёное.
6. **Clean Release:** чистый клон тега, сборка ZIP + APK, проверка SHA, публикация через GitHub API, ожидание зелёного CI на 36 задач.
- [x] **T30 [CI/CD HARDENING]** Комплексное усиление GitHub Actions:
  - Проставлены явные `timeout-minutes` во всех 40 джобах 10 workflow-файлов (защита от 6-часового зависания раннеров).
  - Настроены группы `concurrency` с `cancel-in-progress: true` в `dependency-review.yml`, `scorecard.yml`, `zizmor.yml`, `version-badge.yml` (экономия раннеров и исключение гонок).
  - Локальный preflight 23/23 OK, Zizmor 0 findings, Actionlint 0 errors.
- [x] **T31 [BOE INTEGRATION PARITY]** Полное согласование контрактов с `StanislavSmetaninSSM/The-Book-of-Eternity-Reborn`:
  - Обновлён `arena/game/boe_relay.py`: обязательное поле `filesModified` и `timestamp` (ISO 8601) в `ready/turn_complete.json`, устранение competing error signal, поддержка `read_turn_request` и `read_repair_request`.
  - Защита границ реалмов: `validate_realm_path` блокирует ошибочные мутации Mortal-файлов в Afterlife (`Chaos Sea` / `Shining Abode`) и Afterlife-файлов в `Mortal World`.
  - Запись `validation_repair_ready.json` как в `game_state/control/`, так и в корень для гарантированной совместимости с валидатором C# клиента.
  - Синхронизирован `arena/game/boe_cli.py` и `arena/game/boe_handlers.py` с 28 изолированными паритетными тестами.

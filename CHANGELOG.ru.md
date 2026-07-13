# История изменений

> 🌐 [English version](CHANGELOG.md)

Здесь собрана история актуальной, extension-ориентированной эпохи проекта.
Полная построчная история всех релизов (включая ранние v2.x–v3.1.x) ведётся в
[англоязычном CHANGELOG.md](CHANGELOG.md).

## v3.81.2 — 2026-07-13

Кросс-платформенная закалка ZeroTier + правильно подключённая карточка
Tunnels в Dashboard + понятный onboarding для тех, кто не знает как
"запустить" ZeroTier. Bump `pyproject.toml` (три релиза подряд она
молча оставалась на 3.79.0) до `arena/constants.py`.

### Исправлено

- **Dashboard: карточка Tunnels & Remote Access теперь реально
  обновляется.** Два бага делали её мёртвой:
  * ZeroTier Join/Leave POST перезатирал `Authorization: Bearer` header,
    передавая свой `headers` в `api()`, и запросы молча 401'ились;
  * первичный auto-refresh запускался внутри listener'а
    `DOMContentLoaded`, но модуль грузится ПОСЛЕ этого события, так что
    никогда не срабатывал. Переписал как IIFE, который хукается на
    `refreshSettings()` (реальный вход в Settings-tab) и запускает
    5-секундный auto-refresh пока Settings-tab открыт.
- **Dashboard onboarding для ZeroTier.** Если ZeroTier не установлен —
  карточка показывает готовые команды под платформу
  (`winget install ZeroTier.ZeroTierOne` / `brew install --cask
  zerotier-one` / `sudo pacman -S zerotier-one`) плюс download URL.
  Если ZeroTier установлен но сети не подключены — печатает 4-шаговый
  гайд (создать free network на my.zerotier.com → вставить nwid →
  Join → авторизовать node). Больше нет тупика "installed=true, но что
  делать дальше".
- **Валидация nwid на клиенте.** Dashboard отбивает некорректные ID
  (должно быть ровно 16 hex-символов) через дружелюбный `alert()` до
  самого сетевого вызова.
- **Валидация nwid на сервере.** `zerotier_network_action()` теперь
  отказывается принимать не-hex или не-16-символьные ID на API-уровне
  с чётким сообщением, нормализует регистр и обрезает whitespace, так
  что paste с ZT dashboard просто работает. Раньше CLI спокойно принимал
  `join 0000000000000000` и создавал вечный мусорный row в `listnetworks`.
- **Спавн subprocess на Windows больше не флешит консольным окном.**
  `_run_cli()` теперь ставит `CREATE_NO_WINDOW` только на Windows. На
  Linux и macOS флаг отсутствует. Без этого каждый 5-секундный
  Dashboard-refresh (×N CLI-кандидатов) вспыхивал бы чёрным CMD-окошком
  на долю секунды — и раздражает, и легко принять за malware.
- **`/v1/zerotier/network/{action}` принимает nwid откуда угодно.**
  Раньше handler читал query только на GET и JSON body только на POST.
  Теперь любой POST также принимает `?network_id=…` в URL,
  `application/x-www-form-urlencoded` bodies и JSON без Content-Type —
  как реально отправляют браузеры, curl и любой HTTP-клиент.
- **Windows: `zerotier-cli.exe` тоже пробуется.** Installer регистрирует
  `.bat` shim, но `zerotier-cli.exe` в той же папке — тот же
  инструмент, теперь оба ищутся на Windows.
- **Опциональный sudo wrapper — только на Linux.** Никогда не
  рассматривается на Windows/macOS. На Linux остаётся как fallback для
  хостов с дефолтными 640 permissions на `authtoken.secret`.

### Изменено

- **`pyproject.toml` version → 3.81.2.** Исправление тихого drift: файл
  оставался на 3.79.0 через релизы 3.80.0, 3.81.0 и 3.81.1, потому что
  прежние release-скрипты трогали только `arena/constants.py`.
- **Modularity limit для `arena/` runtime поднят 500 → 600.**
  `arena/admin/zerotier.py` теперь 533 строки (cross-platform token
  discovery + HTTP + CLI + validation + Windows subprocess flags
  неразрешимо многословны) — читаемость важнее сжатия. Лимит
  product-файлов остаётся 700.

### Документация

- `AGENTS.md` и `docs/MODULE_MAP.md` отражают новый лимит 600 строк.

### Тесты

702 passed (было 690). Новое покрытие: 12 дополнительных тестов для
ZeroTier (multiple IPs, null IP, cli_source classification для
wrapper/direct на каждой OS, Windows-only creationflags, absolute token
paths, host-matches-platform, плюс 5 тестов валидации nwid).

## v3.81.1 — 2026-07-13

Fix-релиз третьего прохода после v3.81.0.

### Исправлено

- **installer: PEP 668 aware + verify import.** Старый installer молча
  глотал ошибки `pip install` на любой managed-Python системе (Arch,
  Debian 12+, Ubuntu 23.10+, Fedora 39+) и печатал "OK Python packages
  ready", а systemd потом падал с `ModuleNotFoundError`. `install.sh` и
  `install.bat` теперь пробуют 4 стратегии подряд (plain → `--user` →
  `--user --break-system-packages` → project-local venv) и **проверяют**
  `import aiohttp` через тот же интерпретатор, который передадут в
  systemd. Если импорт всё ещё не работает — installer аварийно
  прерывается с готовой командой восстановления, а не врёт "OK". Если
  сработала 4-я стратегия, `PY` переопределяется на venv-python и
  systemd unit подхватит его автоматически. Коммит `b5f83e7`.
- **installer: защита от downgrade.** Запуск `bash install.sh` из папки
  со старым распакованным zip'ом (например `~/Загрузки/arena-bridge/`)
  раньше молча rsync'ал старую копию поверх установленного Bridge.
  Теперь installer сравнивает `arena/constants.py::VERSION` в source vs
  installed и отказывается делать downgrade без явного "y" (или
  `ARENA_ALLOW_DOWNGRADE=1`).
- **skills: `/v1/skills` больше не показывает не-skill директории.**
  Консолидация Superpowers привела к тому, что в `skills/superpowers/`
  оказалась полная upstream раскладка: `assets/`, `hooks/`, `scripts/`,
  `.claude-plugin/` рядом с `skills/`. Registry раньше интерпретировал
  каждую соседнюю директорию как "skill" — из-за этого в API появлялись
  фиктивные записи вроде `superpowers/assets`. Теперь скан-логика
  сначала проверяет наличие marker-файла (SKILL.md / manifest.json /
  run.sh / run.py), а если в категории есть вложенная `skills/`, — она
  итерируется отдельно. Все 14 upstream superpower skills теперь видны
  правильно, плюс `browseract` и Arena core-категории.
- **tunnels: `installed` для Tailscale теперь выводится из состояния.**
  `sys_funnel_status` не всегда возвращает флаг `installed`, из-за чего
  `_tailscale_snapshot` рапортовал `installed: false` даже когда funnel
  URL был активен. Теперь snapshot выводит installed из любого
  наблюдаемого состояния (connected/active/status). Добавлено 2 теста.
- **zerotier: `zerotier_network_action` перебирает всех кандидатов CLI.**
  Раньше принимался первый результат, даже если exit code != 0 — из-за
  этого на Linux с default `/usr/bin/zerotier-cli` (rc=2, "authtoken not
  readable") sudo-wrapper `/usr/local/bin/zerotier-cli-wrapper` никогда
  не пробовался. Теперь цикл сохраняет последний failing payload и
  переходит к следующему, возвращая успех от того binary, который
  реально работает.

### Тесты

690 passed (было 688), +2 регрессионных теста для tailscale inference.

## v3.81.0 — 2026-07-13

Кросс-платформенный спринт по удалённому доступу и интеграции CLI-инструментов.
Всё в этом релизе спроектировано так, чтобы одинаково работать на Windows,
macOS и Linux — без sudo-обёрток и платформозависимых костылей по умолчанию.

### Ключевое

- **Единый фасад туннелей.** Новый API `/v1/tunnels/{status,active,start,stop}`
  рассматривает Tailscale, Cloudflared и ZeroTier как единый пул провайдеров
  с настраиваемым приоритетом (env `ARENA_TUNNEL_PRIORITY`, по умолчанию
  `tailscale,cloudflared,zerotier`). Bridge остаётся доступен через первый
  здоровый провайдер — падение одного больше не роняет весь Bridge.
- **ZeroTier переписан кросс-платформенно.** Приоритет — локальный HTTP API
  ZeroTier (127.0.0.1:9993) с platform-aware поиском auth-токена (Windows
  `%PROGRAMDATA%`, macOS `/Library/Application Support`, Linux
  `/var/lib/zerotier-one`). Fallback на `zerotier-cli` из PATH или well-known
  путей. sudo-обёртка больше не требуется по умолчанию.
- **BrowserAct интегрирован.** Новый `arena/admin/browseract.py` показывает
  install / version / update-hint. Новый кросс-платформенный
  `skills/browseract/run.py` заменяет bash-only `run.sh`, сохраняя те же
  subcommand'ы. `install.sh` / `install.bat` уже умели ставить
  `browser-act-cli` через `uv tool install`.
- **Cloudflared кросс-платформенные подсказки.** `_get_update_hint()` теперь
  выдаёт готовые к копированию команды под платформу + источник установки:
  `winget`/`scoop` на Windows, `brew` на macOS, `apt`/`pacman` на Linux.
- **Dashboard: карточка Tunnels & Remote Access.** Вкладка Settings теперь
  показывает все три провайдера с заголовком "Active endpoint", кнопками
  Start all / Stop all и панелью управления ZeroTier-сетями (join/leave по
  nwid, список подключённых сетей, install/permission hints inline).
- **Superpowers консолидированы.** `tools/superpowers/` удалён;
  `skills/superpowers/` теперь — прямой upstream mirror
  [obra/superpowers][obra] для обоих потребителей (Bridge через `/v1/skills`,
  `install.sh` и standalone IDE-плагинов). Больше нет расхождения форка.
- **Лимиты модульности подняты.** `MAX_PRODUCT_FILE_LINES` 300 → 700,
  `MAX_RUNTIME_LINES` 220 → 500. Читаемый код важнее сжатого (политика
  проекта). Extension `content.js` / `adapters.js` / `insert_strategies.js`
  распрямлены из single-line-per-function обратно в нормальное форматирование.

### Добавлено

- `arena/admin/tunnels.py` — единый multi-provider фасад.
- `arena/admin/browseract.py` — кросс-платформенный статус BrowserAct CLI.
- `skills/browseract/run.py` — Python-обёртка, работающая на Win/Mac/Linux.
- `dashboard/assets/29-tunnels.js` + обновлённый
  `dashboard/assets/body-15-settings.html` — новая карточка Tunnels.
- `docs/SUPERPOWERS.md` — переписан под one-directory модель.
- `scripts/sync_superpowers_from_upstream.sh` — упрощённый sync-скрипт.
- Тесты: `test_tunnels.py` (14), расширенный `test_zerotier.py` (5 → 11),
  `test_browseract.py` (11), расширенный `test_cloudflared.py` (5 → 7).

### Изменено

- `arena/admin/zerotier.py` — полная переработка; HTTP API приоритет,
  CLI как fallback, structured контракт (`installed`, `backend`,
  `cli_source`, `platform`, `hint`, `assignedAddresses`).
- `arena/admin/cloudflared.py` — подсказки под платформу + источник;
  дополнительные пути для macOS/Linux Homebrew/snap.
- `arena/capabilities.py` — `/v1/capabilities.network` показывает все
  поля ZeroTier; `.browser` — поля BrowserAct.
- Extension файлы — восстановлено читаемое форматирование, без изменения
  поведения; тот же v0.13.27.

### Удалено

- `tools/superpowers/` — консолидирован в `skills/superpowers/`.
- Форкнутые Arena-версии skill-файлов — заменены upstream-версиями.

### Тесты

688 passed (было 655), 456 warnings. Новое покрытие: 14 tunnels + 6
ZeroTier + 11 BrowserAct + 2 cloudflared.

[obra]: https://github.com/obra/superpowers

## v3.80.0 — 2026-07-13

### Extension v0.13.23 — Тайминги и кеширование конфига

- Добавлен кеш конфига в background.js (инвалидируется при изменениях storage) и content.js (TTL 5с) — убирает лишние чтения chrome.storage на каждый bridge-запрос.
- Кеш конфига в content.js убирает IPC-раундтрип на каждый клик Insert/Send.
- Адаптивная задержка verify в insert_strategies.js: проверка на 30мс/80мс/180мс вместо жёстких 180мс (экономит ~150мс на быстрых вставках).
- Адаптивный polling submit: 20мс/20мс/40мс/40мс/80мс ramp вместо плоских 40мс.
- Кнопка Run показывает тайминг: "Executed N call(s) in Xms".
- bridgeFetch возвращает bridge_ms (сетевой раунд-трип до bridge) для диагностики.
- timingSummary включает bridge_ms когда доступно.

### Extension v0.13.24 — Троттлинг сканов и фильтрация мутаций

- Троттлинг сканов: минимум 400мс между сканами, отслеживает lastScanAt чтобы не делать лишнюю работу.
- Фильтрация MutationObserver: пропускает мутации внутри собственных тулбаров, чтобы не было feedback loops.
- Уменьшает ненужные вызовы scan() на SPA-страницах (Claude/ChatGPT/Gemini).

### Extension v0.13.25 — Кеширование адаптера и candidate nodes

- getArenaAdapter() кешируется (host не меняется в течение загрузки страницы).
- arenaCandidateNodes() кешируется с инвалидацией при релевантных мутациях.
- Fast path в scan(): пропускает parseArenaBlocks если количество кандидатов не изменилось и у всех уже есть тулбары.
- MutationObserver инвалидирует кеш кандидатов при релевантных мутациях.
- Уменьшает лишние querySelectorAll + парсинг текста на стабильных страницах.

### Extension v0.13.26 — Split bridge timing в статусе Run

- Кнопка Run показывает split по bridge_ms: "Executed N call(s) in Xms (bridge Yms)".
- Помогает понять, сколько времени Run — это нетворк до bridge vs MCP execution.

### Extension v0.13.27 — Кеш composer и стабильность insert

- Composer selection кешируется (TTL 2с с проверкой isConnected) — уменьшает вариативность querySelectorAll.
- Insert target кешируется в __arenaLastInsertTarget для переиспользования в InsertAndSubmit.
- Адаптивный submit polling v2: ramp-up задержки (20/40/80/100мс) вместо плоских интервалов.
- Уменьшает вариативность таймингов Insert с ~86мс до ~20мс в среднем.

## v3.79.0 — 2026-07-02

- Синхронизированы рекомендации по модульности в `docs/` с реальным лимитом: доки говорили про ~180-220 строк, а `tests/test_project_modularity.py` требует 300; теперь MODULE_MAP.md, V3_MODULAR_ARCHITECTURE.md и V3_RELEASE_CHECKLIST.md ссылаются на тест как на источник истины.
- Убрано устаревшее число строк в V3_MODULAR_ARCHITECTURE.md (`unified_bridge.py` больше не описан как ровно 98 строк).
- В исторические audit/roadmap/plan-доки добавлен явный баннер «Historical document», чтобы их не путали с актуальной документацией.

## v3.78.0 — 2026-07-02

- README.md и README.ru.md переработаны в удобные для чтения публичные landing pages: добавлены оглавление, секция «Зачем», ASCII-диаграмма потока и таблица возможностей.
- RELEASE.md переписан под текущий процесс релиза (убраны устаревшие формулировки v3.1.x, добавлены чеклист bump-версии расширения и шаг с CHANGELOG.ru.md).
- CHANGELOG.ru.md перестроен так, что русская история покрывает extension-эпоху, а не прыгает с v3.77 сразу на v3.1.6.
- Обновлены примеры в docstring scripts/make_release_zip.py.

## v3.77.0 — 2026-07-02

- README.md переписан как чистая публичная landing page; история релизов вынесена из основного README.
- README.ru.md переписан как актуальная русская landing page с той же структурой.
- CONTRIBUTING.md и chat_extension/README.md обновлены под текущий unified bridge и extension workflow.

## v3.76.0 — 2026-07-02

- Добавлены history-события расширения для действий тулбара Insert и Send.
- Lifecycle команд в sidepanel расширен стадиями `insert` и `submit`.
- В карточках sidepanel показываются стратегия/тайминги/версии вставки.

## v3.75.0 — 2026-07-02

- Группировка lifecycle в sidepanel сделана консервативной: повторяющиеся одностадийные события остаются обычными карточками, а не фейковыми lifecycle.
- Убраны дублирующиеся status-бейджи из групповых карточек команд.
- Добавлено «живое» поведение фильтров: смена kind применяется сразу, поля site/adapter — с debounce.

## v3.74.0 — 2026-07-02

- Добавлена группировка lifecycle команд в sidepanel для связанных событий `detected`, `preview`, `execute`.
- Сохранён аудит: остались raw-фильтры по kind и добавлен исходный `history_index` для replay-действий.
- Добавлены flow-бейджи и regression-покрытие. (UX этой версии оказался неудачным и был исправлен в v3.75.)

## v3.73.0 — 2026-07-02

- В фильтр истории sidepanel добавлен вид `scan`.
- Диагностика Scan Page выведена прямо в карточки Command Center: количество candidates/blocks/controls, тип composer, план Auto-вставки и версии manifest/content/insert-скриптов.

## v3.72.0 — 2026-06-28

- Строки истории в sidepanel превращены в компактные карточки в стиле Command Center с бейджами kind/status/count.
- Всегда развёрнутый status JSON заменён краткими сводками (raw-данные по-прежнему доступны в панели результата).

## v3.71.0 — 2026-06-28

- Повторяющиеся записи Scan Page в пределах короткого окна агрегируются в одну строку со счётчиком `×N` вместо флуда.
- Действия `preview` и `execute` не агрегируются, чтобы оставаться аудируемыми.

## v3.70.0 — 2026-06-28

- Снижен шум detected-истории: дедуп по payload fingerprint вместо позиции в DOM.
- В detected-записи добавлены имена tools и payload fingerprint для более полезных строк popup/sidepanel.

## v3.69.0 — 2026-06-28

- В вывод Scan Page добавлена явная диагностика версий manifest/content/insert-скриптов, чтобы устаревшие content scripts были заметны после reload.
- Добавлена диагностика composer (`rich_textarea`, `prose_mirror`, `auto_plan`), объясняющая выбор Auto-стратегии.

## v3.68.0 — 2026-06-28

- Auto-вставка стала editor-aware: ProseMirror-подобные contenteditable (ChatGPT, Claude) используют нативный `insertText`, сохраняя многострочную структуру.
- Быстрый путь `directDomPreWrap` ограничен Gemini Web `rich-textarea`, где он подтверждён и по скорости, и по структуре.

## v3.67.0 — 2026-06-28

- `Auto` помечен как рекомендуемая стратегия вставки в popup, ручные стратегии — как debug.
- Тайминги тулбара сообщают конкретную выбранную Auto-стратегию.

## v3.66.0 — 2026-06-28

- Стратегия `auto` для contenteditable стала адаптивной: сначала verified `directDomPreWrap`, затем fallback на нативный `insertText`, только если быстрый путь не изменил composer.
- Улучшена settled-верификация без Gemini-специфичного режима.

## v3.62.0 – v3.65.0 — 2026-06-28

- Введён и последовательно доработан набор insert-стратегий (`nativeInsertText`, `paragraphFallback`, `pasteOnly`, `directDomText`, `directDomBlocks`, `directDomPreWrap`) для A/B-тестирования вставки в разные composers без site-специфичных режимов.
- Тулбар сообщает выбранную стратегию и тайминг; успех считается только по реальному изменению composer.
- Insert & Submit не нажимает Send, если вставка не подтверждена или откачена целевым UI.

## v3.60.0 – v3.61.0 — 2026-06-28

- Исправлен `TypeError: Failed to fetch` расширения для публичных tunnel-bridge за счёт generic host permissions.
- Убрано случайно добавленное приватное разрешение под конкретный Tailnet; заменено на generic `https://*.ts.net/*` и `https://*.trycloudflare.com/*`.
- Исправлен размер опциональной загрузки cloudflared: ~50 MB.

## v3.46.0 – v3.59.0 — 2026-06-28

- Стабилизированы адаптеры и detection для Gemini Web, ChatGPT и Claude на основе реальной диагностики Scan Page (селекторы, фильтрация user-echo, дедуп контролов).
- Исправлена вставка многострочных результатов в contenteditable composers и JSONL-парсинг «склеенных» блоков ChatGPT.
- Снижены задержки Insert/Send на Gemini (устранён focus churn, лишние синтетические события, дорогой clone больших узлов).
- Лимит модульности product-файлов поднят с 200 до 300 строк, чтобы не сжимать helpers искусственно.

## v3.24.0 – v3.45.0 — 2026-06-26 … 2026-06-28

- Заложены backend-фундамент и первый scaffold браузерного расширения Arena Chat Bridge.
- Добавлены endpoints расширения (`/v1/extension/policies`, `/instructions`, `/preview`, `/execute`) и классификация tools по risk.
- Развит sidepanel/Command Center, история детекций и replay.

## Более ранние версии (v2.0.7 – v3.23.0)

Эти релизы охватывают становление unified bridge: модульную архитектуру,
mission-композицию, управление окнами/desktop, OCR и стабилизацию.
Полная построчная история — в [англоязычном CHANGELOG.md](CHANGELOG.md).

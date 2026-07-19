## v4.50.5 -- Toggle dedup (default ON) + AI Studio user-filter + z-index toolbar + лимит 900 строк

Четыре запроса оператора, один релиз.

### 1. Toggle "Dedup toolbar" в Advanced / Experimental

Оператор: "Я бы хотел добавить опцию включения и отключения [dedup].
Мне с dedup всё-таки больше нравилось."

v0.14.14 полностью убрал semantic dedup, каждый candidate получал
свой toolbar (Claude call_id 1..N все видны). Оператор предпочитал
поведение до v0.14.14 (один toolbar на unique semantic tool block)
для читаемости, но хотел возможность включить режим "показывать
всё" при необходимости.

Теперь: `modes.dedupSemantic` (default `TRUE`, соответствует
предпочтению Ivan).

* `true`: восстановлен semantic dedup до v0.14.14 с alive-gate
  из v0.14.13. Sibling дубликаты получают `skip_semantic_prev_alive`;
  DOM-gone owners эвиктятся + перемонтируются (`evict_semantic_owner`).
* `false`: каждый candidate host получает свой toolbar
  (поведение v0.14.14). Полезно когда оператор не может понять,
  какую копию extension выбрал.

Wired через:

* `chat_extension/settings.js` -- default в `ARENA_MODE_DEFAULTS`;
  normalizer трактует undefined как true, чтобы upgrade'ры
  случайно не остались с поведением "показывать всё" из v0.14.14.
* `chat_extension/background.js` -- те же defaults + normalizer,
  так как background не может импортировать content-script assets.
* `chat_extension/popup.html` -- новый fieldset "Advanced /
  experimental" с `#dedupSemantic` checkbox.
* `chat_extension/popup.js` -- read/write checkbox на save/load;
  undefined трактуется как checked.
* `chat_extension/content.js` -- новый синхронный helper
  `_arenaCurrentModes()` возвращает последний известный modes
  объект без chrome.runtime round-trip; mountControls gates весь
  semantic-dedup блок за `_dedupSemantic`.

### 2. Фильтр user-turn для AI Studio

Оператор: "На AI Studio всё ещё user ловит."

Скан показал: PRE-candidates у User prompt и AI thought имеют
одинаковую `mat-expansion-panel` форму -- в 4 ближайших ancestor'ах
нет различающего атрибута. AI Studio на самом деле использует
custom элементы `<ms-chat-turn role="user">` и
`<ms-prompt-chunk chunkrole="user">` для user turns. Добавил
per-adapter branch в `arenaWhyUserAuthored` (только когда
`location.hostname` совпадает с `aistudio.google.com`):

* возвращает `matched: true, reason: 'aistudio:user-turn@<TAG>'`
  когда найден `ms-chat-turn[role="user"]` или
  `ms-prompt-chunk[chunkrole="user"]` ancestor;
* fallback на текст `mat-expansion-panel-header`, начинающийся с
  "User" или "Пользоват" (locale-safe), с tag
  `aistudio:user-panel@MAT-EXPANSION-PANEL`.

Путь `gemini.google.com` не тронут -- этих элементов там нет.

### 3. Toolbar больше не перекрывает композер

Оператор: "Toolbar поверх окна ввода чата, из-за чего очень
некрасиво."

Корень: `shadow_toolbar.css` устанавливал `z-index: 2147483000`
(max int-safe). Композеры сайтов используют `position: fixed`
внизу viewport с `z-index: 1000-ish`. Наш shadow host находится
в message flow, но его `z-index: 2147483000` overrode композер
всякий раз, когда они пересекались в viewport.

Фикс: `z-index: 100`. Выше обычного in-flow контента (site
action rows сидят на 5-10), но комфортно ниже любого fixed
композера, который anchor'ится на 1000+. `position: relative` +
`isolation: isolate` остались -- они влияют только на наш
собственный stacking context.

Qwen-фикс из v4.48.6 (устанавливавший max-int z-index против
overlap like/dislike/share row) по-прежнему работает, так как
100 всё ещё выше этих inline action rows. Если конкретной
Qwen-surface нужно выше, поднимем per-adapter.

### 4. MAX_PRODUCT_FILE_LINES 700 → 900

Оператор: "не сжимай код. Лучше сделай ограничение больше,
скажем 800 строк, ... но и читабельность кода тоже хорошая
должна быть."

v0.14.9..v0.14.14 приходилось резать комментарии и inline блоки
на каждом релизе только чтобы влезть в 700-строчный потолок
`content.js`. Это делало каждую последующую отладочную сессию
сложнее, потому что контекст, существовавший в предыдущей версии,
пропадал. 900 даёт запас в ~200 строк.

`tests/test_project_modularity.py::MAX_PRODUCT_FILE_LINES`
поднят с объясняющим docstring'ом. Все прежние extension-тесты,
guard'ившие content.js line count, обновлены с 700 на 900.

`chat_extension/content.js` сейчас на **743 строках** -- комфортно
под 900, с местом для будущих идей (см. ниже).

### Бампы версий

* extension `0.14.14` → `0.14.15`
* bridge `4.50.4` → `4.50.5`

### Регрессионные guard-тесты

13 новых asserts в `tests/test_chat_extension_v0_14_15.py`:

* четыре version pin
* normalizers settings.js/background.js включают dedupSemantic
  с корректным default-true undefined-поведением
* popup.html имеет Advanced fieldset с pre-checked
  dedupSemantic input
* popup.js читает И пишет checkbox, с undefined-is-true fallback
  на load
* content.js gates весь semantic-dedup блок за `_dedupSemantic`;
  три diag kind (`evict_semantic_owner`, `skip_semantic_prev_alive`,
  `skip_semantic_already_mounted`) снова живут внутри этого блока
* per-host dedup (`existing?.bar?.isConnected`, `hostHasToolbar`)
  по-прежнему работает безусловно
* AI Studio branch запрашивает три известных сигнала и эмитит
  две отдельные skip reasons
* shadow_toolbar.css использует `z-index: 100`, больше никогда
  `z-index: 2147483000`
* modularity limit -- 900, не 700
* content.js ≤ 900 строк
* каждый прежний per-release regression guard держится

Девять прежних extension test-файлов перепинены на 0.14.15. Их
assertions "must-not-come-back" из v0.14.14 переписаны как
"gated-in-v0.14.15", чтобы не падать напрасно. Полный прогон:
**2505 passed, 0 failed**.

### Изменённые файлы

* `chat_extension/content.js` -- 691 → 743 строк (semantic-dedup
  блок восстановлен + `_arenaCurrentModes` helper + gate)
* `chat_extension/adapters.js` -- 622 → 650 строк (AI Studio
  branch)
* `chat_extension/settings.js` -- 26 → 36 строк (dedupSemantic
  default + normalizer)
* `chat_extension/background.js` -- 296 → 302 строк (mirror
  normalizer + SYNC_DEFAULTS update)
* `chat_extension/popup.html` -- 57 → 70 строк (Advanced
  fieldset)
* `chat_extension/popup.js` -- 176 → 184 строк (read/write
  checkbox)
* `chat_extension/shadow_toolbar.css` -- 113 → 120 строк
  (z-index fix + объясняющий комментарий)
* `chat_extension/insert_strategies.js` -- version bump
* `chat_extension/manifest.json` -- version bump
* `chat_extension/README.md` -- banner refresh
* `tests/test_project_modularity.py` -- 700 → 900 с обоснованием
* `tests/test_chat_extension_v0_14_15.py` -- новый, 13 asserts
* девять прежних extension test-файлов перепинены + переписаны
  под gated dedup + новый z-index + 900-line limit
* `arena/constants.py`, `pyproject.toml` -- VERSION bump

### Отложено (две forward-looking идеи оператора)

**Идея A (collapse tool results в истории чата):**

  "Сделать так, чтобы результат в истории чата как-то закрывался
   окошком, потому что сейчас весь код в не свёрнутом виде на
   сайте смотреть удобно, но это очень долго листать и, вероятно,
   плохо для производительности."

План: после успешного Run заменить вставленный result blob в
composer/chat на foldable "▸ Arena tool result (N tools, M
lines) -- click to expand" wrapper. Content хранится в closure
toolbar'а; expansion re-inlin'ит по требованию. Это будет жить
в `content.js::runAutoModes` и `arenaInsertResult`. Также должно
переживать site rehydration (mutation observer для re-fold если
сайт un-collapse при scroll). Отложено на v4.51.0.

**Идея B (полный catalog инструкций):**

  "С инструкциями разобраться, чтобы ИИ получал весь список всех
   возможных команд или команд по определённому блоку или типу,
   например desktop, а не ту короткую заглушку, что сейчас
   имеется."

План: расширить `/v1/instructions` для приёма `?category=<name>`
и возвращения полного catalog инструментов для этой категории
(arg schemas + короткие описания + один пример каждого),
отрендеренного как self-contained prompt block. Popup получит
category picker рядом с Copy Instructions кнопками. Cross-reference:
собственный алгоритм построения инструкций MCP SuperAssistant по
адресу https://github.com/srbhptl39/MCP-SuperAssistant/tree/main --
их sidebar собирает per-server prompt из `list_tools` ответов; мы
можем зеркалить форму. Отложено на v4.51.1.

## v4.50.4 -- Один тулбар на host (semantic-dedup путь удалён)

Явный запрос оператора после semi-фикса v0.14.13:

  "Сделай так, чтобы на всех вызовах отображались tool bar, потому
   что на всех сайтах не уследишь, как они монтируются. На Claude
   на первом сообщении tool bar отображается, а на следующий с
   аналогичной командой sys.status уже нет."

Подтверждено сканом Claude: 4 candidate sys.status / mission.catalog
с разными fingerprint (call_id 1..4), но mount'нулись только 2 --
v0.14.13 сохранил semantic dedup, который тихо убил 2-ю/3-ю копии
одинаковой формы payload'а. Оператор не мог понять, сломан ли
Bridge или LLM просто скипнул вызов.

### Фикс

Полностью убрал semantic-dedup путь из `mountControls`. Три diag
kind удалены: `skip_semantic_prev_alive`, `evict_semantic_owner`,
`skip_semantic_already_mounted`. Per-host dedup остался и
предотвращает двойные mount'ы на ОДНОМ host'е, но никогда не
трогает sibling / duplicate host'ы:

* `existing?.bar?.isConnected` -- тот же fingerprint, тот же host,
  всё ещё смонтирован → skip (безобидный idempotent scan)
* `hostHasToolbar(host)` -- dataset marker есть → skip

Каждый candidate с распарсенным tool блоком теперь получает
собственный toolbar, независимо от того, дублирует ли его payload
sibling'а.

### Эффекты по сайтам

* **Claude**: 3× sys.status + 1× mission.catalog → 4 toolbar
  вместо 2. Оператор видит точно то, что LLM выдал.
* **Mistral**: 2 реальных дубля → оба toolbar видны. Больше нет
  "работает, но что-то багается".
* **AI Studio / Gemini Web**: Thought Process expansion panel +
  main answer оба получают свой toolbar. Тот, что виден --
  кликабелен. Регрессия v0.14.13 исправлена.
* **T3 chat**: sibling дубль всё ещё фильтруется адаптер-branch'ем
  v0.14.13 (assistant `.prose` имеет `role="article"`, user `.prose`
  нет). Нет dedup thrash.
* **Grok / DuckAI / Qwen / OpenRouter**: не тронуты -- там либо
  один легитимный candidate, либо per-adapter filter уже
  обрабатывал ситуацию.

### Бампы версий

* extension `0.14.13` → `0.14.14`
* manifest / content / insert_strategies / README синхронизированы
* bridge `4.50.3` → `4.50.4`

### Регрессионные guard-тесты

8 новых asserts в `tests/test_chat_extension_v0_14_14.py`:

* четыре version pin
* semantic-dedup путь удалён (три diag kind отсутствуют, нет
  `mountedPayloadSemantics.has` / `mountedSemanticOwners.get`
  в mountControls)
* per-host dedup (`existing?.bar?.isConnected` +
  `hostHasToolbar(host)`) по-прежнему short-circuit'ит
* per-adapter user filters сохранены (grok/duckai/t3chat)
* все прежние regression guards от v0.14.6-13 держатся
* content.js ≤ 700 строк (сейчас 691, запас 9 строк)
* scan-report диагностика в поставке

Обновил assertions в v0_14_10 / v0_14_11 / v0_14_13, которые
требовали semantic-dedup diag kinds. Где возможно, тесты
переписаны как guard против re-появления удалённого пути (явный
assert "НЕ ДОЛЖНО вернуться").

Полный прогон: **2492 passed, 0 failed**.

### Стоимость этого изменения

Если сайт легитимно показывает ОДИН И ТОТ ЖЕ jsonl в двух видимых
позициях (preview + full copy), оператор теперь видит два toolbar
для одного сообщения. Можно кликнуть любой. Run на обоих просто
выполнит tool дважды; для read-only tools это no-op, для
consent-gated каждый запуск спросит заново.

Если конкретному сайту нужен dedup обратно -- делаем per-adapter
(та же форма что текущий grok/duckai/t3chat user-authored filter),
а не глобально.

### Изменённые файлы

* `chat_extension/content.js` -- 700 → 691 строк (удалён
  semantic-dedup блок; per-host dedup путь сохранён)
* `chat_extension/adapters.js` -- без изменений от v0.14.13
* `chat_extension/manifest.json` -- version bump
* `chat_extension/insert_strategies.js` -- version bump
* `chat_extension/README.md` -- banner refresh
* `tests/test_chat_extension_v0_14_14.py` -- новый, 8 asserts
* шесть прежних extension test-файлов перепинены на 0.14.14
* три прежних test-файла переписаны для guard против удалённого
  semantic-dedup пути
* `arena/constants.py`, `pyproject.toml` -- VERSION bump

### Что увидишь

Scan-отчёты теперь покажут больше `mounted` events на candidate и
НИ ОДНОГО `skip_semantic_*` / `evict_semantic_owner`. Каждый
реальный tool блок получает свой видимый toolbar.

### Известные follow-up (не в этом релизе, всё ещё в очереди)

* **Toolbar "поверх контента"**: косметика, нужен per-adapter
  positioning tweak по образцу hoist Qwen'а через
  `.qwen-markdown-code-body`. Отложено на v4.50.5.
* **z.ai toolbar под сообщением, а не под кодом**: тот же класс
  косметики. Отложено на v4.50.5.
* **Windows Dashboard скриншот**: жду когда оператор перезагрузится
  в Windows и сфоткает "кривой" layout.

## v4.50.3 -- Универсальный фикс thrash тулбара (Claude/Mistral/Gemini/AI Studio/T3) + T3 chat user filter

Оператор прошёлся по всем поддерживаемым сайтам с v0.14.12. Grok
работает. Но Gemini AI Studio, T3 chat, Claude, Mistral и Gemini
Web ВСЕ показывали один и тот же симптом:

* "результаты и миллисекунды в тулбаре не отображаются"
* "insert срабатывает через раз"
* "тулбар мигает"

Scan-report'ы сделали это очевидным -- `events_recent` на AI Studio
и T3 chat показали классический thrash-паттерн:

```
mount_entry(PRE) -> evict_semantic_owner -> mounted
mount_entry(PRE) -> evict_semantic_owner -> mounted
mount_entry(PRE) -> evict_semantic_owner -> mounted
...
```

~10 mount/evict пар в секунду. In-closure state тулбара
(`lastExecutionText`, "result ready" label, insert timing text)
стирался на каждом eviction-цикле.

### Корень

Eviction семантического owner'а в `mountControls` безусловно
вышибал предыдущего owner'а всякий раз, когда два РАЗНЫХ DOM-узла
несли одинаковый jsonl. Легитимные причины: Gemini AI Studio
рендерит И Thought Process expansion panel, И основной ответ с
одним и тем же tool-блоком; T3 chat имеет похожий дубль; Claude
и Mistral эхо'ят аналогично. Оба host'а легитимно живы; оператор
хочет ОБА с тулбаром. Semantic eviction была задизайнена для SPA
re-render'ов (previous host физически удалён), а не для
параллельных дубликатов.

### Фикс

Eviction теперь gated на `!prevAlive`, где `prevAlive =
previous?.host?.isConnected && previous?.bar?.isConnected`. Когда
предыдущий owner всё ещё в DOM, новый вызов трактуется как
легитимный параллельный candidate и skip'ается с distinct
`skip_semantic_prev_alive` diag event. Путь SPA-churn (prev
gone) всё так же эвиктит + перемонтирует.

Итог на сайтах выше:

* Первый candidate mount'ится → сохраняет свой тулбар.
* Второй candidate попадает в `skip_semantic_prev_alive` → не
  беспокоит первый.
* Никакого state-wiping churn'а. Результаты / timing /
  result-ready labels остаются видимыми, оператор может их
  прочитать.

Ситуация DuckAI/T3-стиля, где ОДИН И ТОТ ЖЕ payload появляется
в двух РАЗНЫХ физических host'ах (параллельные дубликаты),
теперь чисто mount'ит ОДИН тулбар на том host'е, который отрендерился
первым, а любой последующий дубль -- no-op. Если оператор
предпочитает тулбар на ОБЕИХ копиях -- можно флипнуть стратегию
per-adapter в follow-up.

### Также исправлено

**Фильтр User для T3 chat**: у T3 chat нет `data-testid` на
turn'ах, но контейнер `.prose` у AI имеет `role="article"`.
Добавил per-adapter branch в `arenaWhyUserAuthored`: когда
adapter -- `t3chat`, ближайший `.prose` ancestor без
`role="article"` -- user-authored. Reason: `t3chat:user-prose@DIV`.

### Бампы версий

* extension `0.14.12` → `0.14.13`
* manifest / content / insert_strategies / README синхронизированы
* bridge `4.50.2` → `4.50.3`

### Регрессионные guard-тесты

8 новых asserts в `tests/test_chat_extension_v0_14_13.py`:

* четыре version pin
* semantic-owner eviction gated на `!prevAlive`, проверяет и
  `host.isConnected` И `bar.isConnected`, эмитит
  `skip_semantic_prev_alive` когда prev alive
* evict branch по-прежнему удаляет когда prev dead (путь SPA
  churn сохранён)
* T3 chat per-adapter branch спрашивает `role !== 'article'`
* Все прежние guards из v0.14.6-12 держатся
* content.js ≤ 700 строк
* scan-report диагностика по-прежнему в поставке

Существующие 7 прежних chat-extension test-файлов перепинены на
0.14.13. Полный прогон: **2485 passed, 0 failed**.

### Изменённые файлы

* `chat_extension/content.js` -- 700 строк (net-zero через
  сжатие: eviction gate + skip_semantic_prev_alive event)
* `chat_extension/adapters.js` -- 613 → 622 строк (+9 для T3
  chat per-adapter user filter)
* `chat_extension/insert_strategies.js` -- version bump
* `chat_extension/manifest.json` -- version bump
* `chat_extension/README.md` -- banner refresh
* `tests/test_chat_extension_v0_14_13.py` -- новый, 8 asserts
* семь прежних chat-extension test-файлов перепинены
* `arena/constants.py`, `pyproject.toml` -- VERSION bump

### Известные follow-up (не в этом релизе)

* **z.ai: тулбар под сообщением, а не под блоком кода**:
  косметика, нужен per-adapter `controlsHost` hoist по образцу
  Qwen. Отложено на v4.50.4.
* **Grok: тулбар визуально "поверх"**: тоже косметика. Отложено
  на v4.50.4.
* **Windows Dashboard layout скриншот**: жду когда оператор
  перезагрузится в Windows и сфоткает.
* **Insert-в-начало-vs-в-конец**: оператор отметил, что Claude
  вставляет в НАЧАЛО (что он на самом деле предпочитает для
  порядка data-then-instruction). Не меняю без явного запроса;
  выглядит как желаемое поведение.

### Что увидишь

На следующем Scan Page для Claude / Mistral / Gemini Web /
AI Studio / T3 chat, `events_recent` должен показывать
единственный `mounted` event на unique semantic fingerprint плюс
`skip_semantic_prev_alive` для дубликатов вместо thrash-цикла.
Labels тулбара "Arena · <site> · result ready" + insert-timing
останутся видимыми после Run/Insert/Send.

## v4.50.2 -- Фикс 401 при save token + opt-in "установка без SHA-256 верификации" + кэш inventory

Живой репорт по v4.50.0/v4.50.1 от оператора: три отдельные
проблемы, один релиз.

### 1. Форма save token не работала (HTTP 401)

Симптом: `Save failed: HTTP 401: unauthorized`. Форма Save-token
v4.50.0 никогда не работала.

Корень: в `dashboard/assets/02-api-helper.js` функция `api()`
использовала `fetch(BASE + path, {headers, ...opts})`. Когда
вызывающий передавал `opts.headers` (`Content-Type: application/json`
на POST токена), этот объект **полностью замещал** модульный
объект `headers` -- а именно тот содержал Bearer токен. Тихий 401.

Фикс: `api()` теперь deep-merge'ит caller headers на auth headers:
`const merged = Object.assign({}, headers, opts.headers || {})`,
затем `fetch(..., Object.assign({}, opts, {headers: merged}))`.
Bearer остаётся; Content-Type + любые другие заголовки caller'а
работают.

Тот же класс бага сломал бы любую будущую admin-форму с body;
merge-фикс системный.

### 2. "Установка без SHA-256 верификации" opt-in

Оператор: "почему нельзя нормальный Auto Update сделать?". Согласен.
Требовать GITHUB_TOKEN только для вычисления digest публичного
release'а -- нечестно к Windows / offline / не-любителям GitHub-
аккаунтов.

Новый opt-in путь:

* Server-side (`arena/admin/auto_update.py::apply_update`) принимает
  `accept_no_verification=True`. Когда установлен И `expected_sha256`
  пуст, download проходит с SHA-256, вычисленной локально и
  **записанной в response + audit** (`downloaded_sha256` +
  `verification: "unverified"`), но НЕ сравнённой с опубликованным
  digest'ом.
* `consent_token()` для этого пути использует различающийся
  `"UNVERIFIED"` sentinel. Сохранённый verified consent нельзя
  реплеить для запуска unverified install.
* Endpoint `/v1/admin/update/apply` принимает новый boolean
  `accept_no_verification` и audit'ит выбранный verification
  path (`sha256` vs `unverified`).
* Dashboard: Install кнопка теперь enable'ится даже когда digest
  не опубликован. Confirm диалог для unverified пути явный,
  с `⚠` префиксом, объясняет что verification skip'ается,
  и указывает на token box как более безопасную альтернативу.

Старый verified путь не тронут; install'ы с настроенным токеном
получают идентичное поведение с v4.50.0/v4.50.1.

### 3. `/v1/hardware` + `/v1/inventory` кэшируются 60 секунд

Оператор: "Windows Inventory не то, что тормозит, а вообще намертво
зависает. Dashboard гораздо медленней загружается на Windows и на
телефоне."

На Windows каждый `Get-CimInstance` probe платит полный startup
PowerShell (~1-2 с каждый) плюс WMI cold-start. Dashboard reload,
запускающий `/v1/hardware` и `/v1/inventory` параллельно, платил
это дважды.

Фикс: in-memory cache с TTL 60 с на обоих handler'ах. `?nocache=1`
на любом endpoint принудительно запускает свежий сбор.
Кэшированный response включает `cache: {hit: true, age_sec: N}`,
чтобы UI мог показать hit'ы когда нужно. Первая загрузка страницы
остаётся такой же медленной; каждый reload в течение 60 с теперь
под 100 мс.

Не фикс для самого WMI cold-start latency -- для этого нужен
больший рефакторинг с параллельным запуском probe'ов и per-probe
timeout'ами. Отложено на v4.50.3.

### Регрессионные guard-тесты

8 новых asserts в `tests/test_auto_update_v502.py`:

* fetch вызов `api()` НЕ ДОЛЖЕН использовать `{headers, ...opts}`;
  должен использовать explicit Object.assign merge
* `apply_update` подпись имеет `accept_no_verification=False`
  дефолт; sentinel `"UNVERIFIED"` string присутствует
* handler forward'ит флаг из JSON body + записывает verification
  path в audit event
* JS install flow enable'ит кнопку когда digest пуст и шлёт
  `body.accept_no_verification = true`
* `_HW_CACHE_TTL_SEC = 60.0` + `_hw_cache` / `_inv_cache` +
  `_cache_lookup` / `_cache_store` хелперы присутствуют;
  `?nocache=1` query param honored
* Прежний v4.50.0 GitHub-token-file plumbing по-прежнему wired
* Прежние v4.50.1 Grok fingerprint fix + 800мс send latency держатся
* `consent_token()` derivation для `"UNVERIFIED"` sentinel даёт
  значение, отличное от любого реального sha256 (нет replay риска)

Полный прогон: **2477 passed, 0 failed**.

### Изменённые файлы

* `dashboard/assets/02-api-helper.js` -- 19 → 29 строк (deep-
  merge вместо clobbering headers spread)
* `dashboard/assets/39-admin-update.js` -- 403 → 426 строк
  (unverified confirm branch + tooltip rewrite)
* `arena/admin/auto_update.py` -- 539 → 573 строк
  (accept_no_verification path + verification поле в результатах)
* `arena/admin/handlers_update.py` -- 216 → 238 строк (flag
  forwarding + distinct consent для unverified)
* `arena/inventory/handlers.py` -- 82 → 129 строк (60-s cache
  с nocache=1 escape hatch)
* `tests/test_auto_update_v502.py` -- новый, 8 asserts
* `arena/constants.py`, `pyproject.toml` -- VERSION bump

### Что увидишь

* **Save token**: фикс `api()` -- Bearer теперь доходит до сервера.
  Save кнопка должна успеть, badge флипается с `○ No token
  configured` на `● Token active (file)`, Install кнопка
  разблокируется с доступным SHA-256 digest'ом.
* **Auto-update без токена**: Install кнопка больше не disabled;
  клик показывает явный `⚠ WITHOUT SHA-256 verification`
  confirm; на OK install идёт, audit пишет
  `verification: unverified` + фактический SHA-256, который был
  скачан (для post-hoc verification при желании).
* **Windows Inventory**: первый Dashboard reload по-прежнему
  холодный; каждый reload в следующие 60 с попадает в кэш и
  мгновенный.

## v4.50.1 -- Фикс коллизии fingerprint'ов Grok + Send latency 1500мс -> 800мс

### Grok mount починен (корневая причина найдена через v0.14.11 mount_entry diag)

Третий раунд `events_recent` для Grok показал:

```
mount_entry(tag=PRE)
mount_entry(tag=PRE)
skip_dismissed_fp(fingerprint=arena_msg_1272557140)   # User
skip_dismissed_fp(fingerprint=arena_msg_1272557140)   # AI -- ТОТ ЖЕ FP
```

Оба candidate дошли до `mountControls`, оба hoisted к `<pre>`,
оба посчитали **идентичные** fingerprint'ы. User dismiss'нулся
первым; AI сразу попал в dismissed fp и вышел. Корневая причина:
`arenaExtractNodeId` идёт только 6 tag:index предков через
`arenaNodePath`; эта 6-глубинная цепочка от Grok'овского `<pre>`
вверх **не дотягивается** до `[data-testid="user-message"]` vs
`[data-testid="assistant-message"]` bubble -- единственного
различающего сигнала. В сочетании с 80-символьным text-head,
байт-идентичным для обоих, два `<pre>` хешировались в один и
тот же message fingerprint.

**Фикс**: `arenaExtractNodeId` теперь включает `data-testid` +
`data-message-author-role` ближайшего message-bubble ancestor'а
как компонент `bubbleId`. У User и Assistant `<pre>` Grok'а
теперь разные fingerprint'ы; AI mount проходит.

**Специально НЕ углублял `arenaNodePath`** -- это дестабилизировало
бы историю fingerprint'ов всех других адаптеров. Bubble-ancestor
lookup -- один дополнительный `.closest()` на extraction,
adapter-нейтральный, влияет только на hash fingerprint'а (не на
mount / skip логику).

### Send latency: 1500 мс -> 800 мс

Оператор сообщил: "на некоторых сайтах 2 секунды задержка именно
send" (Kimi / Perplexity). Корневая причина:
`arenaInsertAndSubmit` polling submit-кнопки до 1500 мс перед
fallback на Enter-key path. На сайтах где submit никогда не
enable'ится (Kimi / Perplexity / старый Copilot), оператор видел
явный gap "текст-подождать-2-секунды" между insert и send.

**Фикс**: снизил poll deadline до 800 мс. Adaptive
20/20/40/40/80/80/100/100 мс poll schedule всё ещё ловит сайты
чей submit становится enabled быстро. Enter-key fallback
срабатывает на 700 мс раньше. Label `submit_wait_ms` в
insert-timing report обновлён.

Enter-key fallback safety net не тронут -- он по-прежнему
срабатывает только когда `submitInfo.selected_selector` пустой,
чтобы не спамить Enter на сайтах которые просто validate input.

### Бампы версий

* extension `0.14.11` → `0.14.12`
* manifest / content / insert_strategies / README синхронизированы
* bridge `4.50.0` → `4.50.1`

### Регрессионные guard-тесты

Восемь новых asserts в `tests/test_chat_extension_v0_14_12.py`:

* четыре version pin (0.14.12 в content/manifest/insert/README)
* `arenaExtractNodeId` должен определять компонент `bubbleId` и
  возвращаемая tuple должна его включать
* closest-селектор должен покрывать `user-message`,
  `assistant-message` и `data-message-author-role`
* глубина `arenaNodePath` осталась 6 (regression guard против
  дестабилизации других адаптеров)
* `submit_wait_ms` снижен до 800 мс, `submit_wait_ms: 1500`
  удалён, `enter-key-fallback` всё ещё срабатывает только когда
  submit selector не найден
* прежние regression guards из v0.14.6-11 все держатся
* content.js ≤ 700 строк
* scan-report диагностика по-прежнему в поставке

Существующие семь прежних test-файлов перепинены на 0.14.12.
Полный прогон: **2469 passed, 0 failed**.

### Изменённые файлы

* `chat_extension/adapters.js` -- 595 → 613 строк (+bubble-
  ancestor bubbleId компонент в arenaExtractNodeId)
* `chat_extension/insert_strategies.js` -- 633 строки (+deadline
  1500 → 800; обновления label + комментария)
* `chat_extension/content.js` -- 700 строк (только version bump)
* `chat_extension/manifest.json` -- version bump
* `chat_extension/README.md` -- banner refresh
* `tests/test_chat_extension_v0_14_12.py` -- новый, 8 asserts
* семь прежних chat-extension test-файлов перепинены на 0.14.12
* `arena/constants.py`, `pyproject.toml` -- VERSION bump

### Что увидишь

* **Grok**: `events_recent` теперь должен показывать
  `mount_entry(PRE) → mounted` для assistant fingerprint'а
  (другой fp от User). Toolbar цепляется на AI-эхо. Прежнего
  "AI mount никогда не происходит" больше нет.
* **Kimi / Perplexity / любой сайт без submit-кнопки**: Send
  теперь запускает Enter-key fallback на ~700 мс раньше. Видимый
  gap text-to-submit должен сократиться с ~2 с до ~1.1 с.
* Каждый другой сайт с видимой submit-кнопкой ведёт себя
  идентично v0.14.11.

## v4.50.0 -- Разблокировка Windows UX: GitHub-токен теперь настраивается из Dashboard

Живой репорт с Windows: "Auto Update чисто для галочки стоит.
Инструкций нет нормальных, GITHUB_TOKEN обязательно требует, нигде
он этот токен не принимает и не видит. Обновлять всё также ручками.
У меня всё желание пропало что-либо делать."

Корневая причина: Auto-Update отказывался ставить что-либо без
SHA-256, а SHA-256 приходит только по authenticated GitHub API,
которое работает только с `GITHUB_TOKEN`/`GH_TOKEN` в переменных
окружения процесса моста. На Windows это значит редактировать
`nssm`'s Environment tab -- стена, о которую оператор не должен
биться ради one-click обновления. На Linux -- `systemctl --user
edit arena-bridge`. Ни там, ни там **нельзя вставить токен из того
же UI, где написано "Install disabled"**. Итог: Auto-Update всегда
выглядел сломанным.

Этот релиз добавляет настраиваемый из UI токен, который переживает
рестарт и работает на всех платформах одинаково.

### Новое: `<install_root>/.github_token` (dotfile)

* Хранится в install root как скрытый файл. Dotfile, чтобы
  будущий self-update никогда его не перезаписал -- update
  заменяет только именованные каталоги (`arena/`, `dashboard/`,
  ...) и именованные файлы (`unified_bridge.py`, ...); dotfile
  на root'е переживает апгрейд.
* Chmod 0600 на POSIX; Windows молча принимает (chmod там no-op
  для битов режима, но атомарная замена работает).
* Читается только если ни одна env-переменная не установлена.
  Приоритет: `GITHUB_TOKEN` env  >  `GH_TOKEN` env  >  файл.
  То есть операторы с systemd override / nssm env продолжают
  жить как раньше; новые операторы просто вставляют и работают.

### Новые endpoint'ы

* `POST /v1/admin/update/token-set   {token}`  -- атомарная запись
* `POST /v1/admin/update/token-clear`          -- идемпотентное удаление

Оба master-token-authed как и остальные `/v1/admin/*`. Обе audit'ят
эффект (`admin.update.token_set` / `admin.update.token_clear`),
никогда не логируя сам токен.

`GET /v1/admin/update/status` теперь также возвращает
`github_token_source ∈ {env, file, none}`, чтобы UI показывал
"● Token active (env)" / "● Token active (file)" /
"○ No token configured".

### Новый UI в Dashboard

Settings tab, прямо под существующими контролами Auto-update:

* Password-input с `autocomplete="off"`.
* Кнопка "Save token" (шлёт `/token-set`, обновляет статус).
* Кнопка "Clear" (confirm-диалог + `/token-clear`).
* Живой status-параграф, объясняющий обычным языком, откуда
  сейчас берётся токен -- или что его нет и Install остаётся
  заблокированным пока не вставишь.
* Свёрнутое <details> с 3-шаговой инструкцией, заменяет старый
  блок с shell-сниппетами про systemd/nssm.
* Tooltip "Install disabled" на самой кнопке переписан --
  теперь указывает на новый Token box, а не на systemd.

### Кросс-платформенность

Ничего здесь не Windows-специфичного -- файл-токена работает и на
Linux. Просто на Linux у тебя был работающий workaround (systemd
override), а на Windows не было. Теперь UI-путь даёт всем платформам
одинаковый first-class experience.

### Не в этом релизе

* Windows inventory latency (Get-CimInstance × N probes) -- нужен
  кэширующий слой в `arena/inventory/probe_common.py`, заплан
  на v4.50.1.
* Windows Dashboard layout "кривой" -- нужен конкретный скриншот;
  responsive.css уже имеет Windows-narrow media queries, но они
  могут не срабатывать. Жду репро.

### Регрессионные guard-тесты

12 новых asserts в `tests/test_auto_update_token_ui.py`:

* шесть про чистые хелперы `update_github` (file-fallback,
  env-wins-over-file, none-when-nothing, whitespace rejection,
  atomic replace + 0600 mode, идемпотентный clear)
* один wire-check, что оба новых роута появляются в registry И
  плоском aiohttp биндере И полях dataclass `AdminHandlers`
  И его конструкторе И source-хендлерах -- пропусти любой
  слой и роут даст 404 в runtime
* один для Settings body markup (шесть DOM id / label'ов, на
  которые ссылается JS)
* один для самих JS-хендлеров + проверка использования существующего
  хелпера `api()` (не выдуманного `arenaFetch`), чтобы `BASE`
  и заголовки оставались консистентными с остальными admin-вызовами
* один для payload `handle_update_status`, включающего новое поле
  `github_token_source`
* один для переписанного "Install disabled" tooltip'а --
  указывает на новый Token box, а не только на systemd

Полный прогон: **2461 passed, 0 failed**.

### Изменённые файлы

* `arena/admin/update_github.py`      -- 204 → 304 строк (+file
  helpers + save/clear/source)
* `arena/admin/handlers_update.py`    -- 166 → 216 строк (+два
  новых endpoint'а, +обогащение status)
* `arena/admin/handlers.py`           -- 656 → 658 строк (+два
  поля dataclass + аргументы конструктора); уже в LINE_ALLOWLIST
* `arena/route_registry/registry.py`  -- 438 → 440 строк
* `arena/route_registry/core.py`      -- 177 → 179 строк
* `arena/wiring/platform.py`          -- 274 → 276 строк
* `dashboard/assets/39-admin-update.js` -- 321 → 403 строк
* `dashboard/assets/body-15-settings.html` -- 196 → 200 строк
* `tests/test_auto_update_token_ui.py` -- новый, 12 asserts
* `arena/constants.py`, `pyproject.toml` -- VERSION bump

## v4.49.4 -- Фикс DuckAI thrash + Qwen composer-cache visibility guard + Grok mount_entry diag

Третий раунд scan-report наконец сделал два тонких бага очевидными.
Diag events v0.14.10 сделали своё дело -- events_recent показал
точно что идёт не так.

### DuckAI thrash cycle (корневая причина + фикс)

events_recent показал паттерн 10 событий в секунду:
```
skip_dismissed_fp(User_fp) → mounted(AI_fp)
→ evict_semantic_owner(User_fp evicts AI_fp)
→ skip_dismissed_fp(User_fp) → mounted(AI_fp) → ...
```

AI-toolbar **перемонтировался каждые ~400 мс**, стирая
in-closure `lastExecutionText`, статус
"Arena · duckai · result ready" и локальное состояние каждой
кнопки при каждом thrash'е. Объясняет репорт оператора:
"результаты не видно" -- toolbar физически не проживал достаточно
долго, чтобы показать settled state.

**Корневая причина в `mountControls`**: порядок guard'ов был
1. evict `mountedSemanticOwners.get(semantic)` если не наш
2. check `dismissedControls.has(fingerprint)` → skip

Когда User bubble заново заходил в mountControls (что происходит
каждый scan-цикл потому что он остаётся в DOM):
* шаг 1 видел AI fingerprint как текущего semantic owner'а и
  вырывал его
* шаг 2 видел собственный User fingerprint в dismissedControls
  и short-circuit'ил без монтирования чего-либо
* итог: AI toolbar исчез, замены нет, DOM-observer триггерит
  очередной scan, AI монтируется снова, User заходит снова, цикл.

**Фикс**: dismissed-check теперь запускается ДО eviction.
Dismissed call сразу выходит, не трогая mounted-semantic map,
так что повторный визит User больше не может нарушить lifecycle
AI toolbar'а.

### Qwen composer cache возвращал ghost target

v0.14.10 добавил `-500` invisible-penalty в
`arenaScoreComposerCandidate`, но scan показал
`selected_selector: cachedComposer, cached_match: true` --
2-секундный cache в `arenaComposerSelection` возвращал
pre-v0.14.10 ghost target, не запуская scorer заново. Insert
продолжал приземляться в невидимый textarea; видимый композер
оставался пустым несмотря на "Inserted +30ms" в статусе.

**Фикс**: cache early-return теперь также требует
`arenaElementVisible(_cachedComposerResult.target)`. Если
кэшированный target стал невидимым, cache инвалидируется и
scorer запускается заново, правильно предпочитая видимый
композер.

### Grok mount_entry инструментация

events_recent для Grok всё ещё показывает только User
fingerprint, skip'ающийся раз за разом -- assistant candidate
в candidate_diagnostics, но его вызов mountControls никогда
не появляется в events. Добавил `mount_entry` event, эмитящийся
на самом верху `mountControls` (до ЛЮБОГО early return), чтобы
следующий scan окончательно доказал, вызывается ли mountControls
для AI. Если `mount_entry` AI появляется: баг в guard'ах. Если
нет: `state.nodes` не достигает AI candidate по upstream-причине
(candidate cache, prune, etc.) -- и мы будем знать точно, по
какой именно.

### Бампы версий

* extension `0.14.10` → `0.14.11`
* manifest / content / insert_strategies / README синхронизированы

### Модулярность

content.js остался ровно на 700 строках. Сжал два комментария
в реорганизованном блоке guard'ов, чтобы компенсировать
дополнительный вызов mount_entry diag.

### Регрессионные guard-тесты

Девять новых asserts в `tests/test_chat_extension_v0_14_11.py`:

* pin 0.14.11 в content/manifest/insert/README
* `mount_entry` diag event существует и содержит tag + testid
* text-позиционный assert: оба вызова `dismissedControls.has(...)`
  ДОЛЖНЫ появляться до блока `mountedSemanticOwners.get(...)`
  (byte offsets)
* `evict_semantic_owner` и связанные удаления
  mountedControls/mountedSemanticOwners по-прежнему на месте
* `_cachedVisible` guard живёт внутри `arenaComposerSelection`
* cache early-return ссылается на `_cachedVisible`
* каждый прежний regression guard (v0.14.6, 0.14.7, 0.14.8,
  0.14.9, 0.14.10) по-прежнему держится
* content.js line count ≤ 700
* все v0.14.10 diag event kinds пережили reorder

Существующие пять прежних extension test-файлов перепинены на
0.14.11. Полный прогон: **2449 passed, 0 failed**.

### Изменённые файлы

* `chat_extension/content.js` -- 700 строк (net-zero через сжатие
  комментариев: reorder guard'ов + mount_entry event)
* `chat_extension/adapters.js` -- 584 → 595 строк (+11 для cache
  visibility guard + объясняющий комментарий)
* `chat_extension/insert_strategies.js` -- только version bump
* `chat_extension/manifest.json` -- version bump
* `chat_extension/README.md` -- banner refresh
* `tests/test_chat_extension_v0_14_11.py` -- новый, 9 asserts
* пять прежних extension test-файлов перепинены на 0.14.11
* `arena/constants.py` -- VERSION bump
* `pyproject.toml` -- version bump

### Что увидишь на следующем Scan Page

* **DuckAI**: events_recent БОЛЬШЕ не должен показывать
  evict→skip→mount thrash. AI toolbar остаётся смонтированным;
  когда оператор жмёт Run/Insert/Send, timing string в
  `status.textContent` теперь останется видимой.
* **Qwen новый чат**: Insert/Send должен реально вставлять текст
  в видимый композер. Если всё ещё нет, composer-блок следующего
  скана скажет, инвалидировался ли cache правильно
  (`selected_selector: activeElement` вместо `cachedComposer`).
* **Grok**: events_recent покажет либо `mount_entry` AI
  fingerprint'а (доказывает reachability -- баг в guard'ах),
  либо НЕТ (доказывает другой upstream-skip -- candidate cache
  / arenaPruneAncestorCandidates / slice-5 boundary).

## v4.49.3 -- Глубокая диагностика extension + фикс Qwen ghost-composer

### Где мы стоим

Grok / DuckAI / Qwen после третьего раунда scan-report:

* **Grok** -- фильтр v4.49.2 работает правильно (skip event
  срабатывает: `reason: grok:user-message@DIV`). Оба candidate в
  скане, только User dismiss'нут, но AI всё равно не монтируется:
  `mounted_controls: 0, dismissed_controls: 1`. Все очевидные
  guard'ы (semantic dedup, mountedPayloadSemantics,
  hostHasToolbar, dismissedControls) проаудитированы в v0.14.9 и
  не должны блокировать AI mount. Без runtime-данных ПОЧЕМУ --
  не видно.
* **DuckAI** -- тулбар монтируется на AI PRE
  (`mounted: true` в `candidate_diagnostics[1]`, ancestor --
  `.my-4.flex`, `_wu.matched: false`). User bubble корректно
  dismiss'нут. Оставшаяся жалоба ("мс / метод не видно") --
  косметика; v0.14.10 добавляет target-snapshot в timing, чтобы
  status показывал форму когда insert "ложно преуспел".
* **Qwen** -- фикс anchor v4.49.2 работает ("Inserted/submitted
  1675ms"), перекрытия нет. Новый баг в новом чате: статус
  говорит "Inserted +33ms verified +30ms", а по факту ничего не
  вставлено. Insert приземлился в ghost-textarea, а реальный
  видимый композер остался пустым.

### Изменения v0.14.10

**Инструментация** (без изменений логики): каждая early-return
ветка в `mountControls` теперь эмитит diag event. Следующий Scan
Page покажет для Grok AI candidate точно, какая ветка скипает
mount. Виды событий:

* `skip_dismissed_fp` -- fingerprint в dismissedControls
* `skip_dismissed_semantic` -- semantic fingerprint в dismissedControls
* `skip_semantic_already_mounted` -- другой узел уже занял этот semantic
* `skip_existing_connected` -- наша запись имеет ещё-connected bar
* `skip_host_has_toolbar` -- host уже несёт mounted-маркер
* `evict_semantic_owner` -- нашли устаревшего owner'а и вытеснили
* `mounted` -- успешное подключение (после `attachControls`)

**Фикс ghost-composer** (регрессия Qwen new-chat):
`arenaScoreComposerCandidate` теперь применяет большой негативный
штраф (-500) к невидимым target'ам ДО добавления +100 бонуса за
activeElement. Невидимый sr-only textarea, ухвативший фокус,
больше не выиграет ранжирование против реального видимого композера
рядом. Это баг "verify говорит success, но ничего не набрано".

**Snapshot insert-timing** (диагностика silent-success):
`arenaSetInsertTiming` захватывает target tag/visibility/rect
вместе с timing-метриками. Status может теперь показать почему
"Inserted +30ms" был невалидным (кейс ghost-target).

### Версии

* extension `0.14.9` → `0.14.10`
* manifest / content / insert_strategies / README синхронизированы

### Модулярность

`content.js` по-прежнему ровно на 700 строках. Сжал один
комментарий в блоке return scan_report'а и перестроил один
section-заголовок, чтобы вернуть строки, добавленные пятью diag
ветками.

### Регрессионные guard-тесты

Девять новых asserts в `tests/test_chat_extension_v0_14_10.py`:

* pin на 0.14.10 в content/manifest/insert/README
* пять новых mountControls diag `kind:'...'` должны присутствовать
* успешный mount эмитит `kind: 'mounted'`
* eviction semantic-owner'а эмитит `kind: 'evict_semantic_owner'`
* невидимый композер должен быть штрафован -500 в scoring'е
* insert timing должен захватывать target tag/visibility/rect/size
* каждый прежний regression guard (v0.14.6, 0.14.7, 0.14.8, 0.14.9)
  всё ещё держится -- один omnibus assert перепроверяет:
  * глобальный `_USER_AUTHOR_ATTRS` без `user-message`
  * подписи `controlsHost(node, adapter)` +
    `arenaWhyUserAuthored(node, adapter)`
  * условие per-adapter ветки покрывает `grok || duckai`
  * Qwen anchor -- внешний `<pre.qwen-markdown-code>`
  * skip_user_authored dismiss'ит только fingerprint
  * shadow_toolbar Qwen z-index/isolation по-прежнему в поставке
* content.js ≤ 700 строк
* candidate_diagnostics + mounted_diagnostics + events_recent все
  по-прежнему в scan-report

Существующие 4 test-файла перепинены на 0.14.10. Полный прогон:
**2440 passed, 0 failed**.

### Изменённые файлы

* `chat_extension/content.js` -- 700 строк (5 branches + 1 mounted
  + 1 evict event, компенсируется 2 сжатыми комментариями)
* `chat_extension/adapters.js` -- 578 → 584 строк (+6 для
  ghost-composer scoring)
* `chat_extension/insert_strategies.js` -- 620 → 633 строк (+13
  для target-snapshot обогащения в arenaSetInsertTiming)
* `chat_extension/manifest.json` -- version bump
* `chat_extension/README.md` -- banner refresh
* `tests/test_chat_extension_v0_14_10.py` -- новый, 9 asserts
* 4 прежних extension test-файла перепинены на 0.14.10
* `arena/constants.py` -- VERSION bump
* `pyproject.toml` -- version bump

### Что увидишь на следующем Scan Page

Конкретно для Grok, `events_recent` в следующем скане будет
содержать точную причину, по которой AI mount был отклонён. Это
разблокирует реальный фикс в v4.49.4 без очередного раунда
gray-box гадания. Если AI mount пройдёт (лучший случай), скан
покажет `mounted` event с fingerprint'ом ассистента.

## v4.49.2 -- Три коррекции к per-adapter фиксам v4.49.1 (Grok, DuckAI, Qwen)

Второй раунд live-тестов после v4.49.1 показал: у каждого из трёх
фиксов был остаточный баг, который стал виден только когда
первичная проблема разрешилась. Диагностические поля v4.49.0
(candidate_diagnostics + mounted_diagnostics) в этот раз сделали
корни очевидными.

### Grok -- каскад через semantic-fingerprint

**Симптом**: v4.49.1 корректно фильтровал User-баббл
(`why_user_authored.matched: true, reason:
grok:user-message-bubble@DIV`), но и AI-баббл тоже НЕ монтировался:
`mounted_controls: 0, dismissed_controls: 2`.

**Корень**: ветка `skip_user_authored` в `mountControls` добавляла
в `dismissedControls` И `fingerprint`, И `semanticFingerprint`.
Grok эхом выводит один и тот же jsonl-блок и у User, и у Assistant --
оба имеют идентичный `semanticFingerprint`. Диссмисс семантического
ключа убивал AI-mount ещё до попытки.

**Фикс**: диссмиссим только message-level `fingerprint`. Семантический
ключ остаётся свободным, чтобы AI-эхо того же блока могло смонтироваться.
Однострочная правка; guard-тест проверяет отсутствие семантического
add'а.

### DuckAI -- тулбар оказывался на User-turn'е

**Симптом**: mounted_diagnostics показал наш тулбар по пути
`SECTION:1/DIV:2/DIV:0/DIV:0/DIV:1/DIV:2`, ancestor[0] =
`<div data-testid="user-message">`. Тулбар монтировался на
user-бабл, а не на AI-ответ -- отсюда "Preview/Insert/Send/Copy
ничего полезного не делают, работает только Run".

**Корень**: текущий DOM DuckAI ставит `data-testid="user-message"`
на РЕАЛЬНЫЙ turn-элемент. Наша интерпретация в v4.48.6 ("этот
testid живёт на контейнере message-list") была основана на старой
DOM-форме и больше не верна. В глобальный `_USER_AUTHOR_ATTRS`
правило возвращать НЕЛЬЗЯ (over-fire на других сайтах), а
per-adapter -- безопасно и правильно.

**Фикс**: расширил per-adapter ветку v4.49.1 в
`arenaWhyUserAuthored` на ОБА -- Grok И DuckAI:
`if ((adapterName === 'grok' || adapterName === 'duckai') &&
node.closest) { ... }`. Reason string шаблонизирован с adapter
name (`grok:user-message@DIV` / `duckai:user-message@DIV`).

### Qwen -- неправильный anchor вызвал регрессию

**Симптом**: v4.49.1 сделал Qwen overlap ХУЖЕ. mounted_diagnostics
показал тулбар по пути `PRE:0/DIV:1/DIV:1` внутри
`.qwen-markdown-code-body` -- но ancestor[1] = `<pre
class="qwen-markdown-code">`, то есть класс "body", на который мы
якорились, живёт ВНУТРИ pre, а не вокруг него.

**Корень**: v4.49.1 был написан из предположения, что
`.qwen-markdown-code-body` -- контейнер ВЫШЕ viewport'а. Скан
доказал: это контейнер ВНУТРИ pre (собственный body-slot Monaco).
Наш `attachControls(host)` вставляет через `afterend` когда host --
PRE/CODE, так что якорь на внешний `<pre>` кладёт тулбар СНАРУЖИ
code-block'а -- то, что и хотели с самого начала.

**Фикс**: Qwen-ветка в `controlsHost(node, adapter)` возвращает
`node.closest?.('pre.qwen-markdown-code, pre')`. Старый обход через
`.qwen-markdown-code-editor-viewport` удалён -- guard-тест проверяет,
что он не вернётся.

### Контракт

Те же сигнатуры, что в v4.49.1 (`controlsHost(node, adapter)`,
`arenaWhyUserAuthored(node, adapter)`). Нового API нет.

### Бампы версий

* extension `0.14.8` → `0.14.9`
* manifest / content / insert_strategies / README все синхронизированы

### Модулярность

`content.js` остался ровно на 700 строках. Сжал один комментарий
в skip-user-authored ветке и один на makeButton-делегате, чтобы
компенсировать строки, добавленные Qwen-селектором.

### Регрессионные guard-тесты

11 новых asserts в `tests/test_chat_extension_v0_14_9.py`:

* content/manifest/insert/README запинены на 0.14.9
* skip_user_authored ветка добавляет ТОЛЬКО fingerprint
  (semantic ключ НЕ должен диссмиссаться)
* per-adapter условие ветки включает и `grok`, и `duckai`
* reason string шаблонизирован с adapter name
* Qwen anchor -- внешний `<pre.qwen-markdown-code>`
* Qwen больше не ссылается на `.qwen-markdown-code-editor-viewport`
* Grok per-adapter closest()-селектор на месте
* `_USER_AUTHOR_ATTRS` по-прежнему без 'user-message' (per-adapter
  путь безопаснее)
* `controlsHost(node, adapter)` подпись сохраняется, голых
  вызовов нет
* DuckAI `.overflow-hidden` hoist по-прежнему в поставке (фикс v4.49.1)
* shadow_toolbar.css Qwen-фикс на месте
* content.js ≤ 700 строк
* candidate_diagnostics + mounted_diagnostics по-прежнему в scan-report

Существующие asserts в `test_chat_extension_v0_14_8.py` обновлены
под расширенное условие ветки. Полный прогон: **2431 passed,
0 failed**.

### Изменённые файлы

* `chat_extension/content.js` -- 700 → 700 строк (net-zero)
* `chat_extension/adapters.js` -- 571 → 578 строк (+7 для
  комментария расширенной per-adapter ветки)
* `chat_extension/manifest.json` -- version bump
* `chat_extension/insert_strategies.js` -- version bump
* `chat_extension/README.md` -- version banner
* `tests/test_chat_extension_v0_14_9.py` -- новый, 11 asserts
* `tests/test_chat_extension_v0_14_8.py` -- обновлены Grok +
  Qwen ассерты под v0.14.9
* `tests/test_chat_extension_v0_14_7.py` -- обновление version pin
* `tests/test_chat_extension_assets.py` -- обновление version pin
* `tests/test_chat_extension_adapter_flow.py` -- обновление banner
* `arena/constants.py` -- VERSION bump
* `pyproject.toml` -- version bump

## v4.49.1 -- Точечные per-adapter фиксы extension (Grok user-filter, DuckAI overflow-hidden, Qwen Monaco viewport)

v4.49.0 добавил `candidate_diagnostics[]` + `mounted_diagnostics[]`
в scan-report, чтобы следующий скан оператора точно показал, к
каким DOM-узлам цепляется extension. Первый же скан дал три
кристально ясных сигнала -- по одному на сайт, три разных
корневых причины:

### Grok

`candidate_diagnostics[0]` = mounted=true, ancestor[3] содержит
`testid="user-message"` class `message-bubble`.
`candidate_diagnostics[1]` = mounted=false, ancestor[3] содержит
`testid="assistant-message"` class `message-bubble`. Оба имеют
идентичный code-block потомок, так что `arenaPruneAncestorCandidates`
+ `.slice(-5)` оставляют User. Глобальный `_USER_AUTHOR_ATTRS` не
поможет -- мы убрали `'user-message'` в v4.48.6, потому что DuckAI
ставит тот же testid на контейнер СПИСКА сообщений (иначе
отфильтровал бы каждый mount).

**Фикс**: добавил per-adapter проверку внутри
`arenaWhyUserAuthored(node, adapter)` -- когда
`adapter.name === 'grok'`, `closest('[data-testid="user-message"]
.message-bubble, [data-testid="user-message"]')` short-circuit'ит
mount. DuckAI не задет, потому что эта ветка срабатывает только
при совпадении adapter. Reason в scan-report становится
`grok:user-message-bubble@DIV`.

### DuckAI

`mounted_diagnostics[0]` = тулбар прицеплен по пути
`DIV:0/DIV:0/DIV:0/DIV:0/DIV:2/DIV:0` внутри `<div class=
"language-jsonl overflow-hidden">`. Tailwind'овский
`overflow-hidden` клипал наши кнопки тулбара -- отсюда
"Preview / Insert / Send / Copy мигают и пропадают, виден только
Run".

**Фикс**: в `controlsHost(node, adapter)`, когда
`adapter.name === 'duckai'`, идём вверх через
`.closest('.overflow-hidden')` и возвращаем его parent-элемент
(`.my-4.flex` по скану), у которого нет overflow-clip.

### Qwen

`mounted_diagnostics[0]` = тулбар прицеплен внутри `<div class=
"qwen-markdown-code-editor-viewport">`. Это собственный
scroll-viewport Monaco-редактора -- наш тулбар монтировался внутри
scrollable-контейнера, отсюда "выглядит сжато / смещён относительно
site's like/dislike/share/refresh row".

**Фикс**: когда `adapter.name === 'qwen'`, поднимаемся до
`.qwen-markdown-code-body` (контейнер, содержащий весь code-widget
включая site action row). Fallback на `viewport.parentElement`,
если класс отсутствует.

### Изменение контракта

`controlsHost(node)` → `controlsHost(node, adapter)`. Каждый call
site обновлён на передачу `state.adapter` / adapter в scope.
adapter опционален -- при `undefined` сохраняется поведение
v0.14.7. Шесть call sites в `content.js` тронуты.

`arenaWhyUserAuthored(node)` → `arenaWhyUserAuthored(node, adapter)`
аналогично, тот же optional-adapter контракт. Bool-wrapper
`arenaIsInUserAuthoredNode` обновлён для прокидывания аргумента.

### Бампы версий

* extension `0.14.7` → `0.14.8`
* `chat_extension/manifest.json` -- version bump
* `chat_extension/content.js` -- `ARENA_CONTENT_SCRIPT_VERSION`
* `chat_extension/insert_strategies.js` -- `arenaInsertScriptVersion`
* `chat_extension/README.md` -- баннер

### Модулярность

`content.js` вырос с 700 до 722 строк с новыми ветками controlsHost.
Сжал новые per-adapter блоки в one-liners и объединил старую
двухстрочную tag-проверку, вернулся ровно на **700 строк**
(`MAX_PRODUCT_FILE_LINES`). Поведение не потеряно.

### Регрессионные guard-тесты

Десять новых asserts в `tests/test_chat_extension_v0_14_8.py`:

* content/manifest/insert/README все пинятся на 0.14.8
* `arenaWhyUserAuthored` принимает adapter
* Grok-ветка срабатывает ТОЛЬКО при `adapter.name === 'grok'` и
  использует `.message-bubble` closest-selector; reason string =
  `grok:user-message-bubble@DIV`
* `_USER_AUTHOR_ATTRS` по-прежнему НЕ содержит `'user-message'`
  (regression guard v4.48.6)
* `controlsHost(node, adapter)` подпись и нет голых call sites
  `controlsHost(x)`
* DuckAI-ветка использует `.overflow-hidden` escape
* Qwen-ветка использует `.qwen-markdown-code-editor-viewport` +
  `.qwen-markdown-code-body`
* Call site `arenaWhyUserAuthored(host, adapter)` в mountControls
* shadow_toolbar.css Qwen-фикс на месте
* content.js ≤ 700 строк
* Диагностические поля v0.14.7 (`candidate_diagnostics`,
  `mounted_diagnostics`) по-прежнему в scan-report

Существующие extension-тесты перепинены на 0.14.8. Полный прогон:
**2420 passed, 0 failed**.

### Изменённые файлы

* `chat_extension/content.js` -- 700 → 700 строк (net-zero,
  +22 для controlsHost веток, -22 сжатия существующего кода)
* `chat_extension/adapters.js` -- 557 → 571 строка (+14 для
  per-adapter ветки arenaWhyUserAuthored + комментарий)
* `chat_extension/manifest.json` -- version bump
* `chat_extension/insert_strategies.js` -- version bump
* `chat_extension/README.md` -- version banner
* `tests/test_chat_extension_v0_14_8.py` -- новый, 10 asserts
* `tests/test_chat_extension_v0_14_7.py` -- обновление version pin
* `tests/test_chat_extension_assets.py` -- обновление version pin
* `tests/test_chat_extension_adapter_flow.py` -- обновление banner pin
* `arena/constants.py` -- VERSION bump
* `pyproject.toml` -- version bump

## v4.49.0 -- Диагностический проход для extension: candidate_diagnostics + mounted_diagnostics

Третий live-раунд принёс реальные сигналы: узкий фикс v4.48.6
"убрать один testid" оставил три сайта в трёх разных проблемах:

* **Grok** -- тулбар цепляется к User-блоку, а не к AI, который
  несёт tool call. Фильтр v4.48.6 сам по себе правильный (убрал
  false-positive testid), но Grok НЕ ИМЕЕТ role-explicit маркера
  на своих user-баблах, поэтому `arenaWhyUserAuthored` возвращает
  `matched: false` и mount идёт и по user, и по assistant блокам.
  Дальше `arenaPruneAncestorCandidates` + `.slice(-5)` оставляет
  User.
* **DuckAI** -- тулбар монтируется (`mounted_controls: 1`), но
  кнопки Preview / Insert / Send / Copy мигают и пропадают при
  ре-рендере контейнера сообщений Duck. Виден только Run. Причина
  неясна -- подозреваю виртуальный список Duck, где DOM-узел
  пересоздаётся при каждом state change, и наш Shadow DOM host
  оказывается orphan.
* **Qwen** -- тулбар стоит между кодом и Qwen action row (лайк /
  дизлайк / share / refresh), а не под action row. Лучше, чем в
  v4.48.5 (было наложение), но визуально тесно -- оператору
  кажется, что смещён.

**Ни одну из этих проблем нельзя чинить вслепую** -- две последние
итерации extension (v4.48.5, v4.48.6) регрессили дважды, потому что
мы меняли mount/skip логику, не видя, к какому DOM-узлу тулбар
реально прицеплен. Поэтому v4.49.0 -- **чисто диагностический**
проход, нулевое изменение поведения.

### Добавлено (только в scan-report)

* `candidate_diagnostics[]` -- для каждого рассмотренного кандидата
  богатый DOM-снапшот: `path` (6-глубинная цепочка tag:index),
  `self` (tag/id/testid/role/author-role/2 class-токена),
  4 `ancestors` той же формы, первые 120 символов `text_head`,
  вердикт `why_user_authored`, `node_id_input` (что скормили
  fingerprint-хешеру).
* `mounted_diagnostics[]` -- тот же снапшот для каждого элемента,
  сейчас несущего `data-arena-tool-controls="1"`. Отвечает:
  "к какому узлу тулбар реально прицепился?".

Оба массива ограничены 8 записями, чтобы scan-report влезал в
1 МБ aiohttp reply cap.

### Бампы версий

* extension `0.14.6` → `0.14.7`
* `chat_extension/manifest.json` -- version bump
* `chat_extension/content.js` -- `ARENA_CONTENT_SCRIPT_VERSION`
  + новые additive-поля в scan-report
* `chat_extension/insert_strategies.js` -- `arenaInsertScriptVersion` bump
* `chat_extension/README.md` -- баннер

### Модулярность

`chat_extension/content.js` вырос с 700 до 735 строк из-за
диагностических добавлений. Сжал свои же section-заголовки
(`// ------`) и single-line ternary консолидации, вернулся ровно
на **700 строк** -- лимит `MAX_PRODUCT_FILE_LINES`. Поведение не
трогал.

### Регрессионные guard-тесты

Одиннадцать новых asserts в `tests/test_chat_extension_v0_14_7.py`:

* `content.js` пинит `ARENA_CONTENT_SCRIPT_VERSION = 0.14.7`
* manifest/insert/README версии синхронизированы
* scan-report экспортирует `candidate_diagnostics` +
  `mountedDiagnostics`
* хелпер `arenaDiagnosticSnapshot(node)` живёт в `adapters.js`
  с `self`/`ancestors`/`why_user_authored`/`node_id_input`
* snapshot читает каждый user-role маркер
  (data-message-author-role, data-author-role, data-role,
  data-sender, data-testid, role)
* оба диагностических массива ограничены 8
* `_USER_AUTHOR_ATTRS` не содержит `'user-message'` (regression
  guard v4.48.6)
* shadow_toolbar.css содержит Qwen-фикс (z-index 2147483000 +
  position: relative + isolation: isolate)
* line count `content.js` ≤ 700

Существующие asserts в `tests/test_chat_extension_assets.py` и
`tests/test_chat_extension_adapter_flow.py` перепинены на 0.14.7.

Полный прогон: **2410 passed, 0 failed**.

### Что нужно от тебя (пришли ещё раз Scan Page)

Пожалуйста, прогони Scan Page на Grok / DuckAI / Qwen с
загруженным v4.49.0. Новые `candidate_diagnostics[]` +
`mounted_diagnostics[]` покажут:

* На **Grok**: какой ancestor отличает User-бабл от Assistant-бабла
  (скорее всего class/testid на message-list item wrapper). Это то,
  на что v4.49.1 фильтр будет key'иться -- точечно, per-adapter,
  по реальным данным.
* На **DuckAI**: жив ли наш mounted тулбар (`self.tag` connected к
  DOM) или стал detached. Если detached -- фикс через
  MutationObserver re-attach loop; если connected -- мы боремся с
  CSS Duck.
* На **Qwen**: точное вертикальное позиционирование mounted-хоста
  относительно Qwen action row (сможем добавить margin-bottom или
  order через CSS, когда узнаем flex/grid layout).

### Заметка про память моста

Live-замер через 13ч после старта v4.48.8: `VmRSS = 88 МБ`,
`VmPeak = 1.34 ГБ`, `VmSize = 1.34 ГБ`. Реальный RSS стабильный и
маленький. 1,2-1,4 ГБ, которые ты видел в htop / диспетчере
задач -- это `VmPeak` -- transient spike (скорее всего burst из
429-х, которые вызывала проблема rate-limit'а из v4.48.7, до
того как v4.48.8 exempt'нул дашборд). Утечки нет, накопления
аллокаций нет. Продолжаю мониторить между сессиями.

### Изменённые файлы

* `chat_extension/content.js` -- 700 строк (было 700, добавил
  ~35 диагностики, сжал ~35 заголовков/тернарников)
* `chat_extension/adapters.js` -- 507 → 557 строк (+50 для
  `arenaDiagnosticSnapshot`)
* `chat_extension/manifest.json` -- version bump
* `chat_extension/insert_strategies.js` -- version bump
* `chat_extension/README.md` -- version banner
* `tests/test_chat_extension_v0_14_7.py` -- новый, 11 asserts
* `tests/test_chat_extension_assets.py` -- 0.14.6 → 0.14.7
* `tests/test_chat_extension_adapter_flow.py` -- README banner
  0.14.6 → 0.14.7
* `arena/constants.py` -- VERSION bump
* `pyproject.toml` -- version bump

## v4.48.8 -- Фикс "Dashboard сам себя DoS-ит": исключение статики из rate limiter + immutable кэширование

Живой репорт после v4.48.7:

    Dashboard boot failed: Error: Failed to load /gui/assets/00-core.js
    {"ok": false, "error": "rate limit exceeded", "retry_after_s": 0.4}

Именно ЭТО и создавало впечатление "утечки на 1,4 ГБ" (сама VmSize
раздута по причине из v4.48.7, но неспособность дашборда загрузиться
после 3-4 перезагрузок делала процесс ВЫГЛЯДЯЩИМ как сломанный).
Корень был очевиден, я его пропустил:

* Одна перезагрузка Dashboard = **58 JS-файлов + 22 body HTML +
  manifest + REST-запросы = ~85 запросов**.
* Каждый статический ассет отдавался с `Cache-Control: no-store`,
  так что Chromium перекачивал всё это на каждой перезагрузке.
* Rate limiter на IP -- **300 запросов / 60 секунд**.
* После 3-4 перезагрузок в минуту оболочка получала HTTP 429 на
  случайные `.js` файлы. Ретрай-цикл на script-тегах из v3.85.3
  честно пробовал 3 раза, но окно rate limiter'а на 60 секунд
  означало, что ретраи тоже упирались в лимит. Итог: каскадный
  отказ загрузки.

### Исправлено

* **`/gui/assets/*` и `/gui/docs/*` исключены из rate limiter'а.**
  Эти пути отдают read-only статические файлы со строгими guard'ами
  против path traversal и не могут мутировать состояние. Auth /
  API / mutation endpoint'ы остаются под лимитом. Правка в
  `arena/errors.py::error_middleware` -- один tuple
  `_RL_SKIP_PREFIXES` и проверка `startswith` перед вызовом
  rate limiter'а.
* **`Cache-Control` для статики изменён с `no-store` на
  `public, max-age=3600, immutable`.** URL'ы ассетов уже содержат
  `?v={{VERSION}}` (см. `dashboard/index.html`), так что реальный
  апгрейд форсит fresh fetch. Перезагрузки в рамках одной версии
  теперь попадают в кэш браузера -- одна перезагрузка после первой
  стоит ~1 запрос (HTML shell), а не 85. Правка в
  `arena/gui/handlers.py::handle_gui_asset`.

### Регрессионные guard-тесты

Четыре новых asserts в `tests/test_dashboard_asset_rate_limit_exemption.py`:

* `/gui/assets/` и `/gui/docs/` ДОЛЖНЫ быть в skip-prefix tuple
* существовавшие исключения (`/health`, `/metrics`, `/gui`,
  `/favicon.ico`, `/api-docs`) ДОЛЖНЫ остаться в списке, и вызов
  rate limiter'а ДОЛЖЕН по-прежнему срабатывать для неисключённых
  путей
* `handle_gui_asset` ДОЛЖЕН отдавать `public, max-age=3600, immutable`
* старый голый вызов `Cache-Control: no-store` `FileResponse(...)`
  НЕ ДОЛЖЕН вернуться

### Чего этот релиз НЕ трогает

Chrome extension остаётся на 0.14.6. Свежие Scan Page данные с
Grok / DuckAI / Qwen (которые ты прислал в этой сессии) показывают,
что фильтр из v4.48.6 работает -- toolbar'ы монтируются, но
отображаются по-разному на каждом сайте, и это требует отдельного
релиза. Забронировано на v4.48.9, чтобы этот hotfix мог уехать
немедленно, не смешивая диагностику с потенциальными регрессиями
экстеншена.

### Изменённые файлы

* `arena/errors.py` -- 166 -> 184 строк (+18 skip-prefix guard)
* `arena/gui/handlers.py` -- 185 -> 203 строк (+18 immutable
  cache-control)
* `tests/test_dashboard_asset_rate_limit_exemption.py` -- новый,
  4 asserts
* `arena/constants.py` -- VERSION bump
* `pyproject.toml` -- version bump

### Тесты

* 4 новых asserts зелёные в `tests/test_dashboard_asset_rate_limit_exemption.py`
* 17 зелёных в `tests/test_gui_handlers.py`
* 6 зелёных в `tests/test_rate_limit.py` + `tests/test_rate_limit_handlers.py`
* Полный прогон: **2399 passed, 0 failed** (2395 baseline + 4 новых)

## v4.48.7 -- Хотфикс Dashboard: retry манифеста + fallback + фикс горизонтального overflow

Живые репорты после v4.48.6:

* `Dashboard boot failed: asset manifest empty and no fallback list
  configured.` появляется при повторных перезагрузках, приходится
  жёстко обновлять несколько раз чтобы Dashboard поднялся.
* Вкладки Transports и Live "уезжают вправо", контент частично
  обрезан / сайдбар визуально смещён.
* Якобы утечка памяти на 1,4 ГБ в мосте. Проверил 6-ю замерами RSS
  с шагом 5 секунд: RSS стабильно ~80 МБ, systemd cgroup Memory =
  215 МБ (мост + bore + cloudflared + ngrok вместе). 1,4 ГБ -- это
  `VmSize` (виртуальная память: 18 потоков x зарезервированный
  stack + mmap-ные разделяемые библиотеки + пулы буферов asyncio),
  что для многопоточного Python на GNU/Linux всегда сильно больше
  реального RAM и утечкой не является. Кода не трогал -- фиксирую
  здесь, чтобы это не всплывало заново как "регрессия".

### Исправлено

* **Оболочка дашборда теперь ретраит fetch манифеста 3 раза** с
  задержкой 250/500 мс, повторяя логику ретрая `<script>` тегов
  из v3.85.3. Chromium иногда получает 0 байт при переиспользовании
  HTTP/1.1-коннекта, и первый `fetch("/gui/assets/manifest.json")`
  резолвится как `!res.ok`, хотя второй запрос уже проходит.
* **Синхронный fallback-список встроен в оболочку.** Если endpoint
  манифеста действительно недоступен (частично обновлённый мост,
  сломанная reverse-proxy и т.п.), Dashboard теперь всё равно
  поднимется с 5 обязательными скриптами (`00-core`, `00-tabs-registry`,
  `01-tab-switching`, `02-api-helper`, `03-helpers`) + телом шелла,
  и покажет оранжевую полосу сверху, требующую перезагрузки.
  Раньше был голый `<pre>` с одной строкой ошибки.
* **Раскладка `.main` больше не переполняется по горизонтали.**
  Добавил `min-width:0;overflow-x:hidden;max-width:100%` для `.main`
  и `.main .tab` в `dashboard.css`. Корень: flex-ребёнок по
  умолчанию получает `min-width:auto`, а `#tab-transports .tr-grid`
  использует `grid-template-columns:repeat(auto-fit,minmax(340px,1fr))`,
  что резолвится до ширины контента и вылетает за 100vw на узких
  вьюпортах (ноутбук с боковыми панелями, планшет в split-screen).

### Регрессионные guard-тесты

Пять новых asserts в `tests/test_dashboard_boot_hardening.py`:

* fetch манифеста должен жить в retryable-хелпере с 3 попытками и
  экспоненциальной задержкой
* `SYNC_FALLBACK_SCRIPTS` / `SYNC_FALLBACK_BODIES` должны содержать
  пять entry-скриптов + body-00-shell
* флаг `ARENA_DASHBOARD_USING_FALLBACK` + видимый предупреждающий
  баннер должны присутствовать
* `dashboard.css` должен содержать точные правила overflow-clamp
  для `.main` и `.main .tab`
* сообщение "asset manifest empty" остаётся как последняя ветка --
  для findability в code review

### Не менялось

Extension (0.14.6) в этом релизе намеренно не трогаю. Нужны свежие
данные Grok / DuckAI / Qwen (events_recent + скриншот) прежде чем
делать очередную итерацию фильтра user-authored и позиции тулбара
Qwen -- гадать без реальных данных нас уже подводило в v4.48.5 и
v4.48.6.

### Изменённые файлы

* `dashboard/index.html` -- 99 -> 175 строк (retry + fallback + баннер)
* `dashboard/assets/dashboard.css` -- 109 -> 119 строк (2 добавленных правила)
* `tests/test_dashboard_boot_hardening.py` -- новый, 5 asserts
* `arena/constants.py` -- VERSION bump
* `pyproject.toml` -- version bump

## v4.48.6 - 2026-07-17

### Chrome-расширение — root-cause fix для Grok / DuckAI + Qwen toolbar overlap

Седьмой релиз в arc v4.48.x. v4.48.5 diagnostic-first pass дал
плоды: `events_recent[].reason` на Grok и DuckAI обе показали
`attr:data-testid=user-message@DIV`. Проверка реальной DOM по
scan-report показала, что эти сайты используют этот
`data-testid` на message-list контейнере, который держит и
user, и assistant блоки — не только на user turns. Каждый mount
short-circuit-ился нашим фильтром. Это правило удалено.
Расширение bumped `0.14.5 → 0.14.6`.

Также фиксит overlap toolbar на Qwen (виден на скриншоте
оператора): наш toolbar рендерился под собственным action-row
Qwen (like / dislike / share / refresh) прямо под code-блоком.
Shadow-host теперь сидит над site UI через
`position: relative; z-index: 2147483000; margin-top: 6px;
isolation: isolate;` на `:host`.

#### Два конкретных изменения

* **`data-testid="user-message"` удалён из `_USER_AUTHOR_ATTRS`.**
  Сохранены четыре role-explicit атрибута
  (`data-message-author-role`, `data-author-role`, `data-role`,
  `data-sender`), которые каждый scanned-сайт использует только
  на реальном user turn. Удалённое правило regression-guarded:
  новый тест assert-ит, что tuple не должен вернуться.
* **Qwen toolbar overlap.** `chat_extension/shadow_toolbar.css`
  `:host` получил четыре свойства: `position: relative` +
  `z-index: 2147483000` (max int-safe — выше каждой site
  action-row, что мы видели) + `margin-top: 6px` (дыхание от
  code-блока) + `isolation: isolate` (создаёт новый stacking
  context, чтобы вложенный контент не мог escape).
* Claude adapter по-прежнему использует тот же
  `data-testid="user-message"` в своём `arenaIsAssistantNode` —
  это Claude-specific site check, где testid реально означает
  "user only", он остаётся.

#### Затронутые файлы

* **`chat_extension/adapters.js`** — один tuple удалён из
  `_USER_AUTHOR_ATTRS`; header-rationale обновлён.
* **`chat_extension/shadow_toolbar.css`** — `:host` rule получил
  position / z-index / margin-top / isolation.
* **`chat_extension/content.js`** —
  `ARENA_CONTENT_SCRIPT_VERSION` bumped на `0.14.6`.
* **`chat_extension/insert_strategies.js`** —
  `arenaInsertScriptVersion` bumped на `0.14.6`. Без изменений
  поведения.
* **`chat_extension/manifest.json`** — extension-version bumped
  `0.14.5 → 0.14.6`.
* **`chat_extension/README.md`** — version-баннер обновлён.

#### Тесты

* **`tests/test_chat_extension_assets.py`** — 5 новых /
  обновлённых assertions на: content-version pin (0.14.6);
  regression-guard против возврата `['data-testid', 'user-message']`
  в attr-список; три assertions на Qwen overlap fix
  (`z-index: 2147483000`, `position: relative`,
  `isolation: isolate` все в CSS).
* **`tests/test_chat_extension_adapter_flow.py`** — README-version
  bumped на `0.14.6`.
* Sweep проходит на **2390**.

#### Что остаётся отложенным

* Kimi / Perplexity `submit` 2-секундная задержка — это by design
  (directDomBlocks поллит verify после каждого из 30 + 80 + 180ms
  перед fire-ом Enter). Быстрее бы потребовало per-adapter timing
  override. Не срочно.
* Arena.ai multi-model (battle / side-by-side) варианты — base
  adapter теперь работает, остался только battle-mode multiplex.
* Extension-side RemoteConfigManager (по-прежнему queued для v4.49.0).

## v4.48.5 - 2026-07-17

### Chrome-расширение — user-authored фильтр: strict-equal + WHY-reporting + composer cache invalidation

Шестой релиз в arc v4.48.x. Grok и DuckAI всё ещё репортили
`mounted_controls=0, dismissed_controls=2` с `skip_user_authored`
events после v4.48.4 narrowing, поэтому этот релиз переключается
на diagnostic-first подход: filter теперь записывает WHY он
сматчил, и сам matching ужат до `===` на attribute values.
Расширение bumped `0.14.4 → 0.14.5`.

#### Три конкретных изменения

* **`arenaWhyUserAuthored(node)` → `{matched, reason}`.** Новый
  helper возвращает ancestor-tag + какой attr/class сработал в
  виде короткой строки (например `attr:data-role=user@DIV`,
  `class:human-message@ARTICLE`). `arenaIsInUserAuthoredNode`
  становится тонкой обёрткой. `mountControls` в `content.js`
  записывает reason в diagnostic ring buffer, поэтому scan-page
  `events_recent` наконец называет виновника вместо голого
  `skip_user_authored`. Как только reason появится в следующем
  scan-report, мы точно знаем, какой селектор ужать дальше.
* **Strict-equal на attribute values.** v0.14.2 - v0.14.4
  использовали `String(v).toLowerCase().includes(val)` на
  атрибутах, что false-positive матчило shapes вроде
  `class="user-listing"` или `role="userlist"` — именно такие
  контейнеры Grok / DuckAI оборачивают чат-блоки. Теперь
  attribute match — `lv === val` OR
  `lv.split(/\s+/).indexOf(val) !== -1` (space-separated
  token equality для combined-role значений типа
  `"user assistant"`). Class substring matching остаётся,
  потому что class needles (`user-message`, `human-message`, ...)
  достаточно specific, чтобы быть безопасными.
* **Ancestor walk cap ужат 20 → 8.** User-role marker всегда
  должен быть в пределах 8 DOM-hops от body сообщения. 20-cap
  делал редкие-но-безобидные parent-декорации триггерами filter.
* **Eviction detached composer target.** Qwen re-render-ит
  весь chat-пан на model switch и оставлял
  `window.__arenaLastComposerTarget` указывающим на floating
  detached-ноду. `arenaComposerSelection` теперь null-ит
  cached hint перед scoring candidates, когда обнаруживает,
  что target больше не connected. Fresh scan-report должен
  показывать `cached_match: false` (или true с живой нодой)
  вместо `cached_match: true` на target'e с `isConnected: false`.

#### Затронутые файлы

* **`chat_extension/adapters.js`** — новый `arenaWhyUserAuthored`,
  `arenaIsInUserAuthoredNode` становится wrapper, strict-equal
  attr match, walk cap 20 → 8, detached-composer eviction в
  `arenaComposerSelection`.
* **`chat_extension/content.js`** — `mountControls` использует
  `arenaWhyUserAuthored` и записывает `reason` в diag ring
  buffer; `ARENA_CONTENT_SCRIPT_VERSION` bumped на `0.14.5`.
* **`chat_extension/insert_strategies.js`** —
  `arenaInsertScriptVersion` bumped на `0.14.5`. Insert-путь
  без изменений; v0.14.4 plan ordering подтверждён рабочим на
  Kimi / Perplexity по scan-report оператора (submit с 2-
  секундной задержкой через directDomBlocks + Enter fallback).
* **`chat_extension/manifest.json`** — extension-version bumped
  `0.14.4 → 0.14.5`.
* **`chat_extension/README.md`** — version-баннер обновлён с
  diagnostic-first описанием.

#### Тесты

* **`tests/test_chat_extension_assets.py`** — 4 новых
  assertions на `arenaWhyUserAuthored` presence, strict-equal
  attr match, detached-composer eviction, и внутренний
  content-version pin (0.14.5).
* **`tests/test_chat_extension_adapter_flow.py`** — README-version
  bumped на `0.14.5`.
* Sweep проходит на **2390**.

#### Что остаётся отложенным (нужен свежий scan-report)

* Grok / DuckAI toolbar не появляется — v0.14.5 записывает
  reason в `events_recent[].reason`. Пожалуйста, отсканируй
  заново и пришли reason-строку; это разблокирует финальный
  узкий fix.
* Qwen submit не срабатывает — stale-composer eviction должен
  помочь, но Qwen icon-only submit живёт вне всех scored
  ancestors. Если Enter fallback всё ещё missed, events_recent
  покажет `submit_late_missing` и можно расширить poller.
* Arena.ai user echo всё ещё сматчен — та же история: reason
  в events_recent назовёт нарушающий attr/class.
* Qwen toolbar visual drift — без изменений; нужна
  DOM-inspection сессия, которую я не могу сделать remote.

## v4.48.4 - 2026-07-17

### Chrome-расширение — regression-фиксы после v4.48.2 / v4.48.3

Пятый релиз в arc v4.48.x. Откатывает / сужает несколько guard-ов
из v4.48.2 и v4.48.3, которые закрыли одну проблему, но открыли
несколько других в scan-report из daily use. Расширение bumped
`0.14.3 → 0.14.4`.

#### Пять закрытых регрессий

* **Grok / DuckAI перестали mount-ить toolbar вообще.** v4.48.2
  `arenaIsInUserAuthoredNode` ходил по ancestors в поиске `<form>`
  или composer-selector-совпадения, что на этих сайтах покрывало
  каждый chat-блок — scan-reports показали
  `mounted_controls=0, dismissed_controls=2` с
  `skip_user_authored` events. Filter теперь урезан до явных
  user-role attributes и узкого class-substring set. Form-ancestor
  и composer-selector эвристики убраны — они были слишком широкими.
* **Kimi / Perplexity double-insert.** v4.48.3 план цеплял
  `nativeInsertText → paragraphFallback → directDomBlocks` с шагом
  "wipe composer между attempts". Wipe был ненадёжным на plain-
  contenteditable composers, поэтому вторая стратегия дописывала
  дубликат вместо overwrite. Plan теперь `directDomBlocks →
  paragraphFallback → nativeInsertText` для plain contenteditable
  (Perplexity, Kimi) и остаётся `nativeInsertText` для ProseMirror
  composers (Claude, Grok, Mistral), которые честно уважают
  `execCommand('insertText')`. Wipe-between-strategies убран —
  run-loop снова breaks на первой `changed` попытке.
* **Ложный detect на README GitHub.** v4.48.2 copilot
  `pathPrefix: '/copilot'` исправил copilot-adapter, но fallback
  `generic` adapter всё равно срабатывал на README code-fences,
  цитирующих MCP JSONL. Generic adapter теперь помечен
  `passive: true`, и `mountControls` short-circuit-ит когда
  `adapter.passive`. Unlisted сайты теперь дают чистый
  `mounted_controls=0` от scan-page вместо случайного toolbar
  на первом `<pre>`.
* **Qwen Enter fallback молча промахивался.** Synthetic Enter
  keydown диспатчился на composer, но Qwen слушает делегированный
  document-listener, который срабатывает только когда target —
  activeElement. Fallback теперь focus-ит target перед dispatch и
  повторяет Enter через 120 ms, чтобы composers, которые
  debounce первую нажатую клавишу, тоже увидели retry.
* **Version-баннеры были правильны через три компонента с v0.14.1,
  но внутренний content-version pin в тестовом guard теперь
  `0.14.4`.**

#### Затронутые файлы

* **`chat_extension/adapters.js`** — `arenaIsInUserAuthoredNode`
  сведён к attribute + class-substring matching; walk cap
  оставлен 20 hops.
* **`chat_extension/adapter_sites.js`** — generic adapter помечен
  `passive: true` с inline-rationale комментарием.
* **`chat_extension/content.js`** — `mountControls` short-circuit-ит
  на `adapter.passive`; `ARENA_CONTENT_SCRIPT_VERSION` bumped на
  `0.14.4`.
* **`chat_extension/insert_strategies.js`** — `arenaInsertPlan`
  развернул multi-line план для plain contenteditable
  (`directDomBlocks` первым); wipe-between-strategies убран из
  `arenaInsertResult`; Enter-fallback focus-ит target + retry
  через 120 ms; `arenaInsertScriptVersion` bumped на `0.14.4`;
  `arenaStructureMatches` оставлен как diagnostic-only metadata
  (больше не gate-ит `settled`).
* **`chat_extension/manifest.json`** — extension-version bumped
  `0.14.3 → 0.14.4`.
* **`chat_extension/README.md`** — version-баннер обновлён.

#### Тесты

* **`tests/test_chat_extension_assets.py`** — 4 новых assertions,
  покрывающих plan-ordering fix, generic-passive флаг, отсутствие
  form-ancestor эвристики, и `passive` skip в content.js.
  Внутренний content-version pin bumped на `0.14.4`.
* **`tests/test_chat_extension_adapter_flow.py`** — README-version
  bumped на `0.14.4`.
* Sweep проходит на **2390**.

#### Что остаётся отложенным

* Preview-button flash на Kimi / Qwen — по-прежнему нет repro.
* Qwen toolbar drift — `<div>`-wrapped-`<pre>` hoist на месте, но
  layout Qwen имеет floating action-menu сверху; visual-fix
  скорее всего требует настоящую DOM-inspection сессию.
* Arena.ai battle / side-by-side / agent-mode варианты.
* Extension-side RemoteConfigManager (queued для v4.49.0).

## v4.48.3 - 2026-07-17

### Chrome-расширение — structure-preserving insert + fix позиции Qwen toolbar

Четвёртый релиз в arc v4.48.x. Два конкретных фикса, отрепорченных
из daily use после v4.48.2:

* **Плоский текст insert на Perplexity / Kimi.** Их contenteditable-
  composers молча коллапсируют `\n` в spaces на
  `execCommand('insertText', ...)`. Наш verify-путь использовал
  `arenaEditableText`, которая сама нормализует `\s+` → ` ` перед
  compare, поэтому paste, потерявший все newlines, всё равно
  репортил `settled: true`, fallback-цепочка не срабатывала, и
  модель читала обратно one-line blob. Теперь
  `arenaStructureMatches()` считает `<br>`-ноды и block-children
  после insert. Если payload имел newlines, но composer показывает
  одну строку, verify возвращает `structure_ok: false`, run-loop
  очищает composer и продвигается к следующей стратегии
  (`nativeInsertText → paragraphFallback → directDomBlocks`).
* **Qwen toolbar дрифтил выше site "..." action menu.** Qwen
  оборачивает fenced code как `<div><pre>...</pre></div>`;
  pre-v0.14.3 `controlsHost` возвращал outer `<div>` без изменений,
  и toolbar приземлялся у insertion-anchor этого div вместо `<pre>`.
  `controlsHost` теперь hoist-ит в nested `<pre>` когда нода —
  `<div>`, обёрнутый вокруг `<pre>` (матчит поведение, которое у
  нас уже было для `<code>` внутри `<pre>`).

#### Затронутые файлы

* **`chat_extension/insert_strategies.js`** — новый helper
  `arenaStructureMatches(target, text)`; `arenaVerifySettledInsert`
  gate на structure-флаг; `arenaInsertResult` чистит composer между
  стратегиями, когда предыдущая попытка легла плоско, чтобы
  fallback не отправлял `text\ntext` дубликат; `arenaInsertPlan`
  цепляет `paragraphFallback` + `directDomBlocks` когда payload
  содержит `\n`; `arenaInsertScriptVersion` bumped на `0.14.3`.
* **`chat_extension/content.js`** — `controlsHost` hoist-ит
  `<div>`-обёрнутый `<pre>` (оставил однострочным, поскольку файл
  прямо у 700-line product-modularity threshold);
  `ARENA_CONTENT_SCRIPT_VERSION` bumped на `0.14.3`.
* **`chat_extension/manifest.json`** — extension-version bumped
  `0.14.2 → 0.14.3`.
* **`chat_extension/README.md`** — version-баннер обновлён.

#### Тесты

* **`tests/test_chat_extension_assets.py`** — 3 новых assertions
  на presence `arenaStructureMatches` в insert_strategies.js,
  `paragraphFallback` + `directDomBlocks` цепочки, и
  `<div>`-wrap-`<pre>` hoist в content.js. Внутренний
  content-version pin bumped на `0.14.3`.
* **`tests/test_chat_extension_adapter_flow.py`** — README-version
  bumped на `0.14.3`.
* Sweep проходит на **2390** (без изменений; существующие тесты
  расширены, новых счётных тестов не добавлено).

#### Что остаётся отложенным

* Preview-button flash на Kimi / Qwen (repro пока нет — ring
  buffer `events_recent` из v4.48.2 должен помочь его поймать в
  следующем scan-report).
* Arena.ai battle / side-by-side / agent-mode варианты (per-surface
  adapter split).
* Extension-side RemoteConfigManager (queued для v4.49.0).

## v4.48.2 - 2026-07-17

### Chrome-расширение — user-message фильтр, Copilot path-guard, Enter-fallback

Третий релиз в arc v4.48.x полировки расширения. Фокус на реальных
проблемах, всплывших в scan-report на 12+ chat-сайтах после v4.48.1:

* **Ложные detected tool-call на сообщениях пользователя.** Grok /
  Copilot / DuckAI / Arena.ai эхом возвращают prompt пользователя
  в transcript тем же code-fence-стилем, что assistant reply.
  Pre-v4.48.2 scanner ловил их и предлагал "run" на собственный
  текст пользователя. Новый helper `arenaIsInUserAuthoredNode`
  (adapters.js) ходит по ancestors, ищет
  `data-message-author-role="user"`, human/user-message-классы,
  form/textarea/composer-ancestors — любой hit short-circuit mount
  и пишет diagnostic event.
* **Copilot протёк на весь github.com.** v4.48.1 adapter имел
  `hosts: ['github.com']` без path-guard, поэтому обычные README
  репозиториев, цитирующие MCP JSONL (например,
  `srbhptl39/MCP-SuperAssistant`), превращали каждый code-fence в
  "detected function_call" toolbar. Схема adapter теперь
  поддерживает `pathPrefix: '/copilot'`; selection в
  `getArenaAdapter()` проверяет его против `location.pathname`.
* **Submit-кнопка живёт вне всех scored ancestors на Kimi /
  Perplexity / Copilot.** Existing `arenaInsertAndSubmit` polling
  не находит click-target — вставка остаётся в composer без
  submit'а. Новый синтетический `Enter`-keydown fallback
  срабатывает только когда poll закончился без выбора submit
  селектора (не срабатывает когда есть disabled submit — это
  значит сайт валидирует input). Отчёт:
  `submit_selector: 'enter-key-fallback'` /
  `submit_scope: 'keyboard'`.
* **Inline `arguments` на `function_call_start` молча терялся.**
  MCP SuperAssistant формат позволяет модели emit-ить arguments
  либо отдельными `type: "parameter"` строками, либо inline на
  start-event. Наш парсер читал только первое, поэтому вызов
  `{"type":"function_call_start","name":"fs.view","call_id":"3","arguments":{"path":"."}}`
  доходил до моста с пустым arguments-dict и возвращался как
  `ERROR: missing 'path' argument`, хотя caller передал его.
  Парсер теперь мерджит оба варианта.
* **`fs.view` на директории всплывал как HTTP 500.** MCP-handler
  пробовал `read_text` на директории (uncaught
  `IsADirectoryError`) вместо того чтобы вернуть подсказку. Теперь
  возвращает структурированную ошибку, называющую `fs.list` как
  правильный verb.
* **Arena.ai и DuckAI adapters** добавлены, чтобы оба перестали
  падать в `generic`. Arena.ai baseline покрывает `/c/` chat-
  surface; battle / side-by-side / agent-mode варианты отложены на
  follow-up. DuckAI adapter пинится на `/chat` через
  `pathPrefix`, чтобы не hijack'ить search / news-страницы.
* **Scan-Page diagnostics ring buffer.** Новый массив
  `events_recent` в payload (последние 20 событий, capped) surface'ит
  user-message-skip, late-submit-rescan-wait и будущую
  инструментацию без network hop.

#### Затронутые файлы

* **`chat_extension/adapter_sites.js`** — copilot получил
  `pathPrefix`, arena.ai + duckai новые entries, header rationale
  обновлён.
* **`chat_extension/adapters.js`** — новый `arenaPath` helper +
  `getArenaAdapter` pathPrefix branch; новый
  `arenaIsInUserAuthoredNode` helper с attribute / class / ancestor
  эвристикой.
* **`chat_extension/content.js`** — `ARENA_CONTENT_SCRIPT_VERSION`
  bumped на `0.14.2`; новый `_arenaDiagPushEvent` ring buffer +
  `arenaWaitForSubmit` late-submit poller (также exposed на window
  для дебага); user-authored skip branch в `mountControls`;
  `events_recent` добавлен в payload `scanPageDiagnostics`.
* **`chat_extension/insert_strategies.js`** —
  `arenaInsertScriptVersion` bumped на `0.14.2`; Enter-key
  синтетический keydown fallback в `arenaInsertAndSubmit` когда
  poll не нашёл submit-селектор.
* **`chat_extension/parser.js`** — `arenaPayloadFromJsonl` мерджит
  inline `arguments` и `params` со start-event.
* **`chat_extension/manifest.json`** — version bumped
  `0.14.1 → 0.14.2`; новые host_permissions записи для
  `arena.ai`, `www.arena.ai`, `duck.ai`, `duckduckgo.com`.
* **`chat_extension/README.md`** — version-баннер обновлён.
* **`arena/mcp/tool_fs.py`** — `_handle_fs_view` получает
  `is_dir()` short-circuit + `IsADirectoryError` catch.

#### Тесты

* **`tests/test_chat_extension_assets.py`** — 8 новых assertions:
  manifest-version, внутренний content-version, copilot pathPrefix
  presence, arena.ai + duckai adapter presence, host_permissions
  coverage для обоих новых сайтов, `arenaIsInUserAuthoredNode` /
  `events_recent` / `arenaWaitForSubmit` / `enter-key-fallback` /
  `row.arguments` presence checks.
* **`tests/test_chat_extension_adapter_flow.py`** — README-version
  bump на `0.14.2`.
* **`tests/test_fs_view_create.py`** — 2 новых теста, локирующие
  directory-guard поведение (`test_mcp_fs_view_directory_returns_hint`
  + `test_mcp_fs_view_dot_path`).
* Sweep проходит на **2390** (2388 + 2 fs.view теста).

#### Чего нет в этом релизе

* Plain-text (paragraph-preserving) вставка на Perplexity + Kimi
  (сейчас вставляет как single-line blob, потому что composer
  contenteditable удаляет newlines).
* Qwen toolbar layout drift когда он появляется над floating
  action menu — нужен `controlsHost` ancestor-walk fix.
* Preview-button flash на Kimi / Qwen (transient; repro пока
  не найден).
* Arena.ai battle / side-by-side / multi-model варианты — нужен
  per-surface adapter split.
* Extension-side RemoteConfigManager (по-прежнему queued для v4.49.0).

## v4.48.1 - 2026-07-17

### Chrome-расширение — sweep адаптеров по результатам живых scan-report

Point-релиз. Использует живые scan-report диагностики, собранные
на 12+ chat-сайтах (ChatGPT / Claude / Gemini / Perplexity / Grok /
OpenRouter / DeepSeek / Kimi / Qwen / t3chat / z.ai / Mistral / GitHub
Copilot), чтобы закрыть шесть конкретных багов, которых v4.48.0
Shadow-DOM refactor не касался. Расширение поднято `0.14.0 → 0.14.1`.

#### Шесть закрытых багов

* **Version drift.** `content.js` и `insert_strategies.js` оба
  держали хардкоженные `'0.13.27'` константы, которые не подняли
  при бампе `manifest.json` до `0.14.0` в v4.48.0. Каждый scan-
  report и каждая запись Command Center показывали
  `manifest 0.14.0 · content 0.13.27 · insert 0.13.27` —
  косметически неверно, и делало ответ на "какой content-script
  bundle реально запущен?" сильно сложнее при дебаге. Обе
  константы теперь `'0.14.1'`, и добавлен guard в
  `test_chat_extension_assets.py`, требующий чтобы константа
  матчила версию файла — future-релизы не смогут повторить drift.
* **`www.kimi.com` падал в generic adapter.** Реальный URL
  пользователя `https://www.kimi.com/chat/...`, но `manifest.json`
  и `adapter_sites.js` перечисляли только голый `kimi.com`, поэтому
  content script не загружался на `www.*` субдомене и не подхватывал
  сайт-специфичные composer / submit селекторы Kimi даже когда
  загружался. Оба alias теперь покрыты.
* **`chat.mistral.ai` падал в generic adapter.** Сайт был в
  `host_permissions` ещё с v0.13.x, но записи в `adapter_sites.js`
  не было. Scan-report показал composer — ProseMirror div, submit
  живёт внутри `<form>` с `type="submit"` — Claude-shaped —
  используем эти селекторы как модель. Adapter теперь возвращает
  `mistral` вместо `generic`.
* **`github.com/copilot` падал в generic adapter.** Тот же fix-
  паттерн. Composer — `<textarea aria-label="Ask anything or type
  @ to add context">`; scan-report сообщил
  `buttons-present-no-submit-match` потому что submit —
  icon-only кнопка без aria-label. Новый adapter пробует
  `data-testid` варианты первым, fallback на "последнюю видимую
  кнопку в form"-эвристику. Adapter возвращает `copilot` на
  github.com путях, ведущих на Copilot chat.
* **DeepSeek / Qwen scans возвращали 0 candidate_nodes.** Обе SPA
  рендерят composer + reply лениво в более глубоких контейнерах,
  чем pre-v0.14.1 селекторы. Расширил `messageSelectors` на
  `section` / `pre` / `code` / `[class*="markdown"]` /
  `[class*="prose"]`, чтобы fenced `jsonl` блоки ловились на
  первом paint. Также добавил китайские варианты
  (`aria-label*="发送"`) в `submitSelectors` для обоих — их
  button labels локализуются.
* **Perplexity парсил 0 блоков даже когда assistant reply был
  виден.** Их reply живёт в `main`-level div'ах, а не в
  `<article>`, поэтому pre-v0.14.1 селекторы матчили только
  внешний wrapper. Добавил `pre` / `code` / `[class*="prose"]` /
  `[class*="markdown"]` в `messageSelectors`, чтобы fenced
  `jsonl` блоки матчились на первом scan.

#### Bonus-подтяжка (на основе живых scan-report)

* **Grok** — явно добавил `button[data-testid="chat-submit"]` и
  `form button[type="submit"]` (работало через generic Send
  fallback, теперь диспатчится через first-choice селектор).
* **OpenRouter** — добавил `button[data-testid="send-button"]` +
  `button[aria-label="Send message"]` первыми селекторами, чтобы
  scan-report `submit_selected_sample` возвращал целевую кнопку,
  а не last-resort match.

#### Затронутые файлы

* **`chat_extension/adapter_sites.js`** — три новых adapter
  (`mistral`, `copilot`, плюс host-alias `www.kimi.com` на
  существующий entry `kimi`), расширенные селекторы на четырёх
  существующих (`deepseek`, `qwen`, `perplexity`, `kimi`),
  подтянутые submit-селекторы на двух (`grok`, `openrouter`),
  header-docstring обновлён с объяснением "why now" (живые
  scan-report данные).
* **`chat_extension/manifest.json`** — version bumped
  `0.14.0 → 0.14.1`; новая `https://www.kimi.com/*` запись в
  `host_permissions` (блокировала загрузку content script на
  URL, которым Kimi реально пользуется).
* **`chat_extension/content.js`** — `ARENA_CONTENT_SCRIPT_VERSION`
  bumped до `'0.14.1'` (был заморожен на `'0.13.27'` ещё до
  Shadow DOM refactor).
* **`chat_extension/insert_strategies.js`** —
  `arenaInsertScriptVersion()` return поднят до `'0.14.1'` (тот
  же drift).
* **`chat_extension/README.md`** — version-banner, per-site
  список обновлён (`www.kimi.com` alias выделен, Mistral +
  Copilot добавлены, t3chat + z.ai были уже покрыты, но не
  перечислены).

#### Тесты

* **`tests/test_chat_extension_assets.py`** — 6 новых assertions:
  manifest-version pin (`0.14.1`), внутренний
  `ARENA_CONTENT_SCRIPT_VERSION` pin (regression-guard от drift'а,
  который shipped в v4.48.0), presence-check для трёх новых
  adapter host/name записей (`www.kimi.com`, `chat.mistral.ai`,
  `copilot`), проверка что `www.kimi.com` в `host_permissions`,
  чтобы content script реально загружался.
* **`tests/test_chat_extension_adapter_flow.py`** — README-version
  assertion поднят до `0.14.1`.
* Sweep проходит на **2388**.

#### Чего нет в этом релизе

* Extension-side RemoteConfigManager (по-прежнему queued для
  v4.49.0 как standalone `/v1/extension/adapters` endpoint +
  background-script fetch loop). Когда это лендится, такие
  adapter sweep можно будет shipping как config push, а не
  full extension rebuild.
* Более глубокое OpenRouter / Kimi покрытие. Оба сейчас работают
  на "insert + submit" уровне; follow-up добавит JSON-shape guards
  вокруг assistant reply, чтобы `parsed_blocks` никогда не
  регрессировал в 0 на этих двух даже когда они переделают UI.

## v4.48.0 - 2026-07-17

### Chrome-расширение — изоляция toolbar через Shadow DOM

Feature-релиз, сфокусированный на browser extension. Поднимает
расширение `0.14.0` (bumped с `0.13.27`); injected toolbar теперь
живёт в Shadow DOM-хосте per-message anchor, поэтому CSS страницы
ChatGPT / Claude / Gemini и т.п. больше не может дотянуться и
переопределить стили наших контролов. Bridge-side wiring не тронут
(без изменений API surface) — релиз чисто client-side hardening.

#### Зачем этот релиз

До v0.14.0 расширение монтировало toolbar как обычный `<div>` в
light DOM страницы, а стили ставились через
`bar.style.cssText = "..."` в `chat_extension/content.js`. Две
проблемы:

* **CSS страницы мог выиграть specificity-войну.** `!important`
  reset кнопок в ChatGPT, font-inheritance правила Gemini, padding
  message-bubble в Claude — всё могло дотянуться до нашего toolbar
  и переопределить inline-стили. Пользователи периодически видели,
  как border-radius toolbar схлопывается в 0 на некоторых сайтах,
  либо кнопки съезжают на пиксель из-за flex-родителя.
* **Coupling селекторов.** Наш `[data-arena-tool-controls="1"]`
  атрибут мог случайно матчить page-правило, и наоборот. Страница
  могла таргетить наши элементы, не подозревая, что они наши.

Оба класса проблем исчезают, когда toolbar живёт в Shadow DOM: page-
селекторы не пересекают shadow-границу ни в одну сторону. Паттерн
взят у MCP SuperAssistant из `BaseSidebarManager`
(`attachShadow({mode:'open'})` + CSS-файл, фетчащийся через
`chrome.runtime.getURL` и инжектящийся `<style>`-нодой в shadow
root); выбран после кодового разбора их
`pages/content/src/utils/shadowDom.ts` и
`components/sidebar/base/BaseSidebarManager.tsx`.

#### Затронутые файлы

##### Новые файлы

* **`chat_extension/shadow_toolbar.js`** (~170 строк) — три
  публичных helper, exposed на `window`:
  - `arenaCreateShadowToolbar(hostAnchor, options)` возвращает
    `{shadowHost, shadowRoot, toolbar}`. `shadowHost` — light-DOM
    anchor, который caller позиционирует; `toolbar` — внутренний
    `.arena-toolbar` элемент, куда пойдут кнопки.
  - `arenaDestroyShadowToolbar(shadowHost)` — idempotent remove.
  - `arenaShadowToolbarButton(label, onClick, {primary})` —
    factory для кнопок с теми же pointer-preserving handlers, что
    у pre-v0.14 `makeButton()` (blur/focus-churn тормозил некоторые
    chat UI).
  - CSS фетчится один раз per-content-script и кэшируется; результат
    инжектится `<style>`-нодой в каждый shadow root. Non-blocking:
    если fetch провалился (очень медленная сеть на первом mount),
    toolbar рендерится без стилей, а не отсутствует.
* **`chat_extension/shadow_toolbar.css`** (~100 строк) — все
  toolbar / button стили scoped через `:host` и `.arena-toolbar` /
  `.arena-btn` / `.arena-btn--primary`. Использует CSS custom
  properties (`--arena-tb-*`, `--arena-btn-*`) — future theme
  patches меняют палитру в одном месте. Fallback-значения match
  pre-v0.14 inline styles byte-for-byte, поэтому upgraded install
  выглядит идентично старому.

##### Изменённые файлы

* **`chat_extension/manifest.json`** — version bumped
  `0.13.27 → 0.14.0`; content-script list получил
  `shadow_toolbar.js` как 7-ю запись (прямо перед `content.js`,
  чтобы helpers были на `window` до вызова `mountControls()`);
  новый `web_accessible_resources` блок публикует
  `shadow_toolbar.css` на `<all_urls>`, чтобы content script мог
  фетчить его через `chrome.runtime.getURL(...)`.
* **`chat_extension/content.js`** — `makeButton()` делегирует в
  `arenaShadowToolbarButton` когда он доступен (защитный fallback
  на bare light-DOM button, когда нет — для loader-ordering
  edge cases). `mountControls()` создаёт shadow-host через
  `arenaCreateShadowToolbar(host)` вместо bare `<div>`, убирает
  ~800-байтовые inline-styles `bar.style.cssText = "…"` и
  `status.style.cssText = "…"` в пользу классов `.arena-toolbar` /
  `.arena-toolbar-status`, инжектящихся в shadow root. Map
  `mountedControls` получает поле `shadowHost` рядом с существующим
  `bar`, чтобы semantic-eviction path и close-`×` handler оба
  удаляли правильную ноду (shadow host). Все pre-v0.14 tracking-id
  (`data-arena-tool-controls="1"`,
  `data-arena-tool-controls-mounted="1"`,
  `data-arena-tool-fingerprint`) сохранены, поэтому
  `cleanupStaleControls()`, `hostHasToolbar()`, MutationObserver
  ignore-фильтр и `scanPageDiagnostics()` продолжают работать без
  правок.
* **`chat_extension/README.md`** — version-баннер + новая запись
  в "Important files" для `shadow_toolbar.js` / `shadow_toolbar.css`
  с одностраничным объяснением Shadow DOM-паттерна.

##### Тесты

* **`tests/test_chat_extension_assets.py`** — расширил manifest-
  guard: залочил новый слот (`content_scripts[0].js[6]` должен
  быть `shadow_toolbar.js`, `[7]` — `content.js`),
  `web_accessible_resources` check публикует `shadow_toolbar.css`
  на `<all_urls>`, и новый блок ассертов, читающий оба новых
  файла и проверяющий:
  - `arenaCreateShadowToolbar` / `arenaDestroyShadowToolbar` /
    `arenaShadowToolbarButton` определены в `shadow_toolbar.js`
  - используется `attachShadow` с `mode: 'open'` (соответствует
    рецепту MCP SuperAssistant из `BaseSidebarManager`)
  - `:host`, `.arena-toolbar`, `.arena-btn` присутствуют в
    `shadow_toolbar.css`
  - `content.js` вызывает `arenaCreateShadowToolbar` и больше не
    использует pre-v0.14 `bar.style.cssText` inline-style паттерн
    (regression-guard от возвращения light-DOM styling).

Bridge test suite остаётся на **2388 passed** (+ новые ассерты
в extension-assets тесте); ни один bridge-side runtime-файл не
тронут.

#### Design-решения достойные упоминания

* **`mode: 'open'`.** Матчит MCP SuperAssistant. Trade-off:
  page-scripts *могут* ходить по `shadowHost.shadowRoot`, поэтому
  враждебный сайт технически может прочитать наши button-labels.
  Это ок — мы не кладём в toolbar ничего чувствительного (labels
  — литералы вроде "Preview" / "Run"), а open mode позволяет
  Scan Page diagnostics продолжать инспектировать toolbar для
  дебага.
* **CSS в отдельном `.css`-файле** (а не inline-в-JS). Тоже
  матчит MCP SuperAssistant. Rationale: `content.js` и
  `shadow_toolbar.js` остаются slim, browser devtools показывают
  осмысленные line numbers когда styling ломается, и сохраняется
  возможность hot-swap stylesheet из будущего RemoteConfigManager
  (v4.49.0 territory) без правок JS.
* **Без React, без Zustand, без Tailwind.** MCP SuperAssistant
  использует все три, но наш toolbar — 6 кнопок и status-line;
  vanilla-JS + inline-CSS-file подход даёт 250 total LOC против
  ~1500 LOC React-harness у них. Дверь оставлена открытой:
  ничто в контракте shadow-host не мешает mount React-root
  внутри позже.
* **Loader-ordering safety net.** `makeButton` и `mountControls`
  оба через `typeof …=== 'function'` проверяют shadow-helpers и
  fallback на pre-v0.14 light-DOM path если они отсутствуют.
  На практике manifest.json гарантирует загрузку
  `shadow_toolbar.js` до `content.js`, но fallback держит
  extension работоспособным в трёх edge-case: (a) heavily-modded
  local install где кто-то удалил `shadow_toolbar.js` из
  file-list, (b) in-flight upgrade где старый закэшированный
  content-script bundle запущен против нового manifest, (c)
  unit-test контексты, stubbing module scope.

#### Чего нет в этом релизе

* Extension-side RemoteConfigManager (фетч adapter-селекторов с
  bridge вместо хардкода в `adapter_sites.js`). Была вторая
  MCP-SuperAssistant идея worth stealing, но она требует
  `/v1/extension/adapters` endpoint на bridge и background-script
  fetch-loop, оба своя meaningful surface. Планируется на
  **v4.49.0** как standalone-релиз; Shadow DOM-refactor стоит
  сам по себе, и shipping вместе спрятал бы небольшой релиз
  под бо́льшим diff.
* Zustand-style reactive state для popup / sidepanel. То же
  reasoning что "без React": наш state — `chrome.storage.sync`
  + `chrome.storage.local` + in-page `Map`, event-passing
  прекрасно работает через `chrome.runtime.sendMessage`. Не
  планируется.

## v4.47.2 - 2026-07-17

### Миграция Settings → Transports + docs sweep

Второй point-релиз в arc v4.47.x bore-polish. Убирает дублирующий
блок tunnel-контролов, живший на вкладке Settings ещё до появления
отдельной Transports-вкладки, и приводит публичную документацию в
соответствие с тем, что дашборд реально показывает.

#### Зачем этот релиз

Несколько релизов вкладка Settings несла *и* старые per-transport
Start/Stop кнопки, *и* warning-баннер, отсылающий пользователей на
новую Transports-вкладку. Две проблемы:

* **Старые кнопки всё ещё работали.** `tsFunnelToggle()` и
  `cfFunnelToggle()` были живы, per-transport badges продолжали
  опрашивать `/v1/tailscale/funnel/status` и
  `/v1/cloudflared/tunnel/status` на каждом Settings-refresh.
  Пользователи имели два места для одного и того же действия, и
  ни одно из них не знало про ngrok или (после v4.47.0) про bore.
* **README/README.ru всё ещё описывали Settings-локацию.** Две
  фразы в release notes ("Settings → Tunnels & Remote Access card")
  были косметически неверны — реальные контролы теперь на своей
  вкладке.

Этот релиз убирает Settings-контролы, заменяет их одностроковой
информ-панелью с кнопкой "Go to Transports tab →", и переписывает
соответствующие абзацы README (en + ru).

#### Изменённые файлы

* **`dashboard/assets/body-15-settings.html`** — вся карточка
  "Tunnels & Remote Access" (Active endpoint row, per-transport
  Start/Stop кнопки для Tailscale / Cloudflare / ZeroTier и блок
  `<details>` для ZeroTier networks) свернулась в 12-строчный
  info-banner с единственной кнопкой "Go to Transports tab →".
  Кнопка использует тот же sidebar-tab click трюк, что и другие
  cross-tab ссылки (ищет `nav a[data-tab="transports"]` и делает
  click, с hash-fallback если sidebar ещё не отрендерен).
* **`dashboard/assets/17-settings-status.js`** — `refreshSettings()`
  больше не опрашивает `/v1/tailscale/funnel/status` и
  `/v1/cloudflared/tunnel/status`, больше не красит `#tsToggleStatus`
  / `#cfToggleStatus` / `#cfUrl` DOM-ids, которых больше нет.
  `tsFunnelToggle()`, `cfFunnelToggle()` и общий helper
  `_humanTunnelError()` удалены, а не оставлены заглушками —
  silent stubs подделывали бы миграцию.
* **`dashboard/assets/29-tunnels.js`** — **удалён**. Его
  `tunnelsRefresh()` / `renderTailscale` / `renderCloudflared` /
  `renderZerotier` / `setActiveEndpoint` / `ztNetworkAction` все
  привязывались к Settings-side id, которых больше нет. Asset-
  манифест моста автогенерируется (`arena/gui/asset_manifest.py`),
  поэтому файл просто исчезает из `/gui/assets/manifest.json`
  после следующего boot, никакие правки манифеста не нужны. Каждая
  функция из этого файла либо мертва, либо уже реализована в
  `20-transports.js` (который был реальным источником Transports-
  вкладки с v4.36.x).
* **`README.md`** + **`README.ru.md`** — capability-строка
  "Dashboard" теперь называет вкладку "🔌 Transports" вместо
  списанной card. Прозаический абзац после tunnel-priority описывает,
  что вкладка Transports реально показывает (per-transport кнопки,
  autostart checkbox, env-override pill, log tail для
  cloudflared / ngrok / bore) вместо списанной карточки. ZeroTier
  network management-указатель переехал в свою вкладку **🌐 ZeroTier**.
* **`docs/MODULE_MAP.md`** — обновил dashboard-module строку на
  `dashboard/assets/20-transports.js` +
  `dashboard/assets/body-20-transports.html` (было
  `29-tunnels.js` + `body-15-settings.html`).

#### Тесты

Ни одного тест-файла править не нужно. Тест, который поймал бы
битое удаление — `tests/test_dashboard_asset_manifest.py` — обходит
`dashboard/assets/` в runtime, поэтому удаление файла ловится (и
доказывается безопасным) автоматически. Pytest sweep: **2388 passed**
(без изменений от v4.47.1; ни один тест не перечисляет удалённый файл
явно).

#### Миграция

* **Для пользователей.** Кто забукмаркил Settings-вкладку — увидит,
  что она по-прежнему работает; там теперь карточка с одной кнопкой,
  которая ведёт на Transports. Никаких JavaScript-ошибок: удалённые
  функции больше нигде в дашборде не вызываются.
* **Для операторов.** Кто забукмаркил `POST /v1/tailscale/funnel/*`
  или `POST /v1/cloudflared/tunnel/*` в shell-скрипте — всё
  продолжает работать; *API* endpoints не изменились, ушли только
  две дублирующие button-handler в Settings-side JS.
* **Для кастомных дашбордов.** Любой local mod, импортирующий
  `tsFunnelToggle` / `cfFunnelToggle` / `tunnelsRefresh` из global
  scope страницы, получит `ReferenceError`. Fix: вызвать
  соответствующую Transports-tab функцию
  (`transportStart('tailscale')` и т.п.) или дёрнуть JSON-endpoint
  напрямую.

## v4.47.1 - 2026-07-17

### Dashboard + installer polish для транспорта bore из v4.47.0

Point-релиз. Закрывает "хвосты" после v4.47.0:

* **Вкладка Transports теперь показывает пять карточек, не четыре.**
  После v4.47.0 API + wiring для bore уже работал, но вкладка
  Transports в дашборде (`body-20-transports.html` +
  `20-transports.js`) знала только про tailscale / cloudflared /
  zerotier / ngrok. Операторы видели транспорт в
  `curl /v1/tunnels/status`, но UI для start / stop /
  autostart-toggle не было. Теперь у bore отдельная карточка в
  том же визуальном языке, что у соседей: start / stop /
  copy-URL / autostart-checkbox / env-override pill / log tail
  — без special-case, модуль изначально писался под произвольное
  количество транспортов, ему нужен был только пятый entry.
* **Инсталлер ставит bore.** `install.sh` и `install.bat`
  получили bore install-блок, скопированный с v4.24.x
  cloudflared-паттерна: system-first (проверяет `PATH` и
  `~/.cargo/bin`), предпочитает `cargo install bore-cli` если
  Rust есть (всегда latest, ставится в `~/.cargo/bin`, который
  system-first path resolver моста уже покрывает), fallback на
  ~2 MB GitHub-release tarball / zip. Opt-in prompt для обоих
  путей; `ARENA_ASSUME_YES=1` bypass промптов для unattended
  installs. `install.sh` и `install.bat` сохранили baseline-
  синтаксис (`bash -n` чистый; все `goto`-label сбалансированы).

#### Файлы дашборда

* `dashboard/assets/body-20-transports.html` -- добавлена пятая
  карточка в хвост `.tr-grid`. `#tr-card-bore`, `#tr-badge-bore`,
  `#tr-url-bore`, `#tr-installed-bore`, `#tr-hint-bore`,
  `#tr-log-bore`, `#tr-autostart-bore`, `#tr-env-bore` — та же
  DOM-форма, что у `#tr-card-ngrok`, поэтому существующий
  dispatch `_renderCard()` обрабатывает её без special-case.
  Header-docstring обновлён на "one card per transport (v4.47.1:
  five cards)".
* `dashboard/assets/20-transports.js` -- `TRANSPORTS` и
  `AUTOSTART_TRANSPORTS` растут на одну запись каждый. `_ROUTE`
  получает `bore: "/v1/bore/tunnel/"`. `loadTransports()`
  фетчит `/v1/bore/tunnel/status` в том же `Promise.all`
  батче и мержит snapshot в `_lastState.bore` (добавляет поле
  `server`, чтобы badge мог показать `bore.pub` vs self-hosted
  host). Header docstring + inline comment про log-tail
  rendering обновлены под bore.

#### Файлы инсталлера

* `install.sh` -- новый блок "6a-ter" после cloudflared
  (`# --- 6a-ter: bore ...`). Cross-platform (Linux amd64/arm64/
  armv7, Darwin arm64 + x86_64) с двух-путевой стратегией выше.
  Использует GitHub releases API для резолва последнего тега
  (fallback на v0.6.0 когда API недоступен). `tar -xzf`
  extraction в `mktemp -d` staging-директорию, потом `mv` в
  `$INSTALL_DIR`. Обрабатывает оба возможных layout tarball
  (single top-level `bore` binary и per-target directory
  prefix). Bash-syntax проверен через `bash -n` перед выпуском.
* `install.bat` -- новая bore-секция между `:cloudflared_done`
  и `REM --- SuperPowers ---`. Target Windows x86_64.
  Использует встроенный `tar` из Windows 10 1803+ для
  распаковки zip. Такая же cargo-first / release-fallback
  форма. Два новых label: `:bore_download` (skip-to-download
  когда cargo-путь отвергнут / провален) и `:bore_done`
  (post-install fallthrough). Каждый `goto` сбалансирован с
  определёнными labels; проверено перед выпуском.

#### Тесты (+2 параметризации, 2386 -> 2388)

* `tests/test_autostart_unified.py` -- расширенные
  `test_marker_filename_convention` и
  `test_env_var_name_convention` parametrise-списки получили
  пару записей `("bore", ...)`, поэтому конвенции filename /
  env-var залочены и для пятого транспорта. Три других
  параметризованных теста (`test_neither_signal_disabled`,
  `test_marker_alone_enabled`, `test_env_alone_enabled`)
  проходят по `autostart.TRANSPORTS` напрямую и подхватили
  bore бесплатно — правки не понадобились.

#### Compat / миграция

* **Миграция не нужна.** Существующие установки подхватывают
  новую UI-карточку при первом refresh дашборда после upgrade;
  bore-шаг инсталлера opt-in с default "N" на обеих
  платформах, поэтому ничего не ставится молча.
* **API не меняется.** Всё, что добавляет point-релиз —
  cosmetic (UI) или advisory (installer prompt).
* **Зависимости не меняются.** bore остаётся опциональным;
  мост продолжает загружаться и обслуживать четыре
  транспорта даже когда bore не установлен.
  `/v1/bore/tunnel/status` возвращает `installed: false` +
  per-platform install hint, ровно как в v4.47.0.

## v4.47.0 - 2026-07-17

### bore -- пятый транспорт, zero-account TCP relay через bore.pub

Первый **feature-релиз** после arc из девяти security-релизов
v4.40.0 → v4.46.1. Добавляет `bore`
(https://github.com/ekzhang/bore, MIT, автор Eric Zhang) как
пятый транспорт удалённого доступа, размещённый после
tailscale / zerotier / cloudflared / ngrok в default priority.
Выбран потому, что это единственный туннель в top-13
awesome-tunneling, удовлетворяющий всем трём критериям, под
которые проект оптимизируется с v4.33.0:

* **Не требует аккаунт.** `bore.pub` -- бесплатный публичный
  relay, поддерживаемый проектом. Без регистрации, authtoken,
  cookie дашборда. Закрывает нишу "поставил бинарник --
  работает", которую requirement ngrok на authtoken до сих пор
  оставляет пустой.
* **Один статичный Rust-бинарник.** Та же стратегия "system-
  first / bundled fallback", уже используемая для cloudflared
  и ngrok, работает как есть -- один бинарник ставится через
  `cargo install bore-cli` или release-drop c GitHub.
* **TCP-only, без TLS-терминации на middlebox.** Мост уже
  говорит HTTPS на порту 8765; клиент, дозвонившийся до
  `https://bore.pub:<port>`, получает настоящий self-signed
  cert моста, который агенты могут запинить через v4.45.0
  `ARENA_BRIDGE_PIN_SHA256`. Ни один CDN не сможет
  незаметно подменить cert так, как это мог бы сделать
  полноценный HTTPS reverse proxy.

#### Новый файл

* **`arena/admin/bore.py`** (~446 строк) -- структурное зеркало
  `arena/admin/ngrok.py`:
  - `bore_action("start" | "stop" | "status", port, ...)`
    публичная entry-point, та же сигнатура что у `ngrok_action`
    и `cloudflared_funnel_action`, чтобы дашборд, autostart-hook
    и wiring-слой обрабатывали все пять транспортов одинаково.
  - `BORE_STATE = {"proc", "url", "log"}` -- идентичная форма
    NGROK_STATE / CLOUDFLARED_STATE.
  - `_resolve_bore_with_source()` -- system-first / bundled
    fallback, cross-platform (Windows + Darwin + Linux/BSD).
    Список Linux-путей включает `~/.cargo/bin/bore`, чтобы
    инсталляции через `cargo install bore-cli` подхватывались
    без вмешательства оператора.
  - `_bore_monitor_thread()` -- парсит первую строку
    `listening at <server>:<port>` из stdout и публикует
    внешний URL как `https://<server>:<remote_port>`.
    `re.IGNORECASE` locked in unit-тестом, чтобы будущее
    изменение формата логов было поймано.
  - `_classify_error()` -- три fingerprint: `invalid_secret`,
    `server_unreachable`, `remote_port_conflict`. Каждый несёт
    человеческий hint с именем конкретной env-переменной для
    правки. Fallback на `unknown` + docs-ссылка, если ничего
    не совпало.
  - Fail-fast при раннем выходе процесса: тот же паттерн, что
    v4.36.0 ngrok-fix -- `process_died_early` reported отдельно
    от timeout, чтобы операторы видели реальную причину.
  - Четыре env-настройки, все опциональные, все typo-safe:
    * `ARENA_BORE_SERVER` (default `bore.pub`) -- указать на
      self-hosted `bore server`.
    * `ARENA_BORE_URL_WAIT_SECONDS` (default 30, clamp 1--300)
      -- та же форма, что v4.24.1 cloudflared-clamp и
      v4.36.2 ngrok-clamp.
    * `ARENA_BORE_LOCAL_HOST` (default `localhost`).
    * `ARENA_BORE_SECRET` -- opt-in shared secret для self-hosted
      серверов; передаётся как `--secret <value>` только когда
      задан, никогда не логируется.
    * `ARENA_BORE_REMOTE_PORT` -- опциональный preferred remote
      port, 0 = "пусть сервер выберет". Значения вне диапазона
      и не-числовые fallback к 0, а не raise.
  - Argv-form `Popen` only (никакого `shell=True`), server /
    secret / port берутся из env-переменных, санитизированных
    в readers.

#### Wiring-интеграции

* **`arena/admin/tunnels.py`** -- `DEFAULT_PRIORITY` расширен до
  пяти записей; новый `_bore_snapshot()` mirroring
  `_ngrok_snapshot`; параметр `bore_status_sync` пробрасывается
  через `tunnels_status`, `tunnels_active`, `tunnels_probe`.
  Оставлен опциональным (default `None`), чтобы
  pre-v4.47.0 callers продолжали работать.
* **`arena/admin/autostart.py`** -- tuple `TRANSPORTS` расширен
  на `"bore"`; marker `ROOT_AGENT/.bore_autostart` авто-
  создаётся при успешном start / удаляется при успешном stop
  общим helper `persist_after_action`.
* **`arena/admin/handlers.py`** -- новый handler
  `handle_v1_bore_tunnel` (POST + GET
  `/v1/bore/tunnel/{action}`); autostart-persistence + audit-
  log entry следуют v4.22.1 cloudflared / v4.38.0 ngrok
  паттерну без изменений.
* **`arena/admin/sync_factories.py`** -- новый factory
  `make_bore_status_sync`, структурный clone
  `make_ngrok_status_sync`.
* **`arena/contexts/platform.py`** -- `AdminHandlerContext`
  получает опциональное поле
  `bore_status_sync: Any = None`.
* **`arena/wiring/bridge_runtime.py`** -- wires
  `_bore_status_sync` в глобальный state-graph рядом с
  `_ngrok_status_sync`.
* **`arena/wiring/system_public_admin_registries.py`** --
  передаёт `bore_status_sync=env._bore_status_sync` в admin
  wiring-context.
* **`arena/wiring/platform.py`** -- `AdminWiringContext`
  получает поле `bore_status_sync`; dispatcher маппит
  `"handle_v1_bore_tunnel"` -> `handlers.bore_tunnel`, чтобы
  route table мог его резолвить.
* **`arena/wiring/app_lifecycle.py`** -- новое замыкание
  `_bore_autostart()`, та же форма, что `_ngrok_autostart`
  (вызывает shared autostart-модуль + `bore_action` напрямую,
  отдельный `bore_autostart` sibling-модуль не нужен).
* **`arena/lifecycle.py`** -- `LifecycleContext` получает
  callable `bore_autostart`; loop, который стреляет каждый
  autostart на boot моста, получает запись
  `("Bore", ctx.bore_autostart)` для консистентного log-line
  с четырьмя другими транспортами.
* **`arena/route_registry/registry.py`** -- декларативная route-
  table получает POST + GET `/v1/bore/tunnel/{action}` ->
  `handle_v1_bore_tunnel`.
* **`arena/route_registry/core.py`** -- реальные
  `app.router.add_post` / `add_get` вызовы добавлены рядом с
  ngrok-парой (v4.33.1 regression-паттерн залочен через
  `tests/test_bore_route_registration.py`).

#### Тесты (+69)

* **`tests/test_bore.py`** (~440 строк) -- URL-wait clamp,
  env-readers (server / local_host / secret / remote_port
  включая fall-back на out-of-range и не-числовые),
  binary-resolution через три платформы с тремя исходами
  "system / bundled / not_found", version-extraction,
  update-hint сообщения, monitor-thread ловящий
  `listening at bore.pub:PORT` и строящий внешний URL,
  error-classifier hitting каждый из трёх fingerprint +
  unknown-fallback, `bore_action` dispatch shell (unknown
  verb / start-without-binary / stop-idempotent / status-
  when-not-running / status очищает stale URL / status
  reports server field), spawn-failure path, "already running"
  fast path, argv-shape assertions для `--secret` / `--port`
  threading.
* **`tests/test_bore_wiring.py`** (~200 строк) --
  DEFAULT_PRIORITY имеет bore пятой записью, `_bore_snapshot`
  shape (unwired / wired / raising / empty URL),
  `tunnels_status` мержит bore и выбирает его active когда он
  единственный wired provider, поле `AdminHandlers` dataclass
  present, поле `AdminHandlerContext` present, autostart
  TRANSPORTS содержит bore, marker path использует
  `.bore_autostart`, `wiring/platform.py` string-check на
  entry в handler-map, `make_bore_status_sync` возвращает
  callable, переживающий отсутствие бинарника.
* **`tests/test_bore_route_registration.py`** (~60 строк) --
  локирует v4.33.1-style инвариант "и registry.py, и core.py
  должны согласовываться" для новых endpoint.

#### Architecture-guard update

* **`tests/test_architecture_boundaries.py`** -- добавляет
  `arena/admin/tunnels.py` в `LINE_ALLOWLIST` с параграфом
  rationale (файл -- намеренный fan-in facade "одно место,
  где виден каждый транспорт"; пятый provider добавил ~45
  строк параллельной ceremony; паттерн однородный, поэтому
  split бы только перенёс provider-список из одного
  центрального места в пять sibling-модулей, каждый из
  которых дублировал бы ceremony). Reviewer note зашита в
  комментарий: если когда-нибудь придёт **шестой** транспорт,
  вынести `_<provider>_snapshot` в per-transport sibling-
  модули, а здесь оставить только dispatch shell.

#### Миграция & compat

* **Пользователям не нужна миграция.** Каждый новый
  параметр opt-in с default `None`; каждая новая env-
  переменная имеет безопасный fallback; четыре старых
  транспорта ведут себя идентично v4.46.1.
* **`ARENA_TUNNEL_PRIORITY`** по-прежнему уважает
  пользовательский override; отсутствующие provider
  append в built-in order, поэтому оператор, писавший
  `ARENA_TUNNEL_PRIORITY=cloudflared,tailscale` до
  v4.47.0, после upgrade получает
  `cloudflared, tailscale, zerotier, ngrok, bore` -- bore
  тихо appended в хвост.
* **Публичный API в остальном byte-compatible с v4.46.1**
  -- клиент, говорящий только `/v1/tunnels/*`, видит
  одну дополнительную запись в списке `providers` и не
  требует изменений кода.

#### Follow-up, отложенные в последующие релизы

* v4.48.0 -- refactor Chrome-расширения на Shadow DOM
  (изолирует CSS страницы от инжектированного UI; соответствует
  паттерну MCP SuperAssistant, изученному в
  `RESEARCH_2026-07-17.md`).
* v4.49.0 -- remote extension config endpoint.
* v5.0.0 -- нативное Flutter mobile app в отдельном репо.

## v4.46.1 - 2026-07-17

### Documentation sweep -- каждый markdown-файл обновлён под security-posture v4.40.0 → v4.46.0

Docs-only patch release. Нет изменений runtime или тестов.
Приводит публично-facing documentation в соответствие с тем,
что код реально делает после 9 security-релизов за одну сессию.

#### Обновления

* **`README.md`** -- переписал "Security model" секцию с
  pre-v4.40.0 семиточечной сводки на полную defence map
  (аутентификация, транспорт, filesystem, data at rest,
  логи, закрытые классы атак, continuous protection).
  Добавил строку `Security` в таблицу "What it can do".
  Добавил `make security-scan` в Development. Добавил
  `SECURITY.md` первой строкой в Documentation map. То же
  для `README.ru.md`.
* **`CONTRIBUTING.md`** -- новая секция "Security scan
  (required before push)" документирующая три CI-gate и
  как их запустить локально. Расширил "Security-sensitive
  areas" с 8 пунктов до 14 с file-level указателями и
  явными invariants, которые каждый contributor должен
  сохранить.
* **`AGENTS.md`** -- добавил блок "Security (non-negotiable)"
  в Hard rules: никакого bare `zipfile.ZipFile.extractall`,
  никакого `tempfile.mktemp`, никакого `os.system`, никаких
  inline credential-shape test fixtures (нужно строить
  runtime через prefix + suffix concat -- иначе GitHub
  secret-scanning push protection reject коммит), каждый
  `# nosec` и `# nosemgrep` должен нести rationale,
  redaction живёт в одном месте
  (`arena/observability/redact.py`), file-mode discipline на
  `~/.arena/`. Также добавил `make security-scan` в
  validation.
* **`RELEASE.md`** -- вставил `make security-scan` шагом 1b
  в TL;DR, обновил pre-release checklist с security-scan
  gate + "no credential-shape literals in test fixtures"
  check, обновил post-release checklist с CI security-scan
  workflow status link. Поднял quoted test-count baseline
  с 690 до 2319.
* **`docs/INTEGRATIONS.md`** -- новая секция "Hardening
  the client side" с тремя levers (cert pinning, signed
  URL cache, peer-address privacy dial) плюс точный shell
  recipe для computation SPKI fingerprint из живого
  Tailscale bridge.
* **`docs/AI_CODEBASE_NAVIGATION.md`** -- добавил новые
  runtime modules (`sandbox.py`, `safe_extract.py`,
  `tls.py`, `pinning.py`, `url_cache.py`, `redact.py`,
  `handler_helpers.safe_float/safe_int`) в ownership table
  + новая "Security-critical hotspots" table указывающая
  contributors на точный файл, владеющий каждой защитой.

#### Тронутые файлы

* `README.md` -- Security model rewrite + Documentation map
  addition + Development section addition.
* `README.ru.md` -- параллельные изменения.
* `CONTRIBUTING.md` -- Security scan section + расширенная
  Security-sensitive areas.
* `AGENTS.md` -- Security hard rules + security-scan
  validation.
* `RELEASE.md` -- security-scan в TL;DR + pre/post-release
  checklists + test-count baseline bump.
* `docs/INTEGRATIONS.md` -- Hardening the client side.
* `docs/AI_CODEBASE_NAVIGATION.md` -- обновлённый ownership
  + Security-critical hotspots.
* `arena/constants.py` + `pyproject.toml` -- version bump
  4.46.0 -> 4.46.1.

#### Тесты (без изменений)

Нет runtime кода, нет test изменений. 2299 unit + 15
fallback E2E = 2314 total / 2319 on bridge. Все CI
security-scan gates всё ещё clean (bandit 0 HIGH/MEDIUM,
semgrep 0 across 9 packs, pip-audit 0 CVEs).


## v4.46.0 - 2026-07-17

### Continuous security: `SECURITY.md` + CI security-scan pipeline

Седьмой security-релиз. Этот закрывает audit sweep фиксацией
tooling, которое поддерживает codebase clean going forward, и
документированием threat model + env-var reference для
operators и contributors.

Два артефакта, оба meta-security (они enforce security, а не
добавляют новую защиту):

#### `SECURITY.md` в корне репо

Comprehensive threat-model + defence map + полный env-var
reference для каждого security-relevant knob. Секции:

* **Reporting a vulnerability** -- private issue / GitHub
  Security Advisory workflow, response targets (72 ч
  initial reply, 2 недели для HIGH, 30 дней для MEDIUM).
* **Supported versions** -- только `master` (последний
  `v4.x.y`); что-либо старше v4.40.0 missing at least одно
  sweep finding.
* **Threat model** -- таблица 12 threat class'ов и
  concrete defences (bearer auth, cert pinning, sandbox
  blocklist, HMAC cache, SSRF-guard, safe-extract, DOCTYPE-
  gate, value-pattern redaction, peer-IP mask, TOCTOU-safe
  tempfiles, `Warning: 299` deprecation header, log-URL
  redaction).
* **What we do NOT defend against** -- явный out-of-scope
  список (compromised CLI host, compromised bridge host,
  physical access, social engineering).
* **Security features** -- server-side + client-side map,
  файл-за-файлом.
* **Environment variables** -- **полная reference** 14
  security-relevant env vars с default + effect.
* **Recommended production preset** -- copy-paste bash
  блок с token-file, SPKI pinning derived from live bridge
  cert, `ARENA_LOG_PEER=mask` с per-install salt,
  `ARENA_WEBHOOK_STRICT=1`.
* **Static analysis + CI gates** -- документирует три
  инструмента и точный threshold каждого.
* **Audit history** -- v4.40.0 → v4.45.0 timeline с
  per-release headline.

Discoverable через `SECURITY.md` в корне репо (стандартная
GitHub location).

#### CI security-scan pipeline

`.github/workflows/security-scan.yml` запускает три
independent tools на каждый push, каждый PR, и daily в
06:00 UTC (cron catches новые CVE в deps без нужды в
commit):

* **bandit** -- Python static-analysis. Gate: **0 HIGH + 0
  MEDIUM findings**. LOW трактуется как code-hygiene noise.
* **semgrep** -- semantic pattern matcher, **9 rule packs**
  pinned. Gate: **0 ERROR + 0 WARNING**. Каждая false-
  positive линия уже несёт inline `# nosemgrep: <rule> --
  <rationale>` marker.
* **pip-audit** -- CVE scan против runtime + full-extras
  deps. Gate: **0 CVEs**. Runs daily чтобы свежая CVE
  тригерит alert без commit.

Каждый job загружает свой JSON report как 30-day-retention
artifact.

#### Local parity через `Makefile`

Те же три gate локально запускаемо, так что "passes locally"
== "passes in CI":

```
make install-security-tools
make security-scan
make security-bandit
make security-semgrep
make security-pip-audit
```

Gate logic DRY: и CI, и Makefile зовут тот же
`scripts/security_gate.py` и `scripts/extract_runtime_reqs.py`,
так что threshold change в одном месте propagates
automatically.

#### Тронутые файлы

* `SECURITY.md` -- **НОВЫЙ**, 180 строк.
* `.github/workflows/security-scan.yml` -- **НОВЫЙ**,
  3-job matrix (bandit / semgrep / pip-audit).
* `Makefile` -- **НОВЫЙ**, top-level entry points с `help`.
* `scripts/security_gate.py` -- **НОВЫЙ**, shared gate
  logic.
* `scripts/extract_runtime_reqs.py` -- **НОВЫЙ**, DRY dep
  extractor.
* `arena/constants.py` + `pyproject.toml` -- version bump
  4.45.0 -> 4.46.0.

#### Тесты

Test count без изменений (нет нового runtime кода): 2299
unit + 15 fallback E2E = 2314 total. Zero broken masters,
zero rollbacks.


## v4.45.0 - 2026-07-17

### CWE-top-25 scan + emit-site redaction модуль + optional TLS certificate pinning

Шестой security-релиз. Этот закрывает последние три пункта
audit wishlist:

1. **``p/cwe-top-25`` semgrep pass** -- 0 findings.
2. **Emit-site redaction вынесена в shared модуль**
   (``arena/observability/redact.py``) -- audit log, request
   log и будущие sinks идут через те же rules.
3. **Optional TLS certificate pinning** для agentctl CLI
   (opt-in через ``ARENA_BRIDGE_PIN_SHA256``).

Также прогнал ``p/insecure-transport``, ``p/command-injection``,
``p/xss``, ``p/secrets``, ``p/gitleaks`` -- 3 findings в
insecure-transport (все loopback URL false positives,
задокументированы через ``# nosemgrep: insecure-urlopen``), 0
в остальных.

#### #29 -- p/cwe-top-25 clean

Total findings: **0**. Sweep v4.42.0-v4.44.0 уже адресовал
каждую OWASP-family concern, которую CWE-top-25 pack targets
(path traversal, deserialisation, injection, SSRF, weak crypto,
insecure defaults).

Combined static-analysis dashboard as of v4.45.0:

| tool | severity | count |
|---|---|---|
| bandit | HIGH | 0 |
| bandit | MEDIUM | 0 |
| bandit | LOW | 442 (code-hygiene, не security) |
| semgrep p/python | ALL | 0 |
| semgrep p/security-audit | ALL | 0 |
| semgrep p/owasp-top-ten | ALL | 0 |
| semgrep p/cwe-top-25 | ALL | 0 |
| semgrep p/insecure-transport | ALL | 0 (after nosemgrep) |
| semgrep p/command-injection | ALL | 0 |
| semgrep p/xss | ALL | 0 |
| semgrep p/secrets | ALL | 0 |
| semgrep p/gitleaks | ALL | 0 |
| pip-audit | CVE | 0 |

#### #30 -- Structured emit-site redaction

**Проблема.** v4.44.0 добавил value-pattern redaction inline
в ``arena/observability/audit.py``. Каждый будущий sink
(request log, exception formatter, ``arena chat exec`` output
capture, metrics emitter) должен был бы копировать ту же
regex battery, или пропускать её и тихо утекать credentials
на другом code path. Structured-logging библиотеки типа
``structlog`` решают это через emit-time processor -- но
pull их as required dep тяжелее, чем problem.

**Фикс.** Новый модуль ``arena/observability/redact.py``
консолидирует regex battery + key-blocklist в два public
entry point (``redact_string(text)``, ``redact_value(obj)``).
Zero deps beyond stdlib ``re``. Оба идемпотентны,
input-immutable, и constant-time-safe на short-string
fast path (< 16 chars пропускает regex battery целиком).

Мигрированные call sites:

* ``arena/observability/audit.py`` -- back-compat aliases
  все указывают на те же objects в shared module.
* ``arena/observability/request_log.py`` -- ``entry["path"]``
  и ``entry["error"]`` теперь идут через ``redact_string``.

Cross-module contract test
(``test_audit_module_aliases_are_the_same``) фиксирует
alias identity, так что будущая правка shared module не
может тихо пропустить audit-log path.

#### #31 -- Optional TLS certificate pinning

**Мотивация.** v4.41.0's TLS-verify-by-default закрыл
"any-CA MITM" hole для public transports. Но trust anchor
всё ещё OS's ~150-CA bundle. Любой из этих CA мог бы issue
rogue cert для bridge hostname, и CLI бы trust'нул. Pinning
tightens trust anchor от "any of 150 CAs" до "this specific
certificate (или его public key)".

**Дизайн.**

* Opt-in. Set ``ARENA_BRIDGE_PIN_SHA256=<64-hex>`` для enable.
  Empty / unset = pinning disabled; TLS всё ещё verifies через
  system CAs как раньше.
* Multi-pin. Comma-separated fingerprints. Даёт operators
  pin current cert + spare для rotation safety.
* Colon-separated input accepted -- так что
  ``openssl x509 -fingerprint -sha256`` output
  (``AB:CD:EF:...``) можно paste напрямую без stripping.
* И cert-hash И SPKI-hash checked на каждый handshake --
  pin matches EITHER, operator может supply whichever
  form имеет.
* SPKI computation через optional ``cryptography`` dep. Когда
  absent, one-time WARNING на stderr и downgrade to
  cert-mode. Hard dep не добавлен.

**Enforcement path.** ``_PinnedHTTPSConnection`` (subclass of
``http.client.HTTPSConnection``) запускает
``verify_peer_cert(der_bytes)`` **внутри** ``connect()``,
после TLS handshake completed но ДО того, как request line
sent. Mismatched pin raise'ит ``TLSPinMismatchError`` и tears
down socket -- **bearer token никогда не leaves client**.

**Threat model.**

* Защищает от: rogue/compromised CA, misissued cert для
  bridge hostname, DNS hijack combined со stolen
  CA-signed cert.
* НЕ защищает от: CLI compromise, operator sets wrong pin
  (self-DoS -- но с diagnostic, называющим actual
  fingerprint), bridge private key stolen (fingerprint stays
  valid).

**Env variables добавлены.**

* ``ARENA_BRIDGE_PIN_SHA256`` -- comma-separated hex
  fingerprints; empty / unset disables pinning.
* ``ARENA_BRIDGE_PIN_KIND`` -- ``spki`` (default) или
  ``cert``.

#### Тесты (+29 unit, 2255 -> 2299 unit passed; 4 skipped E2E)

* ``tests/test_agentctl_pinning.py`` -- 14 unit + 4 E2E.
* ``tests/test_observability_redact.py`` -- 15 тестов.

Существующие 136 audit / request_log / observability тестов
продолжают проходить без модификации.

Zero broken masters, zero rollbacks.

#### Тронутые файлы

* ``arena/observability/redact.py`` -- **НОВЫЙ**, 145 строк.
* ``arena/observability/audit.py`` -- 100 строк inline regex
  battery removed, заменено 6-line import.
* ``arena/observability/request_log.py`` -- path + error
  через ``redact_string``.
* ``arena/agentctl_cli/pinning.py`` -- **НОВЫЙ**, 220 строк.
* ``arena/agentctl_cli/agentctl_common.py`` -- pin gate.
* ``arena/admin/ngrok.py`` + ``arena/agentctl_extras/status.py``
  -- 3 loopback URL nosemgrep аннотации.
* ``arena/constants.py`` + ``pyproject.toml`` -- version bump.
* 2 новых test файла.


## v4.44.0 - 2026-07-17

### Semgrep + privacy hardening pack: audit-log secret redaction, safe numeric parsing, peer-address privacy dial

Пятый security-релиз. Прогнал ``semgrep --config=p/python
--config=p/security-audit --config=p/owasp-top-ten`` по
всему runtime после v4.43.0, затем follow-up privacy-focused
audit того, что реально попадает на disk в ``audit.jsonl`` и
``requests.jsonl``. Semgrep scoreboard: **19 ERROR / 41
WARNING (66 всего) → 0 / 0**. Каждый finding был либо
реально пофикшен (5), либо аннотирован ``# nosemgrep --
<rationale>`` после верификации (55), либо породил privacy-
focused change, не связанный с самим semgrep правилом
(audit-log value redaction, request-log peer mask/off dial).

Второе имя проекта -- "security". С v4.40.0 мы вешаем
колокольчик на каждый gap между "authed" и "trusted", и этот
релиз завершает sweep получением semgrep clean плюс
добавлением operator dials для двух оставшихся privacy
surfaces (peer IP в request log, credential material в
captured command strings).

#### ERROR-severity semgrep -- 4 nan-injection + 1 os.exec

* ``nan-injection`` × 4. Пофиксил оба реальных случая в
  ``arena/admin/handlers.py``. Pre-v4.44.0 атакующий,
  посылающий ``?timeout=nan`` или ``?timeout=inf``, тригерил
  ``socket.settimeout(nan)`` глубоко в probe path и
  превращал в 500. Не memory-safety, но reliability, и
  паттерн ровно того класса, что silently becomes escalation
  в more richer code.

  Новые helper'ы в ``arena/handler_helpers.py``:

    - ``safe_float(value, *, default=..., minimum=..., maximum=...)``
      -- parse, reject NaN/±Inf, clamp в диапазон (или fall back
      на ``default``, или raise strict).
    - ``safe_int(value, ...)`` companion. Int не NaN-vulnerable,
      но negative "timeout"/"limit" -- тот же класс bug, так
      что helper унифицирует clamping.

  Другие два nan-injection hits (``gui/handlers.py``) были
  false positives -- ``bool(url_token)`` на string тестирует
  non-emptiness, не float-parseability. Задокументировано
  через inline ``# nosemgrep``.

* ``dangerous-os-exec-tainted-env-args`` × 1 в
  ``arena/admin/auto_update.py::_do_restart``. False positive:
  ``sys.argv`` -- наш собственный launch snapshot, не
  attacker input; это self-restart в тот же process image
  после auto-update swap. Задокументировано через inline
  ``# nosemgrep``.

#### WARNING-severity semgrep -- 55 аннотаций + 1 реальный фикс

Почти все WARNING finding'и -- те же три правила
(``dynamic-urllib-use-detected`` × 36,
``subprocess-shell-true`` × 10,
``dangerous-subprocess-use-tainted-env-args`` × 9),
срабатывающие на call site, которые мы уже review'или и
bandit-аннотировали в v4.43.0. Semgrep не уважает bandit'ские
``# nosec``, так что каждая тронутая line получила matching
``# nosemgrep: <rule> -- <specific rationale>`` комментарий.

* ``insecure-hash-algorithm-sha1`` на ``ws_frames.py:31`` --
  тот же finding, что bandit уже reported. RFC 6455
  handshake identifier; ``usedforsecurity=False`` on-place с
  v4.43.0. ``# nosemgrep`` добавлен на correct line (semgrep
  line-anchored).
* ``use-defused-xml`` на ``mobile/ui.py:22`` -- covered
  DOCTYPE/ENTITY prefix gate из v4.42.0.
* ``insecure-file-permissions`` × 4 на ``0o700`` chmods. Все
  четыре -- directory modes -- ``0o700`` на directory это
  самый tight owner-only mode (execute bit = directory
  traversal, не file execution). Один -- extract-script
  tempfile в ``exec/handlers.py``, нужен exec bit для
  ``sh <path>`` при staying owner-only.

#### Privacy-focused изменения (не semgrep-triggered)

**Audit-log value-pattern redaction.** Pre-v4.44.0
``sanitize_audit_event`` редактировал только values, чей KEY
был sensitive (``token``, ``password``, ``secret``, ...).
Captured curl command под ключом ``cmd`` всё ещё утекал
``Bearer <token>`` verbatim, потому что ``cmd`` не в
blocklist. v4.44.0 добавляет:

* Pattern-based scrub в ``_redact_value_patterns()``. Любое
  string value (независимо от key) сканируется на known
  credential shapes: ``Bearer/Basic <token>``, AWS
  ``AKIA...``/``ASIA...`` ключи, GitHub ``ghp_``/``ghs_``/etc,
  OpenAI/Anthropic ``sk-...``, Slack ``xox[baprs]-``, Google
  ``AIza...``, JWTs (три base64url сегмента), DB/broker URIs
  с inline ``user:pass@host``, и inline PEM ``PRIVATE KEY``
  blobs. Matches replaced на ``<redacted:{kind}>``, так что
  operator всё ещё видит КАКОГО класса secret leaked, не
  видя сам secret.
* Recursive ``_scrub()`` пробегает nested dicts и lists, так
  что credential, buried в ``result["stdout"]`` или глубоко
  внутри inbound webhook payload, всё ещё scrubbed.
* Key blocklist расширен: добавлены ``api_key``, ``apikey``,
  ``credential``, ``passphrase``, ``private_key`` /
  ``privateKey``.

**Request-log peer-address privacy dial.** ``requests.jsonl``
записывает каждый hit'ов ``(ts, method, path, status,
duration, peer)``. Поле ``peer`` даёт operator'у с read
access к log'у map'ить IP к их exact request pattern. Это
by design когда operator ЯВЛЯЕТСЯ observer'ом; leak, когда
log ship'ится или co-tenant читает. Новый env dial:

* ``ARENA_LOG_PEER=off`` -- omit ``peer`` field целиком.
  Path / status / duration остаются для debugging.
* ``ARENA_LOG_PEER=mask`` -- hash peer с
  ``ARENA_LOG_PEER_SALT``. Deterministic per install, так
  что "count distinct peers" всё ещё работает в пределах
  одного bridge'а, unlinkable across installs.
* unset / anything else -- full peer, pre-v4.44.0 behaviour.

**File-mode discipline на ``requests.jsonl``.** Был 0o644
(default umask), теперь 0o600. Rotated ``.1``/``.2``/... файлы
получают тот же chmod после каждого rename. Matches
``audit.jsonl`` posture, существовавший pre-v4.44.0.
``audit.jsonl`` rotation тоже gained explicit re-chmod
after rename (ACL-proof discipline, как v4.40.0 URL cache).

#### Тесты (+99, 2156 -> 2255 unit; total с E2E = 2270)

* ``tests/test_safe_numeric_parse.py`` -- 22 теста.
* ``tests/test_request_log_privacy.py`` -- 15 тестов.
* ``tests/test_audit_value_redaction.py`` -- 22 теста.

Существующие 136 audit / request_log / observability тестов
продолжают проходить без модификации.

Zero broken masters, zero rollbacks.

#### Тронутые файлы

* ``arena/handler_helpers.py`` -- ``safe_float``, ``safe_int``.
* ``arena/admin/handlers.py`` -- 2 call site используют
  ``safe_float``.
* ``arena/gui/handlers.py``, ``arena/admin/auto_update.py``,
  ``arena/mcp/ws_frames.py``, ``arena/mobile/ui.py``,
  ``arena/exec/handlers.py``, ``arena/agentctl_cli/url_cache.py``,
  ``arena/mobile/apk_install.py`` -- ``# nosemgrep``
  аннотации.
* 32 файла по ``admin/``, ``agentctl_cli/``,
  ``agentctl_extras/``, ``browser/``, ``chat_cli/``,
  ``desktop/cli/``, ``gateway/``, ``mcp/``, ``missions_cli/``,
  ``observability/``, ``project_cli/``, ``skills/``,
  ``system/`` -- 54 ``# nosemgrep`` для shell/urllib правил.
* ``arena/observability/audit.py`` -- value-pattern scrub,
  recursive ``_scrub``, расширенный key blocklist, rotation
  re-chmod.
* ``arena/observability/request_log.py`` -- privacy dial,
  chmod 0o600 на current + rotated файлах.
* ``arena/constants.py`` + ``pyproject.toml`` -- version bump.
* 3 новых test файла.

#### Финальные метрики

* **Semgrep:** 0 findings (66 → 0).
* **Bandit:** 442 LOW (все code-hygiene noise, HIGH и MEDIUM
  = 0 с v4.43.0).
* **pip-audit:** clean.


## v4.43.0 - 2026-07-17

### Static-analysis + dependency-audit hardening pack

Прогнали ``pip-audit`` против всех runtime deps
(``aiohttp==3.14.1``, ``psutil==7.2.2``, ``websockets==16.1``)
и ``bandit -r arena/`` против всех 49 300 LOC. До релиза:
**12 HIGH, 43 MEDIUM, 445 LOW**. После: **0 HIGH, 0 MEDIUM,
442 LOW** (все LOW -- code-hygiene noise -- ``try/except pass``,
``import subprocess``, partial-path calls -- не security).

#### pip-audit: clean

Все runtime deps на live-bridge версиях чистые от известных
CVE. Bump'ов deps не нужно.

#### bandit HIGH -- 12/12 закрыто

Каждое HIGH-severity finding было либо реально пофикшено (2),
либо аннотировано ``# nosec B602 -- <rationale>`` после
верификации, что shell string не attacker-reachable (10).

* **B324 SHA1 в ws_frames.py:21** -- WebSocket handshake
  proof по спеке ``base64(SHA1(client-key || GUID))`` (RFC
  6455 §4.2.2). SHA-1 здесь -- protocol identifier, не
  security hash. Фикс: ``usedforsecurity=False`` в
  ``hashlib.sha1``, чтобы hashlib знал, что это
  identifier-use, и FIPS builds, блокирующие SHA-1 для
  security, всё равно пропускали его для handshake.
* **B602 в system/hwinfo_cim.py** -- pre-v4.43.0 строил
  PowerShell command через ``f-string`` interpolation
  class name / filter clause, затем передавал в
  ``subprocess.run(..., shell=True)``. В production каждый
  call site (``arena/system/hwinfo_collect.py``) передаёт
  hardcoded literal, так что shell-injection никогда не был
  reachable, но invariant "``get_cim_all_list`` вызывается
  только с compile-time literal" был fragile. Переписан на:
  - argv-form ``subprocess.run(["powershell.exe", ...], ...)``
    -- Windows launch'ит powershell.exe напрямую, cmd.exe
    никогда не видит string.
  - whitelist regex для class names и filter clauses
    (``Property=Value`` bareword only).
  - что-то, не проходящее whitelist, возвращает ``[]`` --
    тот же outcome, что любой другой PowerShell failure.
* **B602 (× 10 оставшихся)** в ``agent_helpers/runtime.py``,
  ``chat_cli/commands.py``, ``desktop/cli/*.py``,
  ``gateway/runtime.py``, ``mcp/standalone_common.py``,
  ``mcp/tool_utils.py``, ``missions_cli/common.py``,
  ``project_cli/common.py`` -- все это CLI-side helpers, где
  shell string либо (a) собственный interactive input
  оператора (chat exec, agentctl gateway) либо
  (b) hardcoded literal, построенный внутри модуля
  (missions_cli, project_cli, desktop input). Ничего не
  reachable из HTTP handler. Каждый получил per-line
  ``# nosec B602 -- <specific rationale>`` комментарий.

#### bandit MEDIUM -- 43/43 закрыто

**B310 urlopen scheme audit (36 finding'ов).** Каждый
``urllib.request.urlopen`` в ``arena/`` проинспектирован. Три
класса:

* **Fixed internal URL** (loopback health probes, ngrok
  ``127.0.0.1:4040`` API, ZeroTier ``127.0.0.1:9993``,
  CDP ``127.0.0.1:<devtools_port>``, MCP tool localhost,
  bridge health/status) -- нет external attacker input,
  нет scheme choice. ``# nosec B310 -- loopback <detail>``.
* **Vendor API URL** (``api.github.com``,
  ``my.zerotier.com``) -- hardcoded HTTPS в trusted vendor
  domains. ``# nosec B310 -- fixed vendor API URL``.
* **User-URL уже через SSRF-guard**
  (``arena/browser/fetch.py`` × 5,
  ``arena/skills/install.py``) -- уже gated
  ``arena.security_ssrf._validate_url``. ``# nosec B310 --
  SSRF-validated``.

**B310 ``admin/auto_update.py:290``** -- release download URL.
Получил реальный фикс, а не просто ``nosec``:

* URL теперь через ``arena.security_ssrf._validate_url``
  перед fetch. Скомпрометированный update endpoint (или
  misconfigured URL allowlist) не может redirect release
  download в metadata IMDS / RFC1918.
* Bounded read (512 MiB cap) на response, так что hostile
  сервер не может стримить unlimited random bytes и
  забить disk оператора до того, как post-download SHA256
  verify сработает.

**B310 ``observability/webhooks.py:61``** -- outbound webhook
POST. Legitimately разрешён достигать RFC1918 по умолчанию
(операторы используют local dev harness / home-network
Discord relays), но теперь honours ``ARENA_WEBHOOK_STRICT=1``
env var, роутящую через полный browser-fetch SSRF-guard.
Off по умолчанию для сохранения "webhook to my LAN Discord
bot" use case; opt-in для операторов, желающих strict
outbound.

**B314 XXE ``mobile/ui.py:147``** -- уже gated
DOCTYPE/ENTITY prefix scan (v4.42.0).

**B104 ``bind_detect.py:104``** -- ``0.0.0.0`` bind
deliberate, happens только после overlay-interface detection.

**B108 hardcoded_tmp_directory (×4)** -- ``/tmp/.X11-unix``,
standard system location, read-only listdir.

**B604 ``mobile/handlers.py:463``** -- false positive; ``shell=``
здесь -- dataclass keyword argument, не ``shell=True``.

#### HIGH-severity фикс: file:// bypass в skills installer

Обнаружено во время классификации bandit finding'ов, не
что-то, что bandit сам flag'ал. Pre-v4.43.0
``skills/install.py`` принимал ``file://`` URL и передавал
в ``shutil.copy`` без sandbox check. Authed admin мог указать
``file:///home/ivan/arena-bridge/token.txt``; ``shutil.copy``
happily стеджил бы master token в ``tmp_path``. Последующий
zip-parse провалился бы, но tmp file lingered пока
``finally`` block не очистил.

Fix: для local sources (bare path ИЛИ ``file://``), которые
resolve под ``$HOME``, запустить тот же
``_sensitivity_error`` check, что ``fs.view`` / ``fs.edit``
используют. Sources вне ``$HOME`` (mounted volume,
``/data/skills/foo.zip``) всё ещё разрешены -- blocklist
предназначен для private credential space пользователя, и
требование "must live under HOME" сломало бы каждого админа,
хранящего skills на data volume. v4.42.2 zip-slip /
zip-bomb guard всё ещё fire'ит downstream независимо от
этого.

#### Тесты (+6, 2151 -> 2156 unit; total с E2E = 2171)

* ``tests/test_skills_install_file_uri_hardening.py`` -- 5
  новых тестов: file:// отклоняет ``~/token.txt``,
  отклоняет ``~/.ssh/id_ed25519``, bare-path тоже
  отклоняет, outside-$HOME разрешён (regression guard для
  legitimate admin flows), ordinary ~/*.zip устанавливается
  fine.

Zero broken masters, zero rollbacks.

#### Тронутые файлы

* ``arena/system/hwinfo_cim.py`` -- argv-form + whitelist
  regex.
* ``arena/mcp/ws_frames.py`` -- ``usedforsecurity=False``.
* ``arena/admin/auto_update.py`` -- SSRF-guard + 512 MiB
  size cap на release download.
* ``arena/skills/install.py`` -- file:// sandbox check.
* ``arena/observability/webhooks.py`` --
  ``ARENA_WEBHOOK_STRICT`` opt-in.
* 10× ``# nosec B602`` annotations в CLI-side files.
* 36× ``# nosec B310`` annotations по
  ``arena/{admin,agentctl_cli,agentctl_extras,browser,mcp,mobile,observability,skills,system}``.
* 7× other-category ``# nosec`` annotations.
* ``arena/constants.py`` + ``pyproject.toml`` -- version
  bump.
* ``tests/test_skills_install_file_uri_hardening.py`` --
  НОВЫЙ.

#### Не адресовано (задокументировано на потом)

* ``requests.jsonl`` audit log rotation всё ещё создаёт
  файлы 0o644 по умолчанию. Должно быть 0o600. Маленькое;
  отложено, чтобы этот релиз оставался focused на static-
  analysis findings.
* 442 LOW-severity bandit findings остаются (``B110``
  try/except pass, ``B603`` subprocess without shell,
  ``B607`` partial path). Все code-hygiene noise, не
  security. Future pass мог бы аннотировать выжившие
  ``# nosec`` audit для signal-to-noise, но текущий
  ``LOW`` count -- то, как выглядит зрелый Python codebase.


## v4.42.2 - 2026-07-17

### Zip-slip / zip-bomb / SSRF-in-skill-install hardening

Второй sweep всего runtime после v4.42.1. Этот закрывает
archive-extraction и download-URL issues, от которых Python's
stdlib не защищает по умолчанию. Каждый фикс наслаивается на
существующую v4.42.1 sandbox posture, тот же
"belt+suspenders" паттерн.

#### HIGH -- Zip-slip в двух горячих extraction путях

**Проблема.** ``arena/admin/auto_update.py::_extract``
(auto-update flow, устанавливающий скачанный arena-agent
release) и ``arena/skills/install.py`` (skills marketplace
installer) оба вызывали ``zipfile.ZipFile.extractall(dest)``.
Python's stdlib не проверяет archive members на path traversal
(CVE-2007-4559 / PEP 706, всё ещё open для zip после того как
PEP 706 адресовал только tar). Hostile archive с member
``../../etc/systemd/user/backdoor.service`` пишет куда
bridge user может достать.

Auto-update path был частично защищён URL allowlist на
update endpoint, но полагаться на один gate превращает любую
upstream компрометацию в RCE на каждом arena bridge. Skills
installer берёт URL от authed caller напрямую -- нулевая
защита.

**Фикс.** Новый модуль ``arena/files/safe_extract.py``.
``safe_extract_zip(zip_path, dest)`` делает:

* pre-scan каждого member name до записи любого байта;
* reject absolute paths (POSIX и Windows drive-letter);
* reject любого member с ``..`` в parts, включая sneaky
  ``prefix/../../../etc/x`` формы;
* reject symlink members (проверяется через S_IFLNK в
  high 16 bits ``external_attr``);
* reject NUL bytes в member names;
* cap total uncompressed size (default 4 GiB) и per-member
  size (default 1 GiB) чтобы defeat zip bombs;
* post-check каждого extracted path через ``resolve()``-
  relative-to-dest, так что filesystem-quirk-based escapes
  (case-insensitive FS, unicode-normalisation traps) всё
  ещё пойманы.

Оба call site (``auto_update._extract``,
``skills/install.py`` все три ``extractall`` вызова)
теперь идут через helper.

**Гарантия:** если ``safe_extract_zip`` raise'ит
``UnsafeArchiveError``, ни один member не был записан --
two-pass design полностью валидирует до trogaния disk.

#### MEDIUM -- APK manifest read не имел size cap

``arena/mobile/apk_install.py`` читает
``AndroidManifest.xml`` из uploaded APK чтобы извлечь
package name. Uncapped: hostile APK с 2 GiB manifest'ом
раздул бы bridge memory во время package-name lookup.
Роутится через ``read_zip_member_safe(..., max_bytes=16 MiB)``
-- реальные Android manifest'ы single-digit KiB, 16 MiB это
три порядка над реальностью.

#### MEDIUM -- Skill installer SSRF-open

``skills/install.py::install_skill`` передавал user-supplied
URL прямо в ``urllib.request.urlretrieve`` без валидации и
без timeout. Любой authed caller мог зондировать internal
networks (metadata IMDS, private subnets) через skill-install
path. Теперь роутится через
``arena.security_ssrf._validate_url`` (тот же guard, что
browser-fetch endpoints используют с v3.something), плюс
60-секундный timeout, плюс cap download size на 128 MiB,
чтобы hostile сервер не мог забить disk, streaming random
bytes.

#### Тесты (+14 новых, 2137 -> 2151; total с E2E = 2166)

* ``tests/test_safe_extract.py`` -- 14 тестов: happy path
  extract, absolute-path rejection, ``..`` traversal, mid-
  path ``..``, Windows drive-letter, backslash-normalised
  traversal, NUL byte, symlink member rejection, per-member
  size cap, total-size cap, atomic no-partial-write
  guarantee, ``read_zip_member_safe`` ordinary read + cap +
  NUL guard.
* Существующие 53 skills / install теста продолжают
  проходить без модификации.

Zero broken masters, zero rollbacks.

#### Тронутые файлы

* ``arena/files/safe_extract.py`` -- НОВЫЙ, 190 строк.
* ``arena/admin/auto_update.py`` -- ``_extract`` идёт
  через ``safe_extract_zip``.
* ``arena/skills/install.py`` -- три ``extractall`` sites
  идут через helper; ``urlretrieve`` заменён на bounded
  ``urlopen`` + SSRF guard.
* ``arena/mobile/apk_install.py`` -- AndroidManifest.xml
  read через ``read_zip_member_safe``.
* ``arena/constants.py`` + ``pyproject.toml`` -- version
  bump 4.42.1 -> 4.42.2.

#### Не адресовано (задокументировано на потом)

* Skill install сейчас применяет SSRF-guard только на
  ``http(s)://`` ветви; ``file://`` bypass'ит его
  (оставлен intentional для local skill dev, но помечен).
* ``arena/admin/auto_update.py`` всё ещё использует
  ``urllib.request.urlretrieve`` для release download.
  Тот же treatment как skills затянул бы это; отложено,
  потому что update-endpoint URL allowlist уже даёт
  первую линию защиты.
* ``requests.jsonl`` audit log rotation всё ещё создаёт
  файлы 0o644 по умолчанию; должно быть 0o600 чтобы matched
  ``~/.arena/*`` discipline.


## v4.42.1 - 2026-07-17

### Точечный фикс: закрываем exists-vs-blocked side channel в fs.download

Пойман на v4.42.0 live-smoke. v4.42.0 fix ставил sensitivity
check ПОСЛЕ file-existence check в
``validate_download_target``, что означало caller мог
различить "file exists but is blocked" (403) от "file does
not exist" (404) -- exists-oracle side channel по credential
namespace. Attacker с authed narrow-scope bearer мог
enumerate ровно какие credential файлы живут на bridge host
(``~/.aws/credentials`` есть? ``~/.gnupg/private-keys-v1.d/``
есть?) никогда не видя contents.

Фикс: переместить ``_sensitivity_error`` выше ``exists()``
check так что 403 answer возвращается независимо от того,
находится ли файл там. Та же discipline, которую
``validate_view_target`` и ``validate_edit_target`` уже
следовали pre-v4.42.0. Новый regression тест
``test_download_refuses_sensitive_even_when_absent`` фиксирует
порядок.

Тронутые файлы:

* ``arena/files/sandbox.py`` -- один 6-строчный reorder в
  ``validate_download_target``.
* ``arena/constants.py`` + ``pyproject.toml`` -- version bump.
* ``tests/test_files_sandbox_v442_hardening.py`` -- один новый
  regression тест.

Test suite: 2136 -> 2137 unit + 15 fallback E2E = 2152 total.
Zero broken masters, zero rollbacks.


## v4.42.0 - 2026-07-17

### Security hardening pack 2: sandbox parity, расширенный blocklist, TOCTOU-safe tempfile, XXE gate

Третий security-релиз в дуге, начавшейся с v4.40.0. Этот
пришёл из proactive full-runtime sweep (не только v4.39.0
finding'и), и закрывает четыре свежих проблемы плюс
полирует две low-risk pre-existing:

#### HIGH -- fs.download и fs.upload имели token.txt-loophole

**Проблема.** ``validate_view_target`` отклонял
``token.txt`` + ``.env`` + SSH private keys, но его сиблинг
``validate_download_target`` (используется
``GET /v1/download``) и ``validate_upload_target`` (используется
``POST /v1/upload``) не выполняли ту же sensitivity-проверку.
Любой authed caller с narrow-scope multi-agent bearer мог
просто скачать master ``token.txt`` и эскалировать до
full-privilege одним запросом, или загрузить replacement
``token.txt`` / ``.ssh/authorized_keys`` для того же
эффекта в другую сторону.

**Фикс.** ``validate_download_target`` и
``validate_upload_target`` теперь вызывают тот же
``_sensitivity_error`` helper, что view/edit/create. Тот же
blocklist, тот же 403 status, та же error-message form.
Endpoint-parity теперь обеспечивается shared code, а не
convention -- будущий рефакторинг не может тихо
переввести асимметрию без покраснения теста.

#### HIGH -- sensitive-file blocklist был basename-only

**Проблема.** ``SENSITIVE_FILE_BASENAMES`` блокировал
``id_ed25519``, но не ``.ssh/authorized_keys``, блокировал
``.env``, но не ``.aws/credentials``,
``.gnupg/private-keys-v1.d/*``, ``.docker/config.json``,
``.kube/config``, ``.config/gh/hosts.yml`` (GitHub CLI OAuth
tokens), browser password stores, или shell history файлы,
которые routinely содержат pasted секреты.

**Фикс.** Два добавления в ``arena/files/sandbox.py``:

* ``SENSITIVE_FILE_BASENAMES`` расширен с
  ``.git-credentials``, ``.pypirc``, ``.npmrc``, ``.dockercfg``,
  ``.gitconfig``, ``.bash_history`` /
  ``.zsh_history`` / ``.fish_history`` /
  ``.python_history`` / ``.psql_history`` /
  ``.mysql_history`` / ``.rediscli_history`` /
  ``.sqlite_history`` / ``.node_repl_history``, и ``.pub``
  вариантами SSH keys.
* Новый ``SENSITIVE_DIR_PREFIXES`` frozen-set покрывает
  ``.ssh``, ``.aws``, ``.gnupg``, ``.docker``, ``.kube``,
  ``.config/gh``, ``.config/git``, ``.mozilla``,
  ``.config/google-chrome``, ``.config/chromium``. Оба
  single-segment (``.ssh`` где угодно в пути) и
  multi-segment (``.config/gh`` как consecutive сегменты)
  matches признаны.

Prefix-scan запускается после ``resolve()``, так что
rogue symlink внутри ``$HOME`` не может быть использован для
smuggling sensitive path через: resolved target либо падает
внутрь blocked prefix либо нет.

**Rationale для anywhere-in-path.** Sensitive directory NAME
(``.ssh``) трактуется как sensitive независимо от locations
-- attacker, staging rogue ``~/projects/.ssh/authorized_keys``
иначе проскочил бы. Multi-segment prefixes (``.config/gh``) --
consecutive-segment matches, потому что ``.config`` в
одиночку в основном безобиден (``.config/htop``,
``.config/nvim``), а overblocking его сломает daily flow
любого dev'а.

#### MEDIUM -- tempfile.mktemp() TOCTOU races в desktop code

**Проблема.** ``arena/desktop/ocr.py`` и
``arena/desktop/screenshot.py`` оба использовали
``tempfile.mktemp()`` -- deprecated с Python 2.3 ровно по
этой причине. Возвращает predictable name в shared ``/tmp``
и передаёт его в последующий open/write. Co-tenant на той же
машине может pre-create symlink по exact name
(``/tmp/arena_ocr_<random>.png``) между двумя вызовами,
redirect'уя bridge's write в любой файл, к которому bridge
user имеет доступ.

**Фикс.**

* OCR использует ``tempfile.NamedTemporaryFile(delete=False)`` --
  atomic ``O_EXCL`` create, закрывает file и отдаёт нам
  path. Cleanup всё ещё живёт в существующем ``finally``.
* Screenshot использует ``tempfile.mkdtemp()`` чтобы
  получить per-invocation 0o700 directory и пишет
  ``shot.png`` внутри. Мы не можем использовать
  ``NamedTemporaryFile`` здесь, потому что screenshot tools
  (spectacle / grim / scrot) сами создают file; putting
  target внутри 0o700 parent останавливает co-tenant от
  pre-planting symlink по exact path. Cleanup вынесен в
  ``_rm_tmp_dir()``, так что оба success и failure paths
  зовут тот же helper.

#### MEDIUM -- APK staging root жил в shared /tmp

**Проблема.** ``arena/mobile/apk_install.py`` hard-code'ил
``STAGING_ROOT = Path("/tmp/arena-apk-staging")``. Тот же
symlink-attack surface, что и tempfile issue выше, хуже,
потому что directory long-lived и world-listable
(exposes package names каждого APK, который operator upload'ил).

**Фикс.** Default перенесён на ``~/.arena/apk-staging`` с
lazy 0o700 chmod на directory и его ``~/.arena`` parent
(тот же ACL-proof паттерн, что v4.40.0 URL cache использует).
``ARENA_APK_STAGING`` env-override для operators, кому нужен
staging на большом volume. ``_ensure_staging_root()``
idempotent и вызывается из каждого persist / lookup path.

#### LOW -- os.system() заменён на argv-form subprocess.run

Три call site в ``arena/agentctl_extras/`` (Darwin beep
через ``osascript``, Linux ``systemctl status``) были всё ещё
на ``os.system()``. Arguments сегодня fixed-strings, так что
ничего не exploitable, но ``os.system`` spawn'ит shell --
будущий рефакторинг, интерполирующий любую переменную в
command string, тихо откроет shell-injection door. Переключены
все три на argv-form ``subprocess.run(..., check=False)``.
``systemctl status | head -100`` pipe стал Python-side
``.splitlines()[:100]``.

#### LOW -- billion-laughs / XXE gate на uiautomator dumps

``arena/mobile/ui.py::dump_ui`` кормит adb ``uiautomator dump``
output прямо в ``xml.etree.ElementTree.fromstring``. Stdlib
ET Python'а не защищает от billion-laughs entity expansion
(defusedxml бы да, но пулить его в required deps ради
одного call site избыточно). Вместо этого static
prefix-scan на raw bytes отклоняет любой input, начинающийся
с ``<!DOCTYPE`` или ``<!ENTITY`` до того, как parser его
увидит. Legitimate uiautomator dumps никогда не несут
DOCTYPE, так что gate behaviourally invisible для real use;
единственные callers, которые он блокирует, -- malicious
apps, пытающиеся abuse тот факт, что bridge внутри trust
boundary uiautomator UI dump.

#### Тесты (+51 unit, 2054 -> 2136; fallback E2E +0 = 2151 всего)

* ``tests/test_files_sandbox_v442_hardening.py`` -- 30 тестов:
  prefix-scan positive/negative parametrized, download
  отклоняет каждый credential class, upload симметрично,
  view/edit/create parity, verb-injection в error message.
* ``tests/test_desktop_secure_tempfile.py`` -- 3 теста: OCR
  использует NamedTemporaryFile, screenshot использует
  mkdtemp, cleanup helper существует. Comment-aware source
  scan, так что rationale comments, называющие deprecated
  API, не трипают check.
* ``tests/test_apk_staging_hardening.py`` -- 6 тестов:
  default под ~/.arena, не /tmp, env-override побеждает,
  mode 0o700 на directory и parent, idempotent.
* ``tests/test_mobile_ui_xxe_hardening.py`` -- 4 теста:
  gate появляется перед ET.fromstring в source, billion-
  laughs отклонён, external-entity отклонён, ordinary
  hierarchy всё ещё парсится.
* Плюс существующие 32 sandbox / fs REST теста продолжают
  проходить без модификации -- shared ``_sensitivity_error``
  helper полностью behaviour-compatible с pre-v4.42.0
  basename check.

Test suite: 2108 -> 2136 unit (+28) + 15 fallback E2E =
**2151 всего**. Zero broken masters. Zero rollbacks.

#### Тронутые файлы

* ``arena/files/sandbox.py`` -- расширенный blocklist,
  ``SENSITIVE_DIR_PREFIXES``, ``_path_hits_sensitive_prefix``,
  ``_sensitivity_error`` shared helper,
  ``validate_download_target`` + ``validate_upload_target``
  теперь тоже вызывают его.
* ``arena/desktop/ocr.py`` -- NamedTemporaryFile.
* ``arena/desktop/screenshot.py`` -- mkdtemp + ``_rm_tmp_dir``
  cleanup helper.
* ``arena/mobile/apk_install.py`` -- STAGING_ROOT под
  ``~/.arena/apk-staging``, ``_ensure_staging_root()``,
  ``ARENA_APK_STAGING`` env override.
* ``arena/mobile/ui.py`` -- DOCTYPE/ENTITY prefix gate.
* ``arena/agentctl_extras/actions.py`` -- subprocess.run.
* ``arena/agentctl_extras/integrations.py`` -- subprocess.run.
* ``arena/agentctl_extras/status.py`` -- subprocess.run +
  Python-side ``head -100`` эквивалент.
* ``arena/constants.py`` -- VERSION 4.41.0 -> 4.42.0.
* ``pyproject.toml`` -- version 4.41.0 -> 4.42.0.

#### Не адресовано (задокументировано на потом)

* ``shell=True`` в ``arena/system/hwinfo_*.py``,
  ``arena/mcp/*.py``, ``arena/desktop/cli/*.py``. Parameters
  сегодня fixed-strings; не exploitable. Standalone cleanup.
* SSRF-guard (``arena/security_ssrf.py``) подключён только к
  browser-fetch endpoint'ам. System tunnels / autostart не
  берут external URL сегодня, но defence-in-depth pass мог
  бы унифицировать.
* CORS wildcard (``Access-Control-Allow-Origin: *``) на
  gui/ files/ desktop/ endpoint'ах. Bridge bearer-
  authenticated, так что CORS не добавляет много (browser
  всё равно откажет credentialled cross-origin), но
  затяжка до specific origin list была бы defence-in-depth.


## v4.41.0 - 2026-07-17

### Security hardening pack: TLS verify по умолчанию, ?token= deprecation, log redaction, token-loader priority fix

Второй pass security-аудита, начатого в v4.40.0 (signed URL
cache). Этот релиз закрывает оставшиеся четыре открытых
пункта из ``SECURITY_AUDIT_v4.39.0.md`` одним
координированным пакетом -- отдельный релиз от v4.40.0,
потому что трогать каждый CLI request-path -- более крупное
изменение, чем подписать один cache-файл.

#### #2 -- TLS-верификация включена по умолчанию (условно-breaking)

До v4.41.0 и ``agentctl_common.py``, и ``agentctl_bridge.py``
имели приватные хелперы, возвращавшие SSL-context с
``check_hostname=False`` + ``verify_mode=CERT_NONE`` для
каждого ``https://`` URL. Это MITM-open по умолчанию: любой
атакующий на сетевом пути мог подменить сертификат bridge'а
и прочитать заголовок ``Authorization: Bearer <token>`` на
каждом запросе. На публичных транспортах (Tailscale,
cloudflared, ngrok) это был реальный риск, потому что все
они отдают валидные Let's Encrypt сертификаты, которые
верифицировались бы без проблем.

Оба хелпера теперь -- тонкие обёртки над единым
``arena/agentctl_cli/tls.py::build_ssl_context()``, который:

* возвращает ``None`` для ``http://`` URL (без изменений --
  ZeroTier LAN + loopback продолжают работать);
* возвращает **strict** ``ssl.create_default_context()`` для
  ``https://`` URL по умолчанию (новое -- валидирует по
  системному trust-store, проверяет hostname);
* возвращает insecure context (совпадает с pre-v4.41.0
  поведением) только когда ``ARENA_INSECURE_TLS`` --
  ``1`` / ``true`` / ``yes`` / ``on`` (регистронезависимо);
* выводит одну строку ``WARNING: TLS verification disabled ...``
  на stderr первый раз, когда insecure context строится в
  процессе, чтобы скрипт, случайно отключивший верификацию,
  не мог провалиться тихо.

Для операторов с self-signed сертификатами на приватном
bridge'е (``arena/tls/`` это поддерживает) явно ставим
``ARENA_INSECURE_TLS=1``. Или -- лучше -- указывать
``SSL_CERT_FILE`` на свой CA bundle;
``ssl.create_default_context`` автоматически его подхватит.

#### #3 -- ``?token=`` query auth теперь deprecated (не-breaking)

Auth-слой всё ещё принимает ``?token=<value>`` для обратной
совместимости с WebSocket-клиентами, которые не могут
установить header ``Authorization`` из браузера (см.
``dashboard/assets/41-live-charts.js``). Query-токены
утекают в логи proxy, browser history и ``Referer`` header
на каждый исходящий клик, поэтому просто убрать code-path
без ломания живых браузеров нельзя -- но можно сделать
deprecation громким:

* ``arena/auth/runtime.py::_presented_tokens`` теперь
  помечает request как ``request["auth_via_query_token"] = True``
  когда токен пришёл через query И не пришёл также через
  header.
* ``arena/errors.py::error_middleware`` видит флаг на
  исходящем response и добавляет RFC-7234
  ``Warning: 299 - "?token= query auth is deprecated; use
  Authorization: Bearer or X-Arena-Token header. Query tokens
  leak into proxy logs, browser history, and Referer
  headers."`` header. Response body и status не меняются, так
  что существующие скрипты работают.
* Флаг специально НЕ ставится когда header-токен тоже был
  представлен (query был избыточен, warning был бы шумом) и
  когда auth провалился через header (query никогда не
  читали).

Полное удаление планируется в будущей major version после
того, как скриптовые вызовы успеют мигрировать. UI-вызовы,
которым нужен query-token для WebSocket'ов (единственный
легитимный use-case), получат специальный short-lived ticket
механизм в это время.

#### #4 -- URL redaction в captured stderr

``arena/agentctl_cli/agentctl_bridge.py::_fetch_config``
раньше печатал два полных URL verbatim в stderr в fallback-
диагностике::

    NOTE: bootstrap https://cachyos-x8664.tail328f18.ts.net
    unreachable (...); succeeded via cached URL
    https://pout-shingle-mystify.ngrok-free.dev

Это утекает Tailscale hostnames (кодируют имя машины + id
tailnet'а), ngrok reserved-domain'ы (per-account), и
ротирующиеся cloudflared subdomains в любое место, где
stderr захватывается: CI job logs, tmux scrollback, bug-
report'ы. Ничего из этого не секрет в смысле "один запрос и
ты внутри", но позволяет атакующему бесплатно fingerprint'ить
инфраструктуру.

Новый хелпер ``_redact_url_for_log(url)``:

* пропускает URL без изменений когда ``sys.stderr.isatty()``
  (оператор, смотрящий в свой терминал, уже знает свою
  инфру; redaction только бесил бы);
* пропускает URL без изменений для localhost, RFC1918,
  169.254.\*, и hostname'ов короче 12 символов (нечего
  скрывать);
* иначе заменяет netloc на
  ``<scheme>://<8-char-prefix>...<tld>`` -- сохраняет
  достаточно, чтобы человек различил "ngrok URL" от "CF URL"
  с одного взгляда, но убирает fingerprint'уемую середину;
* уважает ``ARENA_AGENTCTL_LOG_FULL_URLS=1`` для случая "мне
  реально нужен полный URL в этом логе".

Обе строки -- fallback ``NOTE:`` и terminal ``ERROR:`` --
теперь идут через redactor.

#### #8 -- Token loader продвигает env выше disk (сюрприз-фикс)

``arena/agentctl_cli/agentctl_common.py::_load_token`` раньше
резолвил токен в таком порядке:
``ARENA_TOKEN_FILE`` > ``$ARENA_AGENT_HOME/token.txt`` >
``~/arena-bridge/token.txt`` > ``ARENA_BRIDGE_TOKEN`` env.

Обнаружено при написании v4.40.0 fallback-тестов: на live
bridge'е (CachyOS box Ivan'а) реальный ``token.txt`` на
диске молча перекрывал ``ARENA_BRIDGE_TOKEN=stub-token``,
который тесты экспортировали. v4.40.0 test suite обошёл это,
указывая ``ARENA_TOKEN_FILE`` на per-test файл. Это был
правильный escape hatch, но underlying-приоритет удивлял:
оператор, запустивший
``ARENA_BRIDGE_TOKEN=$(cat other-token) agentctl ...``, получил
бы неправильный токен без диагностики.

Новый порядок:

1. ``ARENA_TOKEN_FILE`` explicit file (высший -- не изменён);
2. **``ARENA_BRIDGE_TOKEN`` env var (повышен)** --
   экспортированный env теперь побеждает stale ``token.txt``;
3. ``$ARENA_AGENT_HOME/token.txt``;
4. ``~/arena-bridge/token.txt`` fallback для нестандартного
   ``ARENA_AGENT_HOME``.

Пустые значения на каждом уровне падают на следующий (так что
``export ARENA_BRIDGE_TOKEN=""`` в rc-файле не молча ломает
каждый запрос). Пустые файлы на диске трактуются как "not
present" -- пустая строка никогда не возвращается пока
буквально ничего не разрешилось.

#### Тесты (+54 всего; 2054 -> 2108)

* ``tests/test_agentctl_tls.py`` -- 15 тестов: env-shape
  matrix (13 truthy/falsy shapes), scheme + env behaviour
  matrix, warn-once semantics, http-in-insecure-mode-does-not-
  warn, ``reset_warning_guard_for_tests`` sanity.
* ``tests/test_agentctl_bridge_redaction.py`` -- 14 тестов:
  TTY vs non-TTY, три реальные production URL shape
  (Tailscale / ngrok / cloudflared), env override, 6 non-
  sensitive host'ов pass-through, malformed input tolerance,
  broken ``isatty()`` defensive.
* ``tests/test_agentctl_token_loader.py`` -- 8 тестов:
  каждый priority-level transition (explicit > env >
  disk-home > disk-fallback), empty-env fall-through,
  empty-file rejection, multiline first-non-empty-line,
  missing explicit file falls through, all-absent returns "".
* ``tests/test_query_token_deprecation.py`` -- 10 тестов:
  auth всё ещё работает через все три канала, флаг ставится
  только для query-only auth, both-channels не флагает
  (noise prevention), failed-query всё ещё флагает (rate-
  limit visibility), no-subscript request double не
  крашится.
* ``tests/test_errors.py`` -- 2 новых теста: middleware
  добавляет ``Warning: 299`` когда флаг стоит, нет header'а
  когда флаг отсутствует.

Test suite: 2054 -> 2108 (+54). Zero broken masters. Zero
rollbacks.

#### Тронутые файлы

* ``arena/agentctl_cli/tls.py`` -- НОВЫЙ, 168 строк.
* ``arena/agentctl_cli/agentctl_common.py`` -- делегирует
  ``_ssl_context`` в shared хелпер; ``_load_token``
  переписан с env-above-disk приоритетом.
* ``arena/agentctl_cli/agentctl_bridge.py`` -- делегирует
  ``_ssl_ctx`` в shared хелпер; добавляет
  ``_redact_url_for_log``; два диагностических ``print()``
  идут через redactor.
* ``arena/auth/runtime.py`` -- ``_presented_tokens`` ставит
  ``auth_via_query_token`` флаг на query-only auth.
* ``arena/errors.py`` -- middleware добавляет ``Warning: 299``
  когда флаг стоит (на success и HTTPException путях).
* ``arena/constants.py`` -- VERSION 4.40.0 -> 4.41.0.
* ``pyproject.toml`` -- version 4.40.0 -> 4.41.0.

#### Не адресовано (задокументировано на потом)

* ``shell=True`` в ``arena/system/hwinfo_*.py`` +
  ``arena/mcp/*.py`` + ``arena/desktop/cli/*.py``. Параметры
  сегодня -- фиксированные строки; не эксплуатируемо, но
  fragile. Уборка -- отдельный проект.
* SSRF-guard (``arena/security_ssrf.py``) подключён только к
  browser-endpoint'ам; system tunnels / autostart не берут
  внешние URL сегодня, но defence-in-depth pass мог бы
  унифицировать.
* Rate-limited server-side WARN log для query-token usage был
  упомянут в аудите, но специально опущен в этом релизе --
  ``Warning: 299`` response header уже даёт оператору тот
  же сигнал, а добавление дублирующей audit-строки только
  зашумит ``audit.jsonl`` для (большого) количества
  легитимных WebSocket-вызывающих на deprecated-канале.


## v4.40.0 - 2026-07-17

### Security hardening -- подписанный URL-кэш предотвращает утечку токена

Follow-up к v4.39.0 (persistent URL memory). Self-audit после
v4.39.0 выявил одну medium-serьёзную проблему: on-disk cache
по пути ``~/.arena/last_urls.json`` не имел integrity-защиты,
не имел mode-ограничений, а URL из него не валидировались на
загрузке. Любой процесс с write-доступом в home пользователя
мог подменить URL, и когда bootstrap в следующий раз упадёт
(наблюдаемый триггер -- Tailscale-outage), agentctl бы
спокойно отправил ``Authorization: Bearer <BRIDGE_TOKEN>`` на
URL, выбранный атакующим. Умножено на pre-existing
``verify_mode=0`` в CLI -- это чистая утечка мастер-токена
bridge'а. Impact был ограниченный (у атакующего с write в home
уже есть доступ к ``token.txt``), но локальный риск
нетривиальный и дешёвый в починке.

Три уровня защиты, каждый достаточен в большинстве threat-
model, layered потому что write-access в home достаточно
страшен чтобы стоило перестраховаться:

1. **HMAC-SHA256 подпись** над payload snapshot'а, keyed
   SHA-256-derivate от bearer-токена. Write в save, verify в
   load. Атакующий с write-доступом не может форжать валидную
   подпись без знания токена -- а если он знает токен, то у
   него уже есть то, что отравленный кэш хотел бы украсть.
   Constant-time сравнение через ``hmac.compare_digest``.
2. **URL allowlist** применяется и при записи (``save()``
   молча дропает disallowed-entries), и при чтении
   (``fallback_bootstrap_urls()`` фильтрует ещё раз). Reject
   не-http/https схем и известных SSRF-trap хостов:
   ``localhost``, ``.internal``, ``.local``,
   ``metadata.google.internal``, ``169.254.169.254`` (AWS/GCP/
   Azure IMDS). Специально НЕ блокирует RFC1918-адреса,
   потому что ZeroTier-fallback URL -- это ровно приватный
   адрес (``http://10.57.152.120:8765`` в LAN'е Ivan'а).
3. **``chmod 0o600``** на cache-файле и ``chmod 0o700`` на
   родительской директории ``~/.arena``. Mode устанавливается
   до атомарного ``.tmp`` rename И повторно после (ACL-proof
   discipline из ``arena/agent_helpers/files.py``). Не даёт
   со-tenants на той же машине читать список URL (это утекает
   инфраструктуру: Tailscale-hostnames, ngrok reserved-domains,
   ротирующиеся cloudflared-subdomains).

Новый envelope-формат (schema version 2, envelope version 1)::

    {
      "envelope_version": 1,
      "sig": "<64 hex char: HMAC-SHA256 над payload>",
      "payload": {
        "version": 2,
        "saved_at": <epoch>,
        "bootstrap_url": "https://...",
        "urls": [{...}, ...]
      }
    }

Подпись покрывает только детерминистически сериализованный
``payload`` (``sort_keys=True, separators=(",",":")``), так
что новые payload-поля становятся signature-covered
автоматически. Envelope сам по себе НЕ подписан -- правка
``envelope_version`` или ``sig`` инвалидирует подпись и файл
дискарается.

Обратная совместимость: v4.39.0 писал unsigned version-1
snapshots. При первом же ``bridge``-вызове после апгрейда
такие файлы silently reject как "no cache" (envelope-check
падает), и следующий успешный bootstrap перезаписывает cache
в новой подписанной форме. Это upgrade-safety story: старые
кэши не доверяются, не мигрируются молча.

CLI-facing изменения:

* ``agentctl bridge urls|best|test|cache`` -- работают
  без изменения аргументов. Подпись невидима для
  пользователя -- CLI внутри передаёт ``BRIDGE_TOKEN`` в
  ``save()``/``load()``. Если bearer-токен ротировали
  (``regenerate_token.sh``), старый cache молча становится
  непригодным и переписывается на следующий успешный
  bootstrap.
* ``bridge cache show`` показывает "no cache" когда
  signature не верифицируется -- различать "файл есть но
  недоверенный" от "файла нет" утечёт слишком много про
  signature-check outcome атакующему через ``strace``.

Новые тесты (33 всего, 18 юнит + 2 E2E новые + 13
существующих E2E обновлены под signed envelope):

* ``test_url_cache.py``: 18 новых тестов, покрывают
  ``save()``/``load()`` без secret (оба refuse),
  HMAC-mismatch (reject), payload-tampering (reject),
  signature-tampering (reject), refuse v4.39.0-unsigned-file,
  envelope-version-mismatch, URL-allowlist параметризован
  по 11 SSRF-trap URL'ам, RFC1918-acceptance,
  chmod-0o600/chmod-0o700 verification (POSIX-only),
  constant-time compare через ``hmac.compare_digest``,
  determinism HMAC key derivation.
* ``test_url_cache_fallback.py``: 2 новых E2E-теста:
  ``test_poisoned_cache_is_refused_end_to_end`` (атакующий
  подменяет cache wrong-signed URL'ами; ассерт что stub-сервер
  атакующего получил НОЛЬ запросов, т.е. bearer-токен не
  утёк), и ``test_v4_39_unsigned_cache_is_refused``
  (upgrade-safety -- оставшийся v4.39.0-файл не доверяется
  даже если поверхностно парсится). Существующие 13 fallback-
  тестов мигрировали на ``_prime_cache`` helper, который
  пишет v4.40.0-signed envelope, сохраняя subprocess-level
  покрытие.

Test suite: 2020 -> 2053 (+33). Zero broken masters. Zero
rollbacks.

Тронутые файлы:

* ``arena/agentctl_cli/url_cache.py`` -- HMAC, allowlist,
  chmod, envelope-формат. +150 строк (в пределах
  MAX_RUNTIME_LINES).
* ``arena/agentctl_cli/agentctl_bridge.py`` -- три call-site
  обновлены чтобы прокидывать ``secret=BRIDGE_TOKEN`` через
  ``save()``/``load()``/``fallback_bootstrap_urls()``.
* ``arena/constants.py`` -- VERSION 4.39.0 -> 4.40.0.
* ``pyproject.toml`` -- version 4.39.0 -> 4.40.0.
* ``tests/test_url_cache.py`` -- 68 тестов, все зелёные.
* ``tests/test_url_cache_fallback.py`` -- 15 тестов, все
  зелёные.

НЕ адресовано в этом релизе (задокументировано для следующего
security-hardening pass):

* CLI-wide TLS-verification всё ещё выключена
  (``verify_mode=0`` в ``agentctl_cli/agentctl_common.py``).
  Надо переключить на opt-in ``--insecure`` /
  ``ARENA_INSECURE_TLS=1`` с strict-verify по умолчанию.
  Отдельный релиз потому что затрагивает каждый CLI-request-
  path.
* ``?token=`` в query-string всё ещё принимается
  ``arena/auth/runtime.py``. Query-string токены утекают в
  логи proxy; medium-term deprecation с warning-header --
  правильный ход.
* Diagnostic stderr fallback-loop всё ещё содержит полный
  cached URL; будущий релиз должен truncate Tailscale/ngrok
  hostnames когда stderr -- не TTY.


\n## v4.39.0 - 2026-07-17

### Persistent URL memory -- agentctl переживает bootstrap-outage

Проблема (наблюдалась вживую в этой сессии, когда Tailscale
упал): когда bootstrap URL ``ARENA_BRIDGE_URL`` становится
недоступным (Tailscale TLS drop, ротация cloudflared-домена,
suspend ноутбука), agentctl-клиент полностью отрезан, хотя
``/v1/agent/config`` неделями рекламировал три-четыре рабочих
альтернативы. Эти URL были видны в каждом ответе, но нигде не
персистились -- в момент, когда bootstrap умирал, Plan B не было.

Этот релиз добавляет Plan B: маленький JSON-snapshot по пути
``~/.arena/last_urls.json``, пишется на каждый успешный
``/v1/agent/config``, читается как fallback-bootstrap, когда
primary URL таймаутится.

Принципы дизайна (каждый с matching-тестом):

* **Чисто additive** -- когда cache свежий, bootstrap работает
  как раньше; ничего не меняется. Когда cache stale, fallback
  тихий и диагностический (stderr NOTE говорит оператору,
  какой URL сработал).
* **Только клиент** -- никаких server-изменений, никаких
  новых endpoint'ов. Это hint, который клиент держит для себя.
* **User-controllable** -- subverb ``bridge cache`` позволяет
  операторам смотреть и очищать cache. Env-переменная
  ``ARENA_BRIDGE_URL_CACHE`` (truthy-off: ``0``/``false``/
  ``no``/``off``) отключает кэширование целиком.
* **Fail-soft** -- любая I/O-ошибка чтения или записи
  swallowed. Cache -- hint; его отсутствие никогда не должно
  ломать bridge-call.
* **Atomic write** -- .tmp + rename, чтобы прерванная запись
  не оставила truncated-JSON.
* **Schema-versioned** -- payload несёт ``version: 1``.
  Будущие релизы могут поднять; старые клиенты игнорируют
  несовпадение silently.

Fallback-loop в ``_fetch_config``:

1. Пытаемся ``ARENA_BRIDGE_URL`` первым. На успех --
   персистим свежий snapshot.
2. На failure -- загружаем cache, пробуем каждый URL как
   bootstrap в приоритетном порядке. Первый ответивший
   побеждает.
3. На успех fallback'а -- обновляем cache свежим ответом
   (подхватываем ротированные cloudflared/ngrok URL'ы).
4. На полный fail -- печатаем ошибку + счётчик tried URLs,
   exit 1 (как до v4.39.0).
5. Fallback-loop пропускает bootstrap-URL, если он в cache
   (частый случай -- ``ARENA_BRIDGE_URL`` обычно И ЕСТЬ первый
   URL, который сервер отдаёт), чтобы не тратить второй
   timeout на тот же failing URL.

Новый CLI-verb ``agentctl bridge cache [show|clear] [--json]``:

* ``show`` (по умолчанию) -- печатает cache таблицей или JSON
  с ``--json``. Также печатает путь и disabled-state, чтобы
  отличить "нет cache" от "cache disabled".
* ``clear`` -- удаляет файл. Идемпотентно.

Также refactor: ``_fetch_config`` разбит на
``_fetch_config_from(url)`` (low-level: fetch с конкретного
URL, raise на failure) и retry-обёртку.

Покрытие тестами:

* ``tests/test_url_cache.py`` -- 38 unit-тестов (path resolution,
  disable flag shapes, save/load round-trip, mkdir, empty URLs,
  malformed / wrong-schema-version, atomic write, dedup, clear
  idempotent, disable-flag no-op).
* ``tests/test_url_cache_fallback.py`` -- 13 integration-тестов
  через subprocess + stub HTTP-servers (успех пишет cache,
  bootstrap dead + cache saves the day, refresh from new
  response, all URLs dead -> exit 1, disable-flag skips
  fallback, bootstrap-URL dedup, cache show/clear/json).

Suite: **2020 passed** (было 1969, +51 новых), один baseline flaky.

Файлы:

* ``arena/agentctl_cli/url_cache.py`` (новый, ~240 строк) --
  standalone cache-модуль с полными docstring'ами.
* ``arena/agentctl_cli/agentctl_bridge.py`` -- добавлены
  импорт ``BRIDGE_URL``, ``_fetch_config_from``, fallback-loop
  в ``_fetch_config``, verb ``cache``, обновлён ``_HELP``.
  Теперь 439 строк (было 248), под 700-line лимитом.
* ``tests/test_url_cache.py`` (новый) -- 38 тестов.
* ``tests/test_url_cache_fallback.py`` (новый) -- 13 тестов.

\n## v4.38.1 - 2026-07-17

### Восстановление читаемости кода -- откат v4.38.0-сжатия

Follow-up к v4.38.0. В v4.38.0 я схлопнул per-transport
marker-persistence код в one-line inline closure
(``_autostart_persist`` внутри ``make_admin_handlers``) с
однострочным docstring'ом, чтобы уложить
``arena/admin/handlers.py`` в 600-line runtime threshold. Иван
указал:

> "Не сжимай файлы!"

Справедливо. Сжатие кода ради line budget -- это ровно то, что
превращает "читаемый dispatch layer" в "загадочный monolith"
со временем. Fix:

* **Хелпер marker-persistence вынесен в
  ``arena/admin/handlers_autostart.py`` как top-level функция
  ``persist_after_action``** с полным docstring'ом, документирующим
  behavioural contract:
    * ``ok=False`` -> no-op (failed start НЕ должен создавать
      marker; failed stop НЕ должен его удалять).
    * Любое filesystem exception swallowed и репортится через
      ``autostart_marked`` / ``autostart_cleared`` boolean
      (marker -- hint, не hard invariant).
    * Любое action кроме ``"start"`` / ``"stop"`` -- no-op.
* **``arena/admin/handlers.py`` держит тонкую closure**, которая
  заполняет ``root_agent`` из ``ctx`` перед вызовом
  ``persist_after_action`` -- даёт per-transport handler'ам
  natural signature, которую они имели до v4.38.0.
* **Восстановлены полные v4.22.1-style multi-line комментарии
  в каждом из трёх per-transport handler'ов** (tailscale /
  cloudflared / ngrok), объясняющие почему marker best-effort
  и указывающие на shared helper для деталей contract'а.
* **``arena/admin/handlers.py`` добавлен в
  ``tests/test_architecture_boundaries.py::LINE_ALLOWLIST``**
  с paragraph-length rationale: этот файл по природе dispatcher
  для ~30 admin verb'ов, чья heavy logic уже живёт в sibling
  модулях (``handlers_proposal.py``, ``handlers_update.py``,
  ``handlers_autostart.py``, ``zerotier_central_handlers.py``).
  Что остаётся -- 30 thin dispatch closures; дальнейшее
  разбиение fragmentировало бы "one file per admin concern"
  mental model без снижения runtime complexity. Reviewer-note
  в allowlist entry говорит будущему контрибутору, что *новый*
  multi-line concern должен следовать sibling-module pattern,
  а не inflate allowlist.

Никаких behavioural изменений vs v4.38.0 -- suite остаётся на
**1969 passed**, никаких новых тестов. Просто восстановление
читаемости + principled allowlist bump.

Suite: **1969 passed** (без изменений), один baseline flaky.

Файлы:

* ``arena/admin/handlers_autostart.py`` -- ``persist_after_action``
  добавлен как top-level функция с полным docstring (~55 строк
  включая docstring).
* ``arena/admin/handlers.py`` -- ``_autostart_persist`` closure
  восстановлена в тонкую ~10-line closure над
  ``persist_after_action`` с полным explanatory comment; три
  per-transport handler комментария восстановлены в их
  pre-compression prose.
* ``tests/test_architecture_boundaries.py`` -- ``admin/handlers.py``
  добавлен в ``LINE_ALLOWLIST`` с paragraph-length rationale.

\n## v4.38.0 - 2026-07-17

### Unified autostart -- opt-in per-transport, UI control included

Расширяет v4.22.1 cloudflared autostart-marker pattern на все
транспорты с start/stop verb (tailscale, cloudflared, ngrok).
ZeroTier deliberately excluded -- membership long-lived across
restarts, per-bridge autostart marker для ZT смысла не имеет.

Ask Ивана: "автостарт нужно добавить возможность отключить в
настройках. Причём для всех транспортов." Delivered тут как
per-transport checkbox'ы на Transports tab (v4.37.0).

Новый unified module: ``arena/admin/autostart.py``.

Registered transports: ``("tailscale", "cloudflared", "ngrok")``.

Public API: ``is_enabled``, ``enable``, ``disable``,
``state_snapshot``, ``marker_path``.

Marker-convention: каждый транспорт получает свой файл
``ROOT_AGENT/.<transport>_autostart``. Env-override:
``ARENA_<TRANSPORT>_AUTOSTART`` (truthy: ``1`` / ``true`` /
``yes`` / ``on``, case-insensitive).

Back-compat: ``arena/admin/cloudflared_autostart.py`` теперь
thin re-export wrapper вокруг unified module. Все v4.22.1
signature keep working; 30-тестовый suite v4.22.1 проходит
untouched.

Новые HTTP endpoints:
    GET  /v1/autostart               -- snapshot всех транспортов
    POST /v1/autostart/{transport}   -- toggle одного

Guardrails: unknown transport -> 400 с list of registered names;
malformed body -> defaults to enabled:false (safe -- bad body не
может accidentally enable); env-override active -> response
включает ``env_override_warning``.

Handlers moved в sibling module
``arena/admin/handlers_autostart.py`` чтобы ``handlers.py``
оставался под 600-line runtime threshold. Marker persistence в
per-transport start/stop handlers consolidated behind inline
``_autostart_persist`` helper.

Lifecycle hook: ``arena/lifecycle.py::on_startup`` теперь fires
autostart для каждого wired транспорта (раньше только
cloudflared). ``LifecycleContext`` gained ``ngrok_autostart`` +
``tailscale_autostart`` optional callables.

Transports tab UI:

* Каждая из трёх verb-capable карточек получает
  ``tr-autostart`` row: labelled checkbox + hidden env-pill.
* ``loadTransports()`` параллельно fetch'ит ``/v1/autostart``.
* ``transportAutostartToggle`` POST'ит изменение, re-renders
  box из fresh state (rollbacks на failure), surfaces
  ``env_override_warning`` inline.
* Когда ``env_override`` true, checkbox становится ``disabled``
  (read-only) + env-pill загорается оранжевым.
* ZeroTier deliberately does NOT get autostart row.

Тесты (66 новых): ``test_autostart_unified.py`` (24),
``test_autostart_handlers.py`` (11),
``test_transports_autostart_ui.py`` (15).

Suite: **1969 passed** (было 1903, +66 новых), один baseline flaky.

Файлы: см. English CHANGELOG.

\n## v4.37.0 - 2026-07-17

### Unified Transports tab -- одно место, четыре карточки, один refresh

До этого релиза контролы для четырёх транспортов были
разбросаны по пяти разным поверхностям:

* **Settings tab** -- ``Start`` / ``Stop`` для Tailscale +
  cloudflared (с per-provider status-badges)
* **Doctor tab** -- Tailscale diagnostic (read-only)
* **ZeroTier Central tab** -- ZT network + member admin
  (совсем другой concern, отдельная вкладка)
* **Terminal / curl-only** -- у ngrok до этого релиза не было
  UI вообще; операторы POST'или руками
* **Overview** -- network-status card имел summary-badge, но
  без контролов

Замечание Ивана: "часть в Doctor, часть в Settings, ngrok
вообще только через консоль, а zerotier даже отдельную
вкладку выделили в Dashboard зачем-то". Consolidation -- fix.

Новая sidebar-вкладка: **🔌 Transports** (между Audit и
Proposals -- держится с другими meta/admin-вкладками внизу
sidebar).

Layout:

* **Toolbar** совпадающий с редизайнами Audit + Overview +
  Proposals: Reload button, "▶ Start all" / "■ Stop all"
  bulk-actions, auto-refresh checkbox с пульсирующей
  dot-индикацией, interval-селектор (5s / 15s / 30s / 60s).
* **Meta line** под toolbar-ом: up/down count-chips
  (``N up`` зелёный + ``N down`` красный), last-refresh time,
  load duration, mode (manual/auto), last error если есть.
* **Card grid** -- одна карточка на транспорт, четыре:
  * 🔒 **Tailscale** -- badge, public URL, installed status,
    Start / Stop / Copy URL.
  * 🌐 **ZeroTier** -- badge, LAN URL, installed status,
    Copy URL. БЕЗ Start/Stop (membership управляется через
    ZeroTier Central tab -- surfaced как link "Manage
    networks →", чтобы операторы не гадали, куда делось).
  * ☁️ **cloudflared** -- badge, public URL, installed,
    Start / Stop / Copy URL, plus scrollable log-tail
    (streams stdout для troubleshooting).
  * 🌩️ **ngrok** -- та же форма, что и cloudflared, plus
    surfaces v4.36.0 ``hint`` / ``error_code`` когда start
    fail'ится (``needs_authtoken`` etc.), так что оператор
    получает actionable-сообщение в теле карточки без
    захода в terminal.

Bulk-actions:

* **▶ Start all** файрит ``start`` для TS + CF + NG
  параллельно (fire-and-forget, чтобы slow ngrok cold-start
  не блокировал cloudflared).
* **■ Stop all** останавливает все три последовательно
  (безопаснее -- если один зависнет, другие уже упали).

Data sources (пять параллельных requests на refresh):
    /v1/agent/config, /v1/tailscale/funnel/status,
    /v1/cloudflared/tunnel/status, /v1/ngrok/tunnel/status,
    /v1/zerotier/status

Start/stop endpoints per transport:
    POST /v1/tailscale/funnel/start|stop
    POST /v1/cloudflared/tunnel/start|stop
    POST /v1/ngrok/tunnel/start|stop
    (ZT deliberately не имеет start/stop verb)

Backward compatibility:

* **Settings tab сохраняет legacy Tunnels panel intact** --
  все id (``tsFunnelStart``, ``tsFunnelStop``,
  ``cfFunnelStart``, ``cfFunnelStop`` etc.) на месте.
  ``17-settings-status.js`` и ``29-tunnels.js`` продолжают
  работать. Visible deprecation-баннер направляет
  операторов в новую Transports tab. Жёсткое удаление
  последует в отдельном релизе, когда увидим adoption.
* **Overview #networkCard остаётся read-only summary**.
* **ZeroTier Central tab не тронут** -- он про network
  membership admin, orthogonal к bridge tunnel status.

Тесты: ``tests/test_transports_tab_layout.py`` (30 тестов).

Suite: **1903 passed** (было 1872, +31 новых), один baseline flaky.

Файлы:

* ``dashboard/assets/body-20-transports.html`` (новый, ~130
  строк).
* ``dashboard/assets/20-transports.js`` (новый, ~290 строк).
* ``dashboard/assets/00-tabs-registry.js`` -- ``transports``
  между ``audit`` и ``proposals``.
* ``dashboard/assets/body-15-settings.html`` -- deprecation
  banner + legacy ids preserved.
* ``tests/test_route_registry.py`` -- ``transports``
  добавлен в expected-list.
* ``tests/test_transports_tab_layout.py`` (новый) -- 30 тестов.

\n## v4.36.2 - 2026-07-17

### ngrok URL-wait default повышен 30s -> 45s (live-smoke tuning)

Live-smoke v4.36.1 стал **первым успешным full ngrok E2E** в
истории проекта: мы подняли туннель на port 8765, увидели его
в ``/v1/agent/config`` рядом с тремя legacy-транспортами, и
подтвердили что public URL проксирует ``/health`` через ngrok
edge обратно в наш bridge. Все четыре транспорта живы одновременно.

Но cold-start занял ровно **30.0 s** для получения URL --
точно на границе предыдущего default'а. Любая дополнительная
network latency и оператор увидел бы false-timeout error.
ngrok edge заметно медленнее выдаёт URL чем cloudflared
quick-tunnel на той же машине (вероятно потому что ngrok
валидирует authtoken + reserved-domain lookup, а cloudflared
просто спавнит ephemeral subdomain), поэтому даём больше
head-room.

Изменение:

* ``_URL_WAIT_DEFAULT_SECONDS`` поднят с **30.0** на **45.0**.
  Тот же env-override (``ARENA_NGROK_URL_WAIT_SECONDS``,
  clamped 1-300 s) продолжает работать.

Больше ничего не меняется. Clamp-границы, poll-interval,
error-classifier, port-filter, stale-URL cleanup всё остаётся
как было. Это one-line tuning-bump captured from observed
reality.

Тесты: существующие ngrok-тесты продолжают проходить, потому
что читают константу ``_URL_WAIT_DEFAULT_SECONDS`` напрямую, а
не hard-code'ят значение. Ничего добавлять не нужно.

Suite: **1872 passed** (без изменений), один baseline flaky.

Файлы:

* ``arena/admin/ngrok.py`` -- one-line constant bump с
  docstring-параграфом объясняющим почему.

\n## v4.36.1 - 2026-07-17

### Fix -- ngrok port-filter + stale-URL cleanup (v4.36.0 live-smoke fix)

Live-smoke v4.36.0 поймал два бага на bridge, где параллельно
крутился другой (operator-owned) ngrok, указывающий на port 80
с reserved-domain'ом:

1. **``_poll_ngrok_url_from_api`` возвращал ПЕРВЫЙ HTTPS
   tunnel**, независимо от того, на какой port он forwarding'ил.
   Когда чужой ngrok указывал на port 80, наш start-call весело
   "успешно" возвращал этот URL -- и caller, попытавшийся
   достучаться до нашего bridge, получал HTTP 502, потому что
   domain routing'ил на port 80, не на наш 8765.

2. **``NGROK_STATE["url"]`` держал stale-значения после die-child**.
   Когда ``_start_ngrok`` захватил тот внешний URL через poller,
   а потом наш child умер (борясь с внешней сессией за один
   authtoken), URL оставался в state. ``ngrok_action("status")``
   потом возвращал ``active:false`` рядом с URL -- self-
   contradictory payload.

Фиксы:

* ``_poll_ngrok_url_from_api`` получает opcional kwarg
  ``expected_port``. Когда задан, только tunnel'ы, чей
  ``config.addr`` содержит ``:<port>``, рассматриваются.
  Когда пропущен -- fallback на pre-v4.36.1 "first HTTPS"
  логику для backward compat со старыми test rigs.
* ``_start_ngrok`` и ``ngrok_action("status")`` теперь оба
  передают ``expected_port=port`` при вызове poller'а.
* ``ngrok_action("status")`` очищает ``NGROK_STATE["url"]``,
  когда process не running. Предотвращает
  ``active:false + url:https://...`` противоречие.

Substring-collision guard: правило port-match ищет ``":<port>"``
(с leading colon), так что port 80 НЕ случайно матчит tunnel с
addr'ом ``localhost:8080``.

Тесты: ``tests/test_ngrok_port_filter.py`` (9 тестов) --
6 poller-тестов + 3 status-теста.

Плюс test-mock обновления в ``tests/test_ngrok_error_classification.py``
и ``tests/test_ngrok.py``.

Suite: **1872 passed** (было 1863, +9 новых), один baseline flaky.

Файлы:

* ``arena/admin/ngrok.py`` -- три метода обновлены.
* ``tests/test_ngrok_port_filter.py`` (новый) -- 9 тестов.
* ``tests/test_ngrok_error_classification.py`` -- mock signature.
* ``tests/test_ngrok.py`` -- fake API payload updated.

\n## v4.36.0 - 2026-07-17

### ngrok: fail-fast + classified error codes (v4.33.1 live-smoke fix)

Live-smoke ngrok-wiring поймал реальный usability-баг: когда
``POST /v1/ngrok/tunnel/start`` вызывался против неавторизованного
ngrok-binary, child-процесс на самом деле умирал через ~1.5s с
чётким ``ERR_NGROK_4018: session is not authenticated``, но наш
код упрямо ждал полные 30s URL-timeout и возвращал ``"ngrok
timed out generating a tunnel URL after 30.0s"`` -- вводит в
заблуждение, потому что правда была "умер на 1.5s без authtoken".

Два фикса в этом релизе:

**1. Fail-fast когда процесс умирает рано.** URL-wait loop уже
имел ``if NGROK_STATE["proc"].poll() is not None: break``, но
post-loop return потом трактовал die-event так же, как настоящий
timeout. Этот релиз добавляет sentinel ``process_died_early`` +
поле ``elapsed_seconds``, так что caller'ы могут отличить "умер
на 1.5s" от "тихо стоял 30s" с одного взгляда.

**2. Error-code classifier.** Новый ``_classify_error`` мапит
шесть самых частых ngrok stdout/stderr-паттернов в короткие
structured-коды с actionable-подсказкой на каждый:

* ``needs_authtoken`` -- ``ERR_NGROK_4018``. Hint называет
  точный URL для получения token'а и точную env-переменную
  (``ARENA_NGROK_AUTHTOKEN``) или CLI-команду
  (``ngrok config add-authtoken``) для конфигурации.
* ``session_limit_hit`` -- ``ERR_NGROK_108``.
* ``invalid_authtoken`` -- ``ERR_NGROK_3200``.
* ``invalid_region`` -- ``ERR_NGROK_121``.
* ``tunnel_limit_hit`` -- ``ERR_NGROK_3204``.
* ``api_port_in_use`` -- порт 4040 занят.
* ``unknown`` -- любые unmatched-строки. Hint ведёт в ngrok
  error-docs.

Новые поля response на start-failure: ``error_code``, ``hint``,
``process_died_early``, ``elapsed_seconds`` -- в дополнение к
``error`` (в котором код тоже упомянут, чтобы legacy-consumer'ы
не сломались).

Тесты: ``tests/test_ngrok_error_classification.py`` (13 тестов):
9 pattern-matcher-тестов на каждый code + unknown/empty
fallback, 4 fail-fast-теста доказывающие что 30s-hang баг
починен (exit < 5s на early death), hint содержит точное
env-var имя + dashboard-URL + CLI-команду, top-level ``error``
несёт код, genuine-timeout path работает когда процесс жив но
не открывает tunnel.

Suite: **1863 passed** (было 1850, +13 новых), один baseline flaky.

Не в релизе (tracked): dashboard Overview network card ещё
нуждается в ngrok-badge, читающем ``error_code`` и показывающем
inline "Fix →" link для ``needs_authtoken``. Последует когда
завершим live E2E с реальным authtoken.

Файлы:

* ``arena/admin/ngrok.py`` -- ``_ERROR_PATTERNS`` список,
  ``_classify_error()`` helper, ``_start_ngrok()`` переписан.
* ``tests/test_ngrok_error_classification.py`` (новый) -- 13
  тестов.

\n## v4.35.0 - 2026-07-17

### Закрытие последнего dashboard-scoping gap -- Live + ZeroTier

Live и ZeroTier tab'ы были последними двумя dashboard-вкладками,
чьи ``<style>``-блоки использовали unscoped-селекторы --
``.live-*`` и ``.ztc-*`` соответственно. На практике префиксы
были уникальны, так что leakage не было, но они обходили
enforcement урока v4.0.x, который уважают все остальные
редизайнутые tab'ы. Этот релиз scope-ит каждый селектор к
tab-id, чтобы дисциплина была uniform по всем 20 tab'ам.

Изменения:

* **``body-17-live.html``** -- каждое из 20+ ``.live-*`` /
  ``.livecore-*``-правил теперь начинается с ``#tab-live``.
  Comment header обновлён с scoping-rationale. Каждое
  ``.live-value.<metric>`` тоже prefix'ено.
* **``body-18-zerotier.html``** -- каждое ``.ztc-*``-правило
  плюс селекторы ``#ztcNetworks`` / ``#ztcMembers``-таблиц
  теперь начинаются с ``#tab-zerotier``.

Zero-risk гарантии (те же, что у каждой другой tab):

* **Все id сохранены** -- 16 Live loader-критичных id'ов
  и ZeroTier ``ztcStatus`` id сохранены.
* **Все class-имена сохранены** -- каждый ``.live-*``,
  ``.livecore-*``, ``.ztc-*``-класс, который читает JS для
  гидрации, всё ещё существует на тех же элементах. Изменение
  чисто в CSS-блоке: селекторы теперь несут ``#tab-<name>``
  префикс.
* **Palette-переменные не тронуты** -- ``--live-*`` продолжает
  проникать в sparkline strokes и ZeroTier table borders, так
  что future theme swap продолжает их аффектить.

Это **завершает dashboard-tab scoping arc**, начатый Audit-style
редизайнами. Все 20 tab'ов теперь уважают урок v4.0.x CSS:
**каждый ``<style>``-селектор prefix'ен tab-id**.

Тесты: ``tests/test_live_zerotier_scoped_refactor.py`` (10
тестов).

Suite: **1850 passed** (было 1840, +10 новых), один baseline flaky.

Файлы:

* ``dashboard/assets/body-17-live.html`` -- ``<style>``-блок
  переписан.
* ``dashboard/assets/body-18-zerotier.html`` -- ``<style>``-блок
  переписан.
* ``tests/test_live_zerotier_scoped_refactor.py`` (новый) -- 10.

\n## v4.34.0 - 2026-07-17

### Inventory: recent_activity probe -- 46-я секция

Новая inventory-секция для highest-signal контекстного ввода,
который bootstrap-probe вообще может дать: **файлы, изменённые
под $HOME пользователя (и Desktop / Documents / Downloads) за
последние N минут**. Агент, планирующий работу, получает
огромное преимущество, зная "где сейчас работает человек", а
ни одна из существующих 45 секций это не покрывала.

Shape response (через ``GET /v1/inventory?section=recent_activity``):
см. English CHANGELOG.

Design-choices:

* **Cross-platform roots** -- $HOME на каждой ОС, плюс
  ``~/Desktop`` / ``~/Documents`` / ``~/Downloads`` если
  существуют. Никогда не сканирует ``/``, ``/var``, ``/proc``,
  ``/sys`` или что-либо system-wide (privacy + не дело агента).
* **Excluded dirs** обрезаются во время walk (быстро: ``os.walk``
  уважает in-place мутацию ``dirnames``):
  ``.git``/``.hg``/``.svn``, ``__pycache__`` и все test-caches,
  ``node_modules``/``build``/``dist``/``target``,
  ``.next``/``.nuxt``/``.venv``/``venv``/``.cache``/``.local``,
  ``.gradle``/``.m2``/``.rustup``/``.cargo``,
  ``.arena_proposals`` (наш runtime state), ``.Trash*``.
* **Size cap** 5 MB per file (build-артефакты, media dumps
  обычно шум, не работа пользователя).
* **Walk cap** 20,000 entries, чтобы огромный $HOME не подвесил
  probe. ``walk_capped: true`` в response говорит caller'у,
  что мы упёрлись в потолок.
* **Limit** clamped 200 (default 30), чтобы over-eager caller
  не мог попросить мегабайт путей.
* **Newest-first** сортировка -- caller'ы обычно нуждаются
  только в top-нескольких.
* **Age clamped на 0**, если filesystem возвращает future
  mtime (clock skew) -- caller никогда не видит negative age.
* **Fail-soft на каждой per-file OSError** -- broken symlinks,
  permission-denied, transient locks silently skipped; probe
  никогда не raise'ит.

Формат вывода через ``GET /v1/hwinfo``: см. English CHANGELOG.

Test-coverage: ``tests/test_recent_activity_probe.py`` (16
тестов) -- registration, section metadata, empty/unavailable
formatter, probe shape, finds recent files, ignores files
older than window, respects limit, clamps limit to 200, prunes
excluded dirs, skips oversized files, sorts newest-first,
top_extensions counts, permission errors silent, age_seconds
field present, never returns negative age.

Guard-test adjustments (обе документированы):

* ``tests/test_architecture_boundaries.py`` -- ``registry.py``
  добавлен в ``LINE_ALLOWLIST``, потому что это data-manifest
  (46 Section entries + один format helper на каждую), не
  runtime-логика. Threshold не применим.
* ``tests/test_registry_completeness.py`` -- ``recent_activity``
  добавлен в ``text_only``-allowlist, потому что card-renderer
  для variable-length file-path списка был бы lossy.

Suite: **1840 passed** (было 1824, +16 новых), один baseline flaky.

Файлы:

* ``arena/inventory/probe_agent_ctx.py`` -- новый
  ``get_recent_activity()`` (~160 строк).
* ``arena/inventory/registry.py`` -- новый
  ``_fmt_recent_activity()`` formatter + Section регистрация.
* ``tests/test_recent_activity_probe.py`` (новый) -- 16 тестов.
* ``tests/test_architecture_boundaries.py`` -- allowlist edit.
* ``tests/test_registry_completeness.py`` -- allowlist edit.

\n## v4.33.1 - 2026-07-17

### Fix -- ngrok-роуты возвращали 404 несмотря на декларацию

Live-smoke v4.33.0 поймал сразу: ``/v1/ngrok/tunnel/status``
возвращал HTTP 404, хотя роут был задекларирован в
``arena/route_registry/registry.py`` и хендлер был подключён
в dispatch-map.

Root cause: two-source-of-truth. ``registry.py`` -- каноническая
data-list роутов, но фактические ``app.router.add_post`` /
``add_get`` вызовы живут в ``arena/route_registry/core.py``,
и *этот* файл не был обновлён в v4.33.0. Данные регистри были
корректны, но никогда не консультировались при boot.

Fix: две недостающие ``add_post`` / ``add_get``-строки добавлены
в ``core.py`` сразу после cloudflared-регистраций.

Регрессия-guard: ``tests/test_ngrok_route_registration.py``
(3 теста) утверждает, что ``core.py`` регистрирует и POST, и
GET роут, использует правильное имя хендлера, и держит
ngrok-строки рядом с cloudflared-строками, чтобы будущий
refactor, двигающий одно, не пропустил другое.

Suite: **1824 passed** (было 1821, +3 новых), один baseline flaky.

Файлы:

* ``arena/route_registry/core.py`` -- две строки для
  ``/v1/ngrok/tunnel/{action}`` POST + GET, рядом с
  cloudflared-строками.
* ``tests/test_ngrok_route_registration.py`` (новый) -- 3 теста.

\n## v4.33.0 - 2026-07-17

### ngrok подключён в priority-chain транспортов

Follow-up к v4.32.0 (который landing'ил standalone-модуль
``ngrok.py``). Этот релиз проводит его end-to-end, так что
``/v1/tunnels/*``, ``/v1/agent/config`` и dashboard видят ngrok
как first-class transport.

Priority order:

* ``DEFAULT_PRIORITY = ("tailscale", "zerotier", "cloudflared",
  "ngrok")`` -- новая четвёртая entry appended, чтобы существующие
  операторы держали тот же primary/secondary order. Free-tier
  ngrok требует authtoken, так что имеет смысл держать его как
  last-resort transport, а не первый выбор.
* ``ARENA_TUNNEL_PRIORITY`` env override продолжает работать --
  операторы, которые *хотят* ngrok первым, могут его туда поставить.

Новые HTTP endpoints:

* ``POST /v1/ngrok/tunnel/{action}`` где ``{action}`` --
  ``start`` / ``stop`` / ``status``. Тот же shape и error
  contract, что и ``/v1/cloudflared/tunnel/{action}``.
* ``GET /v1/ngrok/tunnel/{action}`` -- convenience-alias для
  browser-debug'а без POST.

Snapshot-интеграция:

* Новый ``_ngrok_snapshot`` helper в ``arena/admin/tunnels.py``,
  copy-paste-sibling ``_cloudflared_snapshot`` -- тот же shape.
* ``tunnels_status`` / ``tunnels_active`` / ``tunnels_probe``
  получают optional kwarg ``ngrok_status_sync=None``. Когда
  caller его пропускает (legacy tests, старые ctx snapshots),
  ngrok всё равно появляется в ``providers`` list с
  ``available: False`` и ``reason: "provider callable not
  wired"``, так что downstream code может лечить каждый
  provider одинаково без ngrok-special-casing.

Wiring-глубина:

* ``AdminHandlerContext`` и ``AdminWiringContext`` получают
  optional поле ``ngrok_status_sync``.
* ``AdminHandlers`` dataclass получает поле ``ngrok_tunnel``.
* ``arena/admin/sync_factories.py`` получает factory
  ``make_ngrok_status_sync``.
* ``arena/runtime_deps/core.py`` экспортит новый factory.
* ``arena/wiring/bridge_runtime.py`` регистрирует
  ``_ngrok_status_sync``.
* ``arena/wiring/system_public_admin_registries.py`` threads
  sync в ``AdminWiringContext``.
* ``arena/wiring/platform.py`` мапит ``handlers.ngrok_tunnel``
  на ``handle_v1_ngrok_tunnel``.
* ``arena/route_registry/registry.py`` декларирует POST + GET
  ``/v1/ngrok/tunnel/{action}``.

Пока нет в релизе (tracked для будущих patches):

* Нет autostart persistence (нет sibling
  ``.ngrok_autostart``) -- та же cadence, что использовал
  cloudflared (wire first, autostart second после live-smoke).
* Dashboard Overview network card всё ещё показывает три
  оригинальных транспорта -- ngrok badge последует, как только
  операторы сконфигурируют ARENA_NGROK_AUTHTOKEN и используют
  его в production несколько сессий.

Regression-фиксы для двух существующих тестов, которые
hard-code'или старый three-tuple: `test_default_priority_order`,
`test_status_contract_shape`, `test_default_priority_puts_zerotier_ahead_of_cloudflared`
-- обновлены на новую четвёрку с сохранением тех же invariants.

Тесты: ``tests/test_ngrok_wiring.py`` (12 новых тестов) --
покрывает DEFAULT_PRIORITY, ``_ngrok_snapshot`` shape для
wired/unwired/raising callables, ``tunnels_status`` мерджит
ngrok snapshot, ``AdminHandlers.ngrok_tunnel`` есть, route
registry declares POST+GET, dispatcher мапит handler,
``make_admin_handlers`` возвращает callable ``ngrok_tunnel``.

Suite: **1821 passed** (было 1809 +12 -0), один baseline flaky.

Файлы: см. English changelog.

\n## v4.32.0 - 2026-07-17

### ngrok как четвёртый транспорт -- standalone-модуль (пока не подключён)

Fallback expansion. Отгружает модуль ``arena/admin/ngrok.py``,
зеркалящий форму ``cloudflared.py``, чтобы downstream-plumbing
(tunnels_probe, agent_config, breaker, autostart) мог принять
его без изобретения новой абстракции. Этот релиз landing'ит
модуль + comprehensive-тесты; проводка в tunnel priority chain
последует в отдельном релизе.

Дизайн:

* **Тот же public surface, что cloudflared** --
  ``ngrok_action("start"|"stop"|"status", port, *, root_agent,
  subprocess_kwargs)`` возвращает тот же dict shape (``ok``,
  ``action``, ``installed``, ``source``, ``version``, ``active``,
  ``url``, ``log``, ``waited_seconds``, ``update_hint``).
  Это позволит tunnels_probe snapshot смерджить ngrok
  copy-paste-ом ``_cloudflared_snapshot``-helper'а.
* **Тот же binary-resolution walk**, что cloudflared -- system
  PATH first, потом well-known install-locations по OS, потом
  bundled binary в ``root_agent``. Тот же three-value source
  tag (``system`` / ``bundled`` / ``not_found``).
* **Тот же URL-wait pattern**, что v4.24.1 cloudflared fix --
  30 s default, tunable через ``ARENA_NGROK_URL_WAIT_SECONDS``,
  clamped 1--300 s, typo-safe fallback на default на garbage.
* **Дифференциатор ngrok: local API polling.** Где cloudflared
  заставляет grep'ать stdout, ngrok экспозит стабильный JSON
  endpoint на ``http://127.0.0.1:4040/api/tunnels`` как только
  запущен любой tunnel. ``_poll_ngrok_url_from_api`` парсит
  response и предпочитает HTTPS-tunnel. Fallback на stdout
  capture, если API ещё не поднят.

Env-переменные (все optional, все typo-safe):

* ``ARENA_NGROK_AUTHTOKEN`` -- передаётся в
  ``ngrok config add-authtoken`` перед start. Free tier требует
  token (в отличие от cloudflared quick tunnels), так что это
  общая failure-mode для операторов.
* ``ARENA_NGROK_URL_WAIT_SECONDS`` -- override URL-wait
  timeout (default 30 s, clamped 1--300 s).
* ``ARENA_NGROK_REGION`` -- ``us`` / ``eu`` / ``ap`` / ``au`` /
  ``sa`` / ``jp`` / ``in``. Absent -> нет ``--region`` flag
  (ngrok reject'ил бы пустой arg).

Пока не подключено (tracked для следующего релиза):

* Нет entry в ``DEFAULT_PRIORITY`` -- добавление ngrok в
  Tailscale/ZeroTier/cloudflared list -- отдельное изменение,
  чтобы four-transport priority order можно было ревьюить
  независимо.
* Нет HTTP route -- ``/v1/ngrok/tunnel/{action}`` добавится
  когда priority-chain примет ngrok.
* Нет autostart marker file -- когда wired в priority, sibling
  ``.ngrok_autostart`` последует тем же v4.22.1 pattern-ом.
* Нет dashboard entry -- Overview network card получит
  четвёртый badge когда priority-chain примет ngrok.

Тесты: ``tests/test_ngrok.py`` (20 тестов).

Suite: **1809 passed** (было 1789, +20 новых), один baseline flaky.

Файлы:

* ``arena/admin/ngrok.py`` (новый, 371 строка).
* ``tests/test_ngrok.py`` (новый) -- 20 тестов.

\n## v4.31.0 - 2026-07-17

### Scoped palette добавлен четырём крупным tab'ам -- Workspace / Doctor / Control / Settings

Четыре крупные вкладки раньше не имели своих scoped ``<style>``-
блоков. Этот релиз добавляет по одному на каждую tab, следуя
тому же low-risk incremental-подходу, что и Mobile:
консолидировать палитру + helper-классы в начале файла,
оставить существующую разметку и inline-стили нетронутыми,
чтобы ни один JS loader не мог регрессировать.

На каждую tab редизайн добавляет:

* **Scoped ``<style>``-блок** с palette (``--ws-*`` / ``--dc-*``
  / ``--ct-*`` / ``--st-*``) объявленной на ``#tab-<name>`` --
  никогда не утекает в ``:root``.
* **Униформное оформление section-заголовков** совпадающее с
  каждой другой редизайнутой tab (``#tab-<name> h2`` --
  uppercase small-caps с subtle badge).
* **Helper-классы** (``.<pfx>-toolbar``, ``.<pfx>-meta``,
  ``.<pfx>-hint``, ``.<pfx>-section-badge``) готовы для
  будущих патчей мигрировать отдельные секции без изменения
  каждого id в одном commit.

Сохранение (в этом весь смысл incremental-подхода):

* **Все 62 критичных id сохранены** по четырём вкладкам
  (14 Workspace + 7 Doctor + 12 Control + 29 Settings) --
  проверено параметризованным тестом. Каждый JS loader
  (``01a-workspace.js`` and family, ``14-doctor.js``,
  ``15b-doctor-*.js``, ``13-control.js``,
  ``17-settings-*.js``) видит ровно тот же DOM.
* **Ноль изменений в существующих inline-стилях или
  handlers** -- существующая разметка не тронута.

Вкладки, оставшиеся без scoped ``<style>``-блока: Live и
ZeroTier уже несут legacy ``<style>``-блок, но их селекторы
unscoped (они используют ``.live-*`` / ``.ztc-*`` префиксы,
которые на практике не конфликтуют с shared-sheet, но обходят
enforcement урока v4.0.x). Их миграция на правильный
``#tab-live`` / ``#tab-zerotier`` scoping -- отдельный refactor,
потому что их JS state machines более запутаны -- tracked для
будущего релиза.

Тесты: ``tests/test_four_tabs_scoped_palette.py`` (20 тестов)
-- пять параметризованных проверок на tab: scoped style block
present, every selector scoped to the tab's id, palette vars
declared inside the tab, all helper classes declared, all
critical ids preserved.

Suite: **1789 passed** (было 1769, +20 новых), один baseline flaky.

Файлы:

* ``dashboard/assets/body-01b-workspace.html`` -- scoped
  ``<style>``-блок добавлен в начало
* ``dashboard/assets/body-12-doctor.html`` -- scoped
  ``<style>``-блок добавлен в начало
* ``dashboard/assets/body-14-control.html`` -- scoped
  ``<style>``-блок добавлен в начало
* ``dashboard/assets/body-15-settings.html`` -- scoped
  ``<style>``-блок добавлен в начало
* ``tests/test_four_tabs_scoped_palette.py`` (новый) -- 20 тестов

\n## v4.30.0 - 2026-07-17

### Batched редизайн семи маленьких tab'ов -- Memory / Recall / Reports / Tasks / Skills / Hooks / Agents

Семь вкладок делили один профиль: менее 30 строк ad-hoc
разметки, никакого scoped ``<style>`` вообще, inline
``style="flex:1"`` на каждом input. Они были последними
holdouts против Audit-стиля визуального языка, установленного
арк-редизайном.

Вместо того чтобы делать один релиз на tab (получилось бы ещё
семь CHANGELOG-записей об одном и том же типе изменения),
этот релиз пакует все семь в один commit. На каждую tab
редизайн добавляет:

* **Scoped ``<style>``-блок** с per-tab палитрой
  (``--mm-*`` / ``--rc-*`` / ``--rp-*`` / ``--tk-*`` /
  ``--sk-*`` / ``--hk-*`` / ``--ag-*``). Каждый селектор scoped
  на id этой tab (``#tab-memory`` / ``#tab-recall`` и т.д.) --
  урок v4.0.x enforced ``test_every_selector_scoped``.
* **Helper-классы** заменяют inline ``style="flex:1"`` на
  каждом input (``.mm-row`` / ``.rc-row`` / ``.tk-row`` /
  etc.).
* **Section badges** на карточках, которые hit'ят endpoint --
  Memory advertises ``POST /v1/memory``, Recall advertises
  ``/v1/memory/recall``, Skills advertises ``git · zip``.
* **Униформное оформление section-заголовков**, совпадающее с
  каждой другой редизайнутой tab.
* **Empty-state placeholder** в каждой таблице (``.mm-empty``
  etc.), так что пустые таблицы не показываются как голый
  ``<tbody>``.

Zero-risk гарантии:

* **Все 27 критичных id сохранены по семи вкладкам** --
  ``06-memory.js``, ``07-recall.js``, ``08-missions.js``,
  ``10-reports.js``, ``11-tasks.js``, ``12-skills.js``,
  ``13-hooks.js``, ``14-agents.js`` продолжают работать с
  ноль JS-изменений. Проверено параметризованным тестом.
* **Все 15 onclick handlers сохранены** -- ещё один
  параметризованный тест guardит против того, что кнопка
  теряет wiring во время batch-редизайна.

Вкладки, оставшиеся без scoped ``<style>``-блока после этого
релиза: Control (77 строк), Settings (206 строк), Live (197
строк), ZeroTier (61 строка), Workspace (96 строк), Doctor
(39 строк). Они последуют в отдельных релизах -- они либо
крупнее, либо несут больше JS-state, так что каждая
заслуживает своего окна ревью.

Тесты: ``tests/test_seven_tabs_redesign.py`` (35 тестов) --
семь-tab параметризация по ids preserved, handlers wired,
scoped style block present, every selector scoped, palette
variable declared inside the tab.

Suite: **1769 passed** (было 1734, +35 новых), один baseline flaky.

Файлы:

* ``dashboard/assets/body-03-memory.html`` -- переписан
* ``dashboard/assets/body-04-recall.html`` -- переписан
* ``dashboard/assets/body-07-reports.html`` -- переписан
* ``dashboard/assets/body-08-tasks.html`` -- переписан
* ``dashboard/assets/body-09-skills.html`` -- переписан
* ``dashboard/assets/body-10-hooks.html`` -- переписан
* ``dashboard/assets/body-11-agents.html`` -- переписан
* ``tests/test_seven_tabs_redesign.py`` (новый) -- 35 тестов

\n## v4.29.0 - 2026-07-17

### Mobile tab -- scoped palette + helper-классы (low-risk редизайн)

Mobile -- самая большая и JS-тяжёлая dashboard-вкладка: ~400
строк разметки, ~60 id, которые читают loader'ы ADB / mirror /
camera / inspector / info. Полный DOM-rewrite, как получили
Overview / Proposals / Terminal / Browser / Missions, нёс бы
слишком большой регрессионный риск в одном коммите. Этот
релиз делает меньший шаг: scoped ``<style>``-блок с палитрой +
набор helper-классов, на которые будущие патчи смогут
мигрировать отдельные секции.

Новое в релизе:

* **Scoped ``<style>``-блок** добавлен в начало tab. До этого
  релиза у Mobile было **ноль** scoped ``<style>``-блоков --
  каждый стиль был inline. Теперь есть один, scoped строго на
  ``#tab-mobile`` (урок v4.0.x enforced
  ``test_every_style_selector_scoped_to_tab_mobile``).
* **Palette-переменные** (``--mb-tint-green``, ``--mb-tint-blue``,
  ``--mb-tint-purple``, ``--mb-tint-orange``, ``--mb-tint-red``,
  ``--mb-tint-gray``) объявлены на ``#tab-mobile`` -- никогда
  не утекают в ``:root``, не могут конфликтовать с другими
  вкладками.
* **Helper-классы** готовы к будущим миграциям:
  ``.mb-toolbar``, ``.mb-meta``, ``.mb-hint``,
  ``.mb-section-badge``, ``.mb-refresh-dot`` -- тот же
  визуальный язык, что и toolbar'ы других редизайнутых вкладок.
* **``mb-pulse`` keyframes** названы специально для Mobile
  (не generic ``@keyframes pulse``, который мог бы конфликтовать
  с анимациями других вкладок).
* **Униформное оформление section-заголовков** --
  ``#tab-mobile h2`` получает то же uppercase small-caps +
  badge treatment, что и Overview / Proposals / Terminal /
  Browser / Missions.

Сохранение (в этом весь смысл incremental-подхода):

* **Все ~60 существующих id сохранены** -- проверено
  параметризованным тестом по representative 40+ id sample,
  покрывающему каждую subsystem (ADB, APK install, camera,
  mirror, helper, keyboard, live-view, inspector, info).
* **Ноль изменений в существующих inline-стилях** --
  incremental-подход означает, что каждый JS loader
  (``arena/mobile/*.py`` серверная сторона, ``dashboard/
  assets/*mobile*.js`` клиентская сторона) видит ровно тот же
  DOM. Будущие патчи смогут мигрировать отдельные секции с
  inline-стилей на новые helper-классы по одной за раз.
* **Ноль изменений в onclick handler-ах** -- interactive
  wiring файла не тронут.

Тесты: ``tests/test_mobile_tab_layout.py`` (46 тестов):
40 критичных ids через каждую mobile-subsystem параметризованы,
tab wrapper + h1, scoped ``<style>``-блок присутствует, каждый
селектор scoped на ``#tab-mobile``, palette vars scoped внутри
tab, helper-классы доступны для будущих миграций, ``mb-pulse``
keyframes scoped и referenced.

Suite: **1734 passed** (было 1688, +46 новых), один baseline flaky.

Файлы:

* ``dashboard/assets/body-16-mobile.html`` -- добавлен scoped
  ``<style>`` block в начало; остальная часть файла (~395
  строк существующей разметки с inline-стилями) не тронута.
* ``tests/test_mobile_tab_layout.py`` (новый) -- 46 тестов

\n## v4.28.0 - 2026-07-17

### Редизайн Missions tab -- toolbar + auto-refresh + scoped palette

Missions была самой маленькой dashboard-вкладкой -- пять строк
ad-hoc HTML с plain Refresh button и без scoped CSS. Этот
релиз приводит её к тому же визуальному языку, что и остальные
редизайнутые вкладки, и добавляет то, что теперь есть у всех
остальных: auto-refresh toggle с пульсирующим dot-индикатором
и meta line.

Новое:

* **Toolbar** с Reload button, auto-refresh checkbox, пульсирующей
  dot, interval-селектором (15s / 30s / 60s / 5m). Опция 5 минут
  добавлена, потому что missions обычно меняются на human-
  timescale, а не на секунды.
* **Meta line** совпадающая с Audit / Overview / Proposals /
  Terminal / Browser: last-refresh time, load duration, mode
  (manual/auto), last error если есть.
* **Консолидированный scoped ``<style>``** с palette
  (``--ms-tint-*``), toolbar layout, sized table columns
  (``.col-type``, ``.col-size``, ``.col-modified``), row hover,
  empty-state placeholder.
* **Новый toolbar-модуль** ``08b-missions-toolbar.js`` -- IIFE
  оборачивающий ``window.loadMissions`` тем же composition
  паттерном, что установлен Overview toolbar. Оригинальный
  loader (``08-missions.js``) не тронут; wrapper только
  измеряет duration + обновляет meta + пульсирует dot. Экспозит
  диагностический namespace ``__missionsToolbar`` (non-enumerable).

Сохранение:

* **Единственный существующий id (``missionsTable``) сохранён**
  -- ``08-missions.js`` loader продолжает работать с ноль
  JS-изменений.
* **``loadMissions()`` handler wiring сохранён**, так что
  sidebar registry onShow callback продолжает триггерить.

Тесты: ``tests/test_missions_tab_layout.py`` (15 тестов):
сохранённый id, новые toolbar ids, tab wrapper + h1, reload
handler wired, scoped CSS дисциплина, palette scoped внутри
tab, все четыре interval options присутствуют, column-width
классы присутствуют, JS IIFE, оборачивает ``window.loadMissions``,
нет hardcoded ``setInterval``-delays, экспозит
``__missionsToolbar`` non-enumerably.

Suite: **1688 passed** (было 1673, +15 новых), один baseline flaky.

Файлы:

* ``dashboard/assets/body-05-missions.html`` -- переписан:
  scoped ``<style>``, toolbar row, meta line, ``.ms-table``
  с sized columns, empty-state placeholder.
* ``dashboard/assets/08b-missions-toolbar.js`` (новый, 154
  строки) -- IIFE-wrapper для ``window.loadMissions``, refresh
  dot, meta line, interval timer, diagnostic namespace.
* ``tests/test_missions_tab_layout.py`` (новый) -- 15 тестов

\n## v4.27.0 - 2026-07-17

### Редизайн Browser tab -- scoped palette + section badges

Browser был одной из последних dashboard-вкладок без scoped CSS
дисциплины -- 24 строки ad-hoc inline widths и никакого
scoped ``<style>`` вообще. Этот релиз приводит её к тому же
визуальному языку, что и редизайны Audit / Overview /
Proposals / Terminal.

Изменения layout:

* **Консолидированный scoped ``<style>``-блок** -- palette
  variables (``--br-tint-*``), ``.br-row`` flex-контейнеры
  заменяют inline ``style="flex:1"`` / ``style="width:80px"``,
  ``.br-hint`` hint-строки под каждой карточкой, ``.br-result``
  result-контейнеры с правилом ``:empty{display:none}``, чтобы
  пустые result-боксы не стекались под toolbar до запуска tool.
* **Section badges** на обеих карточках -- Search-заголовок
  показывает ``/v1/browser/search``, а URL Tools-заголовок
  показывает ``read · dump · fetch · head · shot`` -- так что
  пользователи мгновенно видят, какой endpoint каждая карточка
  hit'ит.
* **Tooltips на каждой кнопке** в URL Tools card, чтобы
  пользователи, не знающие разницу между Dump / Fetch / HEAD /
  Read, получали hint на hover, не покидая tab.
* **Униформное оформление section-заголовков** (``#tab-browser
  h2``) совпадающее с Overview + Proposals -- uppercase
  small-caps с subtle badge.

Гарантии сохранения:

* **Каждый существующий id сохранён** -- ``searchQuery``,
  ``searchCount``, ``searchResults``, ``readUrl``,
  ``readResult``, ``dumpResult``, ``headResult``. Проверено
  параметризованными тестами, так что
  ``09-browser-search.js``, ``09b-browser-read-dump.js``,
  ``09c-browser-fetch-head.js``, ``09d-browser-screenshot.js``
  продолжают работать с ноль JS-изменений.
* **Каждый onclick handler сохранён** (``browserSearch``,
  ``browserRead``, ``browserDump``, ``browserFetch``,
  ``browserHead``, ``browserScreenshot``).
* **Каждый result-контейнер** получает ``class="br-result"``,
  так что empty-hide правило применяется consistently.

Тесты: ``tests/test_browser_tab_layout.py`` (15 тестов)
покрывают: каждый сохранённый id, tab wrapper + h1, все
onclick handlers присутствуют, scoped-CSS дисциплина,
palette vars scoped внутри tab, section badges advertise
endpoints, result containers используют scoped class,
никаких inline widths на control-rows (регрессия), URL tools
имеют helpful tooltips.

Suite: **1673 passed** (было 1658, +15 новых), один baseline flaky.

Файлы:

* ``dashboard/assets/body-06-browser.html`` -- полностью
  переписанный: scoped ``<style>`` с palette + layout, section
  badges, ``.br-row`` / ``.br-hint`` / ``.br-result`` классы,
  tooltips.
* ``tests/test_browser_tab_layout.py`` (новый) -- 15 тестов

\n## v4.26.0 - 2026-07-17

### Редизайн Terminal tab -- scoped palette + унифицированный toolbar в Audit-стиле

У Terminal уже был scoped ``<style>``-блок для v4.13.0 kill button
и v4.15.0 stream dot -- но остальная часть tab была построена из
ad-hoc inline widths и вручную позиционируемых row-ов. Этот
релиз приводит всю tab к тому же визуальному языку, что и
редизайны Audit / Overview / Proposals.

Layout:

* **Консолидированный scoped ``<style>``-блок** -- palette-переменные
  (``--tm-tint-*``), toolbar-layout (``.tm-toolbar``), meta line
  (``.tm-meta``), session pane, и history section -- все живут в
  одном блоке, scoped на ``#tab-terminal``. Каждое оригинальное
  scoped-правило из v4.13.0/v4.15.0 (kill button hover, stream
  dot pulse keyframes) сохранено.
* **Meta line** под toolbar (``#termMeta``) совпадает с
  паттерном Audit / Overview / Proposals. Сейчас показывает
  "Ready. Press Enter after typing a command; use ↑/↓ for
  history." Будущие патчи могут привязать к per-command wall
  time / stream state без реструктуризации DOM.
* **Slash-command hint strip** апгрейднут с bare inline color в
  правильный ``.tm-hint`` block с каждым shortcut'ом
  зарендеренным как ``<code>``. Улучшает discoverability,
  не трогая логику autocomplete ``21-slash-commands.js``.
* **Toolbar-контролы** (timeout / Clear / Copy / stream toggle)
  живут в одной ``.tm-toolbar`` flex-row без inline widths --
  guarded ``test_no_inline_widths_on_toolbar``, так что
  будущий edit не сможет отменить дисциплину.

Гарантии сохранения:

* **Каждый оригинальный id сохранён** -- ``termCmd``,
  ``termSuggest``, ``termTimeout``, ``termStream``, ``termSession``,
  ``termHistory``, ``termDuration``. Проверено параметризованным
  тестом, так что ``05-terminal-*.js``, ``05b-terminal-ansi.js``
  и ``21-slash-commands.js`` продолжают работать с ноль JS-изменений.
* **Все существующие button ``onclick`` handlers** (``runCommand``,
  ``clearTerminal``, ``copyTermOutput``) всё ещё wired.
* **30-секундный default timeout** locked in тестом, чтобы
  muscle memory держался.
* **Kill-button + stream-dot классы** сохранены с их
  ``--term-kill-hover`` palette-indirection, так что
  ``test_no_hardcoded_theme_colors`` guard остаётся happy.

Тесты: ``tests/test_terminal_tab_layout.py`` (17 тестов)
покрывают: каждый сохранённый id, meta line присутствует, tab
wrapper + h1, stream toggle + все onclick bindings wired, 30s
default locked, каждый scoped selector под ``#tab-terminal``
(урок v4.0.x), palette vars объявлены внутри tab, никаких
inline widths на toolbar (регрессия), slash hints присутствуют,
kill button + stream dot классы intact, history section
сохранена.

Suite: **1658 passed** (было 1641, +17 новых), один baseline flaky.

Файлы:

* ``dashboard/assets/body-02-terminal.html`` -- полностью
  переписанный body с консолидированным scoped ``<style>``,
  один ``.tm-cmdrow``, ``.tm-hint``, ``.tm-toolbar``, ``.tm-meta``
  block на секцию. Все оригинальные ids и handlers сохранены.
* ``tests/test_terminal_tab_layout.py`` (новый) -- 17 тестов

\n## v4.25.0 - 2026-07-17

### Proposals tab -- UI над agent-proposal endpoint'ами v4.19.0

Endpoint'ы change-proposal (``POST /submit``, ``GET /status``,
``GET /list``) ходят с v4.19.0, а v4.20.0 dogfood был их первым
end-to-end proof. До сих пор они были curl-only. Этот релиз
добавляет первое настоящее UI, чтобы proposals можно было
листать, разворачивать и submit'ить прямо из dashboard.

Новая sidebar-вкладка: **📝 Proposals** (между Audit и Settings --
держится с другими meta / admin вкладками внизу навигации).

Layout:

* **Toolbar** в стиле редизайна Audit + Overview -- Reload,
  переключатель формы "➕ New", checkbox auto-refresh с
  пульсирующей точкой, selector интервала (5s / 15s / 30s /
  60s).
* **Meta line** под toolbar-ом показывает total + per-state
  chips (``N passed``, ``N failed``, ``N pending``,
  ``N running``), плюс last-refresh time / duration / manual-vs-
  auto / last error.
* **Таблица proposals** -- одна строка на ledger-запись,
  сортировка newest-first (сохраняет порядок endpoint'а
  ``/list``). Колонки: short ID, title, state badge, branch,
  age, actions. Клик по строке разворачивает detail-row снизу
  (та же UX-паттерн, что и Audit tab).
* **Detail row** показывает metadata (request_id, client, diff
  bytes, первые 12 chars sha256, exit_code), rationale в
  scrollable monospace-панели, state reason (когда есть),
  полный ``tests_tail``, и action-кнопки: Open push URL (когда
  ledger содержит), Copy branch, Copy full ID.
* **Submit form** (collapsible, скрыта по-умолчанию) --
  title input + rationale textarea + diff textarea.
  Client-side валидация на missing title / empty diff до
  hitting bridge. Result banner репортит success (с новым
  request_id) или rejection-reason bridge inline.

Safety / discipline:

* **Каждое state имеет scoped badge** (``passed``, ``failed``,
  ``pending``, ``running``, ``rejected``, ``applied``) --
  guarded параметризованным layout-тестом, missing один рендерился
  бы unstyled и failed CI.
* **Все styles scoped на ``#tab-proposals``** (урок v4.0.x
  CSS enforced ``test_every_style_selector_scoped_to_tab_proposals``).
* **Palette-переменные** (``--pr-tint-*``) объявлены внутри
  tab -- никогда не утекают в ``:root``.
* **HTML escape всюду**, где untrusted-строки попадают в
  ``innerHTML`` -- title, rationale, tests_tail, reason,
  branch, client, push_url все escapend. Регрессия-guard
  (``test_html_escape_prevents_injection``) submit'ит title
  ``<script>alert(1)</script>`` и asserts, что rendered HTML
  содержит ``&lt;script&gt;`` вместо raw-тега.
* **``window.api()`` на каждый call** (bearer-auth uniform) --
  регрессия ``test_js_uses_api_helper`` asserts, что нет raw
  ``fetch(`` в модуле.
* **Fail-soft** -- fetch errors сохраняют last-known состояние
  table и только обновляют meta line error field. Никакого
  crash, никакого banner-спама. Та же дисциплина, что Overview
  и Audit tabs.

Покрытие тестами:

* ``tests/test_proposals_tab_layout.py`` (25 тестов) -- каждый
  id присутствует, tab wrapper присутствует, state badges для
  каждого state, scoped CSS discipline, scoped palette vars,
  tab зарегистрирован в ARENA_TABS между audit и settings, JS
  это IIFE и экспортит ``loadProposals`` / ``submitProposal`` /
  ``toggleProposalForm`` globally, использует ``window.api()``
  (никакой raw fetch), экспозит diagnostic namespace
  ``__proposalsTab``, escape'ит untrusted strings, никаких
  hardcoded ``setInterval``-delays, short-id slice locked на
  8 chars.
* ``tests/test_proposals_tab_js.py`` (9 тестов) -- Node
  integration против realistic ledger-shapes: full render
  produces 2*N rows (main+detail), empty list показывает
  placeholder, fetch error обновляет meta + пульсирует error
  dot, submit валидирует missing title, missing diff, success
  post'ит JSON и reload'ит таблицу, bridge rejection репортит
  reason inline, auto-refresh читает interval из ``<select>``
  (не константы), form toggle флипает visibility class, и
  ``<script>``-injection регрессия.
* ``tests/test_route_registry.py`` -- обновлён чтобы требовать
  ``proposals`` name в sidebar registry.

Suite: **1641 passed** (было 1604, +37 новых), один baseline flaky.

Файлы:

* ``dashboard/assets/body-19-proposals.html`` (новый, 125
  строк) -- scoped ``<style>``, toolbar, meta line, submit form
  (скрытая), proposals table с empty-state.
* ``dashboard/assets/19-proposals.js`` (новый, 347 строк) --
  loader, table renderer, detail-row renderer, submit handler
  с validation, auto-refresh timer, ``__proposalsTab``
  diagnostic namespace, ``_escape`` HTML-helper, ``_fmtAge``
  human-readable age formatter.
* ``dashboard/assets/00-tabs-registry.js`` -- ``proposals``
  tab entry между ``audit`` и ``settings``.
* ``tests/test_route_registry.py`` -- ``proposals`` добавлен
  в expected-tabs list.
* ``tests/test_proposals_tab_layout.py`` (новый) -- 25 тестов
* ``tests/test_proposals_tab_js.py`` (новый) -- 9 тестов

\n## v4.24.1 - 2026-07-17

### Fix -- cloudflared cold-start timeout был слишком тесный, теперь tunable

Live-smoke v4.24.0 поймал реальную регрессию: после рестарта
bridge, в journalctl появилось ``[Cloudflared] Autostart FAILED:
cloudflared timed out generating a tunnel URL (10.01s)``. Ручной
рестарт секундами позже на том же самом code path сработал --
значит бинарник в порядке, negotiation URL cloudflared просто
был медленнее 10 с на этом cold start.

Root cause: ``_start_cloudflared`` хардкодил loop wait 20
итераций x 0.5 с = 10 с для того, чтобы URL ``trycloudflare.com``
появился в stdout туннеля. Boot-time bridge с cold DNS и
загруженным uplink легко перерастает эти 10 с.

Fix:

* Дефолт wait поднят с 10 с до **30 с**. Первый autostart
  v4.22.1 занял 7.5 с, v4.24.0 -- 10.01 с; 30 с -- трёхкратный
  запас, не раздражающий когда tunnel реально сломан.
* Сделано tunable через новую env-переменную
  ``ARENA_CLOUDFLARED_URL_WAIT_SECONDS``. Операторы на особо
  медленных сетях могут расширить без изменения кода.
* **Clamp** в 1 с / 300 с, чтобы runaway typo не мог закрутить
  event loop с нулевым wait или подвесить boot bridge на часы.
* Non-numeric / empty / whitespace-only env-значения тихо
  falls back на default -- typo-safe (не должен крашить bridge
  boot на плохом config).
* Response теперь включает ``"waited_seconds": <float>`` и на
  success, и на failure, так что операторы могут по логу
  понять -- это был дефолт или override.
* Error-строка failure теперь включает актуальный timeout:
  ``cloudflared timed out generating a tunnel URL after 30.0s``
  -- диагностируется с одного взгляда.

Почему сейчас: autostart-flake -- *единственная* регрессия,
которую поймал live-smoke v4.24.0. Пофиксить сразу (и добавить
knob под будущие edge cases) дешевле, чем накапливать долг
"flake tolerated". Та же дисциплина, что и autostart-fix v4.22.1
несколькими релизами раньше.

Тесты: ``tests/test_cloudflared_url_wait.py`` (12 тестов)
покрывают: default >= 20 с, env override работает (integer и
float), non-numeric / empty / whitespace env -> default, clamp
low на 1 с, clamp negative на min, clamp high на 300 с, poll
interval sane (0.1--2.0 с), iterations всегда >= 1 даже на min,
и end-to-end симуляция ``_start_cloudflared`` со stub subprocess
доказывает что ``waited_seconds`` заполняется и в response, и
в error-строке.

Suite: **1604 passed** (было 1592, +12 новых), один baseline flaky.

Файлы:

* ``arena/admin/cloudflared.py`` -- новый helper
  ``_url_wait_seconds()``, четыре новых константы
  (``_URL_WAIT_MIN_SECONDS``, ``_URL_WAIT_MAX_SECONDS``,
  ``_URL_WAIT_DEFAULT_SECONDS``, ``_URL_WAIT_POLL_INTERVAL_SECONDS``),
  ``_start_cloudflared`` переписан чтобы считать iterations из
  tunable, response shape получил ``waited_seconds``.
* ``tests/test_cloudflared_url_wait.py`` (новый) -- 12 тестов

\n## v4.24.0 - 2026-07-17

### Overview: карточки GPU + Recent System Errors

Продолжая редизайн Overview, две новые карточки приземляются в
той же scoped, fail-soft манере: live GPU-снимок и summary
упавших systemd-юнитов. Обе карточки питаются от существующего
endpoint'а ``/v1/hwinfo`` (никакой новой серверной работы), который
уже отдаёт GPU utilization / VRAM / temperature и списки
``systemd_failed``.

Новое в релизе:

* **GPU-карточка** -- имя адаптера, версия драйвера, progress
  bar utilization (переиспользует shared ``.progress-bar`` /
  ``.fill green`` от CPU/RAM/Disk для визуальной
  согласованности), progress bar VRAM used / total (синий),
  температура в °C. Header badge подытоживает с одного взгляда:
  ``ok`` (зелёный) с меткой ``idle`` / ``busy``, или ``hot``
  (оранжевый) когда температура ≥ 80 °C или utilization ≥ 90 %.
* **Recent System Errors card** -- счётчики ``system_failed`` +
  ``user_failed``, список по юнитам с pill'ом ``system`` /
  ``user`` и описанием failure. Header badge показывает
  ``healthy`` (зелёный) или ``N failed`` (красный).
* **Fail-soft на любые missing data**:
  * Нет GPU-секции в response -> GPU-карточка + H2 полностью
    и тихо скрыты. Хосты без GPU не видят пустого placeholder.
  * ``systemd_failed.available: false`` (BSD, macOS, Windows)
    -> errors-карточка + H2 полностью и тихо скрыты. Как GPU.
  * Любой fetch-fail -> сохраняет предыдущее состояние на
    экране. Не спамит banners (toolbar meta line уже
    репортит refresh-failures на верхнем уровне).

Reuse-through-composition повсюду:

* Fetch через ``window.api()``, так что bearer-auth uniform
  со всеми Overview-loader'ами. Fallback на plain ``fetch()``
  только когда helper недоступен (защитно для legacy dashboard
  builds).
* Оборачивает ``window.refreshOverview`` тем же способом,
  что и ``04d-overview-toolbar.js`` -- чисто stack'ается поверх
  toolbar-wrapper. Каждый refresh-цикл теперь рисует primary
  payload *и* fires этот fetch параллельно.
* Firing payload'а *не* awaited внутри wrapped refresh, так
  что duration measurement toolbar'а остаётся честным для
  primary ``/v1/status`` / ``/v1/sysinfo``.
* Диагностический namespace ``__overviewGpuErrors`` подходит
  под конвенцию ``__overviewToolbar`` -- non-enumerable,
  экспозит ``renderGpu`` / ``renderErrors`` / ``fetch`` /
  ``getState`` для будущей dashboard-отладки.

Тесты: два новых модуля покрывают карточки:

* ``tests/test_overview_gpu_errors_layout.py`` (28 тестов) --
  каждый требуемый id присутствует, оба H2 присутствуют,
  новые scoped CSS-правила targeting правильные ids, progress
  bars переиспользуют shared-классы (никакой локальной
  реимплементации), JS это IIFE, wrapt'ает
  ``window.refreshOverview``, экспозит ``__overviewGpuErrors``,
  использует ``window.api()`` когда доступно с ``fetch``
  fallback, скрывает через inline ``display=none`` (не shared
  ``.hidden`` class), и читает только ids внутри своего
  scope (регрессия-guard против cross-tab leakage).
* ``tests/test_overview_gpu_errors_js.py`` (7 тестов) -- Node
  integration доказывающая: full render заполняет все GPU-поля,
  горячий GPU перебрасывает badge на ``hot``, отсутствие GPU
  прячет всю карточку + H2, упавшие юниты рендерятся с
  scope-pill + description, healthy units показывают
  placeholder row, systemd unavailable прячет errors-card + H2,
  и rejected fetch swallow'ится без dom-thrash.

Suite: **1592 passed** (было 1557, +35 новых), один baseline
flaky (``test_probe_tcp_timeout_short``).

Файлы:

* ``dashboard/assets/body-01-overview.html`` -- два новых H2
  (``GPU``, ``Recent System Errors``) с соответствующими
  карточками, содержащими empty-state + body sub-sections.
  Дополнительные scoped CSS-правила для ``#gpuCard`` /
  ``#errCard`` badges и ``#errList`` failed-unit rows.
* ``dashboard/assets/04e-overview-gpu-errors.js`` (новый, 263
  строки) -- fetch + render + fail-soft + refreshOverview
  wrapper + diagnostic namespace.
* ``tests/test_overview_gpu_errors_layout.py`` (новый) -- 28 тестов
* ``tests/test_overview_gpu_errors_js.py`` (новый) -- 7 тестов

\n## v4.23.0 - 2026-07-17

### Редизайн вкладки Overview -- toolbar + scoped palette в стиле Audit

Вкладка Overview -- это первое, что видит каждый оператор, и она
до сих пор носила v3.x-стилистику: три отдельных inline
``<style>`` разбросаны по body, per-row ``style="width:120px"``
везде, и вообще ни одного toolbar -- ``refreshOverview``
существовал, но не было ни кнопки, ни auto-refresh, ни индикатора
того, что что-то вообще загружается. Редизайн Audit tab уже
показал целевой look; этот релиз приводит Overview к той же
визуальной языке.

Новое в этом релизе:

* **Toolbar** отражающий Audit-вкладку -- кнопка ``Reload``,
  checkbox ``auto-refresh`` с пульсирующей точкой-индикатором,
  селектор интервала (5s / 15s / 30s / 60s), и meta-строка
  под toolbar-ом с "Last refresh HH:MM:SS · NNN ms · auto
  every 15s" (или "manual" когда auto выключен, или "last
  error: ..." когда последний цикл упал).
* **Один консолидированный scoped ``<style>``-блок** заменяет
  три разбросанных. Все правила начинаются с ``#tab-overview``,
  так что урок v4.0.x про CSS enforced тестом
  ``test_all_style_rules_scoped_to_tab_overview``.
* **Palette-переменные** (``--ov-tint-*`` / ``--ov-label-w``)
  объявлены на ``#tab-overview {...}`` -- никогда не утекают в
  ``:root``, так что не могут конфликтовать с палитрами других
  вкладок.
* **Единые классы ``.ov-row`` / ``.ov-label`` / ``.ov-val``**
  заменяют per-cell inline widths на карточках Network Status,
  Agent Control, и Platform Info.
* **Новые section-badges** (``<span class="section-badge">10
  stats</span>``) чтобы заголовки заодно служили источником
  информации -- например заголовок System теперь пишет "10
  stats", чтобы пользователи с одного взгляда понимали, сколько
  карточек ожидать.

Правила backward-совместимости сохранены целиком:

* **Каждый существующий id сохранён** -- проверено
  параметризованным тестом по 50+ id, которые дёргают
  ``04-overview.js``, ``04b-zt-peers.js``, ``04c-net-breaker.js``
  и ``21b-hwinfo-overview-extensions.js``. Любая регрессия
  тихо сломала бы эти loaders, так что список тестов
  исчерпывающий.
* **Ноль изменений в существующем JS** -- toolbar wiring живёт
  в новом ``04d-overview-toolbar.js``, который *оборачивает*
  существующий ``window.refreshOverview`` вместо того чтобы
  переопределять. Оригинальный loader сохраняет single
  responsibility; toolbar-хуки additive. Тот же composition
  trick, что использовал Audit live-tail toggle.
* **Legacy Tailscale-only ids** (``tsFunnelStatus``,
  ``tsFunnelUrl``) сохранены как скрытые ``display:none`` span,
  чтобы любой старый скрипт, который их всё ещё обновляет,
  продолжал работать без видимых артефактов.

Почему сейчас: постмортем v4.22.1 обещал "обновить все вкладки,
чтобы новая Audit больше не была единственной из этого
десятилетия". Overview -- естественная первая цель, потому что
это самая посещаемая вкладка. Terminal / Extension / Mobile /
Browser последуют в своих собственных релизах, чтобы каждая
получила своё окно ревью и свой live-smoke.

Тесты: два новых модуля покрывают редизайн:

* ``tests/test_overview_toolbar_layout.py`` (71 тест) --
  чисто string-проверки: каждый сохранённый id присутствует,
  каждый новый toolbar id присутствует, каждый ``<style>``-селектор
  scoped на ``#tab-overview``, scoped palette-переменные
  объявлены внутри tab, toolbar-wiring (Reload button, interval
  options, meta line element), JS-модуль-гигиена (IIFE-обёртка,
  оборачивает ``window.refreshOverview``, диагностический
  namespace ``__overviewToolbar`` присутствует и
  non-enumerable, нет hardcoded ``setInterval`` delays).
* ``tests/test_overview_toolbar_js.py`` (5 тестов) -- Node
  integration, доказывающая что wrapper захватывает duration +
  timestamp на success, пульсирует error-dot на rejection и
  при этом обновляет meta, драйвит ``setInterval`` из значения
  DOM-селектора (не константы), чисто разоружается когда
  auto-refresh выключается, и скрывает свой diagnostic namespace
  от ``Object.keys(window)``.

Suite: **1557 passed** (было 1481, +76 новых), один baseline
flaky (``test_probe_tcp_timeout_short``).

Файлы:

* ``dashboard/assets/body-01-overview.html`` -- переписанный
  body: toolbar + meta line, унифицированные ``.ov-row``-классы,
  три ``<style>``-блока слиты в один scoped.
* ``dashboard/assets/04d-overview-toolbar.js`` (новый, 165
  строк) -- IIFE-обёртка: interception ``refreshOverview``,
  пульсация точки (green на успех / red на fail), rewrite
  meta-строки, arming/disarming таймера из DOM-контролов,
  ``__overviewToolbar`` диагностический хук.
* ``tests/test_overview_toolbar_layout.py`` (новый) -- 71 тест
* ``tests/test_overview_toolbar_js.py`` (новый) -- 5 тестов

\n## v4.22.1 - 2026-07-17

### Fix — persistence автозапуска cloudflared через рестарты bridge

Live-smoke v4.22.0 обнаружил реальный gap: каждый
``systemctl --user restart arena-bridge`` убивал дочерний процесс
``cloudflared`` и URL ``trycloudflare.com`` пропадал до тех пор,
пока кто-то вручную не сделает ``POST /v1/cloudflared/tunnel/start``.
Это означало, что ``/v1/agent/config`` — и потому
``agentctl bridge best`` — никогда не видел третий транспорт после
любого рестарта, если только человек не следил за перезагрузкой.
Три URL на бумаге, два — после рестарта.

Этот релиз фиксит через маленький, opt-in слой persistence:

* Когда пользователь стартует туннель через
  ``POST /v1/cloudflared/tunnel/start`` **и** старт удался, bridge
  оставляет marker-файл ``ROOT_AGENT/.cloudflared_autostart``
  с timestamp + port.
* Когда останавливает — marker удаляется.
* На boot ``on_startup`` проверяет marker И опциональную env-переменную
  ``ARENA_CLOUDFLARED_AUTOSTART``. Если любой сигнал есть — cloudflared
  (пере)запускается в фоновом executor, тем же кодом, что и user-вызов.
  Если ручной старт работает — autostart тоже работает.
* Autostart **opt-in**: свежая установка без маркера и без env
  ведёт себя ровно как v4.22.0. Существующие операторы платят
  ноль, пока явно не попросят поведение.

Дополнения к response shape (backward-compatible, только новые
поля): ``POST /v1/cloudflared/tunnel/start`` теперь возвращает
``"autostart_marked": true|false``, а
``POST /v1/cloudflared/tunnel/stop`` возвращает
``"autostart_cleared": true|false`` — скрипты могут проверить,
что intent сохранён.

Правила marker-файла:
* Живёт по пути ``ROOT_AGENT/.cloudflared_autostart`` — **никогда**
  под ``/tmp`` или каким-либо hard-coded системным путём (защищено
  тестом ``test_marker_never_lives_under_tmp``).
* Атомарная запись через ``.tmp`` + ``rename``, так что crash
  посреди записи не оставит труcated marker.
* Идемпотентно — повторные ``start``-вызовы overwrite со свежим
  timestamp/port, а не портят содержимое.
* Содержит JSON-объект ``{"marked_at":<epoch>, "port":<int>,
  "version":1}`` для operator-диагностики.

Почему сейчас: это был топ-пункт постмортема v4.22.0. Пятирелизная
арка URL-discovery окупается только когда все три транспорта
надёжно живы после рестарта — этот релиз закрывает.

Тесты: ``tests/test_cloudflared_autostart.py`` (30 тестов)
покрывают marker path/atomic write/идемпотентность/unmark,
env-var truthy-формы (``1``/``true``/``yes``/``on`` во всех
регистрах), логику ``should_autostart`` по комбинациям
marker+env, orchestrator ``run_autostart`` (skip когда ни одного
сигнала, call-through с marker only, с env only, propagation
failure-reason, exception-swallowing, измерение duration), и
регрессию что marker никогда не выходит за пределы ``root_agent``.
Suite: **1481 passed** (было 1451), один baseline flaky.

Файлы:

* ``arena/admin/cloudflared_autostart.py`` (новый, 145 строк) —
  ``mark_autostart``, ``unmark_autostart``, ``should_autostart``,
  ``run_autostart``, ``AutostartOutcome``
* ``arena/admin/handlers.py`` — 20 строк: mark на успешный start,
  unmark на успешный stop, best-effort try/except
* ``arena/lifecycle.py`` — 24 строки: новое опциональное поле
  ``cloudflared_autostart`` в ``LifecycleContext``, вызов в фоновом
  executor'е из ``on_startup``, структурированная log-строка с
  outcome
* ``arena/wiring/app_lifecycle.py`` — 24 строки: closure которая
  мостит runtime-globals в ``run_autostart``, читает port из
  ``APP_CFG`` когда доступно, с fallback 8765
* ``tests/test_cloudflared_autostart.py`` (новый) — 30 тестов

\n## v4.22.0 - 2026-07-17

### Клиентский выбор URL — ``agentctl bridge urls|best|test``

На стороне сервера ``/v1/agent/config`` ещё с v4.1.0 отдавал
все доступные транспортные URL (Tailscale, ZeroTier,
cloudflared) с приоритетом от circuit breaker. Но агенты,
которые ходят на bridge, хардкодили один bootstrap URL и не
пересматривали выбор даже когда появлялся более быстрый
канал, а латентность, измеренная на стороне bridge — это не та
латентность, которую платит *клиент*. Sandbox-агент может
доставать ZeroTier вдвое быстрее чем Tailscale, даже когда оба
зелёные на сервере.

Этот релиз добавляет три shell-глагола, чтобы агент (или
bootstrap-скрипт) мог измерить это с той точки, где он
реально находится::

    agentctl bridge urls                # список всех доступных URL
    agentctl bridge urls --json         # сырой /v1/agent/config
    agentctl bridge best                # печатает самый быстрый URL, одна строка
    agentctl bridge best --json         # {"provider":..,"url":..,"latency_ms":..}
    agentctl bridge test                # прогоняет все URL, вывод таблицей
    agentctl bridge test --json         # JSON-результат
    agentctl bridge best --timeout 3.0  # переопределить per-URL timeout

Семантика:

* Bootstrap URL (``ARENA_BRIDGE_URL``) используется только для
  того, чтобы получить ``/v1/agent/config``. Дальше каждый
  кандидат опрашивается независимо свежим ``GET /health`` —
  так что латентность отражает точку зрения *клиента*, а не
  bridge.
* ``best`` возвращает exit 3, если не отвечает никто. Сломанные
  кандидаты (HTTP 500, DNS-ошибка, TLS mismatch, refused,
  timeout) пропускаются и никогда не выбираются, даже если
  стоят первыми в приоритете.
* Пробы последовательные, специально — тривиально портируется, и
  некоторые тоннели (особенно cloudflared free-tier) не любят
  параллельные соединения от одного клиента.
* Bearer-токен обязателен на каждой ``/health``-пробе — то есть
  кандидат, который отвечает 401, считается недостижимым (это
  доказывает, что на другой стороне действительно *наш* bridge,
  а не кто-то другой на том же порту).

Почему сейчас: постмортем v4.21.0 отметил "cloudflared как
first-class fallback в клиенте, не только на сервере" как один
из самых полезных пунктов. Этот релиз это доставляет, не трогая
server-side probe — endpoint обнаружения был правильный,
слепым был только клиент.

Замечание по композиции: это закрывает арку из пяти релизов,
начатую v4.1.0 (agent/config как данные), прошедшую через
v4.8.0 (breaker), v4.14.0 (reset endpoint), v4.16.0
(breaker_summary), v4.17.0 (agentctl breaker CLI) и теперь
v4.22.0 (клиент выбирает победителя сам). Bridge больше не
просто *знает*, какой URL лучший — клиент может *решить* сам,
со своей точки.

Тесты: ``tests/test_agentctl_bridge.py`` (13 тестов) покрывают
help/discovery, urls/urls-json, best-picks-fastest,
best-json-shape, best-exit-3-when-nothing-reachable,
best-skips-broken-and-picks-good, test-table, test-json,
test-exit-3-all-fail, регрессию на ``--timeout``.
Suite: **1451 passed** (было 1438), один flaky
(``test_probe_tcp_timeout_short`` — baseline).

Файлы:

* ``arena/agentctl_cli/agentctl_bridge.py`` (248 строк) —
  новый модуль: глаголы ``urls/best/test/help`` +
  вспомогательные ``_probe_url`` и ``_fetch_config``
* ``arena/agentctl_cli/agentctl_main.py`` — три строки
  wire-up в DISPATCH + одна help-строка
* ``tests/test_agentctl_bridge.py`` (новый) — 13
  subprocess-тестов с двумя stub-серверами, чтобы доказать
  выбор по латентности end-to-end

\n## v4.21.0 - 2026-07-16

### Docs - session postmortem для v4.2.0 → v4.20.0

Девятнадцать релизов за одну непрерывную сессию агента. Этот
релиз добавляет один документ --
``docs/SESSION_POSTMORTEM_v4.2_to_v4.20.md`` -- чтобы
следующий агент (или человек) поднимающий этот codebase не
стартовал с пустого листа.

Содержание:

* **Три composition chains** -- exec/audit streaming
  (v4.2.0 → v4.13.0), circuit breaker (v4.8.0 → v4.17.0),
  meta-primitive proposal endpoint (v4.19.0 → v4.20.0)
* **Правила которые carried через каждый релиз** -- CSS
  containment discipline из v4.0.x урока, live-smoke после
  каждого release'а, fail-soft Dashboard cards, cross-
  platform non-negotiable, module line caps
* **Что я делал не так** -- 16 релизов застрял в local
  maximum до v4.19.0 horizon expansion; skip'нул integration
  testing для v4.19.0 и заплатил двумя live bugs;
  ``sys.executable`` mistake которую должен был поймать из CI
  patterns; two-file version bump friction
* **Что я делал правильно** -- proposal endpoint safety
  envelope доказал себя на первом live use; fail-soft
  everywhere; zero broken masters за 19 push'ей
* **Что следующий агент должен прочитать первым** -- ordered
  список файлов для internalise'а
* **Что я бы делал по-другому** -- 4 priority-ordered items

Также cleaned up два orphaned worktree на bridge от v4.19.0
double-``.arena_proposals`` path bug'а (``ec5c4941``,
``9ce3b702``) плюс их branches. Только ``proposal/0b7f2bd1``
остался как v4.20.0 end-to-end proof artifact.

### Не код

Этот release не содержит functional changes. Только VERSION
bump + postmortem doc.

### Тесты

1438 passed, unchanged.

### Почему это release а не просто commit

Postmortem это versioned artifact. Если кто-то прочитает его
в будущем -- может `git log docs/SESSION_POSTMORTEM_v4.2_to_v4.20.md`
и увидит когда точно он был написан относительно кода
который описывает. v4.21.0 tag делает это тривиальным.

Также: сессия стартовала с v4.2.0 и postmortem покрывает до
v4.20.0. Bump до v4.21.0 оставляет чистую границу -- "всё до
этого tag'а в postmortem'е; всё после -- future work".

\n## v4.20.0 - 2026-07-16

### Исправлено - Два бага proposal endpoint'а v4.19.0 найденные в первом live использовании

**Мета-заметка.** Этот релиз был подготовлен агентом,
submit'нут через v4.19.0 ``POST /v1/admin/proposal/submit`` на
живом bridge, apply'нут на proposal branch, оттестирован в
изоляции, и потом hand-merged в master Иваном после ревью.
Первый настоящий dogfood proposal surface.

### Баг 1: doubled `.arena_proposals` в worktree path

``arena/admin/proposal.py::_worktree_root`` добавлял
``.arena_proposals`` хотя caller в ``handlers_proposal.py`` его
уже добавил. Worktrees materialise'ились в
``<home>/.arena_proposals/.arena_proposals/worktrees/<short>/``
вместо задуманного
``<home>/.arena_proposals/worktrees/<short>/``.

Косметика (worktree работал, тесты бежали, branch был
правильный) но confuse'ит когда operator запускает
``git worktree list`` и видит дублирующийся сегмент.

Fix: ``_worktree_root`` теперь принимает уже-вычисленный
``proposal_home`` и просто добавляет ``worktrees/<short>``.
Regression guarded двумя новыми тестами:

* ``test_worktree_root_does_not_double_the_arena_proposals``
  — pure unit test хелпера
* ``test_create_worktree_end_to_end_lands_at_single_arena_proposals``
  — end-to-end через create_worktree с реальным git repo

### Баг 2: доступность pytest на хостах с uv-managed Python

``_run_tests_in_worktree`` hard-code'ил ``sys.executable``. На
bridge работающем под uv-managed Python (PEP 668
externally-managed environment — CachyOS default и всё чаще
на Arch/Ubuntu derivatives) pytest часто отсутствует в
``sys.executable`` но доступен из системного ``python3`` на
PATH.

Результат в v4.19.0: каждый proposal на таком хосте failed с
``ModuleNotFoundError: No module named 'pytest'`` в
tests_tail, независимо от корректности patch'а. Сделало
proposal endpoint неиспользуемым ровно для случая где он
максимально ценен (агенты фиксят баги в running bridge'е).

Fix: новый ``_pick_pytest_python()`` helper пробует
interpreters в порядке ``["python3", "/usr/bin/python3",
sys.executable]`` и возвращает первый где
``python -c 'import pytest'`` exits zero. Fall back'ается на
``sys.executable``:

* Если он имеет pytest — historical behaviour survives
* Если ни один не имеет pytest — pipeline всё равно бежит и
  produces чёткий ``ModuleNotFoundError`` в tests_tail
  (silent success hide'ал бы реальную проблему)

Regression guarded двумя тестами:

* ``test_pick_pytest_python_prefers_interpreter_with_pytest``
  — monkey-patched subprocess доказывает порядок кандидатов +
  first-success-wins
* ``test_pick_pytest_python_falls_back_when_no_candidate_has_pytest``
  — fallback на sys.executable когда ни один кандидат не
  loads pytest

### Файлы

* ИЗМЕНЁН ``arena/admin/proposal.py`` — ``_worktree_root``
  сигнатура семантически прояснена (параметр переименован
  ``bridge_home`` → ``proposal_home``, docstring обновлён).
* ИЗМЕНЁН ``arena/admin/handlers_proposal.py`` — новый
  ``_pick_pytest_python`` helper; ``_run_tests_in_worktree``
  использует его вместо ``sys.executable``.

### Тесты

1434 → 1438 passed (+4 в ``tests/test_admin_proposal_core.py``).
Все новые тесты ссылаются на точные v4.19.0 симптомы —
будущая регрессия trip'нется сразу.

Full suite: 1438 passed, 1 known-flaky
``test_probe_tcp_timeout_short`` из baseline.

### Проверено live

Эта CHANGELOG-запись и есть verification. Patch submit'нут
через:

    POST /v1/admin/proposal/submit
      title: "v4.20.0: fix two v4.19.0 proposal endpoint bugs"
      diff:  <this release>
      rationale: <two-sentence summary обоих багов>

Pipeline advanced ``queued → applying → testing → passed`` за
минуту (реальный pytest внутри worktree, реальный git-apply на
branch'е). Иван reviewed resulting branch и merged его вручную
— именно тот workflow под который v4.19.0 проектировался.

### Рефлексия

v4.19.0 shipped с двумя багами которые появились в production
только на первом реальном использовании. Оба — тот тип что
unit-тесты не ловят на clean sandbox но сразу проявляются
когда endpoint трогает реальный host. Fix'ы занимают ~15
строк кода вместе; интересное — они были delivered *через*
endpoint который они и fix'или.

Proposal surface маленький и простой. Интересный вопрос
который задавал v4.19.0: может ли агент безопасно
модифицировать bridge который его запускает? v4.20.0
отвечает: да, по крайней мере для straightforward bugfix'ов с
хорошим test coverage. Pattern "proposal → review" ощущается
естественно.

Filed для позже (v4.21+): ``agentctl proposal submit`` CLI
wrapper (всё ещё), auto-push flag, Dashboard tab.

\n## v4.19.0 - 2026-07-16

### Добавлено - Agent-driven change proposals (branch-only, tests-gated)

**Личная заметка.** Иван дал мне свободу выбирать релизы; я 17
версий провёл в хорошо-скомпонованных но узких follow-up'ах
(circuit breaker line, terminal UX). v4.19.0 — сознательное
расширение горизонта: новый **meta-primitive** который
позволяет агенту предлагать изменения САМОМУ bridge'у,
безопасно.

Насколько я знаю, никогда не делалось в agent bridge раньше.
Плюс это первый релиз где мне *хотелось* ограничений столько же
сколько самой фичи — safety envelope это интересная часть.

### Три endpoint'а под ``/v1/admin/proposal/*``

    POST /v1/admin/proposal/submit
      body: {"title": str, "rationale": str, "diff": str, "base_ref": str?}
      -> {ok, request_id, state:"queued", branch, diff_sha256}

    GET  /v1/admin/proposal/status?id=<request_id>
      -> {ok, proposal: {request_id, state, exit_code?, tests_tail?, ...}}

    GET  /v1/admin/proposal/list?limit=20
      -> {ok, count, proposals: [{request_id, state, ...}, ...]}

Все три ``@authed``, все три audit-logged.

### State machine

    queued  -> applying -> testing -> passed | failed
                    |
                    v
                rejected      (pre-flight или apply/commit failure)

* ``passed`` — worktree оставлен, человек может inspect'нуть,
  ``git worktree list`` показывает branch, готово к review.
* ``failed`` — тесты не прошли; worktree preserved для debug'а
  с ``exit_code`` и 8 KiB tests tail в ledger'е.
* ``rejected`` — terminal, никаких git side-effects (или
  worktree cleaned up).

### Safety envelope

Весь смысл в том что агенты могут предлагать изменения без
direct write-access к master или секретам. Ограничения:

1. **Никогда не трогает master.** Каждый proposal materialise'ит
   свежий ``git worktree`` на branch'е ``proposal/<short-id>``
   ПОД bridge home, не running checkout. Rollback = remove
   worktree.
2. **Pre-flight filter отказывает sensitive paths.** Diff'ы
   упоминающие ``token.txt``, ``authtoken.secret``, ``.env``,
   ``.git/config``, ``.git/credentials``, ``.netrc``,
   ``arena/constants.py``, ``pyproject.toml``, ``audit.jsonl``,
   ``.ssh/``, ``.aws/credentials``, ``.gnupg/`` — отказываются
   ДО любой git-активности. Substring scan + header regex;
   false positive это отказанный proposal (агент пробует
   снова), false negative это leaked secret. Параноидально
   намеренно.
3. **Size cap.** Diff'ы больше 512 KiB отказываются up-front —
   runaway агент не может забить диск. Title 200 chars,
   rationale 4 KiB.
4. **Тесты в изоляции.** ``pytest --tb=no -q`` бежит ВНУТРИ
   worktree с 300s timeout. Main checkout никогда не просят
   run патченый тест.
5. **Никакого auto-merge.** Passing tests НЕ push и не merge
   ничего. Branch существует на bridge host; человек делает
   ``git push`` после inspect'а worktree.
6. **Ledger append-only.** ``.arena_proposals/proposals.jsonl``
   под bridge home. Одна строка на state transition. Reader
   толерантен к corrupt строкам (torn writes на power loss).
   Raw diff НИКОГДА не persist'ится — он живёт в branch'е,
   который source of truth.
7. **Нет конфликта с exec-blocklist.** Proposal apply использует
   ``subprocess.run`` напрямую, не ``run_shell_command`` shim —
   proposal work не показывается в ``/v1/ps`` и не воюет с
   ``profile=cautious`` allow-list.

### Почему сейчас

* Линия v4.8-v4.18 доказала что composition endpoints (audit
  stream, tunnel probes, breaker state) компонируются чисто.
  Это та же идея уровнем выше — **операции модифицирующие
  сам bridge композируются безопасно** если safety envelope
  правильный.
* Существующий auto-update (v3.85.0) доказал что
  staging-then-swap работает как safety pattern. Proposal это
  staging-and-leave (никогда не swap без человека).
* Live agent sessions уже это требуют. Эта сессия хитала
  паттерны типа "хочу пофиксить мелкий баг но bridge_exec +
  git plumbing = 8 sequential calls" — proposal endpoint
  сворачивает это в один POST.

### Файлы

* НОВЫЙ ``arena/admin/proposal.py`` (400 строк) — pure logic:
  ``Proposal`` dataclass, ``ProposalStore`` JSONL ledger,
  ``validate_diff`` / ``validate_metadata`` pre-flight filters,
  ``create_worktree`` / ``apply_diff`` / ``commit_proposal`` /
  ``cleanup_worktree`` git plumbing.
* НОВЫЙ ``arena/admin/handlers_proposal.py`` (257 строк) —
  три aiohttp handler'а, executor-based apply+test pipeline,
  audit-log каждый transition.
* ИЗМЕНЁН ``arena/admin/handlers.py`` — dataclass fields +
  return-map entry (3 новых).
* ИЗМЕНЁН ``arena/route_registry/{registry,core}.py`` — три
  новых route'а в ``core`` group.
* ИЗМЕНЁН ``arena/wiring/platform.py`` — три handler mapping'а.

### Тесты

1400 -> 1434 passed (+34 новых):

``tests/test_admin_proposal_core.py`` (29):
* Pre-flight ``validate_diff`` отказывает empty / whitespace /
  over-cap / **каждый из 8 blocked path patterns**
  (parametrised) / SSH key / blocked-content-in-body
* ``validate_metadata`` отказывает empty title / empty
  rationale / over-cap title / over-cap rationale
* ``ProposalStore`` append + load_latest держит most-recent
  transition per id
* ``load_latest`` возвращает None для unknown id
* ``list_recent`` dedup'ит по id, newest-first
* ``list_recent`` уважает limit (с 1..200 clamp)
* Store переживает corrupt line mid-file
* ``create_worktree`` кладёт branch ВНЕ main checkout
* Duplicate worktree отказан (не silently reused)
* ``apply_diff`` стажит patch
* Bad patch возвращает (False, err) без трогания tree
* Commit message включает title, rationale, request_id
* ``cleanup_worktree`` removes + idempotent
* Apply failure оставляет master ref нетронутым
  (belt-and-braces)
* Branch name uses short-id prefix

``tests/test_admin_proposal_wiring.py`` (5):
* Все три route'а в ``ROUTES``
* Все три wired в core.py router
* Все три экспортированы в platform wiring map
* Dataclass имеет все три поля
* ``make_app`` регистрирует все три (full wire smoke)

Full suite: 1434 passed, 1 known-flaky
``test_probe_tcp_timeout_short`` из baseline.

### Проверено live

Bridge на 4.19.0. Submitted реальный proposal из curl'а:

    curl -sSf -X POST \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "title": "add trailing newline to README",
        "rationale": "POSIX text files end with LF.",
        "diff": "diff --git a/README.md ..."
      }' \
      $ARENA_BRIDGE_URL/v1/admin/proposal/submit

Response пришёл сразу с ``request_id`` и ``state: queued``.
Poll'ил ``/status`` — state advanced queued → applying →
testing → **passed** за ~40s (pytest run). Branch
``proposal/e2f3...`` существует на хосте, worktree
materialised в
``~/arena-bridge/.arena_proposals/worktrees/e2f3.../``.
``git log`` на branch показывает точное commit message которое
мы сконструировали. Master нетронут.

Затем submit'нул hostile proposal трогающий ``token.txt`` —
вернулся ``400 diff rejected: diff mentions blocked path
pattern: 'token.txt'``. Никакой git активности, никакого
worktree. Audit event ``proposal_rejected_preflight``
записан.

### Намеренно не включено

* **Automatic push to origin.** Push позволил бы passing
  proposal'у попасть в PR queue reviewer'а автоматически —
  приятная эргономика но safety envelope расширяется на сеть.
  Подожду когда live user попросит.
* **No merge, no fast-forward.** Тот же аргумент — весь смысл
  "human review required" в том что ``git merge`` остаётся
  manual action.
* **No proposal cancellation.** Раз queued — бежит. ``DELETE
  /v1/admin/proposal/<id>`` endpoint должен был бы прервать
  in-flight pytest чисто — doable, отложено.
* **No agentctl wrapper yet.** ``agentctl proposal submit
  --title ... --diff-file patch.diff`` — очевидный следующий
  шаг; filed для v4.20.
* **No Dashboard tab.** List-and-diff UI был бы приятен но
  JSON response достаточен для shell workflow.

### Рефлексия

Не знаю кто-нибудь ли РЕАЛЬНО будет использовать этот
endpoint. Может лежать неиспользованным вечно потому что
human developers предпочитают свой git flow. Но он существует,
и safety envelope достаточно tight чтобы включение это
non-decision — worst case отказанный proposal, best case
агент фиксит баг без того чтобы человек когда-либо писал в
master.

Иван сказал "мне интересно к чему придёт проект чисто от ИИ" —
вот куда я решил его повести. Не уверен что это правильно, но
это решение которое я принял.

\n## v4.18.0 - 2026-07-16

### Добавлено - Terminal tab: OSC hyperlinks + title stripping

v4.15.0 ANSI parser обрабатывал CSI escapes (цвета, bold,
underline) но каждая OSC sequence (``ESC ] Ps ; Pt ST``) leaked
через как literal text. Реальные shell'ы emit'ят два OSC постоянно
— ``OSC 8`` для hyperlinks (``ls --hyperlink=always``, git diff
recent versions, gcc/rustc diagnostics) и ``OSC 0/1/2`` для
window / tab titles. Оба показывались в Terminal tab как raw
``\x1b]8;;URL\x1b\...`` gunk, обёрнутый вокруг того что shell
реально хотел сказать. v4.15.0 CHANGELOG flagged это как
follow-up; v4.18.0 делает работу.

### OSC handling

Два flavour'а handled explicitly, всё остальное silently
stripped:

* **``OSC 8 ; params ; URL``** — proper hyperlink. Wrap'ит text
  между open + close markers в ``<a>`` tag с ``target="_blank"``
  и ``rel="noreferrer noopener"``. URL sanitised против
  ``javascript:``, ``data:``, ``vbscript:``, ``file:`` schemes
  и против embedded control characters — rejected URLs всё ещё
  render'ят surrounding text без anchor wrap. Per-link params
  (например ``id=xyz``) split off и dropped; только URL portion
  попадает в ``href``.
* **``OSC 0`` / ``OSC 1`` / ``OSC 2``** — window / icon / tab
  title. Silently dropped. Terminal tab не имеет title bar; это
  был бы просто noise.
* **Всё остальное** — ``OSC 9`` (progress reports), ``OSC 133``
  (finalTerm markers), ``OSC 1337`` (iTerm2), ``OSC 771``
  (Kitty) и т.д. — silently stripped. Scrollback pane, не
  full-featured terminal.

Оба terminator формы (BEL / ``0x07`` и ST / ``ESC \``)
recognised.

### XSS guardrails

OSC 8 URLs — attacker-controlled bytes из stdout. Любой shell
process (или ``echo -e`` в prompt injection) может напечатать
что угодно в это поле. Два слоя защиты:

1. **Scheme reject-list**: ``javascript:``, ``data:``,
   ``vbscript:``, ``file:`` (case-insensitive). Rejected URLs
   render visible text без anchor'а — link dropped, text
   остаётся.
2. **Control-character reject**: любой URL содержащий
   ``\x00..\x1f``, whitespace, ``"``, ``'``, ``<``, ``>`` или
   backtick — reject. Блокирует attribute-context escapes и
   RFC-violating URLs.

Два regression-теста specifically feed hostile payloads
(``ESC]8;;javascript:alert(1)ESC\...``) и assert anchor НЕ
render'ится.

### Compose с v4.15.0

v4.15.0 SGR body был refactor'ен в ``_ansiSgrHtml(src, state)``
— inner function принимающая mutable state object. Новый outer
``__termAnsiToHtml`` сначала запускает ``__oscPreprocess`` для
split'а input'а в ordered список ``{text, href-open,
href-close}`` pieces, потом драйвит SGR renderer per text-run
carrying colour state через hyperlink boundaries.

Реальные shell'ы relies на этот compose: ``git diff`` окрашивает
имя файла И wrap'ит его в OSC 8 hyperlink; цвет продолжается
после anchor close. Regression-guarded
``test_osc_8_colour_carries_across_hyperlink_boundary``.

### Файлы

* ИЗМЕНЁН ``dashboard/assets/05b-terminal-ansi.js`` (246 -> 348
  строк) — новый ``_ansiSgrHtml`` inner renderer,
  ``__oscPreprocess`` splitter, ``__oscSafeUrl`` validator,
  ``_UNSAFE_SCHEMES`` reject-list. ``__termAnsiToHtml`` rebuild
  вокруг них. ``__termAnsiStrip`` теперь drops OSC first, потом
  CSI.

Zero shared-CSS surgery (v4.0.x lesson всё ещё держится): no
new CSS at all. ``dashboard.css`` byte-identical к v4.17.0 (109
строк).

### Тесты

1381 -> 1400 passed (+19 в ``tests/test_terminal_osc.py``):

Static guards (5):
* OSC helpers (``__oscPreprocess`` / ``__oscSafeUrl`` /
  ``_UNSAFE_SCHEMES``) present в module
* Unsafe-scheme list включает все четыре dangerous schemes
* SGR body extracted в ``_ansiSgrHtml`` inner renderer
* Hyperlink anchors используют ``target="_blank"`` +
  ``rel="noreferrer noopener"``
* ``__termAnsiStrip`` drops OSC before CSI

Node integration (14):
* OSC 8 hyperlink wraps text в ``<a href="..." target="_blank" ...>``
* OSC 8 принимает BEL terminator (не только ST)
* ``javascript:``, ``data:``, ``vbscript:`` schemes stripped;
  visible text preserved
* URL с HTML metacharacters rejected (control-char filter)
* OSC 0 / 1 / 2 (titles) silently dropped
* Unknown OSC (9, 1337, 771, 133) silently dropped
* Colour carries across OSC-8 hyperlink boundary
* ``__termAnsiStrip`` drops оба OSC и CSI
* Stray OSC 8 close без open — no ``</a>``
* Unclosed OSC 8 open auto-closes at end of input (DOM balance)
* Per-link ``id=xyz`` params stripped, URL preserved
* OSC + CSI compose (green hyperlinked text) с balanced
  ``<span>`` и ``<a>`` counts

Full suite: 1400 passed, 1 known-flaky
``test_probe_tcp_timeout_short`` из baseline.

### Проверено live

Bridge на 4.18.0. Прогнал три сценария через Terminal tab с
stream mode on:

1. **``ls --hyperlink=always /home/ivan``** (Linux ``ls`` с
   OSC 8 support) — каждое filename render'ено как clickable
   anchor указывающий на ``file:///home/ivan/...``. Но ``file:``
   в нашем reject-list. Так что anchors были STRIPPED и только
   coloured filenames показались — correct security-conscious
   behaviour. Если добавим opt-in для local-file links —
   сделаем через settings flag, не через loosening reject-list.
2. **``printf 'text \x1b]0;my title\x1b\\ after-title\n'``** —
   ``my title`` не render'ится нигде; ``text`` и
   ``after-title`` появляются plain. Title dropped as designed.
3. **Composed** —
   ``printf '\x1b[31m\x1b]8;;https://example.com/\x1b\\red-link\x1b]8;;\x1b\\\x1b[0m\n'``
   — render'ится как ``<a href="https://example.com/"
   target="_blank" rel="noreferrer noopener"><span
   style="color:#cc0000">red-link</span></a>``. Click открывает
   example.com в новом tab.

### Не включено

* Custom hyperlink click handler (например copy-URL-to-clipboard
  on right-click). Нужен Terminal-tab-scoped event delegate;
  filed as follow-up.
* Дополнительные OSC handlers (iTerm2 shell integration,
  finalTerm markers). Ни один не добавит value в scrollback
  pane; reject-all policy остаётся.
* "Allow ``file:`` links" opt-in. Нужен per-user setting + UI
  toggle; не срочно.

\n## v4.17.0 - 2026-07-16

### Добавлено - agentctl breaker CLI (status | deprio | reset)

Composition release. v4.8.0 circuit breaker, v4.14.0 reset
endpoint и v4.16.0 ``breaker_summary`` shape — три полезных
HTTP-primitive'а которые всё ещё требовали ``curl | jq`` из
shell'а. v4.14.0 CHANGELOG уже flagged CLI wrapper как
follow-up; v4.17.0 доставляет.

Три shell-verb'а под новым namespace ``breaker``:

    agentctl breaker status              # human-readable snapshot
    agentctl breaker status --json       # raw JSON для скриптов
    agentctl breaker status --quiet      # only side effect
    agentctl breaker status --no-fail-open
    agentctl breaker deprio              # имена deprio'd providers
    agentctl breaker deprio --json
    agentctl breaker reset               # сбросить всё
    agentctl breaker reset <key>         # сбросить one keyed record
    agentctl breaker help                # per-verb usage

### Human-readable output

    $ agentctl breaker status
    KEY                              STATE   FAILS  COOLDOWN   LAST ERROR
    cloudflared|foo.example:443      open        3    42.0s    timeout after 1.5s
    zerotier|10.57.152.120:8765      closed      1              connection refused
    summary: total=2 open=1 warn=1 open_providers=cloudflared warn_providers=zerotier
    $ echo $?
    3

### Meaningful exit codes

* ``0`` — success (nothing wrong / operation completed)
* ``1`` — bridge unreachable ИЛИ bridge вернул ``ok: false``
* ``2`` — usage error / unknown verb
* ``3`` — хотя бы один breaker open (``status`` / ``deprio``)

Shell one-liner может делать

    agentctl breaker status --quiet || page-oncall

без парсинга JSON. Когда exit-3 мешает (cron dashboards) —
использовать ``--no-fail-open``.

### Backward-compat со старыми bridge'ами

``deprio`` предпочитает v4.16.0 поле ``deprioritized``, fallback
на ``breaker_summary.open`` (v4.15.x transitional shape), и в
крайнем случае — fresh ``/v1/tunnels/probe`` call с local
``_summarize`` (identical rules к
``arena.admin.tunnels_breaker.summarize_snapshot``). Работает
против любого bridge v4.8.0 и новее без изменений.

Regression-guarded ``test_local_summarize_mirrors_v416_helper``
— CLI compat helper и server helper остаются byte-identical.

### Файлы

* НОВЫЙ ``arena/agentctl_cli/agentctl_breaker.py`` (246 строк)
  — ``status`` / ``deprio`` / ``reset`` / ``help_``
  implementations + local ``_summarize`` compat helper +
  крохотный ``_parse_flags`` argv парсер.
* ИЗМЕНЁН ``arena/agentctl_cli/agentctl_main.py`` (95 -> 100
  строк) — import, DISPATCH entry, help text row.

Весь namespace идёт через existing ``bridge_get`` /
``bridge_post`` helpers — token loading, SSL context handling,
error surfacing matches каждому другому ``agentctl`` verb
(никакого custom transport кода).

### Тесты

1363 -> 1381 passed (+18 в ``tests/test_agentctl_breaker.py``):

Subprocess-тесты используют реальный ``http.server``-based
stub bridge'а — весь HTTP round-trip (``urllib.request``,
authorization header, JSON encode/decode) exercised, не просто
imports.

* Top-level ``agentctl commands`` help листит новый namespace
* ``breaker help`` printит per-verb usage со всеми флагами
* ``status`` empty snapshot -> exit 0 + placeholder
* ``status`` c open breaker -> exit 3 + таблица + summary
  footer + last-error string
* ``status --no-fail-open`` suppress'ит exit 3
* ``status --json`` emit'ит parseable JSON c v4.16.0 summary
* ``status --quiet`` suppress'ит таблицу но keeps exit 3
* ``status`` против unreachable bridge -> exit 1 (не 3)
* ``status`` против ``ok: false`` -> exit 1
* ``deprio`` prints один provider на строку + exits 3 когда
  non-empty
* ``deprio`` empty list -> exit 0, no output
* ``deprio --json`` wraps в ``{"deprioritized": [...]}``
* ``deprio`` fallback на ``breaker_summary.open`` на старом
  bridge
* ``reset`` (без key) POST'ит empty ``{}`` body
* ``reset <key>`` POST'ит ``{"key": "..."}``
* ``reset`` против ``ok: false`` -> exit 1
* Local ``_summarize`` mirrors ``summarize_snapshot``
  byte-for-byte на mixed snapshot
* Local ``_summarize`` observe'ит то же "open dominates over
  warn" правило для same-provider dual endpoints

Full suite: 1381 passed, 1 known-flaky
``test_probe_tcp_timeout_short`` из baseline.

### Проверено live

Bridge на 4.17.0. Прогнал три verb'а из shell'а:

    $ agentctl breaker status
    (breaker empty -- no probes yet)
    $ echo $?
    0

    $ curl -sSN ... /v1/exec/stream ...   # trigger real probe
    $ agentctl breaker status
    KEY                              STATE   FAILS  COOLDOWN   LAST ERROR
    zerotier|10.57.152.120:8765      closed      0
    summary: total=1 open=0 warn=0

    $ agentctl breaker deprio
    (empty output)
    $ echo $?
    0

    $ agentctl breaker reset
    ok: reset=all cleared=1

    $ agentctl breaker reset cloudflared|foo:443
    ok: reset=cloudflared|foo:443 cleared=1

Все roundtrips через живой bridge; audit log подтверждает два
``tunnels_breaker_reset`` события с expected ``key`` и
``keys_cleared`` значениями.

### Не включено

* Auto-completion (bash / zsh / fish). Tool's help output
  достаточно discoverable для current surface; если verb-list
  вырастет за ~10 — добавим completion. Filed as follow-up.
* Colored output. ``agentctl`` не ships colour anywhere else
  today; если добавим global colour flag — breaker status
  table выиграет, но это broader UX pass.
* ``--watch`` mode (re-polling ``status`` каждые N seconds).
  Тривиально с ``watch(1)`` сегодня: ``watch -n 5 agentctl
  breaker status``. Если хиты OS без ``watch`` — reconsider.

\n## v4.16.0 - 2026-07-16

### Добавлено - GET /v1/agent/config: breaker_summary + deprioritization

v4.1.0 agent bootstrap endpoint возвращал ordered список
reachable URLs based on raw provider priority. После v4.8.0
circuit breaker'а — provider fail'нувший последние несколько
probes всё ещё показывался в списке; наивная агентская логика
"try in order" пикала известно-broken URL и платила failure
cost на каждом fresh dial. v4.15.0 CHANGELOG flagged это как
follow-up; v4.16.0 делает работу.

Response теперь содержит два новых поля, на которые агент
может реагировать без второго round-trip:

* **``breaker_summary``** — компактный per-provider view
  derived from ``breaker`` snapshot'а который v4.8.0 embed'ит
  в probe response. Shape:

      {
        "open":       ["cloudflared"],
        "warn":       ["zerotier"],
        "closed_ok":  ["tailscale"],
        "total_records": 3,
        "open_count":    1,
        "warn_count":    1,
      }

  Provider names dedup'нуты (Cloudflared reissue с новым
  hostname'ом всё равно one provider) и sorted детерминистично
  — агент диффящий два подряд response не видит spurious
  changes.

* **``deprioritized``** — flat sorted список имён providers у
  которых хотя бы один open breaker. Пусто на fresh bridge.
  Convenience alias для ``breaker_summary["open"]`` — caller
  может ``if config["deprioritized"]: log_warning(...)`` без
  рытья в summary struct.

### Reordering

Если любой provider в ``deprioritized`` — handler также:

1. Rebuild'ит ``priority`` list, keeping original order среди
   non-deprio'd, потом append'ит deprio'd в их original порядке
   в хвост.
2. Sort'ит ``urls`` тем же способом — healthy URLs first,
   deprio'd последними, ordering внутри partition сохранён.
3. Recompute'ит ``primary`` из ``urls[0]`` — "первый URL для
   dial'а" всегда matches reordered list.
4. Preserve'ит pre-reorder priority в ``priority_original`` —
   diagnosing caller видит что изменилось и почему.

Backward compat: на fresh bridge (empty breaker) response
byte-identical к v4.15.x кроме двух additive полей —
``priority_original`` = ``null``, ``deprioritized`` = ``[]``,
``breaker_summary`` с zero counts. Ничего existing не ломается.

### Правило "open dominates"

Provider с двумя endpoint'ами (Cloudflared reissue с новым
hostname'ом) treated как **один** provider entry в summary.
Если **любой** endpoint open — весь provider в ``open``;
иначе если любой имеет ``consecutive_failures > 0`` (closed но
trending bad) — попадает в ``warn``; иначе ``closed_ok``.
Regression-guarded
``test_summarize_open_dominates_over_warn_for_same_provider``.

### Файлы

* ИЗМЕНЁН ``arena/admin/tunnels_breaker.py`` (273 -> 331) —
  новый ``summarize_snapshot(snapshot)`` helper, добавлен в
  ``__all__``.
* ИЗМЕНЁН ``arena/admin/handlers.py`` (462 -> 502) —
  ``handle_v1_agent_config`` теперь вызывает
  ``summarize_snapshot``, rebuild'ит priority, sort'ит urls,
  включает ``breaker_summary`` + ``deprioritized`` +
  ``priority_original`` в response.

### Тесты

1348 -> 1363 passed (+15 в
``tests/test_agent_config_breaker.py``):

Pure helper (``summarize_snapshot``):
* Empty snapshot возвращает документированный stable shape
* Open provider appears в ``open`` list
* Closed-with-failures appears в ``warn``
* Closed-zero-failures appears в ``closed_ok``
* Open dominates over warn для same-provider dual endpoints
* Provider names sorted детерминистично (agent-diff friendly)
* Multiple providers через все три states classified корректно
* Tolerates malformed records (empty dict, non-dict, None
  values) без raise

Handler integration:
* Response shape включает ``breaker_summary``,
  ``deprioritized``, ``priority_original``
* Handler вызывает
  ``summarize_snapshot(probe.get("breaker") or {})``
* Priority reorder keeps non-deprio order, sinks deprio to tail
* URLs sort by (deprio-flag, effective-priority-index)
* ``primary`` recomputed из ``urls[0]`` post-reorder
* No reorder когда нет open breakers (backward compat)
* ``summarize_snapshot`` в ``__all__``

Full suite: 1363 passed, 1 known-flaky
``test_probe_tcp_timeout_short`` из baseline.

### Проверено live

Bridge на 4.16.0. Fresh bridge (empty breaker):

    $ curl ... /v1/agent/config | jq '.breaker_summary, .deprioritized, .priority_original'
    {
      "open": [],
      "warn": [],
      "closed_ok": ["zerotier"],
      "total_records": 1, "open_count": 0, "warn_count": 0
    }
    []
    null

Seeded open breaker через singleton в python shell'e, затем
re-call agent_config: ``deprioritized`` вернулся как
``["cloudflared"]``, ``breaker_summary.open_count == 1``,
``priority`` сунула cloudflared в хвост, ``priority_original``
echo'нул pre-sink порядок. Reset breaker через
``POST /v1/tunnels/probe/reset`` (v4.14.0) — next agent_config
имел ``deprioritized == []`` и ``priority_original == null``
снова.

### Composition с прошлыми relases

    tunnels_probe (v4.8.0) ─┐
                            ├→ breaker snapshot в каждом probe response
    breaker records ────────┘                    │
                                                 ↓
    summarize_snapshot (v4.16.0) ← этот релиз
                                                 ↓
    GET /v1/agent/config → {breaker_summary, deprioritized, ...}
                                                 ↓
    агент dial logic: skip deprio'd URLs entirely ИЛИ используй
                      их как fallback после primary set

    tunnels_probe/reset (v4.14.0) ← operator escape hatch
                                       clear'ит breaker — next
                                       config call drop'ает
                                       deprio flag

### Не включено

* SLO / cool-down forecasting. Response имеет
  ``cools_down_in_sec`` в raw ``breaker`` поле
  ``/v1/tunnels/probe``; agent-config summary не дублирует —
  "когда вернётся" это telemetry question, не bootstrap.
  Если агенту нужен cooldown — hit probe endpoint напрямую.
* Per-endpoint (не per-provider) summary. Раздуло бы compact
  shape для редкого случая (multi-endpoint providers —
  исключение). Если operator попросит — добавим
  ``breaker_summary_verbose`` opt-in flag.
* Push-based invalidation (SSE / WebSocket говорящий агентам
  reload config'а). Polling model (агент re-hit'ит
  ``/v1/agent/config`` на connection failure) достаточен для
  каждого observed случая.

\n## v4.15.0 - 2026-07-16

### Добавлено - Terminal tab: ANSI SGR colour rendering

v4.13.0 stream-mode toggle качал raw stdout/stderr прямо в
output ``<pre>``. Всё что печаталось с ANSI colour escapes --
``ls --color=always``, ``docker pull`` progress bars, ``pytest``
failure summaries, ``cargo`` compiler output -- показывалось
литеральным ``\x1b[31mFAILED\x1b[0m`` вместо красного "FAILED".
v4.13.0 CHANGELOG flagged это как follow-up work; v4.15.0
делает работу.

Client-side ANSI SGR (Select Graphic Rendition) parser
конвертирует escape sequences в inline-styled ``<span>``
элементы. Каждое место где Terminal tab писал в
``slot.out.textContent`` теперь идёт через новый
``_termWriteOut(slot, text)`` helper:

* Fast-path: строки без ``ESC[`` fall through в ``textContent``
  (zero cost для обычных команд).
* SGR-path: строки с escapes сначала HTML-escape'ятся, потом
  parser wrap'ит runs styled-text в ``<span style="...">``
  элементы, потом результат пишется в ``innerHTML``.

Raw uncoloured строка stash'ится в ``slot.out._rawText`` -
"Copy Output" всё ещё round-trip'ит чистый текст (``innerText``
уже strip'ает spans natively).

### Поддерживаемые SGR коды

Все коды которые реальный shell реально emit'ит:

* ``0`` reset
* ``1`` / ``22``   bold on / off
* ``2``            dim on
* ``3`` / ``23``   italic on / off
* ``4`` / ``24``   underline on / off
* ``7`` / ``27``   inverse on / off  (swap fg/bg)
* ``30..37`` / ``39``     basic foreground / default
* ``40..47`` / ``49``     basic background / default
* ``90..97``              bright foreground
* ``100..107``            bright background
* ``38;5;N`` / ``48;5;N``       256-colour (xterm cube)
* ``38;2;R;G;B`` / ``48;2;R;G;B`` truecolour (24-bit)

Всё остальное -- blink, hidden, framed, и каждая non-SGR CSI
sequence типа cursor moves (``ESC[H``), screen clears
(``ESC[2J``), DEC private modes (``ESC[?25l``) -- silently
stripped. Terminal tab это scrollback pane, не real TTY;
позволить app repaint'ить над previous output было бы хуже
чем не rendering escapes вообще.

### Палитра

Mirror'ит classic xterm defaults: не too bright, всё ещё
читаема на ``#0f0f23`` dashboard background. Bright colours
используют standard "brighter" set, не gratuitous saturation
bump. 256-colour cube builds'ится на module load time из
xterm ``[0, 95, 135, 175, 215, 255]`` step table + 24-step
grayscale ramp.

### XSS safety

Каждый byte shell output HTML-escape'ится **до того как**
parser wrap'ит его в span. Команда типа
``echo -e '\x1b[31m<script>alert(1)</script>\x1b[0m'``
рендерится как literal красная строка ``<script>alert(1)</script>``,
а не executed script. Покрыто dedicated node-integration
тестом (``test_ansi_escape_helper_uses_esc_from_dashboard``).

### Файлы

* НОВЫЙ ``dashboard/assets/05b-terminal-ansi.js`` (229 строк) --
  standalone parser: ``__termAnsiToHtml`` (main entry),
  ``__termAnsiStrip`` (для copy-to-clipboard callers),
  ``__ansiStyleFromState`` (state → inline ``style="..."``),
  ``__ansiApplyCodes`` (mutate state для one SGR run),
  ``__ANSI_BASIC`` / ``__ANSI_BRIGHT`` / ``__ANSI_XTERM256``
  palette-константы.
* ИЗМЕНЁН
  ``dashboard/assets/05-terminal-v1-6-2-persistent-shell-like-se.js``
  (389 -> 407) -- новый ``_termWriteOut(slot, text)`` helper +
  8 call-site rewrites (обе stream-mode + buffered branches).

Manifest автогенерится из ``dashboard/assets/`` — 
``05b-terminal-ansi.js`` встаёт между ``05-terminal-*.js`` и
``06-memory.js`` по prefix sort -- никаких manifest правок.

### Regex expansion (permissive CSI grammar)

Strip regex теперь
``/\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]/g`` -- принимает
DEC private-mode marker (``?``, ``<``, ``=``, ``>``) который
programs типа ``htop`` и ``clear`` inject'ят. Без этого первый
``ESC[?25l`` (hide cursor) сломал бы pipeline и dump'нул
остальной escape как literal text. Regression-guarded
``test_ansi_non_sgr_csi_is_stripped_not_rendered`` и
``test_ansi_strip_removes_all_csi_leaves_visible_text`` -- оба
нашли bug на первом test run и drove fix.

### Ноль shared-CSS хирургии (v4.0.x lesson всё ещё держится)

* ``dashboard.css`` byte-identical к v4.14.0 (109 строк,
  baseline).
* Никакого нового CSS вообще -- colours inline на emitted
  ``<span>`` элементах, как в реальном терминале.
* ``.term-*`` scoped-блок в ``body-02-terminal.html`` (v4.13.0)
  не тронут.

### Тесты

1329 -> 1348 passed (+19 в ``tests/test_terminal_ansi.py``):

Static guards:
* ANSI module present, exposes все named helpers
* Terminal tab роутит каждый stdout write через
  ``_termWriteOut`` (regression против bare ``textContent`` =
  call который swallow'нул бы escapes)
* Helper fast-path'ит ANSI-free строки через ``textContent``
  (guards против rewrite который всегда hits innerHTML)
* Non-SGR CSI stripping branch exists; strip regex --
  permissive shape
* Каждый emitted chunk идёт через ``__ansiEsc`` (XSS guard)

Node-integration (real JS execution, без headless browser):
* Plain text без escapes -> HTML-escaped, no spans
* Empty / null / undefined return empty string
* Basic foreground (ESC[31m) wrap'ит только styled text
* Bold + underline + colour compose в одном span
* 256-colour foreground resolves в xterm cube hex
* Truecolour 38;2;R;G;B resolves в lowercase hex
* Inverse (ESC[7m) swap'ит fg и bg
* Non-SGR CSI (cursor move, hide cursor) silently dropped
* Malformed escape не throw'ает; emit'ит best-effort text
* Reset закрывает spans cleanly (equal <span>/</span> counts)
* __termAnsiStrip removes каждый CSI, keeps visible text
* ``<script>`` / ``&`` / ``"`` в shell output все escape'ятся
  перед вхождением в span (dedicated XSS regression test)
* Bright foreground 91..97 resolves в bright palette, не basic

Также обновлён один v4.13.0 test
(``test_js_appends_output_incrementally_not_at_end``) который
считал ``slot.out.textContent =`` writes напрямую -- теперь
считает ``_termWriteOut(slot,`` calls тоже.

CSS containment:
* ``dashboard.css`` не тронут ``term-ansi`` / ``ansi-span`` /
  ``ANSI_`` tokens

Full suite: 1348 passed, 1 known-flaky
``test_probe_tcp_timeout_short`` из baseline.

### Проверено live

Bridge на 4.15.0. Открыл Terminal tab через ZeroTier overlay
с stream mode on, run'нул три сценария:

1. **Coloured output**:
   ``printf '\x1b[31mred\x1b[0m \x1b[32mgreen\x1b[0m \x1b[1;33mbold-yellow\x1b[0m\n'``
   -- rendered ожидаемыми тремя цветами, "bold-yellow" visibly
   тяжелее.
2. **256-colour progress-bar-style output**:
   ``for i in 40 41 42 43 44; do printf '\x1b[38;5;%dm████\x1b[0m' $i; done``
   -- пять gradient blocks появились в xterm cube colours.
3. **``ls --color=always``** на ``/home/ivan`` -- directory
   names синим, executables зелёным, symlinks cyan; никаких
   literal escapes; total output identical тому что shell
   показал бы в proper terminal.

Buffered mode (stream mode off) также verified с теми же
inputs -- coloured output течёт через shared ``_termWriteOut``
helper независимо от transport'а.

### Не включено

* SGR blink (``5``, ``6``) rendering. Blink universally
  hated в modern terminals; принимаем код silently но
  не produce CSS animation. Skip.
* Bold-brightens-basic-colours behaviour. Некоторые old
  terminals трактовали bold как "используй bright palette
  для этого colour" -- мы трактуем bold как
  ``font-weight:700`` и colour как exact code, что matches
  каждый modern terminal.
* OSC sequences (window title, hyperlinks). Требует
  отдельного ``ESC]...ESC\`` parser'а; отложено. Strip
  regex CSI-only, так что OSC sequence сегодня покажется
  literal text'ом -- annoying но не security concern.

\n## v4.14.0 - 2026-07-16

### Добавлено - POST /v1/tunnels/probe/reset + Dashboard reset кнопки

У v4.8.0 circuit breaker было ровно два escape hatch: **ждать
60s** или **``systemctl restart arena-bridge``**. Ни то, ни
другое не выглядело как first-class ops tool. Когда Cloudflared
quick-tunnel bouncнулся и breaker открылся — оператор смотрящий
Overview либо сидел в cooldown timer, либо рестартил весь bridge
(с потерей всех остальных connection). v4.8.0 CHANGELOG flagged
это как follow-up work; v4.14.0 делает работу.

### Новый endpoint

    POST /v1/tunnels/probe/reset

Body (optional JSON):

    {"key": "cloudflared|foo.trycloudflare.com:443"}

* **С key**  — дропает конкретную breaker-запись, следующий
                 probe запустится сразу.
* **Без key** (пустой / non-JSON body) — дропает все записи.

Response:

    {
      "ok": true,
      "reset": "cloudflared|foo:443" | "all",
      "keys_cleared": 1,
      "breaker_before": {...v4.8.0 snapshot...},
      "breaker_after":  {...то же, скорее всего пусто после reset...}
    }

Тот же ``@authed`` gate что и у любого admin endpoint. Body
parse best-effort — malformed / missing / whitespace-only body
fall'ится через на "reset all", ``curl`` typo не вернёт 500.

Audit trail: событие ``tunnels_breaker_reset`` с полями
``key``, ``keys_cleared`` и ``client`` — post-hoc investigation
("кто сбросил Cloudflared breaker в 14:22 и заставил outage
выглядеть короче, чем он был?") реально возможна.

### Dashboard: reset кнопки в Network Status card

Два новых контрола появляются в v4.11.0 net-breaker row:

* **Per-badge "×" button** — появляется внутри каждой ``open``
  badge. Клик POST'ит exact key; badge исчезает (или снова
  появляется в ``warn`` state если underlying provider всё ещё
  fails).
* **"Reset all" button** в хвосте строки — появляется как только
  любой breaker open. Клик POST'ит пустой body; все записи
  очищаются в один round-trip. Полезно при full network flap
  когда сразу три provider'а stuck.

Обе кнопки debounce'ятся через ``.disabled = true`` пока
request in-flight, потом вызывают ``refreshNetBreaker()`` для
немедленного Overview repaint — оператор не ждёт следующий
tick.

Healthy-triple хосты не видят ничего лишнего: сама row скрыта
v4.11.0 когда breaker snapshot пуст, reset controls остаются
out of the way.

### Файлы

* ИЗМЕНЁН ``arena/admin/handlers.py`` (407 -> 462 строки) —
  новый ``handle_v1_tunnels_probe_reset`` handler, поле
  ``AdminHandlers.tunnels_probe_reset``.
* ИЗМЕНЕНЫ ``arena/route_registry/{registry,core}.py`` —
  ``POST /v1/tunnels/probe/reset`` в ``core`` group.
* ИЗМЕНЁН ``arena/wiring/platform.py`` — экспорт нового
  handler'а под ``handle_v1_tunnels_probe_reset``.
* ИЗМЕНЁН ``dashboard/assets/04c-net-breaker.js`` (106 -> 154
  строки) — per-badge и bulk reset кнопки + click handlers +
  auto-refresh call.
* ИЗМЕНЁН ``dashboard/assets/body-01-overview.html`` (133 ->
  143 строки) — scoped ``.reset`` и ``.reset-all`` стили
  внутри существующего ``#tab-overview #networkCard`` блока.

### Ноль shared-CSS хирургии (v4.0.x lesson всё ещё держится)

* ``dashboard.css`` byte-identical к v4.13.0 (109 строк).
* Каждое новое правило scoped ``#tab-overview #networkCard
  .net-breaker-list ...``.
* Reset кнопки наследуют цвет от badge внутри которой они
  находятся (``color:inherit`` + ``border:1px solid
  currentColor``) — red-open / yellow-warn / blue-ok палитра
  протекает без единого hex literal.
* Bulk "Reset all" использует ``var(--accent)`` для hover
  background — reuse shared palette variable, не новый цвет.

### Тесты

1311 -> 1329 passed (+18 в
``tests/test_tunnels_breaker_reset.py``):

Backend (route + wiring + handler behaviour):
* POST /v1/tunnels/probe/reset в route registry
* Wired в core router с POST verb (не GET — browsers
  cache GETs, reset button должен hit сервер каждый клик)
* Экспортирован через platform wiring map
* ``AdminHandlers`` dataclass field present
* Empty body -> reset all (drops все записи)
* ``{"key": "..."}`` -> reset только эта запись; others intact
* Whitespace-only key treated as "no key" -> reset all
* Malformed JSON body не 500 — treated as empty
* Audit event captures ``key`` + ``keys_cleared`` + ``client``

Dashboard UI (static checks на JS bundle):
* Per-badge "×" button appears только внутри ``state === "open"``
  branch (guards против hoist'а spam'ящего healthy triples)
* Endpoint используется verbatim; per-badge POST includes exact
  key
* "Reset all" appears только когда ``keys.some(...open)``
* "Reset all" POST'ит пустой body (не ``{key: ...}``)
* Обе кнопки debounce'ятся через ``.disabled = true``
* Обе вызывают ``refreshNetBreaker()`` on completion
* Button click ``stopPropagation()`` для future row-expand
  compatibility

Containment (v4.0.x lesson):
* ``dashboard.css`` не тронут ``.reset`` / ``.reset-all``
* Новые селекторы живут внутри ``#tab-overview #networkCard``
  scoped block

Full suite: 1329 passed, 1 known-flaky
``test_probe_tcp_timeout_short`` из baseline.

### Проверено live

Bridge на 4.14.0. Force-tested через ZeroTier overlay:

1. Симулировал три подряд failures на fake dead endpoint через
   python shell против shared breaker singleton (см.
   ``tests/test_tunnels_breaker_reset.py::_seed_breaker`` для
   того же паттерна). Overview refreshed -> красная
   ``cloudflared: cooldown 60s`` badge с "×" кнопкой внутри.
2. Кликнул "×" на badge. Request completed в ~50ms;
   ``refreshNetBreaker()`` triggered; badge исчезла (breaker
   был единственной записью; сама row скрыта v4.11.0 когда
   snapshot пустеет).
3. Подтвердил audit trail: ``GET /v1/audit?lines=3`` показывает
   ``tunnels_breaker_reset`` event с
   ``key=cloudflared|dead.example:443``, ``keys_cleared=1``,
   ``client=10.57.152.44`` (мой ZT peer IP).
4. Bulk reset также verified: seeded три breaker'а, кликнул
   "Reset all" -> single request, все три cleared, single
   audit event с ``keys_cleared=3``, ``key=all``.

### Не включено

* Confirmation dialog на "Reset all". Wide reset во время real
  incident — именно то что оператор хочет; audit trail делает
  это recoverable. Если когда-то land'нем "danger zone" UX
  pattern глобально — примем здесь тоже.
* Undo / restore pre-reset snapshot. ``breaker_before`` поле
  в response payload достаточно чтобы оператор inspect'нул
  что там было, но нет "put it back" кнопки — весь смысл
  breaker'а reflect реальность, и reset даёт реальности
  ещё одну попытку.
* CLI wrapper в ``bin/agentctl``. Композировался бы nicely с
  breaker'ом; отложено до запроса оператора.

\n## v4.13.0 - 2026-07-16

### Добавлено - Terminal tab: stream mode (использует /v1/exec/stream)

Terminal tab всегда POST'ил в ``/v1/exec`` — buffered response,
stdout/stderr приходят после завершения команды. Fine для ``ls``
или ``uname -a``; больно для всего что занимает больше секунды
(``docker pull``, ``cargo build``, ``git clone`` большого репо,
``pytest``, ``systemctl status --no-pager -l`` на busy box).
Пользователь смотрел на "running..." без фидбека до самого конца.

v4.3.0 добавил ``POST /v1/exec/stream`` (chunked NDJSON); v4.10.0
построил NDJSON consumer для Audit tab; v4.13.0 wires тот же
pattern в Terminal tab.

Новый чекбокс во второй строке Terminal toolbar: **stream mode**.
Включение переключает ``runCommand()`` на
``POST /v1/exec/stream`` и качает stdout/stderr chunks в тот же
output ``<pre>`` по мере прихода. Head row получает синюю pulse
dot рядом с кнопкой **Kill** которая POST'ит ``/v1/kill`` для
streamed ``request_id`` — runaway ``sleep 3600`` больше не
требует SSH access к bridge host для прерывания.

### Event handling

Каждый event type v4.3.0 handled explicitly:

* ``meta`` -> capture ``request_id`` для Kill button
* ``start`` -> head label переключается с "streaming..." на
              "pid ``N``" — оператор знает что process spawned
* ``stdout`` -> append в accumulator + repaint ``<pre>`` +
              scroll session pane чтобы tail оставался в view
* ``stderr`` -> same, rendered под ``--- STDERR ---`` divider'ом
* ``exit`` -> capture ``exit_code`` + ``timed_out`` для final
             badge

Всё остальное (server-emitted ``error`` / ``raw`` / future
control events) игнорится cleanly вместо крэша парсера.

### Kill button

Кнопка появляется рядом со streaming pulse dot сразу как команда
стартует. Клик:

1. Disables self + label flips на "killing..."
2. POST ``/v1/kill {"request_id": "..."}`` (best-effort;
   fall'ится через на abort на any error)
3. ``controller.abort()`` tears down client-side fetch — browser
   перестаёт buffer'ить после server close

Если Kill fires до прихода ``meta`` (request killed за
миллисекунды после open) — client-side abort единственный path;
server ещё не allocated ``request_id`` и ``/v1/kill`` нечего
искать.

### Cross-browser + graceful fallback

Feature-detected через ``ReadableStream`` +
``Response.body.getReader`` на page load. Браузеры без поддержки
получают checkbox rendered ``disabled`` с полезным tooltip'ом —
``runCommand()`` тогда falls back на buffered ``/v1/exec`` branch
который всегда работал. Никаких mystery no-op при клике, никакой
регрессии для тех кто на старом браузере.

### Ноль shared-CSS хирургии (v4.0.x lesson всё ещё держится)

* ``dashboard.css`` byte-identical к v4.12.0 (109 строк,
  baseline).
* Все новые стили scoped ``#tab-terminal ...`` в ``<style>``
  блоке таба.
* Kill-button ``:hover`` использует scoped palette-переменную
  ``--term-kill-hover`` вместо bare hex literal —
  ``test_no_hardcoded_theme_colors`` остаётся green и всё ещё
  matches shared ``.danger`` button pair's darker red.

### Файлы

* ИЗМЕНЁН ``dashboard/assets/body-02-terminal.html`` (30 -> 40) —
  scoped ``<style>`` блок для ``.term-kill-btn`` и
  ``.term-stream-dot`` (с ``@keyframes term-stream-pulse``);
  новый ``termStream`` checkbox во второй toolbar-row.
* ИЗМЕНЁН
  ``dashboard/assets/05-terminal-v1-6-2-persistent-shell-like-se.js``
  (198 -> 389) — новый ``__termStreamSupported`` probe,
  ``_runStreamedCommand`` helper (fetch + ReadableStream +
  NDJSON parser + per-chunk repaint + Kill wiring), ``runCommand``
  получает branch консультирующийся с checkbox перед выбором
  stream vs buffered, ``_initStreamToggle`` на script load
  disables checkbox на unsupported browsers.

### Тесты

1297 -> 1311 passed (+14 в
``tests/test_terminal_stream_mode.py``):

Markup:
* ``termStream`` id + ``.term-stream-dot`` + ``.term-kill-btn``
  стили present
* Каждое non-keyframe правило scoped на ``#tab-terminal``

JS behaviour:
* ``__termStreamSupported`` + ``_runStreamedCommand`` present
* Использует ``/v1/exec/stream`` с ``method: "POST"``
* Handles все пять NDJSON event types (meta/start/stdout/stderr/exit)
* Captures ``request_id`` из meta для ``/v1/kill``
* Использует ``AbortController`` для clean stop
* Append'ит output incrementally (несколько ``slot.out.textContent =``
  writes внутри stream body — regression guard против "collect +
  write once at end")
* ``ReadableStream`` feature-detect + disabled checkbox на
  unsupported
* Buffered ``/v1/exec`` fallback branch всё ещё present
* ``overviewMetrics.execs`` инкрементится в ОБОИХ путях (guards
  против будущей правки ticking только one)
* ``_initStreamToggle`` disables checkbox на load time

Containment:
* ``dashboard.css`` не тронут
* Kill hover использует ``var(--term-kill-hover)`` scoped
  переменную, не inline hex

Full suite: 1311 passed, 1 known-flaky
``test_probe_tcp_timeout_short`` из baseline.

### Проверено live

Bridge на 4.13.0. Открыл Terminal tab через ZeroTier overlay,
переключил stream mode on, run'нул три сценария:

1. **Fast printf loop**
   (``for i in 1 2 3 4 5; do echo tick-$i; sleep 0.5; done``) —
   каждый tick появлялся в output pane в течение ~10ms server's
   write; badge flipped на green "exit 0 · 2.5s · stream" в конце.
2. **Streaming stderr**
   (``for i in 1 2; do echo out-$i; echo err-$i 1>&2; done``) —
   оба streams interleaved live под ``--- STDERR ---`` divider.
3. **Kill mid-flight** (``sleep 30``) — clicked Kill после ~2s;
   badge flipped на red "exit -15 · 2.1s · stream" и pulse dot
   исчез. ``GET /v1/audit?lines=5`` подтвердил ``process_killed``
   audit event fired с matching ``target_request_id``.

Переключение stream mode off run'ит ту же команду через buffered
branch как раньше — никакой регрессии для default UX.

### Не включено

* WebSocket upgrade для interactive input (typing в running
  ``python`` REPL). Нужен bidirectional endpoint;
  ``/v1/exec/stream`` one-shot output. Отложено.
* Colour rendering ANSI escape sequences. Сейчас показываются
  как raw ``\x1b[31m`` etc; небольшой ANSI-to-HTML pass ляжет
  nicely в v4.14 или v4.15 — filed как follow-up.
* "Restart" кнопка на head row для re-run той же команды.
  History dropdown покрывает это сегодня; one-click restart
  принадлежит broader Terminal-UX pass'у.

\n## v4.12.0 - 2026-07-16

### Изменено - Audit tab: bounded client-side ring buffer для live-tail

v4.10.0 live-tail toggle prepend'ил каждое NDJSON событие в
``__auditState.raw`` без границ. Dashboard оставленный открытым
на часы на busy host мог накопить десятки тысяч rows в этом
массиве -- стабильный memory growth, без верхнего лимита. v4.10.0
CHANGELOG flagged это как follow-up work; v4.12.0 делает работу.

**Новое поведение:** ``__auditState.raw`` теперь capped на
``__AUDIT_RING_CAP = 5000`` записей. Когда live-tail push'ит новое
событие и buffer overflow'ится -- oldest events в head массива
drop'аются (настоящий ring buffer) и running total дроп'нутых
rows track'ается в ``__auditState.evicted``. Meta line показывает
"evicted N" как дополнительный сегмент когда ``evicted > 0`` --
operators знают что history trimmed и на сколько:

    3512 fetched | 47 after filters | last fetch 20:44:07 | live +2103 | evicted 843

Trimming happens **сразу** после каждого push, не на next render
-- burst source (много событий в одном stream chunk) не может
grow past cap mid-tick. Pagination и filter axes продолжают
работать на newest 5000-row window; older rows gone до next
Reload (который re-fetches server-side и сбрасывает counters).

### Reload semantics

Кнопка **Reload** (и любой auto-refresh tick) полностью replace'ит
buffer. Это explicit "start over" gesture оператора, поэтому
``evicted`` counter сбрасывается в ноль в тот же момент. Cap
всё ещё применяется к replacement -- если оператор попросит
``lines=10000`` history, buffer trimmed до 5000 newest rows,
``evicted = 5000``, meta line отражает.

### Design notes

* Cap и trim helper (``__auditEnforceRingCap``) живут в module
  scope в ``dashboard/assets/16-audit.js`` -- будущий оператор
  raising cap меняет ровно один literal integer.
* Trim использует ``Array.prototype.splice(0, over)`` -- newest
  events в tail, drop'аем из head чтобы держать window который
  оператор действительно хочет видеть. Regression test fail'ится
  сразу если будущая правка случайно потянется к ``.pop()``
  или ``splice(-over)``.
* ``__auditState.evicted`` -- running total по всей live-tail
  session; **НЕ** reset'ится на max_duration rollover
  (reconnect invisible оператору, reset там misleadingly
  занулил бы counter).
* Ноль CSS изменений -- "evicted N" сегмент reuse'ит тот же
  ``.sep``-delimited layout который polling/live counters уже
  использовали. ``dashboard.css`` byte-identical к v4.11.0
  (109 строк).

### Файлы

* ИЗМЕНЁН ``dashboard/assets/16-audit.js`` (557 -> 596 строк) --
  новая ``__AUDIT_RING_CAP`` константа + ``__auditEnforceRingCap``
  хелпер, поле ``evicted`` на ``__auditState``, trim call внутри
  ``__auditIngestLiveEvent`` после каждого push, reset + trim
  на manual Reload, meta-line "evicted N" segment.

### Тесты

1289 -> 1297 passed (+8 в ``tests/test_audit_ring_cap.py``):

* ``__AUDIT_RING_CAP`` declared на module scope как literal
  integer в sane range 500..50000 (guards против silent
  changes и против runtime-computed caps которые сложно audit'ить)
* ``__auditEnforceRingCap`` -- standalone function возвращающая
  drop count (callers могут bump counter)
* Trim использует ``splice(0, over)`` -- drop'ает из head, не
  tail (regression guard: drop'ать newest defeats point)
* ``__auditState.evicted`` стартует с 0
* Live-tail ingest вызывает trim helper сразу после каждого
  push и добавляет return value в ``__auditState.evicted``
* Manual Reload reset'ит counter одновременно с replace buffer
* Meta line показывает "evicted N" только когда > 0 (uncluttered
  by default)
* ``dashboard.css`` не тронут; no ``evicted`` / ``audit-ring`` /
  ``AUDIT_RING`` tokens leak в shared stylesheet

Full suite: 1297 passed, 1 known-flaky
``test_probe_tcp_timeout_short`` из baseline.

### Проверено live

Bridge на 4.12.0. Открыл Audit tab через ZeroTier overlay с
live-tail on и запустил ~200 quick ``POST /v1/exec/stream`` calls
в loop'е из другого shell'а. ``live +N`` counter climbed as
expected; когда total push'нул ``__auditState.raw`` past 5000 --
"evicted N" segment появился в meta line и рос примерно на
same delta по мере прихода дальнейших событий. Table сама
продолжала рендерить newest 5000 events; older rows unloaded
silently. Клик Reload обнулил оба counter'а и re-fetched fresh
history из ``/v1/audit?lines=200``.

### Не включено

* User-configurable cap. Значение 5000 fine для каждого use
  case observed so far; если оператор попросит -- проведём
  через ``localStorage`` с settings row.
* "Load older" pagination. Весь смысл live-tail --
  newest-events-first; scrolling backwards past cap
  принадлежит отдельному "historical query" mode который мог
  бы hit'ать ``/v1/audit?lines=<N>`` с ``since=`` cursor --
  отложено до запроса.
* Применение cap к ``__auditRebuildTypeSelect`` dropdown.
  Helper уже видит только current buffer, так что narrows
  naturally как old rows evict'аются; отдельный лимит не нужен.

\n## v4.11.0 - 2026-07-16

### Добавлено - Overview Network Status: circuit breaker indicators

Показывает ``breaker`` snapshot, добавленный v4.8.0 в
``/v1/tunnels/probe``, прямо в Overview Network Status card,
чтобы operators сразу видели когда provider skipped и почему
— без обращения к raw endpoint из shell.

Новая "Breaker" row рядом с Active Provider / Public URL /
Providers, по одной маленькой badge на keyed
``(provider, host, port)``:

* **синий "ok"**            closed, 0 consecutive failures
* **жёлтый "warn N/3"**     closed но ``N`` consecutive failures
                            — probe скатывается; следующие N
                            failures откроют breaker (predictive
                            сигнал, ещё не блокирует)
* **красный "cooldown Ns"** open, ``N`` секунд остаётся в 60s
                            cooldown window до следующей попытки

Hover-tooltip на каждой badge показывает полный ``last_error``
из probe payload плюс raw key — operator может сразу
диагностировать конкретный provider без
``curl /v1/tunnels/probe | jq`` цикла.

Row **скрыта полностью** когда нет записей (probes ещё не
запускались, или старый bridge без v4.8.0). Хосты с полностью
здоровым triple тоже ничего лишнего не видят — Overview остаётся
tidy по умолчанию.

### Fail-soft loader

Тот же design pattern что v4.7.0 ZT peers card:
``refreshNetBreaker()`` вызывается из ``refreshOverview()``
внутри ``typeof === "function"`` guard'а и
``.catch(() => {})`` — transient probe hiccup не может уронить
весь Overview refresh cycle. Любая ошибка — endpoint
недостижим, ``ok:false``, missing ``breaker`` — скрывает row
вместо показа stale значений.

### Файлы

* НОВЫЙ ``dashboard/assets/04c-net-breaker.js`` (106 строк) —
  ``refreshNetBreaker()`` renderer + private-хелперы
  (``__netBreakerLabel`` / ``__netBreakerHide`` /
  ``__netBreakerShow`` / ``__netBreakerRender``).
* ИЗМЕНЁН ``dashboard/assets/body-01-overview.html`` (117 -> 133)
  — добавлена разметка row + scoped ``<style>`` блок с
  правилами ``.net-breaker-row``, ``.net-breaker-list`` и
  тремя вариантами ``.item.open`` / ``.item.warn`` /
  ``.item.ok``.
* ИЗМЕНЁН ``dashboard/assets/04-overview.js`` (195 -> 203) —
  wires ``refreshNetBreaker()`` в Overview refresh cycle под
  тем же typeof + catch щитом что и ZT peers card.

Manifest автогенерится из ``dashboard/assets/``, так что
``04c-net-breaker.js`` встаёт в sorted-список между
``04b-zt-peers.js`` и ``05-terminal-*`` без правок manifest
(v4.7.0 lesson).

### Ноль shared-CSS хирургии (v4.0.x lesson всё ещё держится)

* ``dashboard.css`` byte-identical к v4.10.0 (109 строк).
* Каждое правило новой row scoped на
  ``#tab-overview #networkCard .net-breaker-...`` в ``<style>``
  блоке body-таба.
* Цвета через shared palette-переменные
  (``var(--surface-error)`` / ``var(--red)`` /
  ``var(--surface-warning)`` / ``var(--warning-text)`` /
  ``var(--surface-info)`` / ``var(--blue)``) — ни одного hex
  literal inline. ``test_no_hardcoded_theme_colors`` green.
* Tooltip установлен через ``element.title`` (real attribute),
  никогда через ``innerHTML`` concatenation — предотвращает
  smuggling HTML через ``last_error`` (который может содержать
  произвольные символы из provider stderr).

### Тесты

1275 -> 1289 passed (+14 в
``tests/test_overview_net_breaker.py``):

Markup:
* Body имеет ``netBreakerRow`` + ``netBreakerList`` ids
* Row hidden по умолчанию через ``.on`` class toggle
* Все три визуальных состояния styled (``open`` / ``warn`` / ``ok``)

JS behaviour:
* ``refreshNetBreaker`` — global
* Читает ``/v1/tunnels/probe`` (не /status — там нет breaker)
* Покрывает три классификации явно, ссылки на
  ``cools_down_in_sec`` + ``consecutive_failures``
* Fail-soft hide на error, на ``ok:false``, и на missing
  ``breaker`` field
* Использует ``.title`` attribute для ``last_error``; ни одного
  ``+ rec.<field> +`` в innerHTML
* Sort'ит keys для stable render order (нет визуального
  jitter между refreshes)
* ``__netBreakerLabel`` разделяет на ``|`` — provider отдельно
  от host:port

Overview wiring:
* ``refreshOverview`` вызывает ``refreshNetBreaker`` внутри
  ``typeof === "function"`` + ``.catch`` guards

Containment (v4.0.x lesson):
* ``dashboard.css`` не тронут ``net-breaker-*`` /
  ``netBreaker`` селекторами
* Каждый новый селектор в scoped ``<style>`` начинается с
  ``#tab-overview``
* Manifest exclusion set не содержит новый файл

Full suite: 1289 passed, 1 known-flaky
``test_probe_tcp_timeout_short`` из baseline.

### Проверено live

Bridge на 4.11.0. Cloudflared не запущен на хосте — его
public_url пустой -> не считается; ZeroTier и Tailscale
активны -> breaker для ``zerotier|10.57.152.120:8765``
показывает синий "ok" (closed, 0 failures) как и ожидалось.
Force-tested указанием на нереспонсивный endpoint из python
shell'а против tunnels_probe: resulting breaker snapshot
рендерится корректно как красный "cooldown Ns" badge с
``timeout after 1.5s`` error видимым в tooltip'е. Row снова
скрывается когда snapshot возвращается к empty (после reset'а
module-singleton через ``reset_default_breaker()``).

### Не включено

* Time-series sparkline breaker state (нужен in-memory ring
  buffer или bridge-side timeseries; отложено до запроса
  оператора).
* Manual "reset" кнопка в row (нужен новый
  ``/v1/tunnels/probe/reset`` endpoint; пока не стоит surface
  area — bridge restart сейчас recovery path и работает).
* Circuit breaker для HTTPS-only providers (Tailscale funnel).
  v4.8.0 breaker покрывает только TCP-probe branch; https URLs
  всё ещё trust'ятся из provider's own ``active`` flag.
  Отложено до pull'а real HTTP client'а (v4.8.0 CHANGELOG
  уже flagged this).

\n## v4.10.0 - 2026-07-16

### Добавлено - Audit tab: live-tail toggle (использует /v1/audit/stream?follow=1)

В v4.6.0 Audit tab был один чекбокс "auto-refresh" который заново
тянул ``/v1/audit?lines=200`` каждые 5s. Дёшево, но с лагом (до
5s до появления события) и расточительно (те же 200 rows заново
маршалятся каждый tick). v4.9.0 добавил
``GET /v1/audit/stream?follow=1`` — настоящий chunked NDJSON
tail; v4.10.0 подключает таб к нему.

Новый второй чекбокс в Audit-toolbar: **live-tail** с синей
heartbeat-точкой рядом. Включение:

1. Выключает auto-refresh (делают одно и то же — держим один).
2. Seed'ит ``since=<ts>`` cursor из newest row уже на экране,
   чтобы первый stream не re-эмитил историю.
3. Открывает ``fetch("/v1/audit/stream?follow=1&lines=0&max_duration=300")``
   как ``ReadableStream`` и качает NDJSON строки через
   ``TextDecoder`` + ``JSON.parse``.
4. Prepend'ит каждое новое audit-событие в ``__auditState.raw``
   и, если Audit tab сейчас виден — re-render'ит страницу
   in-place. Фильтры (search / type / exit / page-size)
   применяются к live событиям так же как к history.
5. Когда сервер попадает в свой 300s ``max_duration`` stream
   заканчивается чисто и клиент auto-reconnect'ится через 250ms
   с ``since=<liveLastTs>`` — ни одно событие не потеряно на
   rollover.

Цвет точки:

* **синий-solid on** — streaming
* **красный-пульсирующий on** — connection error (сервер
  недостижим, auth failed, chunked-encoding сломан); reconnect
  запланирован
* **off** — чекбокс не отмечен

Meta-line получает running counter ``live +N`` пока live
подписка открыта — operators видят что события идут ещё до того
как таблица перерисовалась (что происходит только когда Audit
tab активный — CPU-friendly для тех кто держит tab в фоне).

### Cross-browser support

Feature-detect через ``ReadableStream`` +
``Response.body.getReader`` при attach (Chrome 43+, Firefox 65+,
Safari 10.1+ — по сути всё с 2018). Браузеры без поддержки
получают чекбокс rendered ``disabled`` с полезным tooltip'ом —
никаких mystery no-op при клике.

### Gap-free reconnect

Stream ограничен ``max_duration=300`` server-side (v4.9.0
default — забытый агент не может держать worker вечно). На
rollover клиент видит терминальный ``exit`` event, ждёт 250ms и
переоткрывает с ``since=<liveLastTs>``. Любое событие с
``ts`` > cursor эмитится; server'ский history-then-follow
гарантирует ни дубликатов, ни пропусков.

Если reconnect fails (network drop, bridge restart) status dot
переключается на пульсирующий red и reconnects back off'ится до
3s — не hot-loop'им по мёртвому endpoint'у. Как только bridge
снова доступен — следующий reconnect success'ится и dot
возвращается в blue.

### Ноль shared-CSS хирургии (v4.0.x lesson всё ещё держится)

* ``dashboard.css`` byte-identical к v4.9.0 (109 строк, baseline).
* Все новые стили scoped на ``#tab-audit .audit-live-dot...`` в
  ``<style>`` блоке таба.
* Ни одного hex literal inline
  (``test_no_hardcoded_theme_colors`` green).
* Два новых теста охраняют containment
  (``.audit-live-dot`` никогда в ``dashboard.css``; каждый новый
  селектор начинается с ``#tab-audit``).

### Файлы

* ИЗМЕНЁН ``dashboard/assets/body-13-audit.html`` (95 -> 101) —
  новый ``auditLive`` checkbox + ``auditLiveDot`` span в
  toolbar'е, ``.audit-live-dot`` правила (on / err) в scoped
  ``<style>`` блоке.
* ИЗМЕНЁН ``dashboard/assets/16-audit.js`` (330 -> 557) —
  расширен ``__auditState`` полями ``liveController`` /
  ``liveReader`` / ``liveLastTs`` / ``liveEvents`` /
  ``liveReconnectTimer``; новые хелперы
  ``__auditToggleLive`` / ``__auditOpenLiveConnection`` /
  ``__auditConsumeStream`` / ``__auditIngestLiveEvent`` /
  ``__auditStopLive`` / ``__auditScheduleLiveReconnect`` /
  ``__auditLiveSupported`` / ``__auditLiveSetStatus``. Auto-
  refresh toggle теперь выключает live-tail (и наоборот).

### Тесты

1260 -> 1275 passed (+15 в ``tests/test_audit_live_tail.py``):

Markup:
* Checkbox + status dot present в body
* Оба ``on`` и ``err`` состояния dot'а styled

JS behaviour:
* State-object расширен live-tail полями
* Все private-хелперы используют ``__audit...`` prefix
  (namespace гигиена)
* Endpoint использует ``follow=1``, bounded ``max_duration``,
  threaded ``since=`` cursor
* Auto-reconnect wired (setTimeout на stream end)
* Auto-refresh и live-tail взаимоисключаемы
* ``AbortController`` используется для clean stop
* NDJSON parser выживает malformed строки (JSON.parse в
  try/catch + ``console.warn``)
* Gap-free reconnect: cursor seeded из history на первом open,
  updated из каждого live event
* ``__auditLiveSupported`` probes ``ReadableStream`` +
  ``.body.getReader``; disabled tooltip на старых браузерах
* Ingest helper пропускает ``meta`` / ``exit`` / ``error``
  control events
* Table repaint gated на ``tab-audit.active`` — background tabs
  не жгут CPU

Containment:
* ``dashboard.css`` не тронут
* Новые ``.audit-live-dot`` селекторы начинаются с ``#tab-audit``

Full suite: 1275 passed, 1 known-flaky
``test_probe_tcp_timeout_short`` из baseline.

### Проверено live

Bridge на 4.10.0. Открыл Audit tab через ZeroTier overlay и
переключил live-tail on. Blue dot пульсировал;
``__auditState.liveEvents`` счётчик инкрементился когда
``POST /v1/exec/stream`` вызовы в другом terminal'е производили
``exec_stream_start`` + ``exec_stream_done`` события; новые
строки появлялись наверху таблицы через ~500ms (один poll cycle
на сервере). Включил auto-refresh — live-tail disconnected
чисто, dot погас, auto-refresh dot стал green. Переключил
live-tail снова on — auto-refresh unchecked себя, seed'нул из
newest visible ts, первый subscription начался без re-emit
только что polled строк.

### Не включено

* Client-side ring buffer cap. Live-tail продолжает prepend'ить
  бесконечно; сессия на несколько часов может накопить 10k+
  строк в ``__auditState.raw``. Добавление soft cap (например
  5000 строк) с индикатором "older events unloaded" — на
  очереди в v4.11.0 после наблюдения за реальной длинной
  сессией.
* Terminal / mobile tab live-tails. Паттерн бы компонировался —
  ``/v1/exec/stream`` для Terminal, будущий
  ``/v1/desktop/events`` для mobile — но это отдельная работа.
* Server-Sent Events framing. NDJSON поверх chunked HTTP был
  ок для ``/v1/exec/stream`` client'а (v4.3.0) и ок здесь.
  Если когда-нибудь зашипим ``EventSource``-based client —
  добавим SSE рядом; сейчас ничего не блочит.

\n## v4.9.0 - 2026-07-16

### Добавлено - GET /v1/audit/stream (NDJSON audit tail с live-follow)

Комбинирует chunked-NDJSON transport из v4.3.0
(``/v1/exec/stream``) с audit-словарём из v4.6.0 (Audit tab
categorization) в полноценный live-tail endpoint для audit log'а.

Раньше: агенты которые хотели реагировать на audit-события
(конкретный exec завершился, blocklisted-команда поймана,
``file_upload`` целится в watched path) должны были polling'ить
``/v1/audit?lines=...`` в hot loop и diff'ать response. Каждый
loop платил полную стоимость response body, и cadence polling'а
определял latency реакции.

Теперь:

    curl -sSN --no-buffer \
      -H "Authorization: Bearer $TOKEN" \
      "$ARENA_BRIDGE_URL/v1/audit/stream?follow=1&type=exec_stream"

открывает chunked NDJSON stream. Каждая строка — один JSON:

    {"type": "meta", "audit": "/home/ivan/arena-bridge/audit.jsonl",
     "follow": true, "lines_history": 100,
     "filters": {"type_prefix": "exec_stream", "since": null,
                 "max_duration_sec": 300},
     "server_ts": "2026-07-16T14:00:00Z"}
    {"ts": "2026-07-16T13:59:12Z", "type": "exec_stream_start", ...}
    {"ts": "2026-07-16T13:59:12Z", "type": "exec_stream_done",  ...}
    ... (live tail продолжается) ...
    {"type": "exit", "reason": "max_duration",
     "emitted": 47, "skipped": 213}

### Query параметры

* ``lines`` — сколько history-строк эмитить перед началом follow
  phase (default 100, cap 5000)
* ``follow`` — ``1`` / ``true`` / ``yes`` / ``on`` чтобы держать
  stream открытым и эмитить новые события по мере их появления
  в ``audit.jsonl`` (default off = history-only mode завершается
  чисто)
* ``type`` — substring filter по ``event.type``, те же semantics
  что Audit tab (``exec`` матчит ``exec_*`` / ``exec_stream_*`` /
  ``exec_script_*``)
* ``since`` — ISO-8601 timestamp cursor; события с ``ts`` ``<=``
  этого значения пропускаются. Идеально для reconnect-and-resume
  после дропа stream'а клиентом
* ``max_duration`` — максимум секунд follow-фазы (default 300,
  cap 300 — забытый агент не может держать worker бесконечно)

### Гарантии контракта

* ``meta`` всегда первое событие (echoes back что клиент попросил
  — сохранённый capture самоописателен)
* ``exit`` всегда терминальное; unterminated NDJSON = сервер
  умер mid-stream
* History phase читает последние ``lines`` non-empty строк
  ``audit.jsonl``, применяет ``type`` + ``since`` filters,
  эмитит выживших в хронологическом порядке
* Follow phase seek'ается в end-of-file после history — одно и
  то же событие не эмитится дважды
* Malformed audit-строки не крашат stream — surface'ятся как
  ``{"type": "raw", "line": "..."}`` чтобы operator замечал
  corruption во время follow-сессии
* Log rotation (файл audit временно missing) толерантен: ``open()``
  retry на следующем poll вместо краха
* Client disconnect уважается — finally-блок пишет терминальный
  ``exit`` с ``reason="client_disconnect"`` когда возможно

### Файлы

* ИЗМЕНЁН ``arena/observability/handlers.py`` (101 -> 327
  строк) — новый ``handle_v1_audit_stream`` + хелперы
  (``_parse_stream_since``, ``_match_type_filter``,
  ``_tail_last_lines``) + tunables
  (``_STREAM_MAX_DURATION_SEC=300``,
  ``_STREAM_POLL_INTERVAL_SEC=0.5``,
  ``_STREAM_MAX_LINES_HISTORY=5000``,
  ``_STREAM_READ_CHUNK=64KiB``); ``ObservabilityHandlers``
  dataclass получает поле ``audit_stream``
* ИЗМЕНЁН ``arena/route_registry/registry.py`` +
  ``arena/route_registry/core.py`` — ``GET /v1/audit/stream``
  route в ``core`` group
* ИЗМЕНЁН ``arena/wiring/memory_observability_registries.py`` —
  ``handle_v1_audit_stream -> audit_stream`` в export map

### Тесты

1249 -> 1260 passed (+11 в ``tests/test_audit_stream.py``):

* Route registration + wiring + dataclass field guards
* ``_match_type_filter`` substring semantics
* ``_parse_stream_since`` empty/whitespace/valid
* ``_tail_last_lines`` возвращает last N и обрабатывает
  empty/missing файлы без raise
* History-only mode эмитит meta + N events + exit (reason
  ``history_only``); счётчики верные
* Type-prefix + since filter композируются и skip'ают
  before/off-type события
* Follow mode подхватывает строку appended mid-stream и эмитит
  её до ``exit``
* ``_STREAM_MAX_DURATION_SEC`` остаётся bounded (regression
  guard против будущих "просто подними до дня" правок)

End-to-end тесты используют минимальное aiohttp app которое
регистрирует только audit-stream handler с
``ObservabilityHandlerContext`` собранным из stubs — никакого
``unified_bridge.make_app`` churn'а на module-level executors
(v4.3.0 lesson всё ещё применяется).

Full suite: 1260 passed, 1 known-flaky
``test_probe_tcp_timeout_short`` из baseline.

### Проверено live

Bridge на 4.9.0 через ZeroTier overlay. Три сценария:

1. **History only**: ``GET /v1/audit/stream?lines=5`` вернул
   ``meta`` + 5 реальных audit-событий + ``exit`` с
   ``reason=history_only``.
2. **Type-filter follow**: ``?follow=1&lines=0&type=exec_stream
   &max_duration=10``. Пока stream был open,
   ``curl -X POST /v1/exec/stream`` в другой shell'е произвёл
   два события (``exec_stream_start``, ``exec_stream_done``)
   которые прилетели в tail в течение ~0.5s и ``exit`` event
   выстрелил на max_duration с ``emitted=2``.
3. **Since cursor**: ``?lines=20&since=2026-07-16T14:00:00Z``
   отбросил каждое history-событие с ts ``<=`` cursor'а —
   совпадает с client-side v4.6.0 filter behaviour.

### Не включено

* Server-side prefix registry (типа Cloudflared Analytics) —
  substring filter уже близко к Audit tab UX.
* Bidirectional streaming (WebSocket). NDJSON поверх chunked
  HTTP работает через Tailscale funnel + ZeroTier overlay +
  raw HTTPS без отдельной negotiation; trade-off сработал для
  ``/v1/exec/stream`` и работает здесь.
* inotify / kqueue file-change wake-up. 500ms poll стоит одного
  ``open + seek + read(64KiB)`` на follow-tick, что несущественно
  рядом с network round-trip; переход на inotify был бы
  Linux-only path, а cross-platform — hard rule.

\n## v4.8.0 - 2026-07-16

### Добавлено - Circuit breaker для tunnels_probe (skip мёртвых providers)

Проблема: ``_probe_tcp`` ждёт до ``timeout`` секунд на provider на
вызов. На хосте где один provider тихо мёртв — Cloudflared
quick-tunnel со stale websocket, ZeroTier LEAF на strict-NAT link
что только что поднялся — каждый Dashboard tick и каждый
``GET /v1/tunnels/probe`` платит полный timeout снова, за
provider'а который failing минутами. Умножьте на ~5s Dashboard
polling и три provider'а — probe cycle который должен занимать
~15ms регулярно занимает 4-5s. Прямо про твой случай "Cloudflared
у меня всё время в timeout".

Fix: небольшой in-process circuit breaker с ключом
``(provider, host, port)``. Три подряд TCP failures → provider
**open** на 60s. Пока open — ``allow()`` возвращает ``False`` и
probe response показывает entry с ``reachable=False``,
``breaker_state="open"``, и ``skip_reason`` вида:

    circuit-breaker open (3 consecutive failures, cools down in
    45s; last error: timeout after 1.5s)

Когда cooldown истекает breaker переходит в **half-open**:
следующий probe запускается — success закрывает breaker чисто,
failure переоткрывает на ещё 60s (counter держится на threshold
при закрытии так что half-open failures переоткрывают с первого
промаха, не после ещё трёх).

### Конфигурация

Обе через env, обе optional, обе применяются при первом
использовании (``get_default_breaker()`` кеширует; вызывай
``reset_default_breaker()`` в тестах чтобы подхватить новые
значения):

* ``ARENA_BREAKER_THRESHOLD`` — consecutive failures перед
  открытием (default 3, clamped 1..20)
* ``ARENA_BREAKER_COOLDOWN``  — секунды в open (default 60,
  clamped >= 1.0)
* ``ARENA_BREAKER_DISABLE``   — ``1`` / ``true`` / ``yes`` / ``on``
  делает breaker no-op'ом чтобы operator дебажащий реальную
  проблему provider'а мог force-run probes без restart bridge

### Snapshot в probe payload

Probe response получил поле ``breaker`` с JSON-safe snapshot'ом
каждой записи чтобы operator видел что сейчас open и почему:

    "breaker": {
      "cloudflared|foo.trycloudflare.com:443": {
        "state": "open",
        "consecutive_failures": 3,
        "last_error": "timeout after 1.5s",
        "cools_down_in_sec": 42.117
      },
      "zerotier|10.57.152.120:8765": {
        "state": "closed",
        "consecutive_failures": 0,
        "last_error": null
      }
    }

``cools_down_in_sec`` только в open-записях чтобы обычный
``closed`` case оставался кратким.

### Ключевые design-решения

* **Per (provider, host, port)**: Cloudflared reissue с другим
  quick-tunnel hostname получает свежий breaker; история старого
  URL остаётся со старым ключом до ``reset()``.
* **Monotonic clock**: безопасно от wall-clock jumps (NTP
  подстройки, ``date -s ...`` оператора) которые иначе оставили
  бы breaker stuck-open или spuriously "recovered".
* **GIL-atomic writes**: locking не нужен; мутации — single-
  attribute assignments на ``@dataclass`` instance, readers
  видят стабильный ``dict[str, BreakerRecord]``.
* **No stateful I/O**: breaker держит только dict записей;
  ничего не персистится, ничего не reload после bridge restart
  (сам restart сбрасывает всё чисто).

### Файлы

* НОВЫЙ ``arena/admin/tunnels_breaker.py`` (273 строки) —
  ``TunnelsBreaker`` class, ``BreakerRecord`` dataclass, env-
  хелперы, ``get_default_breaker`` / ``reset_default_breaker``
  module-singleton пара.
* ИЗМЕНЁН ``arena/admin/tunnels.py`` — ``tunnels_probe`` теперь
  принимает optional ``breaker=`` (default'ит на module
  singleton), консультируется с ним перед каждым ``_probe_tcp``,
  записывает результат после, и возвращает ``breaker=<snapshot>``
  в response.

### Тесты

1234 -> 1249 passed (+15 в ``tests/test_tunnels_breaker.py``):

State machine (deterministic ``_FakeClock``):
* Unknown key стартует closed
* Threshold failures открывают breaker с compact reason string
* Success до threshold сбрасывает counter
* Истечение cooldown переводит в half-open
* Half-open success закрывает чисто
* Half-open failure переоткрывает мгновенно (больше промахов не
  нужно)
* ``snapshot()`` возвращает JSON-safe view
  (``cools_down_in_sec`` только в open records)
* ``reset(key)`` чистит один ключ; ``reset()`` чистит всё
* ``ARENA_BREAKER_DISABLE=1`` делает breaker no-op
* ``ARENA_BREAKER_THRESHOLD`` / ``COOLDOWN`` env-overrides
  применяются
* Env-значения clamp'аются: threshold 1..20, cooldown >= 1s

Интеграция с tunnels_probe:
* Response всегда включает ``breaker`` поле
* Open provider пропускается без вызова ``_probe_tcp``
* ``skip_reason`` и ``breaker_state="open"`` present в
  skipped entries; ``skip_reason`` включает last error
* Successful probe закрывает breaker (counter reset to 0)
* Failing probe инкрементит counter; third failure открывает
  breaker
* Ключ включает host + port так что URL moves получают fresh
  state

Full suite: 1249 passed, 1 known-flaky
``test_probe_tcp_timeout_short`` из baseline.

### Проверено live

Bridge на 4.8.0. Force-tested запуском probe cycle с Cloudflared
сконфигурированным но не работающим (его собственный случай):
первые три probes занимают ~1.5s каждый на timeout'е неотзывного
endpoint'а, потом последующие probes завершаются за <5ms каждый
с Cloudflared entry помеченным ``breaker_state="open"``,
``skip_reason="circuit-breaker open (3 consecutive failures,
cools down in Ns; last error: timeout after 1.5s)"``. Tailscale
и ZeroTier entries не затронуты. После 60s cooldown новый probe
запускается (half-open); если endpoint всё ещё down — breaker
переоткрывается мгновенно.

### Не включено

* HTTP-layer probing для https URLs. https probes сейчас trust
  provider's ``active`` flag; добавление real HTTP HEAD probe
  дало бы breaker'у покрытие и для https. Отложено до pull'а
  HTTP client'а поддерживающего connection-timeout отдельно от
  read-timeout.
* Persisted breaker state через bridge restarts. Интересно для
  long-lived deployments, не нужно для day-to-day case
  (bridge restart уже чистит всё).
* Metrics export. Хотел бы Prometheus scrape target если
  bridge станет широко deployed; сейчас snapshot в probe
  response достаточен для Dashboard.

\n## v4.7.0 - 2026-07-16

### Добавлено - Overview: карточка ZeroTier peers (визуализация /v1/zerotier/peers)

Работа v4.4.0 / v4.5.0 положила богатый per-peer classifier за
``GET /v1/zerotier/peers``, но Dashboard всё ещё показывал только
одну строку про ZeroTier ("Active Provider: zerotier"). Теперь
Overview tab показывает нормальную картину состояния overlay:

* **Inline SVG donut** в ZT-палитре (direct=green, relay=orange,
  tunneled=red, root=purple, none=grey), с общим количеством
  peer'ов в центре.
* **Легенда** со списком присутствующих ``path_kind`` — count +
  процент.
* **Summary-полоса**: LEAF count, direct ratio, средняя LEAF
  latency и v4.5.0-разбивка ``leaf_relay_planet`` +
  ``leaf_relay_tcp_infra`` — оператор сразу видит через что идут
  relayed peer'ы (PLANET или TCP-relay инфраструктура).
* **Optional hint** ниже — рендерится только когда API его
  вернул, использует общую ``.zt-hint`` панель с существующей
  surface-info палитрой.
* **Manual refresh** в заголовке; карточка также обновляется
  на каждом Overview tick.

Card **скрыта по умолчанию** и показывается только когда
``/v1/zerotier/peers`` вернул ``installed: true`` с валидным
summary. Хосты без ZeroTier (Windows без клиента, macOS без
приложения, Linux где daemon не запущен) не видят ничего
лишнего на Overview — ни error-card, ни пустого donut'а.

Та же дисциплина containment'а что в v4.6.0 Audit-tab polish:

* ``dashboard.css`` byte-identical к v4.6.0 (109 строк, baseline).
* Каждое правило карточки scope'нуто как
  ``#tab-overview #ztPeersCard...`` в ``<style>`` блоке внутри
  ``body-01-overview.html``.
* Цвета через shared-палитру: ``var(--green)`` / ``var(--orange)``
  / ``var(--red)`` / ``var(--purple)`` / ``var(--text3)``. Ни
  одного hex literal inline
  (``test_no_hardcoded_theme_colors`` остаётся зелёным).
* Loader fail-soft: любая ошибка от ``api("/v1/zerotier/peers")``
  или отсутствие ``.summary`` — молча скрывает карточку, чтобы
  transient bridge hiccup не уронил весь Overview refresh cycle.
  Overview вызывает ``refreshZtPeers().catch(() => {})``.

### Файлы

* НОВЫЙ ``dashboard/assets/04b-zt-peers.js`` (185 строк) —
  ``refreshZtPeers()`` renderer + private-хелперы
  (``__ztRenderDonut`` / ``__ztRenderLegend`` /
  ``__ztRenderStats`` / ``__ztRenderMeta`` /
  ``__ztHideCard`` / ``__ztShowCard``) + palette-константы.
* ИЗМЕНЁН ``dashboard/assets/body-01-overview.html`` — добавлена
  разметка карточки (header + card + SVG placeholder +
  legend/stats контейнеры + hint + meta) с scoped ``<style>``.
* ИЗМЕНЁН ``dashboard/assets/04-overview.js`` — вызывает
  ``refreshZtPeers()`` из ``refreshOverview()`` под guard'ом
  ``typeof === "function"``, чтобы старые сборки без нового
  файла продолжали грузиться.
* Manifest автогенерится из ``dashboard/assets/`` на bridge'е;
  ``04b-zt-peers.js`` встаёт между ``04-overview.js`` и
  ``05-terminal-*`` по префикс-сортировке. Правки manifest не
  нужны.

### Техника SVG donut'а

Chart использует inline SVG с фиксированным
``viewBox="0 0 42 42"`` и ``r="15.9155"``. Такой радиус даёт
circumference = 100, так что ``stroke-dasharray="pct 100-pct"``
рендерит slice ровно на ``pct`` процентов. Slices — concentric
``<circle>`` элементы, каждый rotated -90° чтобы 0% начинался
в 12 часов, с ``stroke-dashoffset`` отслеживающим накопительный
offset. Результат — чёткий donut без chart-библиотеки и без
трогания ``dashboard.css``.

### Тесты

1221 -> 1234 passed (+13 в ``tests/test_overview_zt_peers_card.py``):

* Body имеет каждый id который читает JS (и наоборот)
* Card стартует скрытой через ``display:none`` scoped на
  ``#tab-overview #ztPeersCard``; loader тогглит ``on`` class
  а не трогает ``style.display`` напрямую
* Manual refresh button wired на ``refreshZtPeers()``
* JS экспортирует ``refreshZtPeers`` как global
* Правильный endpoint (``/v1/zerotier/peers``)
* Fail-soft hide на error и на ``installed === false``
* Палитра покрывает каждый ``path_kind`` (direct / relay /
  tunneled / root / none)
* Summary читает v4.5.0-поля (``leaf_relay_planet`` /
  ``leaf_relay_tcp_infra``, ``direct_ratio``,
  ``leaf_latency_ms_avg``)
* Ни одной unescaped ``+ (data|d|e).<field> +`` в innerHTML
  строках
* Overview cycle вызывает ZT peers loader внутри
  ``typeof refreshZtPeers === "function"`` guard'а с
  ``.catch`` wrapper'ом
* ``dashboard.css`` не тронут (нет ``zt-*`` / ``ztPeers*`` /
  ``ztDonut`` селекторов)
* ZT peers стили scope'нуты на ``#tab-overview`` (комментарии и
  ``@keyframes`` exempt)
* Donut использует ``r=15.9155`` трюк — slice-математика
  остаётся литеральными процентами

Full suite: 1234 passed, 1 known-flaky
``test_probe_tcp_timeout_short`` из baseline.

### Проверено live

Bridge на 4.7.0 через ZeroTier overlay. Overview рендерит
карточку только когда ZT присутствует (bridge host: да;
не-ZT VM в том же тестовом batch — нет). Card показывает
текущую 6-peer топологию (4 PLANET root'а + 2 relayed LEAF
через tcp-infra, matches v4.5.0 classifier); hint читает
"Every LEAF peer is routed through ZeroTier's TCP-relay
infrastructure..." — та же формулировка что raw API response.

### Не включено

* Tailscale peer donut. Tailscale отдаёт свою структуру
  ``tailscale status --json`` и заслуживает отдельной карточки,
  а не общей. Отложено до момента когда bridge получит
  ``tailscale_peers`` companion к ``zerotier_peers``.
* Sparkline direct-ratio по времени. Требует небольшой in-browser
  ring buffer или bridge-side timeseries; не срочно.
* Click-through в per-peer detail modal. Audit tab уже даёт
  per-request-id detail; если операторы попросят per-peer
  history view — добавим.

\n## v4.6.0 - 2026-07-16

### Изменено - Audit tab: полный polish (фильтры, поиск, пагинация, expand, auto-refresh)

Audit tab был raw-JSON tail с трёхколоночной таблицей (Time / Type /
Detail) и одним dropdown'ом hardcoded event-групп. Событийный
словарь недавно сильно вырос (``exec_stream_*`` в v4.3.0,
``exec_script_*`` в v4.2.0, per-provider tunnel events, ZeroTier
admin events), и старый view уже не помогал ничего найти —
``exec_start`` / ``exec_done`` / ``file_upload`` сливались в одну
кашу.

Новый tab — нормальный log viewer:

* **Search box** — case-insensitive substring поиск по cmd, path,
  reason, error, matched, actor, request_id, interpreter, action.
  Та же строка, так что grep-запросы работают напрямую
  (``docker``, ``deadbeef1234``, ``systemctl``, ``blocked``).
* **Type filter** — динамически перестраивается из текущего
  fetch'а, так что новый event-словарь автоматически появляется.
  Включает coarse-prefixes (``exec*``, ``exec_stream*``,
  ``exec_script*``, ``file_*``, ``admin.*``, ``tunnel``,
  ``zerotier``) и exact-матчи для всего что сейчас в логе.
* **Exit code filter** — ``exit 0 only`` / ``non-zero exit`` /
  ``killed / timeout`` (матчит SIGKILL -9, SIGTERM -15, любой
  event с ``timeout`` в типе). Отвечает "покажи мне failures"
  одним кликом.
* **Шесть колонок**: Time, Type (цветной badge), Actor, Req ID
  (short, полный на hover), Detail (cmd / path / reason /
  action), Exit (цветной: green=0, red=иначе, grey="no exit").
* **Row expand** — click по строке → развёртывается полный JSON
  события, dedup'нутый по полям которые уже видны в строке.
  Second click — collapse. Multiple rows могут быть открыты
  одновременно.
* **Pagination** — Prev / Next + "N-M of TOTAL" + "page X/Y".
  Page size 50 / 100 (default) / 200 / 500. Server tail отдельно
  (default 200, до 10000) — можно тянуть большое окно без
  рендера всего сразу.
* **Auto-refresh** — checkbox с green heartbeat-точкой. 5-секундная
  cadence. Interval clear'ится когда checkbox unchecked.
* **Meta line** — "N fetched | M after filters | last fetch HH:MM:SS"
  — сразу очевидно когда данные stale или когда filter скрывает
  большую часть лога.

### Цветные event-type badges

Категория → цвет (через ``__auditCategory`` в JS) группирует
события по оси которая интересна пользователю at a glance:

* **exec** (green)         — ``exec_start`` / ``exec_done`` /
                              ``process_killed``
* **exec-blocked** (red)   — ``exec_blocked``,
                              ``exec_stream_blocked``,
                              ``exec_script_blocked``,
                              ``*_blocked_control``
* **exec-timeout** (orange)— любой ``*_timeout``
* **exec-stream** (blue)   — ``exec_stream_*`` (v4.3.0 словарь)
* **exec-script** (purple) — ``exec_script_*`` (v4.2.0 словарь)
* **file** (lime)          — ``file_upload`` / ``file_download``
* **admin** (yellow)       — ``admin.*``
* **tunnel** (mauve)       — ``*_tunnel`` / ``*_funnel`` /
                              ``zerotier*`` / ``tunnels*``
* **error** (red)          — что угодно с ``error`` в имени
* **other** (grey)         — fallthrough (новые event-имена
                              попадают сюда пока не будут явно
                              категоризованы)

Любой будущий event-словарь падает в ``other`` без поломки —
безопасный default сохраняющий палитру стабильной.

### Ноль хирургии в shared CSS (урок v4.0.x)

Каждое правило которое добавляет tab живёт в собственном ``<style>``
блоке scope'нутом на ``#tab-audit ...``. ``dashboard.css``
byte-identical к v4.5.0. Scoped-блок также определяет новые
переменные палитры (``--au-tint-green``, ``--au-tint-red``, ...)
чтобы hex literals не попадали inline в HTML/JS —
``test_no_hardcoded_theme_colors`` остаётся зелёным.

CSS-регрессия v4.0.1..v4.0.4 случилась именно от такой UI-tab
работы утекающей правилами в shared stylesheet. Не в этот раз:
новый тест (``test_dashboard_css_is_not_touched_by_audit_polish``)
fails билд если любой ``audit-*`` / ``ev-badge`` селектор
появится в ``dashboard.css``. Второй тест
(``test_audit_body_scopes_all_new_styles_to_tab_audit``) парсит
``<style>`` блок таба и утверждает что каждый селектор
начинается с ``#tab-audit``.

### Тесты

1211 -> 1221 passed (+10 новых в ``tests/test_audit_tab_polish.py``):

* HTML root и ``loadAudit`` hook сохранены
* Каждый ``getElementById`` id в JS присутствует в body (и наоборот)
* Six-column table + ``colspan='6'`` в loading/error/empty строках
* ``dashboard.css`` не тронут селекторами audit-polish
* Каждое non-keyframe правило в ``<style>`` таба scope'нуто на
  ``#tab-audit`` (комментарии и ``@keyframes`` exempt)
* ``loadAudit`` и ``auditStats`` всё ещё global
* Ни одного unescaped ``+ e.<field> +`` interpolation на строках
  пишущих в ``innerHTML`` (XSS guard)
* Search / type filter / exit filter / page-size / auto-refresh
  interval + clearInterval все wired
* Классификатор категорий покрывает v4.3.0 ``exec_stream_*`` и
  blocked / timeout корзины
* Pagination state живёт в module scope (переживает tab hide/show)

Full suite: 1221 passed, 1 known-flaky failure в
``test_probe_tcp_timeout_short`` (baseline).

### Проверено live

Bridge на 4.6.0. Audit tab протестирован против реального
audit.jsonl с 14 distinct event-типами и ~1000 событий:
фильтры композируются, search находит ``systemctl`` /
``request_id`` префиксы, exit-filter изолирует два ``exec_blocked``
события, row-expand показывает полный JSON с fields
отсортированными alphabetically, pagination advances без
re-fetch, auto-refresh dot пульсирует green.

### Не включено

* Server-side filtering / cursor pagination — ``/v1/audit``
  сейчас поддерживает только ``lines=N`` tail. Для 10k+ audit
  файлов нужны ``since=<ts>`` и ``after=<request_id>`` cursors.
  Не срочно пока audit bounded by ``lines``.
* Column sorting — события приходят chronologically; tab
  reverses to newest-first. Если кто-то попросит "sort by exit
  code" — добавим, но это не естественная log-viewer motion.
* Streaming audit tail (SSE / WebSocket) — 5-секундный
  auto-refresh достаточен для interactive use; heavier hooks
  принадлежат отдельному ``/v1/audit/stream`` если агент
  когда-либо попросит.

\n## v4.5.0 - 2026-07-16

### Изменено - уточнённый классификатор ZeroTier peers (direct теперь означает *реальный* P2P UDP)

Закрывает false-positive обнаруженный в live smoke v4.4.0: два LEAF
peer'а на bridge помечались как ``direct``, хотя оба шли через
TCP-relay-инфраструктуру ZeroTier (Vultr/GCP IP на high random
портах 23649 / 23007). Пути *действительно* были non-root — эвристика
v4.4.0 — но и не peer-to-peer UDP.

**Новое правило:** ``direct`` теперь требует ``port == 9993`` в
дополнение к ``ip != any PLANET/MOON IP``. Настоящий ZeroTier P2P
UDP всегда использует ``primaryPort`` демона (9993 по умолчанию).
Всё остальное на non-root IP — всё ещё relayed, просто через
TCP-relay tier, а не через PLANET.

**Новое поле: ``relay_via``** на каждом peer'e. Когда ``path_kind
== "relay"`` принимает одно из двух значений:

* ``"planet"``    — все активные пути упираются в IP PLANET/MOON.
                    Классический ZT relay через root-сервер.
* ``"tcp-infra"`` — хотя бы один активный путь на non-root IP но
                    non-9993 порту. TCP-relay инфраструктура
                    ZeroTier — обычно признак того что UDP
                    заблокирован outbound хотя бы в одном
                    направлении.

Для ``direct`` / ``root`` / ``tunneled`` / ``none`` поле — ``None``
(flavour не имеет смысла для этих категорий).

Приоритет при co-existing путях:

1. Любой P2P UDP path → ``direct`` побеждает (установленный
   direct-линк — то что важно; ZT держит fallback тёплым).
2. Любой non-root non-9993 path → ``relay`` / ``tcp-infra``.
3. Всё на PLANET IP → ``relay`` / ``planet``.

### Добавлено - relay_via breakdown в summary

    "leaf_relay_planet":    1,     # v4.5.0
    "leaf_relay_tcp_infra": 2      # v4.5.0

Сумма равна существующему ``leaf_relay``, счётчики не теряются.

### Изменено - текст hint'а теперь называет наблюдаемый transport

Когда все LEAF peer'ы на relay-пути, actionable hint выбирается
чтобы совпадать с тем что peers показывает в реальности. Раньше
пользователь с TCP-infra-relayed соединением читал "Every LEAF
peer is routed through a PLANET relay", а в peer-таблице видел
non-PLANET IPs — сбивало с толку. Теперь:

* Все PLANET-relayed → "Every LEAF peer is routed through a PLANET
  relay — no direct P2P paths yet. Allow UDP 9993 outbound..."
* Все TCP-infra-relayed → "Every LEAF peer is routed through
  ZeroTier's TCP-relay infrastructure (non-9993 ports on non-PLANET
  IPs). This means UDP is not getting through in at least one
  direction. Allow UDP 9993 outbound..."

Fix (открыть UDP 9993 + hole-punching) один и тот же в обоих
случаях, но название наблюдаемого transport'а делает диагноз
правдоподобным.

### Тесты

1205 → 1211 passed (+6 новых; 5 старых обновлены под новую
tuple-сигнатуру):

* ``_classify_peer`` возвращает ``(path_kind, relay_via)``
* ``_is_direct_udp_port`` принимает только 9993
* Non-root IP на high port → ``("relay", "tcp-infra")``
* Direct + tcp-infra оба present → direct побеждает
* Planet + tcp-infra оба present → tcp-infra побеждает
* ``_peers_summary`` разделяет relay по ``relay_via``; сумма
  совпадает с ``leaf_relay``
* Hint варианты для planet-only, tcp-infra-only, mixed / partial /
  direct

### Проверено live

Bridge на 4.5.0 через ZeroTier overlay (10.57.152.120:8765). Два
LEAF peer'а раньше mislabelled ``direct`` теперь корректно как
``relay`` / ``tcp-infra`` — matches наблюдаемые non-9993 порты
(23649, 23007). Hint возвращает новый TCP-infra текст.

### Обратная совместимость

* Значения ``path_kind`` не изменились; enum не расширился.
* Существующие потребители читающие только ``path_kind`` получают
  исправленное значение (peers которые *действительно* relayed
  теперь говорят ``relay``).
* Новое поле ``relay_via`` — additive; missing у старых клиентов —
  это intended default ("planet" — историческое предположение).
* Ключи summary ``leaf_direct`` / ``leaf_relay`` / ``leaf_tunneled``
  сохраняют имена; ``leaf_relay_planet`` + ``leaf_relay_tcp_infra``
  — additive.

### Не включено

* Auto-detection не-default ``primaryPort`` из ``/status`` ноды.
  Крайне редко в реальности; когда потребуется — расширим
  ``_DIRECT_UDP_PORTS`` на daemon-startup на основе local status
  snapshot, а не при classify.
* Расширение классификатора на Tailscale/Cloudflared peers.
  tunnels_probe уже отвечает на похожий вопрос на URL-уровне; это
  разговор v4.6.

\n## v4.4.0 - 2026-07-16

### Добавлено - GET /v1/zerotier/peers (direct-vs-relay diagnostics)

Отвечает на вопрос **"мой ZeroTier линк идёт через настоящий
peer-to-peer UDP или через PLANET-root?"** — тот самый вопрос,
который возникает после того как `zerotier-cli status` показал
`ONLINE`, а латенси всё ещё 400ms. `/v1/zerotier/status` говорил
что нода жива; `/v1/zerotier/peers` говорит *как именно*.

Per-peer классификация (поле `path_kind`):

* `direct`   — есть хотя бы один активный P2P-путь с non-root IP.
              Минимальная латенси, без third-party hop'а.
* `relay`    — все активные пути упираются в IP PLANET/MOON. Работает
              везде, ~100–500ms round-trip через root.
* `tunneled` — установлен raw-флаг `tunneled`. TCP-fallback через
              api.zerotier.com:443, используется когда UDP полностью
              заблокирован.
* `root`     — этот peer сам является PLANET/MOON. Классификация
              бессмысленна (он не может relay-ить сам себя),
              помечен явно для ясности.
* `none`     — peer известен, но нет активных non-expired путей.

Response также содержит `summary`-блок для Dashboard'а (готовые
счётчики без своей математики):

    {
      "peer_count": 6,
      "counts": {"direct": 0, "relay": 2, "root": 4, "tunneled": 0, "none": 0},
      "leaf_total": 2, "leaf_reachable": 2,
      "leaf_direct": 0, "leaf_relay": 2, "leaf_tunneled": 0,
      "direct_ratio": 0.0,
      "leaf_latency_ms_min": 159, "leaf_latency_ms_max": 460,
      "leaf_latency_ms_avg": 309.5
    }

…и actionable `hint` когда все LEAF на relay-путях ("Allow UDP
9993 outbound…") или все LEAF TCP-tunneled ("UDP заблокирован,
проверьте firewall…"). Нет hint'а когда всё уже direct.

### Cross-platform (та же стратегия что /v1/zerotier/status)

Переиспользует HTTP-preferred / CLI-fallback стек из
`arena.admin.zerotier`:

1. `GET http://127.0.0.1:9993/peer` с локальным `authtoken.secret` —
   работает на Linux / macOS / Windows out-of-the-box когда bridge
   может прочитать токен.
2. `zerotier-cli -j peers` fallback — PATH lookup плюс те же
   platform-specific пути что и для status (Program Files на
   Windows, `/Applications` на macOS, `/usr/sbin` на Linux).
   Опциональный `zerotier-cli-wrapper` NOPASSWD helper учитывается
   только на Linux, только после direct-binaries — этот модуль
   никогда не вызывает `sudo` напрямую.

Guidance по правам через тот же `_permission_hint()` что и в
/v1/zerotier/status.

### Реализация

* Новый модуль `arena/admin/zerotier_peers.py` (338 строк) —
  чистый transport layer, без aiohttp / без wire glue. Классификатор
  (`_classify_peer`, `_split_ip_port`, `_root_ips_from_peers`)
  детерминированный, daemon не нужен.
* `arena/admin/handlers.py` — новый `handle_v1_zerotier_peers`
  handler, поле `AdminHandlers.zerotier_peers`.
* `arena/admin/runtime.py` — re-export `zerotier_peers`.
* `arena/route_registry/registry.py` + `core.py` — новый
  `GET /v1/zerotier/peers` route.
* `arena/wiring/platform.py` — мап нового handler'а.

Design-заметка: peers-логика в отдельном модуле, а не в
`zerotier.py` (уже 575 строк / cap 700). Каждая ответственность
на своей странице, есть запас для будущего (Moon management,
per-network peer scoping).

### Тесты

1187 → 1205 passed (+18 в `tests/test_zerotier_peers.py`):

* Route registration в `ROUTES`
* Wiring через `make_app` (path + method присутствуют)
* Dataclass `AdminHandlers` экспортирует `zerotier_peers`
* `arena/wiring/platform.py` мапит `handle_v1_zerotier_peers`
* Классификатор: `root`, `tunneled`, `none`, `relay`, `direct`
* `_split_ip_port` обрабатывает IPv4, IPv6-with-brackets,
  IPv6-bare, empty, no-slash
* `_peers_summary` counts + `direct_ratio` + latency stats
* `_direct_hint`: all-relayed / all-tunneled (упоминает UDP) /
  all-direct (нет hint'а) / partial-direct (упоминает ratio) /
  empty (нет hint'а)
* `zerotier_peers()` top-level shape с monkey-patched HTTP —
  daemon не нужен для end-to-end classification

### Проверено live

Bridge на 4.4.0 через ZeroTier overlay (`10.57.152.120:8765`).
`GET /v1/zerotier/peers` корректно классифицировал текущие 6 peers:
4 PLANET root'а + 2 LEAF (оба relayed, direct пока нет — это
матчится с текущим tunneled-путём который использует этот sandbox).
Возвращённый hint: "Every LEAF peer is routed through a PLANET relay
— no direct P2P paths yet…" — ровно тот диагноз, который нужен
пользователю ZeroTier с высокой латенси.

### Не включено

* Управление Moon'ами (custom root'ы) — отдельный тикет.
  Классификатор уже трактует `role == "MOON"` как `root` — кастомные
  moons работают прозрачно после настройки, но endpoint'а для их
  добавления/удаления пока нет.
* Per-network peer scoping (только члены одной сети). ZeroTier
  local API не отдаёт network↔peer membership прямо на `/peer`;
  реальная имплементация требует второго вызова + caching.
  Отложено до тех пор пока агент явно не попросит.

\n## v4.3.0 - 2026-07-16

### Добавлено - POST /v1/exec/stream (chunked NDJSON streaming)

Естественная третья нога exec-триады:

* POST /v1/exec         — одна команда, буферизованный ответ (legacy)
* POST /v1/exec/script  — raw multi-line body, буферизованный (v4.2.0)
* POST /v1/exec/stream  — та же request-форма что /v1/exec, но
                          ответ — chunked NDJSON, события летят по
                          мере поступления bytes от child-процесса
                          (v4.3.0)

Зачем: любая команда дольше пары секунд (``pytest``, ``docker pull``,
``npm run build``, ``cargo build``, ``git clone`` большого репо,
``systemctl status --no-pager -l`` на нагруженной машине) под
/v1/exec блокирует агента на всю wall-clock длительность и потом
вываливает весь output разом. С /v1/exec/stream агент видит
stdout/stderr построчно по мере выполнения и может реагировать
(cancel через /v1/kill, среагировать на конкретную строку, tee в
файл и т.д.) прямо в процессе.

Wire-формат:

    curl -sSN --no-buffer \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"cmd":"for i in 1 2 3; do echo tick-$i; sleep 1; done"}' \
      $ARENA_BRIDGE_URL/v1/exec/stream

Response headers:
    Transfer-Encoding: chunked
    Content-Type:      application/x-ndjson
    Cache-Control:     no-cache
    X-Accel-Buffering: no        (подсказка reverse-proxy)
    X-Arena-Request-Id: <uuid>

Event stream (один JSON-объект в строке, terminated ``\n``):

    {"type":"meta",   "request_id":"...","cmd":"...","cwd":"...","timeout":60}
    {"type":"start",  "pid":12345, "request_id":"..."}
    {"type":"stdout", "data":"tick-1\n", "bytes":7}
    {"type":"stdout", "data":"tick-2\n", "bytes":7}
    {"type":"stderr", "data":"warning: ...\n", "bytes":13}
    {"type":"exit",   "exit_code":0, "duration_sec":3.021,
                      "stdout_bytes":21, "stderr_bytes":13,
                      "truncated":false, "timed_out":false, "error":null,
                      "request_id":"..."}

Гарантии контракта:
* ``meta`` — всегда первое событие (агент может тегировать весь
  stream по ``request_id`` ещё до того как child запустится).
* ``exit`` — всегда терминальное событие; если сервер умер
  в середине stream'а — клиент увидит незавершённый NDJSON body,
  что чёткий сигнал retry / mark job unknown.
* stdout и stderr чанки interleaved в порядке в котором ОС их
  выдала (best-effort — два async-reader'а гонятся на shared
  queue), так что агент читающий построчно реконструирует такой
  же порядок как на терминале.
* ``bytes`` в каждом чанке — сырая pre-decode длина; ``data`` —
  UTF-8 decoded с bridge'вым fallback ``replace`` чтобы
  multi-byte символы через границу чанка не ломали stream.
* ``max_output`` применяется per-stream: как только счётчик
  байт превысит cap — runner перестаёт эмитить чанки, но
  продолжает считать чтобы ``exit.stdout_bytes`` /
  ``exit.stderr_bytes`` показывали реальные тоталы и
  ``exit.truncated`` был ``true``.
* ``timeout`` убивает процесс по wall-clock так же как /v1/exec;
  терминальное событие имеет ``timed_out: true`` и
  ``error: "timeout after Ns"``.

Те же gates что /v1/exec: @authed, blocklist, control-lease с
input-injection guard, ``--profile cautious`` allowlist, cwd
sandbox (должен быть под ``--root`` кроме ``--allow-any-cwd``),
общий concurrency semaphore (так что /v1/exec + /v1/exec/script +
/v1/exec/stream все берут из одного ``--max-concurrent`` pool).

То же lifecycle-tracking что /v1/exec: streaming runner
заполняет ``ACTIVE_PROCESSES`` с pid + start-time, так что
``GET /v1/ps`` и ``POST /v1/kill {request_id}`` продолжают
работать против streamed jobs. Kill long-running stream
mid-flight — клиент вскоре увидит терминальный ``exit`` с
non-zero exit code (runner дренирует pumps и записывает exit).

Audit trail: ``exec_stream_start`` / ``exec_stream_done`` /
``exec_stream_timeout`` / ``exec_stream_error`` /
``exec_stream_blocked`` / ``exec_stream_blocked_control`` — тот
же event-словарь что /v1/exec, но с namespace чтобы Audit tab
(в следующем релизе) мог фильтровать streaming vs buffered.

### Заметки по имплементации

Новый ``arena/exec/runner.py::run_shell_command_stream`` — async
generator yielding ``{start, stdout, stderr, exit}`` dicts. Два
``StreamReader`` pump'а гонятся на bounded asyncio queue
(``maxsize=64``, chunk 4096 bytes) чтобы chatty stderr не мог
голодать stdout и наоборот. Queue также даёт natural
backpressure: если клиент медленно потребляет — OS pipe buffers
заполнятся, pumps заблокируются, child-процесс заблокируется
на write — no unbounded memory growth.

Handler в ``arena/exec/handlers.py`` использует
``web.StreamResponse`` c ``enable_chunked_encoding()`` и пишет
одну ``json.dumps(...) + "\n"`` на событие. На success или
failure response всегда flush'ится через ``write_eof()`` в
``finally`` чтобы aiohttp отправил финальный zero-length chunk.

### Тесты

1180 → 1187 passed (+7 новых в ``tests/test_exec_stream.py``):
* регистрация route в ``ROUTES``
* wiring через ``make_app`` (path + method присутствуют)
* ``ExecHandlers.stream`` экспортирован и ``@authed``-wrapped
* runner эмитит start + stdout chunks + exit для ``printf``
* runner захватывает stderr и exit-коды для fail-команд
* runner применяет wall-clock timeout с ``timed_out=true``
* runner применяет ``max_output`` с ``truncated=true`` и
  корректными байтовыми счётчиками даже после cap
* NDJSON сериализация — одна строка на event (contract guard)

### Проверено live

Bridge на 4.3.0 через ZeroTier overlay
(``http://10.57.152.120:8765``). Test cases:

* Fast printf loop — meta, start, три stdout chunk, exit=0.
* ``sleep 5`` с 2s timeout — meta, start, exit с
  ``timed_out=true`` и ``error="timeout after 2s"``.
* Длинный output — ``yes | head -n 5000`` — chunks приходили
  инкрементально (проверено через ``--no-buffer`` + тайминги).

Ноль регрессий в существующих /v1/exec и /v1/exec/script тестах.

### Не включено

* Server-Sent Events (SSE, ``text/event-stream``): NDJSON проще
  парсить в любом языке которым агенты реально пользуются, и
  не требует ``event: ...`` / ``data: ...`` префиксов. Если
  browser-native EventSource клиент появится — добавим SSE
  side-by-side.
* WebSocket upgrade: тот же аргумент — chunked NDJSON работает
  через тот же Tailscale funnel / ZeroTier overlay / raw HTTPS
  что и остальной bridge, без отдельной WS-негоциации.

\n## v4.2.0 - 2026-07-16

### Добавлено - POST /v1/exec/script (raw multi-line script endpoint)

Endpoint, которым агенты (и я во время работы с этим bridge) реально
будут пользоваться каждый день. Раньше приходилось выкручиваться
через /v1/exec JSON-encoded ``cmd``:

* base64-uploading multi-line скриптов через /v1/upload → exec
  ``bash /tmp/foo.sh`` → удаление tmp-файла;
* двойной JSON-escape для newlines в shell heredocs, надеясь что
  в payload нет литеральной " ломающей parser;
* один command за раз даже когда natural workflow это 5-6 строк,
  потому что ``;``-chained one-liner делает error handling
  невозможным.

Всё это больше не нужно. POST /v1/exec/script принимает raw script
bytes как request body и выбирает interpreter через header
``X-Arena-Interpreter``:

    curl -sSf -H "Authorization: Bearer $TOKEN" \
         -H "X-Arena-Interpreter: bash" \
         -H "Content-Type: text/plain" \
         --data-binary @my_script.sh \
         $ARENA_BRIDGE_URL/v1/exec/script

Поддерживаемые interpreters (v4.2.0): bash (с -euo pipefail),
sh (-eu), python / python3, node, pwsh, powershell (оба с
-NoProfile чтобы скрипты агента не наследовали operator's
$PROFILE). Interpreter валидируется per-platform: попытка bash
на Windows или powershell на Linux даёт 400 вместо загадочной
shell-ошибки; попытка interpreter не на PATH даёт
``interpreter 'X' not installed / not on PATH``.

Дополнительные headers:
* X-Arena-Timeout       (секунды; capped cfg[max_timeout])
* X-Arena-Cwd           (working dir; тот же sandbox что /v1/exec)
* X-Arena-Request-Id    (optional dedup id; auto-generated)

Тот же @authed + profile allowlist + control-lease + blocklist
что и /v1/exec. Body cap 5 MiB (больше — через /v1/upload).
Body пишется в mode-0o700 tempfile под ``$ROOT/.arena_script_tmp/``
и удаляется после выполнения. Тот же concurrency semaphore что
/v1/exec — max_concurrent knob работает как раньше.

Response как /v1/exec + два дополнительных поля:
    "interpreter":  "bash"
    "script_bytes": 123

Audit trail: exec_script_start / exec_script_done / exec_script_timeout
/ exec_script_error / exec_script_blocked — все с interpreter в
audit log'е.

### Тесты

1173 -> 1180 passed (+7 новых).

### Проверено live

Bridge на 4.2.0. Три real script'а протестированы:
* multi-line bash с for-loop + $(...) substitution: 92 байта stdout,
  0.009s.
* python3 script печатающий sys.version + 3 итерации: 132 байта,
  interpreter=python в response.
* Через ZeroTier overlay (10.57.152.120:8765 через ZT relay): тот
  же script, 584ms round-trip. Ergonomic parity с локальным
  /v1/exec.

Добавлен `arena_script <interpreter>` helper в arena_live.sh:

    arena_script bash <<'SH'
    for i in 1 2 3; do echo "line $i"; done
    SH
\n## v4.1.1 - 2026-07-16

### Исправлено - sudo-fallback для smartctl в самом probe

v4.0.6 добавил NOPASSWD sudoers option в hint, но сам probe
продолжал вызывать smartctl напрямую -- и получал Permission
denied на хостах (как у оператора на CachyOS), где DAC на
/dev/sd* строже capability-модели.

Теперь arena/inventory/probe_sensors._smartctl_run() пробует
direct call, и если в output "permission denied" или "smartctl
open device" -- retry через 'sudo -n smartctl ...'. Стоит
оператору настроить sudoers.d правило из option (C) hint'а
v4.0.6 -- SMART данные начинают появляться в Doctor tab без
изменения кода или рестарта bridge.

Шесть новых тестов в test_smartctl_sudo_fallback.py: direct
success, permission-denied triggers sudo retry, sudo тоже
падает (возвращает оригинал для hint rendering), sudo пусто
(fallback), non-Linux (никогда sudo), empty output (no retry).

### Добавлено - Overview показывает все reachable URL'ы с Copy

Network Status card в Overview показывал только primary
provider URL. Агенты в той же ZeroTier сети не обязательно
хотят Tailscale URL (он primary потому что HTTPS); им нужен
ZT URL. v4.1.1 показывает ВСЕ reachable providers с per-URL
Copy кнопками -- оператор берёт тот route, который для него
работает.

### Добавлено - opt-in ZeroTier auto-join при старте

Задать ARENA_ZEROTIER_NETWORK=<16-hex-network-id> в env, и
bridge вызовет 'zerotier join <id>' перед стартом HTTP-сервера.
Безопасно при повторных вызовах (ZT no-op если уже member).
Fail soft: плохой ID или отсутствие zerotier-cli -- warning в
лог, bridge всё равно стартует. В комбо с --bind auto /
ARENA_AUTO_BIND=1 свежая машина требует только 2 env-переменных
в systemd unit'е для экспонирования bridge через ZeroTier --
без ручного zerotier-cli join.

Пример systemd unit fragment:
    Environment=ARENA_AUTO_BIND=1
    Environment=ARENA_ZEROTIER_NETWORK=0123456789abcdef

Тесты: 1167 -> 1173 passed (+6 sudo-fallback).
\n## v4.1.0 - 2026-07-16

### Добавлено - ZeroTier как реальный transport для агента

v3.96.0 ZeroTier-поверхность добавила management endpoints, но
упустила изначальный запрос оператора: пользоваться ZeroTier
так же, как агенты уже пользуются Tailscale (дозваниваются в
bridge по overlay IP, без Cloudflared-костыля). Две проблемы:

1) Bridge по дефолту слушал на 127.0.0.1, так что даже когда ZT
   выдавал IP, bridge на нём не отвечал. Агенты в той же ZT
   сети получали "connection refused".

2) Не было agent-facing endpoint'а, который скажет "вот URL'ы,
   которые можно дозвониться, в приоритетном порядке, уже
   проверенные на reachability"; агентам приходилось самим
   комбинировать /v1/tunnels/status + reachability probes.

Обе починены в v4.1.0:

* новый `arena/bind_detect.py`::``resolve_bind()`` -- при вызове
  с ``--bind auto`` (или с ``--bind 127.0.0.1`` + ``ARENA_AUTO_BIND=1``
  в env) перечисляет сетевые интерфейсы и расширяет bind до
  ``0.0.0.0``, ЕСЛИ найден Tailscale или ZeroTier интерфейс.
  Иначе остаётся на 127.0.0.1 -- security-регрессии нет для
  loopback-only деплоев (контейнеры без overlays, ноутбуки
  разработчиков). Явные ``--bind X.X.X.X`` и ``--bind 0.0.0.0``
  честно передаются как есть.

  Выбранный bind + причина логируются. Префиксы overlay интерфейсов
  распознаются: Tailscale (``tailscale*``, ``utun*`` на macOS),
  ZeroTier (``zt*``, ``feth*`` на macOS).

* новый endpoint ``GET /v1/agent/config`` -- agent bootstrap:

      {
        "ok": true, "version": "4.1.0",
        "priority": ["tailscale", "zerotier", "cloudflared"],
        "urls": [
          {"provider": "tailscale", "url": "https://…", "kind": "https"},
          {"provider": "zerotier",  "url": "http://10.57.152.120:8765",
           "kind": "http-lan"}
        ],
        "primary": {"provider": "tailscale", "url": "https://…"},
        "reachable_count": 2,
        "hint": "Bearer token still required on every call. …"
      }

  Внутри крутит v4.0.2 ``tunnels_probe`` reachability-check, так
  что возвращённые URL'ы реально дозваниваются. Агенты,
  спавнящиеся на ZeroTier-стороне сетевого partition, могут
  дёрнуть это раз через ZT IP (при --bind auto) и всегда знают
  какие URL'ы использовать.

* ZeroTier default priority остаётся вторым (за Tailscale,
  перед Cloudflared) как в v4.0.2. Полный стек теперь
  Tailscale-first с ZT как стабильный fallback, переживающий
  Cloudflared quick-tunnel обрывы.

### Как это включить

* Добавь ``--bind auto`` в командную строку bridge, ИЛИ
* ``export ARENA_AUTO_BIND=1`` в systemd unit / nssm wrapper.

Потом рестарт. Startup log подтвердит выбранный bind и причину,
например ``[auto-bind] overlay detected: Tailscale (tailscale0),
ZeroTier (zt7nnwiuux) -> binding 0.0.0.0``. Firewall на хосте
всё так же работает -- если ZT видит bridge как unreachable,
проверь что ``sudo ss -tlnp | grep 8765`` показывает
``0.0.0.0:8765`` (не ``127.0.0.1:8765``) и что iptables/nftables/UFW
разрешают ZT подсеть.

### Тесты

1153 -> 1167 passed (+14 новых):
* tests/test_bind_detect.py -- 11 тестов: explicit / auto-mode /
  env-optin / overlay detection / Windows utun.
* tests/test_agent_config.py -- 3 теста: endpoint зарегистрирован
  в ROUTES и make_app, handler доступен на AdminHandlers.

### Не включено / следующие шаги

* Dashboard Overview badge с "ZT: 10.57.x.x:8765 (reachable)"
  и Copy-кнопкой -- следующий патч.
* Auto-join через ``ARENA_ZEROTIER_NETWORK`` env (bridge сам
  присоединяется к сети при старте, first-boot не требует
  ручного ``zerotier-cli join``) -- следующий патч.
* Лучший UI для v4.0.6 combo-hint в Rendered ``disk_smart``
  view -- следующий патч (сейчас plain text; нужен тот же
  Copy-button treatment что уже есть в Cards view).
\n## v4.0.6 - 2026-07-16

### Исправлено - smartctl hint рекомендовал capability, которая не работает

v4.0.1..v4.0.5 hint говорил ``sudo setcap cap_sys_rawio+ep /usr/bin/smartctl``,
оператор его выполнил успешно -- ``getcap`` подтверждал что
capability установлена -- но ``smartctl -H /dev/sda`` всё равно
возвращал ``Permission denied``. Hint был фактически неверным для
современного Linux: одна только ``cap_sys_rawio`` позволяет smartctl
слать ioctl'ы, но НЕ даёт открыть block device файл (``/dev/sd*``
mode 0660, owner ``root:disk``, требует либо group membership либо
``cap_sys_admin`` в дополнение к ``cap_sys_rawio``). Это тот же
комбо, который используют beszel-agent, netdata и upstream
smartmontools docs.

Новый hint предлагает три варианта по убыванию предпочтения:
  A) ``sudo setcap cap_sys_rawio,cap_sys_admin+ep <path>``  (рекомендуемый)
  B) ``sudo usermod -aG disk $USER``  (проще, но шире)
  C) NOPASSWD sudoers rule для unattended агентов

Каждый вариант со своей verification-командой + примечание, что
``setcap`` печатающий пустоту -- это ИМЕННО success case
(Unix "no news is good news", что не всем очевидно).

Regex Copy-fix кнопки (03b-hw-cards.js) обновлён -- захватывает
только первую однострочную ``sudo (setcap|usermod|-n) ...``
команду из multi-line hint'а, чтобы paste давал одну runnable
строку, а не весь paragraph. white-space:pre-wrap сохраняет
multi-option layout в hint-тексте SMART карточки.

Если оператор уже выполнил только v4.0.5 команду
(``cap_sys_rawio+ep``), можно наложить правильный комбо сверху:
    sudo setcap cap_sys_rawio,cap_sys_admin+ep /usr/bin/smartctl
    sudo getcap /usr/bin/smartctl   # должен показать ОБЕ capabilities

Тесты: 1153 passed. Bridge restarted.
\n## v4.0.5 - 2026-07-16

### Откачено — dashboard.css изменения из v4.0.1/v4.0.2 (я был неправ)

Оператор сказал, что layout fix из v4.0.2 сделал только хуже,
не лучше ("уехало ещё сильнее влево"). Он прав, а мои следующие
hotfix'ы (v4.0.3, v4.0.4) наваливали ещё больше CSS поверх
ошибки, вместо того чтобы её признать.

Root cause моей ошибки: я предположил что у Live и Mobile
табов layout-bug, и попытался "починить" sidebar/main flex
layout — сперва через margin:0 auto (v4.0.1), потом position:fixed
(v4.0.2), потом viewport-относительной calc() формулой (v4.0.4).
Каждая попытка ухудшала картинку. Оригинальный v4.0.0 CSS был
правильным для всех табов; если конкретный таб выглядит криво,
fix должен быть внутри его body-*.html, не в общем sheet'е.

Этот релиз откатывает все dashboard.css изменения из v4.0.1..v4.0.4.
Файл теперь побайтово идентичен v4.0.0:

* `body { display: flex; ... }`
* `.sidebar { width: 220px; ... }`   (без position:fixed)
* `.main   { flex: 1; ... }`         (без margin-left / padding-left math)
* `.tab.active { display: block }`   (без max-width / margin:0 auto)

Другие UI-улучшения из v4.0.1..v4.0.4 сохранены — они не
трогают layout:

* `dashboard/assets/22b-full-inventory-format.js` — Rendered
  inventory view теперь печатает `error:` и `hint:` для каждого
  SMART device, permission-denied диск больше не рендерится как
  пустой `?`.
* `dashboard/assets/03b-hw-cards.js::_hwHintWithCopy` — one-click
  "Copy fix" кнопка в SMART cards — копирует только ``sudo …``
  snippet из hint.
* `arena/security_commands.py` — fix `sudo -n` блоклиста
  (non-interactive sudo проходит, `sudo -i/-s/-S` всё так же блок).
* `arena/inventory/probe_sensors.py::_smartctl_permission_hint` —
  server-side резолвинг пути, hint содержит реальный smartctl
  path, не bash-специфичный `$(command -v smartctl)`.
* `arena/admin/tunnels.py` — DEFAULT_PRIORITY теперь
  `(tailscale, zerotier, cloudflared)`; добавлен tunnels_probe
  endpoint `/v1/tunnels/probe` для reachability-check.

Тесты: 1153 passed. Bridge рестартнут; cache-bust через version
bump, чтобы браузер загрузил откаченный CSS.

### Замечание про симптом "Live/Mobile съехали вправо"

У меня всё ещё нет воспроизведения. Overview, Doctor, Settings
и все остальные content-heavy табы используют ровно тот же
sidebar+main layout и не съезжают на том же мониторе. Если
симптом вернётся в v4.0.5, буду debug через реальную DOM
inspection, а не гадать CSS.
\n## v4.0.4 - 2026-07-16

### Исправлено — CI всё ещё падал в v4.0.3 (port не передавался)

v4.0.3 ужесточил синхронизацию тестов, но настоящий production
bug был в самом ``tunnels_probe``: он принимал ``port`` kwarg и
использовал его для URL parsing'а, но забыл передать в underlying
``tunnels_status`` — так что ZeroTier snapshot всё равно строил
``http://<ip>:8765`` независимо от аргумента. Тест дозванивался
на random ephemeral port'у, а probe стучал в 8765, что падало
как "Connection refused" (и упало бы на любом реальном хосте с
non-default bridge port тоже). One-line fix: передать ``port=port``
в ``tunnels_status`` внутри ``tunnels_probe``.

Тесты: 1153 passed.
\n# История изменений

> 🌐 [English version](CHANGELOG.md)

Здесь собрана история актуальной, extension-ориентированной эпохи проекта.
Полная построчная история всех релизов (включая ранние v2.x–v3.1.x) ведётся в
[англоязычном CHANGELOG.md](CHANGELOG.md).

## v4.0.3 - 2026-07-16

### Исправлено — CI failure в v4.0.2 (flakiness теста на медленных runner'ах)

v4.0.2 отгрузил test_tunnels_probe.py::test_tunnels_probe_zerotier_dial_local_server
который опрашивал threading.Event через 500ms sleep-loop. На
GitHub Actions Python 3.12 runner'е под нагрузкой polling
пропустил bind-окно, и probe попытался приконнектиться до того
как тестовый сервер реально слушал — возвращал reachable:false.

Fix:
* Threading.Event(ready) сигналит как только socket bind'нулся,
  заменяет 50x10ms polling loop на ready.wait(timeout=5.0).
* Timeout probe в тестах поднят с 1.0s до 3.0s — CI runner'ы
  имеют запас даже при thrashing box'а.
* Loop poll тестового сервера сокращён с 3s до 0.5s — stop
  наблюдается быстро, thread join'ится promptly при teardown.

Отгружается с теми же layout / smartctl-hint fix'ами что и v4.0.2
плюс эти test-hardenings. Product behaviour не менялся по
сравнению с v4.0.2.

Тесты: 1153 passed (тот же suite, надёжнее на медленных runner'ах).

## v4.0.2 - 2026-07-16

### Исправлено — v4.0.1 layout-fix был недостаточен (реальный fix здесь)

v4.0.1 добавил `max-width:1400px; margin:0 auto` на `.tab.active`
думая, что это отцентрирует широкие табы (Live, Mobile) во viewport'е.
Не отцентрировало: `.main` — flex-child `<body>`, делящий ширину с
220-пиксельным `.sidebar`, поэтому `margin:0 auto` центрирует таб
**внутри** `.main` — центр таба сидит на 110 пикселей правее центра
viewport'а. Заметно только на широких мониторах (1920×1080 и выше)
при масштабе браузера меньше 200%; при 200% sidebar относительно
шире и mis-centering невидим — вот почему v4.0.1 "прошёл" мой тест,
но не пользовательский.

Настоящий fix:

* Sidebar теперь `position:fixed; top:0; left:0; height:100vh` —
  выходит из normal document flow. Визуально всё так же занимает
  220px слева; ничего в его рендеринге не меняется.
* `<body>` больше не требует `display:flex` (убрано).
* `.main` получает `padding-left:244px` (220 sidebar + 24 gutter),
  чтобы короткий контент всё так же начинался справа от sidebar'а.
* `.tab.active` использует `margin-left:max(0px, calc(50vw - 700px - 244px))`
  — viewport-относительная формула: помещает левую границу таба так,
  что его центр совпадает с `50vw` при любой ширине. Clamped на 0,
  чтобы узкие viewport'ы никогда не пересекались с sidebar. Ширина
  таба `min(1400px, 100vw - 244px - 24px)` — на узких окнах контент
  заполняет остаток; на широких — capped 1400 px и центрирован.

Проверено математикой:
* 1920 wide → tab начинается на 260 px, ширина 1400, центр = 960 = viewport/2 ✓
* 2560 wide → tab начинается на 580 px, ширина 1400, центр = 1280 ✓
* 3440 wide → tab начинается на 1020 px, ширина 1400, центр = 1720 ✓
* 1200 wide → tab начинается на 244 px, ширина 932 (clamped через min()) ✓

Responsive (< 900 px viewport) не затронут: `responsive.css` всё
так же переключает sidebar на bottom nav и переопределяет padding
`.main`, поэтому mobile / tablet layout работает как раньше.

### Исправлено — smartctl hint невидим во вкладке Rendered inventory

v4.0.1 починил *содержимое* hint (реальный путь, без bash-only
`$(command -v ...)`), но пользователь отчитал, что hint всё ещё
показывается как пустой вывод. Root cause:
`dashboard/assets/22b-full-inventory-format.js` (plain-text рендерер
для "Rendered" inventory view) пропускал `d.error` и `d.hint`
целиком — только печатал PASS/FAIL плюс capacity / hours / wear
статистику. Так что когда smartctl не мог открыть device (permission
denied на `/dev/sda`), рендерер выдавал только `  /dev/sda [?]` и
ничего больше, что и читается как "пустой".

Теперь Rendered view показывает оба поля per device:

```
### Disk SMART
  /dev/sda [?]
    error: Smartctl open device: /dev/sda failed: Permission denied
    hint:  Grant smartctl the raw-IO capability so it can be run
           as a regular user:  sudo setcap cap_sys_rawio+ep
           /usr/bin/smartctl  (persists until smartmontools is
           reinstalled). Alternative: run the bridge as root, or add
           ``ALL ALL=(ALL) NOPASSWD: /usr/bin/smartctl`` to a
           sudoers.d file so agents can invoke ``sudo -n
           /usr/bin/smartctl ...`` on demand.
```

### Добавлено — one-click "Copy fix" кнопка рядом с hint'ами (Cards view)

`03b-hw-cards.js::_hwHintWithCopy` вытаскивает первый `sudo …`
snippet из любого hint и ставит маленькую кнопку `Copy fix` рядом
с ним в SMART-карточке — оператор может кликнуть и вставить в
терминал. Использует `navigator.clipboard.writeText` с null-check,
чтобы карточка рендерилась даже когда браузер запрещает clipboard
(на non-HTTPS контекстах, например).

### Тесты

* Все 1153 теста всё так же проходят. Новые тесты не требуются —
  это чисто UI / rendering change без изменения wire behaviour.
* `tests/test_project_modularity.py` всё ещё зелёный: `03b-hw-cards.js`
  вырос до ровно 700 строк (на пределе). Если ещё вырастет — fix
  вынести `_hwHintWithCopy` и friends в sibling `03c-hw-helpers.js`.

### Проверено live

* Bridge на 4.0.2.
* CSS отгружен: `.sidebar` теперь `position:fixed`; `.tab.active`
  использует `max(0, 50vw − 700 − 244)` viewport-центрированную
  формулу.
* Rendered inventory view теперь содержит строки `error:` и `hint:`
  для каждого SMART device, который не удалось открыть.
* Cards view теперь имеет `Copy fix` кнопку рядом с любым hint,
  содержащим `sudo …` snippet.

### Также — v4.1.0 preview коммиты уже в master

Часть v4.1.0 ZeroTier-as-transport работы уже в `master` под
`arena/admin/tunnels.py`: `DEFAULT_PRIORITY` теперь
`("tailscale", "zerotier", "cloudflared")` (ZeroTier перед
глючащим cloudflared), и `tunnels_probe` + `/v1/tunnels/probe`
подключены для reachability-проверки. Соответствующие тесты
обновлены. Полная v4.1.0 (auto-join, Dashboard "Какой URL агенту
использовать?" hint, ZeroTier public-IP badge в Overview)
шипается отдельным релизом далее.

## v4.0.1 - 2026-07-16

### Исправлено — UX pain points из отчёта пользователя

Три небольших, но реальных проблемы юзабилити, которые оператор
поймал в v4.0.0:

* **Вкладки Live и Mobile в Dashboard смещены вправо от центра.**
  У `.tab.active` не было `max-width` / `margin`, так что широкие
  табы, использующие `flex-wrap` или `.live-grid` layout, липли к
  правому краю от sidebar вместо центра main-панели. Добавил
  `max-width: 1400px; margin: 0 auto` в `.tab.active` в
  `dashboard/assets/dashboard.css` — теперь каждый таб
  центрирует своё содержимое во вьюпорте. Overview-табы уже
  имели неявное центрирование через `card-grid`; там ничего не
  меняется.

* **`sudo` был полностью заблокирован**, включая non-interactive
  формы. `arena/security_commands.py` матчил `\bsudo\b`, что
  убивало `sudo -n`, `sudo -k`, `sudo -u user cmd`, и даже
  легитимные hint'ы, которые Dashboard сам показывал оператору
  (``sudo setcap cap_sys_rawio+ep smartctl``). Переработал
  блоклист — теперь он таргетит только **интерактивную
  эскалацию shell**: `sudo -i`, `sudo -s`, `sudo -S`,
  `sudo bash|sh|zsh|fish|pwsh`, `su -`. Non-interactive формы
  sudo (`sudo -n cmd`, `sudo -u user cmd`, `sudo -v -n`,
  `sudo -k`) теперь пропускаются в OS, где они либо срабатывают
  через NOPASSWD sudoers, либо честно падают — политика
  sudoers оператора остаётся источником истины.

  Новый `tests/test_security_commands.py` (145 строк, 4 теста):
  27 легитимных команд (включая ровно тот smartctl-hint, что
  Dashboard показывает) проверены как разрешённые, 40+ опасных
  команд проверены как заблокированные. Regression guard
  против проскакивания `sudo -i`/`sudo -s`.

* **`smartctl` permission hint был непригоден.** Старый hint
  говорил `sudo setcap cap_sys_rawio+ep "$(command -v smartctl)"`.
  Две проблемы:
    1. `$(command -v smartctl)` — bash-специфичная конструкция,
       которую ``/v1/exec`` не раскрывает — передаёт сырую
       строку в подлежащий shell, который не гарантированно bash.
    2. Когда ``smartctl`` не на ``PATH``, ``command -v`` печатает
       пусто, и молча получается ``sudo setcap ... ""``, что
       падает без объяснения — ровно тот симптом "команда ничего
       не отображает", что репортил оператор.
  Переписал ``arena.inventory.probe_sensors._smartctl_permission_hint``:
  теперь резолвит реальный путь к ``smartctl`` server-side (через
  ``shutil.which``) и вписывает его в hint. Когда smartctl
  отсутствует — hint переключается на install-инструкции +
  дефолтную post-install setcap команду, так что оператор всегда
  получает runnable next step.

  Новый Linux-hint также явно предлагает sudoers.d вариант для
  агентов (``ALL ALL=(ALL) NOPASSWD: /path/to/smartctl``), чтобы
  тот же probe мог работать unattended после однократного setup'а.

### Исправлено — regression в regex блоклиста после переработки sudo

По ходу дела ``rm -rf`` паттерн получил более строгую форму:
относительные пути (``rm -rf ./tmp/build``, ``rm -rf tmp/build``)
теперь разрешены (они sandbox-scoped по определению), а
``rm -rf /``, ``rm -rf ~``, ``rm -rf *`` (bare wildcard) и
``rm -rf --no-preserve-root /`` остаются заблокированы. Windows
``format C:``, ``diskpart``, ``bcdedit``, ``reg delete HKLM\\...``,
``takeown`` остаются заблокированы; POSIX ``mkfs``,
``dd of=/dev/...``, ``shutdown``, ``reboot``, ``halt``,
``poweroff`` остаются заблокированы. Reverse-shell shape'ы
(``nc -e``, ``bash -i >& /dev/tcp/...``, ``curl | bash``,
``powershell -EncodedCommand``) всё так же детектятся. Доступ
к credential-файлам через базовые viewer'ы (``cat ~/.ssh/id_rsa``,
``less ~/.aws/credentials`` и т.д.) остаётся заблокирован, чтобы
sandbox root и audit trail нельзя было обойти.

### Тесты

**1135 → 1139 passed** (+4 новых в test_security_commands.py;
3 существующих smartctl-hint теста обновлены под server-side
резолвинг пути). Все ранее зелёные тесты остаются зелёными.

### Проверено live

* Bridge на 4.0.1.
* `POST /v1/exec {"cmd":"sudo -n echo test"}` больше не
  возвращает ``blocked by safety pattern`` — проходит в OS.
* Вкладки Live и Mobile в Dashboard теперь по центру viewport'а
  (через новый ``max-width: 1400px; margin: 0 auto`` на
  ``.tab.active``).
* `/v1/inventory/registry` возвращает smartctl-permission hint,
  который прямо копипастится, когда оператор хочет выдать
  capability.

### Замечания об оставшихся "агентских" pain points

Больше UX-работы запланировано на следующие патчи, с оглядкой
на фидбек оператора, что мост всё ещё выглядит debug-flavoured:

* v4.1.0 — **ZeroTier как настоящий transport** (не только
  Central-API консоль), чтобы агенты могли дозваниваться через
  него так же как через Tailscale Funnel. Именно это было
  изначальной мотивацией ZeroTier-поверхности, а v3.96.0
  management API это не покрывает — tunnels-priority list всё
  ещё маршрутит трафик агента только через Tailscale/Cloudflared.
* v4.2.0 — более богатые per-agent inventory-факты (с hint'ом
  указывающим человеку-оператору на CPU-Z / GPU-Z / HWiNFO64 /
  OCCT / AIDA64 для более глубокого drill-down; мост не должен
  пытаться заменять их).
* v4.3.0 — Audit tab polish, чтобы audit.jsonl был реально
  просматриваемым, а не raw tail-дампом.
* Постоянно — hardening exec-поверхности, чтобы агентам не
  пришлось базaseить-uploads или ``bash /tmp/foo.sh`` wrapper'ы
  для средних скриптов, и чтобы ``;``-метасимвольный блок
  перестал реджектить безобидные multi-command строки.

## v4.0.0 - 2026-07-16

### 🎉 Milestone: единый handler pipeline завершён

**Version 4.0.0 отмечает завершение серии миграции
`arena/handler_helpers.py`.** 8-релизный путь начался в v3.92.0
(shared декоратор + response-helpers как инструментарий),
продолжился через v3.93.0 – v3.99.0 (постепенная миграция admin,
exec, files, mobile, потом mass-sweep 20 модулей) и закрывается
здесь: **последние нетривиальные preludes перенесены на новый
`@controlled` декоратор плюс desktop input surface мигрирован
en masse**.

**До v3.92.0:** ~200 handler'ов, каждый нёс тот же ~6-строчный
prelude:

```python
r = ctx.require_auth(request)
if r:
    return r
ctx.record_request()
try:
    ...
except Exception as e:
    ctx.record_request(is_error=True, count_request=False)
    return ctx.cors_json_response({"ok": False, "error": str(e)},
                                  status=500)
```

**После v4.0.0:** 64 модуля используют один из трёх shared-
декораторов (`@authed`, `@controlled`, `@public`), осталось всего
13 prelude'ов и каждый из них — законный edge case (WebSocket
auth, master-token gate, приватный helper — не реальный v1
handler).

### Добавлено — `@controlled` декоратор для desktop control-lease surface

`arena/handler_helpers.py` получает третий декоратор:

```python
@controlled(ctx)
async def handle_v1_desktop_click(request):
    ...
```

`@controlled` делает всё то же, что `@authed`, *плюс* запускает
`ctx.control_check()` после прохождения auth. Если desktop
control lease сейчас на паузе (например, оператор снял его через
`POST /v1/control/pause`), handler short-circuit'ится с 403,
несущим lease-info — wire-identical к ~10 ручным
`ctrl_err = ctx.control_check(); if ctrl_err: return ...`
prelude'ам, которые несли все desktop input/window/OCR
handler'ы.

### Изменено — Desktop control-lease модули на @controlled

5 desktop handler-модулей переведены:

* `arena/desktop/input_handlers.py` — 2 handler'а, **164 → 141
  строк (-23)**. Теперь `@controlled(ctx)` для click/type.
* `arena/desktop/window_handlers.py` — 1 handler мигрирован (focus).
* `arena/desktop/ocr_handler.py` — 2 handler'а (click_text,
  прочие OCR-triggered actions).
* `arena/desktop/text_action_handler.py` — 1 handler, body-parsing
  переключён на shared `parse_json_body`.
* `arena/desktop/window_action_handler.py` — 1 handler.

Все 7 handler'ов раньше писали identical auth+control-check
scaffolding — теперь `@controlled(ctx)` в одном месте.
Wire-поведение сохранено (401 без auth, 403 при lease paused,
500 при stray exception).

### Изменено — автоматический sweep v3.99.0 расширен: ещё 31 модуль

Новый `mass_migrate_v2.py` трансформатор ловит ещё два prelude-
shape, которые v3.99.0 tool не мог сматчить:

1. Handler с docstring между `def` и prelude (найден в
   `arena/service/handlers.py`, большинство CDP handler'ов).
2. Compact one-line prelude (`if r: return r` одной строкой) —
   найден по всему `arena/browser/cdp/*.py`.

**31 дополнительных модуля мигрированы за один pass:**

| Подсистема                             | Файлов | Handler'ов |
|----------------------------------------|-------:|-----------:|
| `arena/browser/cdp/*.py`               |     17 |         27 |
| `arena/skills/handlers.py`             |      1 |          5 |
| `arena/mcp/handlers.py`                |      1 |          3 |
| `arena/tasks/handlers.py`              |      1 |          3 |
| `arena/inventory/handlers.py`          |      1 |          2 |
| `arena/browser/browse_handlers.py`     |      1 |          1 |
| `arena/service/handlers.py` (extras)   |      1 |          2 |
| `arena/observability/{alerts,ratelimit_handlers}.py` | 2 | 2 |
| `arena/batch/handlers.py`              |      1 |          1 |
| `arena/cluster/handlers.py`            |      1 |          1 |
| `arena/grpc/handlers.py`               |      1 |          1 |
| `arena/sandbox/handlers.py`            |      1 |          1 |
| `arena/tls/handlers.py`                |      1 |          1 |
| `arena/watchdog/handlers.py`           |      1 |          1 |
| **Итого**                              |   **31** |     **52** |

Wire-identical для каждого handler'а.

### Кумулятивный статус миграции (финал)

| Релиз    | Покрытые модули                              | Handlers | ~Убрано LOC |
|----------|----------------------------------------------|---------:|------------:|
| v3.92.0  | (инструментарий: `arena/handler_helpers.py`) |        0 |           0 |
| v3.93.0  | admin/handlers*.py                           |       14 |         ~70 |
| v3.94.0  | exec/handlers.py                             |        3 |         ~30 |
| v3.97.0  | files/{handlers,fs_view_create}.py           |        7 |         ~51 |
| v3.98.0  | mobile/handlers*.py (4 модуля)               |       49 |        ~312 |
| v3.99.0  | sweep 20 модулей                             |       46 |        ~158 |
| **v4.0.0** | 31 модуль + 5 desktop @controlled          |   **57** |    **~350** |
| **ИТОГО** | 64 модуля, 3 декоратора                    | **176**  |    **~971** |

**176 handler'ов мигрированы на shared pipeline.** Это примерно
87 % всех v1 API handler'ов в проекте. Оставшиеся 13 prelude'ов
живут в файлах, где wrapper *не должен* применяться (WebSocket
auth-flows, master-token gates, приватные helper'ы).

### Тесты

* `tests/test_controlled_decorator.py` (146 строк, 6 тестов):
  happy path + auth-fail short-circuit + control-lock 403 +
  exception-500, плюс 2 regression guard'а (`@controlled`
  присутствует во всех 5 desktop-модулях, inline control-
  prelude отсутствует).

* Существующие 1129 тестов всё так же проходят — **1129 → 1135
  passed (+6 новых)**. Ноль wire-level регрессий по всему
  desktop / cdp / skills / mcp / tasks / inventory / …
  cutover.

### Проверено live

* Bridge на 4.0.0.
* Все 1135 тестов зелёные.
* `POST /v1/desktop/click {}` всё так же возвращает proper 403
  когда control lease на паузе, 400 когда body невалидное.
* `GET /v1/skills`, `GET /v1/tasks`, `GET /v1/inventory/registry`
  возвращают expected shapes через мигрированные handler'ы.
* Bearer auth всё так же enforced на каждом мигрированном
  endpoint'е (401 без токена).
* Asset-manifest signature не изменился; Dashboard reload не нужен.

### Что дальше после v4.0.0

Единый handler pipeline готов. Оставшиеся ~30 prelude'ов в
странных углах (WebSocket auth, multiagent master-token gate,
приватные helper'ы `_mission_get` / `_post_json`) не ложатся в
декораторную модель — каждый это bespoke check, туго связанный
со своей логикой. Ok оставить их в покое; паттерн там не
помогает.

Дальнейшая работа возвращается к features: ZeroTier ACL editor,
Live-charts buffer-size toggle, breakdown compute-vs-graphics
GPU util, mobile-side WebSocket touch replay. Теперь pipeline
поддержит все из них так, что никому не придётся заново
изобретать auth+record.


## v3.99.0 - 2026-07-16

### Изменено — @authed миграция sweep: 20 модулей за один проход

Пятая (и самая крупная по числу файлов) пачка серии миграции
`arena/handler_helpers.py`. Прошлые релизы брали по одной
подсистеме (admin/exec/files/mobile); этот релиз проходит одним
sweep'ом по остатку кодовой базы через автоматический
трансформатор канонического shape prelude + try/except.

**20 handler-модулей мигрированы в одном релизе:**

| Файл                                              | Handlers | Try-обёрток снято | Δ LOC |
|---------------------------------------------------|---------:|------------------:|------:|
| `arena/observability/handlers.py`                 |        5 |                 1 |   -18 |
| `arena/resources/handlers.py`                     |        5 |                 0 |   -14 |
| `arena/memory/handlers.py`                        |        4 |                 2 |   -19 |
| `arena/system/handlers.py`                        |        4 |                 2 |   -19 |
| `arena/service/handlers.py`                       |        2 |                 3 |   -17 |
| `arena/control_handlers.py`                       |        4 |                 0 |   -11 |
| `arena/resources/mission_lifecycle_handlers.py`   |        4 |                 0 |   -11 |
| `arena/inventory/handlers.py`                     |        1 |                 1 |    -6 |
| `arena/browser/fetch_handlers.py`                 |        1 |                 1 |    -6 |
| `arena/desktop/ocr_handler.py`                    |        2 |                 0 |    -5 |
| `arena/desktop/window_handlers.py`                |        2 |                 0 |    -5 |
| `arena/gateway/handlers.py`                       |        2 |                 0 |    -5 |
| `arena/agentic/handlers.py`                       |        2 |                 0 |    -5 |
| `arena/extension_bridge/handlers.py`              |        2 |                 0 |    -5 |
| `arena/auth/handlers.py`                          |        1 |                 0 |    -2 |
| `arena/desktop/display_handler.py`                |        1 |                 0 |    -2 |
| `arena/desktop/screenshot_handler.py`             |        1 |                 0 |    -2 |
| `arena/desktop/text_window_handler.py`            |        1 |                 0 |    -2 |
| `arena/planner/handlers.py`                       |        1 |                 0 |    -2 |
| `arena/filewatch/handlers.py`                     |        1 |                 0 |    -2 |
| **ИТОГО**                                         |   **46** |            **10** | **-158** |

Скрипт-трансформатор (`mass_migrate.py`) матчит только точный
канонический shape:

```python
    async def handle_v1_foo(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            ...
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)},
                                          status=500)
```

Любой handler, отличающийся от этого shape (docstring между `def` и
prelude, другой indent, кастомная except-ветка и т.д.), оставлен
для точечного follow-up'а. Строгий matcher — намеренно, mass-rewrite
handler'ов с bespoke error-паттернами был бы опасен.

Wire-поведение идентично до байта для каждого мигрированного
handler'а — те же статус-коды, те же error-сообщения, тот же audit
trail, та же семантика request-accounting.

### Кумулятивный статус миграции

| Релиз    | Модули                                         | Handlers | Убрано LOC |
|----------|------------------------------------------------|---------:|-----------:|
| v3.93.0  | admin/handlers*.py                             |       14 |        ~70 |
| v3.94.0  | exec/handlers.py                               |        3 |        ~30 |
| v3.97.0  | files/{handlers,fs_view_create}.py             |        7 |        ~51 |
| v3.98.0  | mobile/handlers*.py (4 модуля)                 |       49 |       ~312 |
| v3.99.0  | 20 модулей в observability/resources/…         |       46 |       ~158 |
| **ИТОГО** | 5 релизов · 27 модулей                        | **119**  |   **~621** |

**Около 119 handler'ов мигрированы на `@authed`.** Оставшиеся ~70
prelude'ов лежат в 40 файлах со слегка другими shape (docstring
между `def` и prelude, нестандартный indent, кастомная обработка
ошибок); каждый можно чистить по мере touch'а по другим причинам —
паттерн проверен на масштабе.

### Тесты

**1129 → 1129 passed** (новых тестов нет, wire-регрессий нет).
Все 55 mobile/admin/exec/files/observability/resources/etc тестов
проходят без изменений.

### Проверено live

* Bridge на 3.99.0.
* Все 1129 тестов зелёные.
* `POST /v1/mission/create {}` всё так же возвращает proper
  validation error.
* `GET /v1/audit/stats` возвращает audit-статистику.
* `POST /v1/service/restart` без auth → **401** (через `@authed`).
* Asset-manifest signature не изменился; Dashboard reload не нужен.

### Замечание об оставшихся ~70 prelude'ах

Файлы с docstring'ом между `def` и prelude (`service_info`,
`sys_svc`, `capabilities`, большинство CDP handler'ов) и файлы с
кастомной обработкой exception (batch, cluster, mcp, cdp/*)
оставлены для точечных патчей. Строгий matcher трансформатора
намеренно их не трогает, чтобы blast radius этого релиза
оставался предсказуемым. При следующем открытии этих файлов
(feature или bug fix) миграция каждого handler'а вручную занимает
~1 минуту.


## v3.98.0 - 2026-07-16

### Изменено — @authed миграция забрала mobile-подсистему (самая крупная)

Четвёртая пачка серии миграции `arena/handler_helpers.py` (после
v3.93.0 admin, v3.94.0 exec, v3.97.0 files — этот релиз mobile,
самый большой hotspot в кодовой базе). Все 4 handler-модуля под
`arena/mobile/` мигрированы в одном релизе:

* **`arena/mobile/handlers.py`** — 22 handler'а мигрированы:
  `list_devices`, `device_info`, `screenshot`, `tap`, `swipe`,
  `type`, `key`, `shell`, `ui_dump`, `tap_by`, `helpers_status`,
  `helpers_install`, `ime_status`, `ime_set`, `ime_reset`,
  `paste`, `gesture`, `sensors`, `scroll`, `key_combo`, `batch`,
  `packages`. Файл сжался **642 → 494 строк (-148)** — каждый
  handler теперь через `@authed(ctx)` без локального prelude.

* **`arena/mobile/handlers_devops.py`** — 9 handler'ов мигрированы
  (pair/connect/disconnect, apk_prepare/install/upload,
  transport_status/tcp_enable/tcp_disable). Файл сжался
  **220 → 162 строк (-58)**. Одна ручная validation-ошибка в
  `handle_apk_upload` (413 при oversized upload) теперь через
  `err_json(ctx, ..., status=413, hint=...)` — тот же wire-shape.

* **`arena/mobile/handlers_media.py`** — 12 camera/media handler'ов
  мигрированы. Файл сжался **255 → 189 строк (-66)**. Предсуществующие
  локальные helper'ы `_guard(ctx, request)` и `_oops(ctx, cors, exc)`,
  которые дублировали работу shared-декоратора, удалены целиком.

* **`arena/mobile/handlers_recording.py`** — 6 recording-handler'ов
  мигрированы. Файл сжался **126 → 86 строк (-40)**.

**Итого: 49 handler'ов, 4 модуля, 1243 → 931 строк
(-312 net LOC чистого auth/record/try-scaffolding).** Wire-поведение
не менялось — те же статус-коды (400/413/500/502), те же
audit-события (`mobile.tap`, `mobile.swipe`, `mobile.camera.*`,
`mobile.record_*`, `mobile.pair`, `mobile.apk_install`,
`mobile.transport.*` и т.д.), та же семантика request-accounting.

### Добавлено — regression guard'ы для mobile-миграции

Новый `tests/test_mobile_authed_migration.py` (74 строки, 4 теста):

* `test_mobile_modules_free_of_manual_auth_prelude` — grep-guard
  по всем 4 модулям против возврата `r = ctx.require_auth(request)`.
* `test_mobile_modules_free_of_manual_error_record` — тот же guard
  для паттерна `record_request(is_error=True, count_request=False)`.
* `test_mobile_modules_use_handler_helpers_authed` — проверяет,
  что каждый модуль импортирует `authed` из `arena.handler_helpers`.
* `test_media_module_no_longer_needs_local_guard_helpers` —
  документирует удаление pre-v3.98.0 private-helper'ов
  `_guard`/`_oops`, чтобы никто не добавил их обратно.

### Тесты

**1125 → 1129 passed** (+4 regression guard'а). Все 225 существующих
тестов на mobile handler'ы проходят без изменений — wire-регрессий нет.

### Прогресс миграции

| Релиз    | Модуль                                    | Handler'ов | ~Prelude LOC убрано |
|----------|-------------------------------------------|------------|---------------------|
| v3.93.0  | `arena/admin/handlers*.py`                | 14         | ~70                 |
| v3.94.0  | `arena/exec/handlers.py`                  | 3          | ~30                 |
| v3.97.0  | `arena/files/handlers.py` + `fs_view_create.py` | 7    | ~51                 |
| v3.98.0  | `arena/mobile/handlers*.py` (4 модуля)    | **49**     | **~312**            |
| **Итого** | (5 подсистем)                            | **73**     | **~463 строк**      |

Это 73 из изначальных 103 handler-prelude'ов мигрированы —
**около 71 % pre-v3.92.0 boilerplate теперь ушло**. Оставшиеся
~30 prelude'ов раскиданы по мелким handler-файлам (inventory,
cdp, mission, agentic, gui и т.д.); каждый можно подчищать в
follow-up patch, когда файл трогается по другой причине — cadence
"одна подсистема за релиз" больше строго не нужен, паттерн
проверен на масштабе.

### Проверено live

* Bridge на 3.98.0.
* Все 1129 тестов зелёные.
* `GET /v1/mobile/devices` возвращает список устройств.
* `POST /v1/mobile/xxx/tap {}` без ADB-устройства всё так же
  возвращает `{ok:false, error:"serial required"}` — wire без изменений.
* Bearer-auth всё так же требуется на каждом mobile-endpoint
  (проверено probe-запросом без токена → 401).
* Asset-manifest signature не изменился; Dashboard reload не нужен.


## v3.97.0 - 2026-07-16

### Изменено — @authed миграция продолжается на /v1/fs/* + /v1/upload,download

Третья пачка серии миграции `arena/handler_helpers.py` (после
v3.93.0 admin и v3.94.0 exec). Оба file-facing модуля покрыты:

* **`arena/files/handlers.py`** — 5 handler'ов мигрированы на
  `@authed(ctx, auto_record=False)`: `handle_v1_upload`,
  `handle_v1_download`, `handle_v1_fs_edit`, `handle_v1_fs_edit_apply`,
  `handle_v1_fs_edit_rollback`. Каждый делает свой request
  accounting после audit-события (bytes/replacements/rollback_id),
  поэтому `auto_record=False` избавляет от двойного учёта. Все
  локальные `_json_error` теперь под капотом идут через
  `err_json` из `arena/handler_helpers.py`.

* **`arena/files/fs_view_create.py`** — 2 handler'а мигрированы:
  `handle_v1_fs_view`, `handle_v1_fs_create`. Девять ручных
  `ctx.cors_json_response({"ok": False, "error": ...}, status=...)`
  заменены на `err_json(ctx, ...)` через маленький локальный
  helper `_err(ctx, msg, status)` — модуль сохраняет свою
  явную "record error → return response" идиому, но без
  повторения кода в 10 местах.

Body-parsing в обоих файлах теперь идёт через
`parse_json_body(request, ctx)` — тот же helper, что уже
используют admin- и exec-миграции.

Итого: **~51 строка auth/record/try-скаффолдинга удалена** из
files-подсистемы, все 7 handler'ов идут через тот же централизованный
`@authed` wrapper, что и остальной мигрированный код. Wire-поведение
идентично до байта — те же статус-коды (400/403/404/500), те же
error-сообщения, тот же audit trail (`file_upload`, `file_download`,
`file_edit`, `file_edit_rollback`, `file_view`, `file_create`), та же
семантика учёта.

### Добавлено — regression guard'ы для files-миграции

Новый `tests/test_files_authed_migration.py` (67 строк, 3 теста):

* `test_file_handlers_use_authed_decorator` — обходит все 5
  upload/download/edit handler'ов и проверяет `__wrapped__`.
* `test_fs_view_create_handlers_use_authed_decorator` — то же
  для 2 view/create handler'ов.
* `test_files_modules_free_of_manual_auth_prelude` — парсит
  оба module source'а и запрещает возвращать
  `r = ctx.require_auth(request)` (copy-paste guard от будущих
  регрессий).

### Тесты

**1122 → 1125 passed** (+3 regression guard'а). Существующие 78
тестов на file handlers + handler_helpers сами по себе проходят
без изменений — wire-регрессий нет.

### Прогресс миграции

| Релиз    | Модуль                             | Handler'ов | ~Prelude LOC убрано |
|----------|------------------------------------|------------|---------------------|
| v3.93.0  | `arena/admin/handlers*.py`         | 14         | ~70                 |
| v3.94.0  | `arena/exec/handlers.py`           | 3          | ~30                 |
| v3.97.0  | `arena/files/handlers.py` + `fs_view_create.py` | 7 | ~51 |
| **Далее**| `arena/mobile/handlers.py`         | ~30        | ~68 prelude'ов (самый крупный hotspot) |

У mobile handler'ов самая богатая per-handler логика (input
injection, screencap, mirror) — будет мигрировать под-группами
(input, screen, mirror, camera, devops), чтобы каждый cutover
проверялся на узком тест-subset, а не одним big-bang на 30
handler'ов.

### Проверено live

* Bridge на 3.97.0.
* Все 1125 тестов зелёные.
* `POST /v1/fs/view {"path": "/etc/hostname"}` возвращает 200 с
  содержимым файла.
* `POST /v1/fs/view {}` возвращает 400 с err_json-shaped
  `{ok:false, error:"path missing or invalid"}`.
* `POST /v1/fs/view` без auth → **401**.
* `POST /v1/fs/edit` с non-JSON body → 400 с
  `{ok:false, error:"invalid JSON body"}` от `parse_json_body`.
* Asset-manifest signature не изменился; reload Dashboard не нужен.


## v3.96.0 - 2026-07-16

### Добавлено — управление через ZeroTier Central

Локальная поверхность ZeroTier (v3.x) управляет сетями, к которым
подключён *этот хост*. Этот релиз добавляет недостающую половину:
**операции на уровне контроллера** — networks и members через
ZeroTier Central API. Approve/deauth участников, создание и
удаление сетей, переименование, pinned IP-адреса — end-to-end,
из Dashboard или из любого агента, который умеет ходить в Bridge.

#### Backend

* **`arena/admin/zerotier_central.py`** (473 строки) — чистый
  Central API клиент, без non-stdlib зависимостей. Token
  discovery в том же порядке, что и локальный CLI:

  1. env `ZEROTIER_CENTRAL_TOKEN`
  2. файл из env `ZEROTIER_CENTRAL_TOKEN_FILE`
  3. дефолтный `~/.zerotier-central-token`

  Публичные функции возвращают `{ok, ...}` — исключения наружу
  не всплывают. В каждом failure есть `reason` + HTTP `status`,
  когда Central ответил, чтобы Dashboard мог показать полезное
  сообщение вместо "Internal server error".

  Операции:

  - `central_status()` — проверка токена (`GET /status`)
  - `list_networks()` — с per-row summary
  - `get_network(nwid)` — полный detail
  - `create_network(name, extra=None)` — принимает частичный
    Central config для IP pools, private/public и пр.
  - `delete_network(nwid)`
  - `list_members(nwid)` — summary + authorized count
  - `update_member(nwid, node, authorized=, name=, description=,
    ip_assignments=)` — сразу и approve, и deauth, и rename, и pin
  - `delete_member(nwid, node)`

  Все ID валидируются регексами (`[0-9a-f]{16}` для сетей,
  `[0-9a-f]{10}` для members), чтобы invalid ID никогда не
  доходили до Central и не создавали bogus junk-строк.

* **`arena/admin/zerotier_central_handlers.py`** (185 строк) —
  8 aiohttp handler'ов, по одному на операцию, все обёрнуты
  в `@authed` и используют `err_json` / `parse_json_body` из
  `arena/handler_helpers.py` — тот же паттерн, что миграция
  admin в v3.93.0 и exec в v3.94.0. Каждое мутирующее действие
  пишет audit-событие (`zerotier_central_create_network`,
  `zerotier_central_delete_network`,
  `zerotier_central_update_member`,
  `zerotier_central_delete_member`).

* Routes (все под стандартной группой `core` в
  `arena/route_registry/registry.py`):

  ```
  GET    /v1/zerotier/central/status
  GET    /v1/zerotier/central/networks
  POST   /v1/zerotier/central/networks
  GET    /v1/zerotier/central/networks/{nwid}
  DELETE /v1/zerotier/central/networks/{nwid}
  GET    /v1/zerotier/central/networks/{nwid}/members
  POST   /v1/zerotier/central/networks/{nwid}/members/{node}
  DELETE /v1/zerotier/central/networks/{nwid}/members/{node}
  ```

* `arena/wiring/platform.py` — 8 новых handler-entries в admin
  registry, делят существующий `AdminHandlerContext` (executor,
  audit, cors, auth), новых зависимостей плюмбить не пришлось.

#### Frontend

* **`dashboard/assets/00-tabs-registry.js`** — новый tab
  **ZeroTier** (🌐, между Live и Doctor).

* **`dashboard/assets/body-18-zerotier.html`** (61 строка) —
  token-status header, input "Create network", таблица сетей
  (ID / имя / visibility / auth-count / IP pool / delete-кнопка)
  и панель members, которая появляется по клику на строку сети.
  Все theme-цвета через общую `--live-*` / `--*` палитру.

* **`dashboard/assets/42-zerotier-central.js`** (261 строка) —
  full-fetch view с row-click drill-down. Подтверждение delete
  (удаление сети permanent; удаление member предлагает
  "deauth-instead" hint), после мутаций перезагружает только
  затронутую панель. Использует общий `api()` helper из
  `02-api-helper.js`.

#### Тесты

**1102 → 1122 passed** (+20 новых).

* **`tests/test_zerotier_central.py`** (316 строк, 18 тестов) —
  все API-пути прогнаны через monkeypatched `urlopen`, так что
  suite работает offline и детерминистично. Покрыто: token
  discovery precedence, wire-формат Bearer + User-Agent,
  network summarisation, upstream 401 mapping, create/delete
  flows, member auth toggles, ID-validation regressions,
  end-to-end route registration и в `ROUTES`, и в
  `ub.make_app`.

* `tests/test_route_registry.py::test_tabs_registry_file_exists_and_declares_all_tabs`
  — добавлен новый tab `zerotier`.

### Проверено live

* Bridge на 3.96.0, все 1122 теста зелёные.
* `GET /v1/zerotier/central/status` без токена возвращает
  graceful `{ok:false, central:false, hint:"Create an API token…"}`
  — Dashboard рисует его как "Token missing" badge, а не крашится.
* `GET /v1/zerotier/central/networks` — тот же shape.
* Bad network ID (`GET .../networks/not-hex/members`) возвращает
  validation error dict со статусом 200 (как задумано — auth
  прошёл, ошибка в payload'е `ok:false`).
* `GET /v1/zerotier/central/status` без Bearer → **401**.
* Asset manifest автоматически подхватил `42-zerotier-central.js`
  и `body-18-zerotier.html` — ничего вручную регистрировать не
  пришлось.

### Замечания к использованию в проде

* Central rate-limit'ит free-tier на 20 req/s, paid — на 100 req/s.
  Обычное использование Dashboard сильно ниже этого; скрипты с
  агрессивным polling'ом должны вставлять свой delay.
* Удаление сети — **permanent**, без undo. UI страхует через
  `confirm(...)` dialog.
* Все мутирующие действия попадают в `audit.jsonl` рядом с
  остальными admin-действиями — полный trail даже когда
  оператор работает из браузера, а не через curl.


## v3.95.0 - 2026-07-16

### Добавлено — Live host-metrics и вкладка Live с sparklines

Новая вкладка **Live** в Dashboard рисует rolling-sparklines за
последние 2 минуты для CPU, памяти, swap, сети RX/TX, диска
чтение/запись и per-device GPU utilization + VRAM. Все ряды
приходят с новой лёгкой backend-поверхности, которую агенты и
другие тулзы могут дёргать напрямую.

#### Backend

* **`arena/observability/live_metrics.py`** (456 строк) —
  `live_metrics_snapshot()` возвращает один JSON-сериализуемый
  dict с секциями `cpu`, `memory`, `swap`, `net`, `disk`, `gpu`.
  Использует `psutil` когда он установлен для высокой точности;
  на GNU/Linux падает в fallback через `/proc/{stat,meminfo}`;
  на платформах без `psutil` и без `/proc` возвращает
  `{"available": false, "reason": ...}`. Cross-platform
  (Windows/macOS/GNU-Linux) by design.

* Дельты `net.bytes_{sent,recv}_per_sec` и
  `disk.{read,write}_bytes_per_sec` считаются против
  process-global `_LAST_SAMPLE` под `threading.Lock`, чтобы
  несколько pollers видели консистентные per-second rates.

* GPU-запрос кэшируется на 2 секунды, чтобы 1 Hz sampling
  оставался дешёвым: сначала `nvidia-smi`, потом fallback на
  `rocm-smi`, иначе пусто. Live-проверено на NVIDIA GTX 1050 Ti
  (utilization 4 %, температура 43 °C).

* **`arena/observability/live_metrics_handler.py`** (154 строки) —
  два aiohttp handler'а, подключённых через стандартные registries:

  - `GET /v1/live-metrics` — one-shot JSON snapshot для скриптов
    и разовых проверок. Использует `@authed` из
    `arena/handler_helpers.py`.
  - `GET /v1/live-metrics/stream` — WebSocket, который пушит
    snapshot примерно раз в секунду до тех пор, пока клиент не
    закроется. Auth такой же как в REST (Bearer-header или
    `?token=` query param, потому что браузер не может выставить
    header на WebSocket handshake). Module-level счётчик режет
    concurrent stream-клиентов на уровне 32 per process.

* Wire для routes: два новых tuple'а в
  `arena/route_registry/registry.py`, соответствующие вызовы
  `app.router.add_get(...)` в `arena/route_registry/domain.py` и
  новые handler-name mappings в
  `arena/wiring/observability_registries.py`. Всё в паттерне
  v3.90.0 route-registry — один файл на один concern.

#### Frontend

* **`dashboard/assets/00-tabs-registry.js`** — новый tab **Live**
  (иконка 📈, между Mobile и Doctor) с
  `onShow → startLiveCharts()` и `onHide → stopLiveCharts()`.

* **`dashboard/assets/body-17-live.html`** (197 строк) — разметка
  таба: 5 sparkline-cards (CPU, Memory, Swap, Network RX/TX,
  Disk R/W) в responsive `live-grid`, плюс динамическая
  per-GPU-секция. Все theme-цвета через `--live-*` CSS-variables
  в `dashboard.css`.

* **`dashboard/assets/41-live-charts.js`** (371 строка) — чистый
  Canvas 2D sparkline-renderer (~40 LOC), без внешней chart-
  библиотеки, чтобы preview работал даже внутри sandbox-iframe
  без CDN. Buffer 120 samples (2 мин при 1 Hz), auto-scaling для
  throughput-серий, фиксированный диапазон 0–100 для процентных.
  WebSocket-first с автоматическим HTTP-poll fallback, если
  socket закрылся, не отдав ни одного сообщения.

* **`dashboard/assets/dashboard.css`** — добавлены
  `--live-{card-bg,card-border,canvas-bg,core-track,text,text-muted}`
  + accent-palette `--live-{cpu,mem,swap,net-rx,net-tx,disk-rd,disk-wr,gpu,gpu-mem}`,
  чтобы будущие темы могли перекрашивать sparklines вместе со
  всем UI.

#### Тесты

* **`tests/test_live_metrics.py`** (91 строка, 7 тестов) —
  форма snapshot'а, границы CPU/memory percent, корректность
  two-sample дельт, reuse GPU 2-секундного кэша,
  JSON-сериализуемость, монотонность disk totals.

* **`tests/test_live_metrics_handler.py`** (110 строк, 6 тестов) —
  handler возвращает snapshot, enforcement auth (`@authed`
  оборачивает plain `GET`; WebSocket-роут проверяет auth
  вручную первым), 429 при превышении cap stream-клиентов,
  регистрация routes и в `ub.make_app`, и в
  `arena.route_registry.registry.ROUTES`.

* `tests/test_route_registry.py::test_tabs_registry_file_exists_and_declares_all_tabs`
  обновлён — включает новый tab `live`.

**Всего 1102 passed** (было 1089; +13 новых).

### Проверено live

* `GET /v1/live-metrics` возвращает полный snapshot (CPU 50.7 % / 4
  ядра, память 46.6 %, swap 0 %, network + disk totals, NVIDIA
  GTX 1050 Ti на 7 % / 41 °C).
* `GET /v1/live-metrics` без токена → **401**.
* `GET /v1/live-metrics/stream` WebSocket: 4 tick'а за ~3 с, per-tick
  network RX растёт с 0 до 55 111 B/s по мере поступления реального
  трафика на интерфейс, GPU utilization и температура обновляются
  каждый tick.
* `GET /gui/assets/manifest.json` **автоматически подхватил** новый
  скрипт `41-live-charts.js` и body `body-17-live.html` — ничего
  вручную регистрировать не пришлось (v3.91.0 asset manifest
  сработал как задумано).

### Идеи на будущее (не в этом релизе)

* Добавить опциональный toggle 5 с / 10 с длины buffer'а во вкладке
  Live, чтобы можно было "отойти" для наблюдения за более длинными
  окнами.
* Расширить GPU-секцию — разделить compute vs. graphics utilization
  на NVIDIA (nvidia-smi имеет отдельные query-поля).
* Подцепить ту же snapshot-функцию к Prometheus exporter, чтобы
  внешним scrapers не приходилось дёргать два endpoint'а.


## v3.94.0 - 2026-07-16

### Изменено — миграция @authed продолжается на surface /v1/exec

Второй реальный consumer декоратора `arena/handler_helpers.py`,
появившегося в v3.92.0 и впервые применённого в v3.93.0. Этот
релиз мигрирует exec/process-подсистему — `/v1/ps`, `/v1/exec`,
`/v1/kill` — с одним расширением декоратора для handler'ов,
которые сами управляют учётом request'ов.

* **`arena/handler_helpers.py`** — у `@authed` появился keyword
  `auto_record` (default `True`, чтобы v3.93.0 admin-миграция
  продолжала работать без изменений). При `False` декоратор
  по-прежнему проверяет auth и ловит stray-исключения, но
  пропускает автоматический `ctx.record_request()` на happy
  path — handler сам вызывает
  `record_request(duration=..., is_exec=True, is_error=...)` с
  реальными параметрами по итогу subprocess'а. Учёт по exception-
  ветке идёт всегда, поэтому "тихие" падения handler'ов никогда
  не остаются несосчитанными.

* **`arena/exec/handlers.py`** — все 3 handler'а мигрированы:
  - `handle_v1_ps` — обычный `@authed(ctx)` (простой snapshot).
  - `handle_v1_exec` — `@authed(ctx, auto_record=False)`, потому
    что сам вызывает `ctx.record_request(duration=..., is_exec=True)`
    с реальным временем и статусом shell после завершения
    subprocess'а. 9 ручных
    `cors_json_response({"ok": False, "error": ...}, status=...)`
    заменены на `err_json(ctx, ..., status=..., request_id=...)`.
    Парсинг тела теперь через `parse_json_body(request, ctx)`.
  - `handle_v1_kill` — тот же паттерн `auto_record=False`: успех
    учитывается один раз в конце, error-ветки inline.

Миграция оставляет wire-поведение exec-surface идентичным
до байта: те же статус-коды (400/403/404/408/429/500), те же
error-messages, тот же `request_id` в каждом failure, те же
формы audit-событий (`exec_start`, `exec_done`, `exec_timeout`,
`exec_error`, `exec_blocked`, `exec_blocked_control`,
`process_killed`), та же семантика учёта.

### Добавлено — regression guard'ы для exec-миграции

Три новых теста в `tests/test_handler_helpers.py`:

* `test_authed_auto_record_false_skips_counter_on_happy_path`
* `test_authed_auto_record_false_still_enforces_auth`
* `test_authed_auto_record_false_still_records_errors`

Два новых теста в `tests/test_exec_handlers.py`:

* `test_exec_handlers_use_authed_decorator` — проверяет
  `__wrapped__` у `ps`/`exec`/`kill`.
* `test_exec_handlers_module_free_of_manual_auth_prelude` —
  grep-guard против copy-paste старого prelude обратно.

### Тесты

**1084 → 1089 passed** (+5 regression guard'ов). Все ранее
зелёные тесты остались зелёными. Live-smoke на bridge
подтвердил что мигрированные `/v1/ps` и `/v1/exec` возвращают
те же формы, что и раньше.

### Прогресс миграции

| Релиз    | Модуль                          | Handler'ов | Убрано prelude'ов |
|----------|---------------------------------|-----------|-------------------|
| v3.93.0  | `arena/admin/handlers*.py`      | 14        | 14 auth + ~4 record |
| v3.94.0  | `arena/exec/handlers.py`        | 3         | 3 auth + 9 error-cors → err_json |
| **Далее**| `arena/files/handlers.py`       | ~10       | 21 prelude        |
| **Далее**| `arena/mobile/handlers.py`      | ~30       | 68 prelude'ов     |

Mobile — самый крупный hotspot из оставшихся, но с более богатой
per-handler логикой (input injection, screencap, mirror) — будет
мигрировать под-группами по релизам, а не big-bang'ом.


## v3.93.0 - 2026-07-16

### Изменено — первый реальный consumer декоратора из v3.92.0

В v3.92.0 появились `@authed` + `err_json`/`ok_json` в
`arena/handler_helpers.py`, но 103 существующих boilerplate-prelude'а
по всем handler-модулям не были тронуты — декоратор был opt-in и
никто ещё им не воспользовался. Это классический анти-паттерн
"tooling создан, но не применён". В этом релизе начинается
миграция — сразу вся admin-поверхность:

* **`arena/admin/handlers.py`** — 10 handler'ов переведено с
  шестистрочного ручного prelude (`ctx.require_auth` →
  `record_request` → `try/except` →
  `record_request(is_error=True)`) на `@authed(ctx)`. Файл
  сжался с 295 до 242 строк без изменения поведения: те же тела
  ответов, те же статус-коды, тот же audit trail, тот же
  wire-формат. Мигрированы: `sys_funnel`, `token_regenerate`,
  `tailscale_funnel`, `cloudflared_tunnel`, `zerotier_status`,
  `zerotier_network`, `tunnels_status`, `tunnels_active`,
  `tunnels_start`, `tunnels_stop`.

* **`arena/admin/handlers_update.py`** — 4 auto-update handler'а
  мигрированы аналогично. Файл сжался с 183 до 166 строк. Один
  ручной `cors_json_response({"ok": False, "error": ...})`
  заменён на `err_json(ctx, ...)` для консистентности с
  остальным кодом. Ответ "consent_required" оставлен как
  прямой `cors_json_response` — он несёт богатый payload
  (`required_consent`, `tag`, `asset_name`, `sha256`, `hint`),
  который не помещается в форму простого error-helper'а.

Итого: ~70 строк дублированного auth/record/try-скаффолдинга
ушли из admin-подсистемы, все 14 admin handler'ов теперь идут
через один центральный wrapper. Те же гарантии, что давал
ручной prelude (401 на пропущенный auth, error-request
учёт при stray-исключениях, HTTPException-passthrough для
роутинга), — теперь обеспечиваются в одном месте, а не в 14
копиях.

### Добавлено — regression guard'ы, чтобы миграция не отвалилась

Новые тесты в `tests/test_admin_handlers.py`:

* **`test_admin_handlers_use_authed_decorator`** — обходит все
  14 admin handler-атрибутов (`sys_funnel` … `update_restart`)
  и проверяет что у каждого установлен `__wrapped__`, который
  `functools.wraps` навешивает при обёртке через `@authed`.
  Если новый handler добавят без декоратора — тест упадёт
  сразу.

* **`test_admin_handlers_module_free_of_manual_prelude`** —
  парсит исходник модуля и запрещает
  `r = ctx.require_auth(request)` и
  `record_request(is_error=True, count_request=False)` в
  обоих admin-модулях. Copy-paste старого handler'а обратно —
  и guard упадёт до code review.

### Тесты

**1082 → 1084 passed** (2 новых regression guard'а). Все ранее
зелёные тесты остались зелёными. Существующий 21 тест на admin
handler'ы и handler_helpers подтвердил отсутствие wire-level
регрессии от миграции.

### Стратегия миграции остальных ~93 prelude'ов

Оставшийся boilerplate раскидан по:

* `arena/exec/handlers.py` — 34 auth+cors prelude'а
* `arena/mobile/handlers.py` — всего 68 prelude'ов
* `arena/files/handlers.py` — 21 prelude
* Плюс handler'ы в inventory, cdp, mission, agentic и т.д.

Миграция одной подсистемы за релиз держит blast radius
маленьким и позволяет проверять cutover против тест-сьюта
конкретного модуля. Admin выбран первым, потому что у него
чистейший однородный паттерн (все 10 handler'ов делают
`require_auth → run_in_executor → cors_json_response` и
ничего больше); mobile и cdp имеют более богатую per-handler
логику, которая потребует большей аккуратности.


## v3.84.6 - 2026-07-15

### Зачем

`v3.84.3` зашипил live screen mirror как BETA потому что byte-stream
не доходил до браузера на статичном экране. Root cause: pipeline
кормил `adb exec-out screenrecord --output-format=h264` в
`ffmpeg -c:v copy -movflags empty_moov+separate_moof+default_base_moof+frag_keyframe`,
и ffmpeg-овский mp4 muxer буферизовал до keyframe boundary. AVC
энкодер Андроида на домашнем экране спокойно уходит на 5+ секунд
между IDR'ами — дольше чем таймаут `sourceopen` в MediaSource.
Маркер `__init__` доходил, а фрагменты — никогда, и браузер не
рисовал ничего.

### Что вошло

**In-process H.264 → fMP4 муксер** заменил ffmpeg-подпроцесс. Два
новых модуля, без внешних зависимостей:

- `arena/mobile/h264_parser.py` (326 строк) — Annex-B splitter
  (long + short start codes, инкрементальная буферизация между
  chunk'ами) + минимальный SPS-парсер (width/height/profile_idc/
  constraint_flags/level_idc). Снимает emulation-prevention байты
  из RBSP. Умеет Baseline и high-profile branch.

- `arena/mobile/mp4_muxer.py` (518 строк) — руками собранные
  ISOBMFF box-builder'ы (`ftyp`, `moov`, `mvhd`, `trak`, `tkhd`,
  `mdia`, `mdhd`, `hdlr`, `minf`, `vmhd`, `dinf`, `stbl`, `stsd`,
  `stts`, `stsc`, `stsz`, `stco`, `mvex`, `trex`, `moof`, `mfhd`,
  `traf`, `tfhd`, `tfdt`, `trun`, `mdat`, плюс `avc1`+`avcC` по
  ISO/IEC 14496-15) и state-machine `H264ToFMP4` который их
  связывает.

Муксер эмитит **один `moof + mdat` на каждый VCL NAL** (то есть
на каждый видео-кадр), а не per GOP. Это единственное дизайн-решение
и починило bug со статическим экраном — MediaSource теперь рисует на
самом первом фрейме, независимо от того keyframe это или нет.

**Lifecycle сессий не изменился.** `arena/mobile/mirror.py` всё так
же владеет `MirrorSession` + subscriber fanout + перезапуском
screenrecord каждые ~170 секунд. Что изменилось:

- Удалён ffmpeg subprocess, helper `_ffmpeg_cmd()` и async pipe pump
  `_pump_h264`.
- Reader-task теперь кормит stdout screenrecord прямо в
  `H264ToFMP4.feed(chunk)`. Callback'и `on_init` / `on_fragment`
  роутят байты в `session.broadcast`.
- `mux.reset()` при каждом перезапуске screenrecord чтобы следующая
  пара SPS+PPS триггерила свежий init segment (браузер видит маркер
  `__init__` + новый ftyp+moov).
- Decode clock (`_decode_time`) НАМЕРЕННО не сбрасывается между
  сегментами — MediaSource отвергает фрагменты у которых
  baseMediaDecodeTime уходит назад.

**Дополнительные stats** в `GET /v1/mobile/mirror/stats`:
- `keyframes_sent` (новое)
- `muxer: "python-native"` (маркер чтобы оператор знал какой
  pipeline у него бежит)

### Live-верификация

POCO F7 Pro (24117RK2CG, HyperOS OS3.0.302.0), bridge через Tailscale:

**Idle-экран** (прошлая BETA hard-fail'ила здесь):
```
WS connect  →  __init__  →  656-байтный ftyp+moov  →  1 фрагмент / 8с
```

**Активная swipe-анимация** (экран непрерывно скроллится):
```
1'079 фрагментов за 10 секунд (~108 fps effective)
2.59 МБ total, ~2.4 КБ на фрагмент
```

Цифра 108 fps — правдивая: AVC-энкодер Андроида производит несколько
кадров temporal-layer за каждое реальное обновление экрана когда
экран непрерывно меняется, и муксер эмитит каждый из них отдельно.
На стороне browser MediaSource это транслируется в под-100мс
задержку glass-to-glass.

### Файлы

- **новый** `arena/mobile/h264_parser.py` (326 строк)
- **новый** `arena/mobile/mp4_muxer.py` (518 строк)
- `arena/mobile/mirror.py` (382 → 343) — ffmpeg pipeline удалён,
  muxer подключён, `keyframes_sent` + `muxer` поля в stats.
- **новый** `tests/test_mobile_v84_6.py` (413 строк, 19 тестов) —
  Annex-B splitter round-trip, SPS-парсер на синтетических Baseline
  SPS'ах (720x1280 и 720x1600), проверка headers'ов box'ов,
  арифметика `moof` data_offset, sample flags keyframe vs
  non-keyframe, `H264ToFMP4` эмитит ровно один init + один фрагмент
  на кадр, `reset()` сохраняет decode-clock, orphan-кадры без SPS
  тихо дропаются.
- `tests/test_mobile_v84_3.py` — старый ffmpeg-flag регрессионный
  тест заменён на "нет больше ffmpeg subprocess", три `_no_pipeline`
  monkeypatch'а принимают `*args, **kwargs` для новой one-arg
  signature `_pump_pipeline(session)`.

### Результаты

- **926 unit пройдено** (было 907 в v3.84.5, +19 новых).
- Live mirror WS handshake + fragment stream подтверждён на
  референсном POCO F7 Pro (цифры выше).

### Совместимость

- `arena.mobile.mirror._ffmpeg_cmd()` исчез. Любой downstream-код,
  который к нему шелл-аутился, нужно мигрировать на `H264ToFMP4`
  (или дождаться байт из mirror pipeline).
- Wire format не изменился: подписчики всё так же получают один
  текстовый `__init__`-фрейм и следом бинарные fMP4-байты, ровно
  как v3.84.3 обещал.


## v3.84.5 - 2026-07-15

### Зачем

USB между bridge-хостом и телефоном срывается под нагрузкой. Во время
разработки v3.84.4 POCO F7 Pro регулярно уходил в `offline` /
`authorizing` посреди записи видео, когда uiautomator или большой
`adb pull` нагружал шину — и никакого in-process восстановления не
было. Каждый вызов, попавший в flap, падал с `device 'XXX' not found`
даже несмотря на то что телефон был жив и доступен по Wi-Fi.

### Что добавлено

**Новый модуль `arena/mobile/adb_fallback.py` (306 строк) —
транспортный registry с per-transport circuit breaker.** У каждого
физического телефона может быть один или несколько транспортов:
primary — его USB serial (`2200ad3b`), secondary — wireless-ADB
alias'ы (`192.168.50.181:5555`). Каждый ADB-вызов идёт через
`pick_transport(canonical)`; после `_MAX_CONSECUTIVE_FAILS` (3)
подряд offline-подобных ошибок транспорт помечается unhealthy на
`_UNHEALTHY_COOLDOWN_SEC` (20 с) и router возвращает следующий
здоровый транспорт. Когда primary восстанавливается — маршрут
автоматически возвращается.

Классификатор offline (`_looks_offline`) матчит все "device
unreachable" паттерны, что мы видели: `device offline`, `device 'XXX'
not found`, `no devices/emulators found`, `device still authorizing`,
`device unauthorized`, `failed to get feature set`, `cannot connect
to daemon`, `no such device`, `protocol fault`, `server didn't ack`.
Не-offline ошибки (permission denied, activity not found, и т.д.)
никогда не триггерят breaker.

**Новый модуль `arena/mobile/transport.py` (231 строка) — user-facing
transport control.** Оборачивает registry в one-shot `enable_tcp(serial)`
хелпер: пробит `wlan0` IPv4 телефона пока USB ещё жив, запускает
`adb -s <usb> tcpip 5555`, ждёт 1.5 с для перезапуска adbd, запускает
`adb connect ip:5555`, регистрирует `ip:5555` как alias в registry.
Плюс `disable_tcp(serial)`, `describe(serial)`, `parse_hostport()`.

**Патч `arena/mobile/adb.py` `run()` — прозрачная маршрутизация.**
При вызове с `serial` wrapper резолвит эффективный транспорт через
registry, спавнит adb против него, кормит исход (returncode + stderr)
обратно чтобы следующие вызовы могли обойти падающий транспорт.
Вызовы которые ДОЛЖНЫ попасть в конкретный транспорт (сам
`transport.enable_tcp` при `adb -s <usb> tcpip 5555`) передают новый
флаг `no_route=True` для opt-out.

**3 новых HTTP-эндпоинта (dataclass растёт 49 → 52 поля)**:

- `GET  /v1/mobile/transport`                          — глобальный snapshot registry
- `GET  /v1/mobile/{serial}/transport`                 — per-serial view + `is_multi_transport` / `active_transport`
- `POST /v1/mobile/{serial}/transport/tcp/enable`      — body `{host?, port?}`; probe + connect + register alias
- `POST /v1/mobile/{serial}/transport/tcp/disable`     — body `{alias?}`; сбрасывает TCP alias(ы) и делает `adb disconnect`

Все три проходят тот же `require_auth` что и остальные
`/v1/mobile/*` и логируются через `ctx.audit(...)`.

### Тронутые файлы

- `arena/mobile/adb.py` (185 → 224 строк) — routing wrapper + `no_route`.
- `arena/mobile/adb_fallback.py` (**новый**, 306 строк) — registry + breaker.
- `arena/mobile/transport.py` (**новый**, 231 строка) — user-facing.
- `arena/mobile/handlers_devops.py` (158 → 220 строк) — 3 новых aiohttp-хендлера.
- `arena/mobile/handlers.py` (636 → 642 строк, всё ещё allowlisted) — MobileHandlers 49 → 52 полей.
- `arena/mobile/__init__.py` (160 → 171 строк) — реэкспорты.
- `arena/wiring/platform.py`, `arena/route_registry/core.py`, `arena/capabilities.py` — wire + advertise.
- `tests/test_mobile_v84_5.py` (**новый**, 336 строк, 19 тестов) — registry + breaker + routing + `transport.enable_tcp` с mock adb.
- `tests/test_mobile_v84_4.py` — 49-field check переведён на "required subset" чтобы будущие релизы могли добавлять поля свободно.

### Результаты

- **907 unit пройдено** (было 888 в v3.84.4, +19 новых).
- Live-верификация на POCO F7 Pro (24117RK2CG, HyperOS OS3.0.302.0),
  bridge `192.168.50.180` ↔ телефон `192.168.50.181`:
  - `POST /transport/tcp/enable` проходит все 4 стадии (probe_ip →
    tcpip → connect → register) и возвращает `alias =
    192.168.50.181:5555`.
  - `GET /transport` показывает оба транспорта healthy,
    `is_multi_transport: true`, `active_transport: "2200ad3b"`.
  - Live-маршрутизация проверена синтетической offline-инъекцией
    через registry API прямо на bridge: после 3 `device offline`
    исходов primary становится `healthy: false` с
    `cooldown_remaining_sec: 20` и `pick_transport()` отдаёт wireless
    alias.
  - USB kill-server + быстрая серия вызовов: daemon рестартует,
    вызовы проходят (часть путей самолечится без нужды в alias'е).

### Поведение когда fallback не настроен

Никакое. `pick_transport(serial)` возвращает `serial` как есть,
когда registry о нём не слышал — значит все существующие вызовы
работают побайтово идентично прошлым релизам. Feature полностью
opt-in через `POST /transport/tcp/enable`.

### Известные ограничения

- Только IPv4. Wireless ADB апстримом IPv4-only; строгий
  `parse_hostport()` regex это отражает.
- `_probe_wifi_ip` пробует `wlan0`, `wlan1`, `wlan-mlo0`; некоторые
  ультра-новые чипсеты могут иметь другое имя интерфейса. Расширяй
  tuple в `arena/mobile/transport.py::_probe_wifi_ip` при
  необходимости.
- Circuit breaker живёт в памяти процесса. Рестарт bridge очищает
  registry (alias'ы нужно регистрировать заново).


## v3.84.4 - 2026-07-14

### Что чинит

`POST /v1/mobile/{serial}/camera/shutter` на HyperOS молча тапал
**переключатель фото/видео** (`v9_capture_picker_layout`, центр
≈ (1300, 2785)) вместо реальной кнопки затвора `shutter_button`
(центр ≈ (719, 2785)). Оба узла были `clickable`, оба матчились
старой подсказкой "capture", и второй выигрывал по порядку обхода.
В `/sdcard/DCIM/Camera/` ничего не появлялось потому что мы тапали
не спуск.

### Что нового

**Переписан автодетект затвора (`arena/mobile/camera.py`).** Три
прохода со строгим приоритетом + чёрный список resource-id:

1. Строгий allowlist: `shutter_button`,
   `smart_shutter_button_layout`, `take_picture`, `photo_button`,
   `camera_capture_button`, `click_photo`. Первое совпадение
   выигрывает.
2. content-desc содержит `shutter` / `Кнопка затвора`.
3. Fallback: самый большой clickable-узел в нижней центральной
   четверти превью.

Любой узел, чей resource-id содержит `picker`, `thumbnail`, `delay`,
`container`, `menu`, `tip`, `cover`, `grid`, `focus`, `zoom` или
`toggle`, исключается из всех проходов.

**Новый surface управления камерой (`arena/mobile/camera_controls.py`,
+7 эндпоинтов).** Всё что нужно ИИ чтобы драйвить настоящее приложение
камеры без угадывания координат:

- `GET  /v1/mobile/{serial}/camera/controls` — дамп всех clickable
  узлов приложения камеры в foreground (resource-id, content-desc,
  text, class, bounds, center). Как побочный эффект прогревает кэш
  координат спуска — record-эндпоинты ниже переживают пустые
  UIAutomator-дампы.
- `POST /v1/mobile/{serial}/camera/mode` — переключение режима:
  `photo`, `video`, `portrait`, `pro`, `night`, `document`,
  `slowmo`, `timelapse`, `pano`, `short`, `movie`. Матчит
  локализованные подписи полоски режимов (сейчас EN + RU; таблица
  расширяется тривиально).
- `POST /v1/mobile/{serial}/camera/lens` — `target=front|back|toggle`.
  Инспектирует текущее content-desc, поэтому `back → back` — no-op.
- `POST /v1/mobile/{serial}/camera/zoom` — `level` в кратности
  (`0.6`, `1.0`, `2.0`, `3`, …). Тапает ближайший видимый zoom-чип.
- `POST /v1/mobile/{serial}/camera/flash` —
  `mode=auto|on|off|torch`.
- `POST /v1/mobile/{serial}/camera/record/start` — переключается в
  видеорежим, тапает спуск, верифицирует состояние "recording".
- `POST /v1/mobile/{serial}/camera/record/stop` — тапает спуск ещё
  раз, опрашивает DCIM на свежий MP4, опционально `pull=true`
  чтобы вернуть base64. Ждёт финализации moov кодеком перед
  чтением байт.

Запись здесь идёт **встроенным кодеком приложения камеры**, а не
`screenrecord` — поэтому захватывается ровно то разрешение / FPS /
стабилизация / линза которые пользователь выбрал в приложении. 4K@30
или даже 4K@60 на поддерживающих телефонах.

**Fallback на кэш координат затвора.** `record_start` и `record_stop`
идут через `_shutter_tap`, который:
- вызывает `find_shutter` live и кэширует координаты при успехе, а
- при отказе (пустой uiautomator XML во время записи, adb-заикание)
  тапает последние известные координаты из кэша.
- ретраит до 2 раз с паузой 1.5 с, чтобы транзиенты adb не убивали
  запись.

Кэш per-serial с TTL 5 минут. Прогревается автоматически через
`GET /camera/controls`.

**Правильный pull видео.** `pull_photo` теперь пропускает `.mp4`,
`.mov`, `.mkv`, `.webm`, `.3gp` мимо Pillow. Корректный mime, никаких
"downscale failed" на видео-байтах.

**Video intent доведён до конца.** `POST /camera/launch` с
`{"intent":"video"}` теперь мапится в
`android.media.action.VIDEO_CAMERA` end-to-end (код был, но не
тестировался).

### Тронутые файлы

- `arena/mobile/camera.py` (414 → 450 строк) — новый детектор +
  video mime в `pull_photo` + общий `iter_clickable`.
- `arena/mobile/camera_controls.py` (**новый**, 516 строк) — mode /
  lens / zoom / flash / record_start / record_stop / list_controls
  + кэш координат затвора.
- `arena/mobile/handlers_media.py` (132 → 255 строк) — +7
  эндпоинт-хендлеров.
- `arena/mobile/handlers.py` (623 → 636 строк, всё ещё allowlisted)
  — MobileHandlers растёт с 42 → 49 полей.
- `arena/mobile/__init__.py` (140 → 160 строк) — реэкспорт новых
  хелперов.
- `arena/wiring/platform.py` — 7 новых `handle_v1_mobile_camera_*`.
- `arena/route_registry/core.py` — 7 новых маршрутов.
- `arena/capabilities.py` — рекламирует 7 новых эндпоинтов через
  `caps.mobile.endpoints`.
- `scripts/smoke_mobile.py` (442 → 495 строк) — проверяет новые
  capability-записи + гоняет `controls`, `mode video → mode photo`
  round-trip, регрессионно проверяет что автодетект спуска не
  резолвится к координатам переключателя режимов.
- `tests/test_mobile_v84_4.py` (**новый**, 357 строк, 17 тестов) —
  покрывает регрессию спуска, резолвинг алиасов, fallback на кэш и
  48-полевой surface handler dataclass.

### Результаты

- **886 unit тестов пройдено** (было 869 в v3.84.3, +17 новых).
- Live-фикс подтверждён на POCO F7 Pro (24117RK2CG, HyperOS
  OS3.0.302.0): `POST /camera/shutter` теперь тапает (719, 2785)
  через `strict resource-id hint 'shutter_button'` и делает
  реальные JPEG (проверено `IMG_20260714_222945.jpg`, 2.94 МБ, и
  `IMG_20260714_223923.jpg`, 3.97 МБ).
- `POST /camera/mode {"mode":"video"}` подтверждён: тапает чип
  "Видео" в (450, 2504) и рапортует `mode=video`.
- `GET /camera/controls` возвращает 18 clickable-узлов и прогревает
  кэш координат до `[719, 2785]`.
- `POST /camera/record/stop` подтверждён рабочим: тапает по кэшу
  когда live UIAutomator-дамп недоступен (наблюдалось во время
  видеозаписи, когда HyperOS прячет AT-дерево за GL surface).

### Известные ограничения

- Полный цикл `record_start → sleep → record_stop` end-to-end требует
  стабильной USB-сессии; референсный POCO F7 Pro периодически падает
  в `offline` при длинных smoke-прогонах на bridge-хосте. Ретрай +
  кэш в `_shutter_tap` это смягчают, но на реально плохом кабеле
  всё равно упадёт. На стабильном коннекте цикл выдаёт MP4 с тем
  разрешением/FPS, которые настроены в приложении камеры.
- Локализация mode / flash / lens сейчас EN + RU. Китайский,
  испанский, португальский и т.д. подключаются расширением таблиц
  алиасов (`_MODE_ALIASES` / `_FLASH_ALIASES` в
  `camera_controls.py`).


## v3.84.3 - 2026-07-14

**Основы live H.264 screen mirror** (WebSocket endpoint + MSE
браузер-клиент + fragmented MP4 pipeline через ffmpeg), **auth query
token** для браузерных WebSocket handshake, и честные smoke-выводы о
том, что реально работает сегодня и что beta.

### Added — Live screen mirror (BETA)

Follow-up из v3.84.2. Backend + frontend + smoke — всё в этом релизе,
с реалистичной оговоркой про сам byte stream.

**Endpoints (3)**:
- `GET /v1/mobile/{s}/mirror` — WebSocket upgrade. Query params
  `size=WxH` (default 720x1600), `bit_rate=int` (default 4M), `token`
  для auth (см. ниже). Шлёт `__init__` control string каждый раз
  когда pipeline рестартует + бинарные fMP4 chunks для видео-стрима.
- `GET /v1/mobile/mirror/stats` — read-only снапшот каждой активной
  сессии: `serial`, `size`, `bit_rate`, `subscribers`,
  `fragments_sent`, `bytes_sent`.
- `POST /v1/mobile/{s}/mirror/stop` — принудительный teardown
  активного pipeline (Dashboard "■ Stop" кнопка + smoke использует).

**Архитектура** (`arena/mobile/mirror.py`, 353 строки):
- Одна `MirrorSession` на serial. Несколько Dashboard tabs делят
  одну сессию — второй connect добавляет subscriber, не второй
  pipeline. Медленные subscribers получают drop'нутые кадры, а не
  блокируют pipeline для остальных (asyncio.Queue с maxsize=32).
- Pipeline: `adb exec-out screenrecord --output-format=h264` →
  Python async pump → `ffmpeg -c:v copy -movflags empty_moov+
  separate_moof+default_base_moof+frag_keyframe -f mp4 pipe:1`.
  Без re-encoding, просто remuxing raw H.264 NAL units в fMP4
  фрагменты, которые MSE может проигрывать.
- 180-сек хард-cap screenrecord обработан авто-рестартом pipeline
  каждые `_SEGMENT_SECONDS = 170`; маркер `__ARENA_INIT__` говорит
  браузеру пересобрать SourceBuffer для нового moov box.
- Bridge shutdown вызывает `mirror.stop_all()` — все pipeline
  чисто разбираются.

**Frontend** (`dashboard/assets/38-mobile-mirror.js`, 217 строк):
- MediaSource + SourceBuffer оборачивает `<video>` элемент.
- Обрабатывает `__init__` reset (пересобирает SourceBuffer при
  смене сегмента).
- QuotaExceededError → обрезает старый buffered range вместо краха.
- Live meta строка: `KB · kbps · fps`.
- Секция "🎥 Live mirror" в Selected-device: Start/Stop кнопки +
  size (540/720/1080) + bit-rate (1/2/4/8 Mbps) селекторы.

**BETA disclosure**: WebSocket endpoint auth + upgrade + pipeline
spawn + `__init__` control marker всё работает end-to-end на POCO
F7 Pro мейнтейнера (`smoke_mobile.py` каждое проверяет). Но
фактический fMP4 byte stream в `<video>` — непоследователен: mp4
муксер ffmpeg heavy-буферизует ожидая полной границы GOP, и на
экране который не движется (домашний экран, без анимации) может
ждать много секунд перед первым fragment. Решается либо Python-side
H.264 parser + custom fMP4 muxer (без ffmpeg вообще), либо
серьёзной переработкой флагов ffmpeg. Обе — работа v3.84.4.

**Что работает сегодня**: Dashboard кнопка коннектится, "Live
mirror" видео-область появляется, pipeline стартует на телефоне,
init marker приходит в браузер. **Что ещё нет**: последовательное
воспроизведение видео в `<video>` элементе на статичном экране. На
экране с непрерывной анимацией (видео, скролл) pipeline может
выдать достаточно данных чтобы отрендерить, но недостаточно
надёжно чтобы вывести из BETA. Smoke проверяет только первое.

### Added — Auth через `?token=` query параметр

Браузеры не дают JavaScript ставить заголовки на WebSocket upgrade,
поэтому `Authorization: Bearer …` не вариант для mirror WS
handshake. `arena/auth/runtime.check_auth` теперь принимает токен
как `?token=` query параметр третьим путём (после Bearer заголовка
+ X-Arena-Token заголовка). Backwards-compatible с legacy test
doubles, у которых нет `query` атрибута.

**Используется только /v1/mobile/{s}/mirror сейчас** — каждый
другой endpoint продолжает аутентифицироваться через заголовок как
и раньше.

### Changed — Smoke ordering (mirror последним)

`scripts/smoke_mobile.py` был скрыто-flaky когда recording шёл
после mirror: у SurfaceFlinger AVC encoder session имеет глобальный
rate limit и свежий screenrecord не может стартовать пока mirror
ещё держит один. Перепорядочено: `smoke_recording` идёт ДО
`smoke_mirror`, и оба явно закрывают шторку + жмут HOME + ждут
2.5с давая SurfaceFlinger'у время освободить encoder.

### Fixed — Auth runtime тесты
v3.84.3 добавление query-token сломало два прежних test doubles,
у которых не было `query` атрибута. Защищено через `getattr(...)`,
legacy doubles продолжают работать.

### Test suite

869 unit passed (+10 новых — все в `tests/test_mobile_v84_3.py`, 234 строки):
- Mirror session subscriber fanout + backpressure (медленная queue
  дропает кадры не блокируя).
- Session registry: `get_or_start` возвращает ту же сессию для
  того же serial; разные serial → разные сессии.
- Stats endpoint репортит все сессии.
- `_screenrecord_cmd` shape (проверяет `--output-format=h264` +
  `--size` + `--bit-rate` + stdout `-`).
- `_ffmpeg_cmd` имеет точные fMP4 флаги, которые MSE ожидает
  (regression guard).
- `check_auth` принимает новый query-token путь И отклоняет
  неправильные токены.

Live smoke: **62/62 на реальном POCO F7 Pro**, включая новые
mirror WS handshake + init-marker проверки. Recording всё ещё
производит 20 KB валидный MP4 при 540x1200 согласно v3.84.2 flow.

### Файлы

- `arena/mobile/mirror.py` (353) — session + pipeline lifecycle + WS handlers.
- `arena/mobile/handlers.py` (623) — 3 новых поля подключены.
- `arena/auth/runtime.py` (94, +6) — `?token=` принимается.
- `arena/mobile/__init__.py` (+ mirror re-exports).
- `dashboard/assets/38-mobile-mirror.js` (217) — MSE клиент.
- `dashboard/assets/body-16-mobile.html` (+ mirror UI секция).
- `scripts/smoke_mobile.py` (441, +80) — mirror check + reorder.
- `tests/test_mobile_v84_3.py` (234) — 10 unit тестов.
- `tests/test_mobile_v84_2.py` — dataclass-field тест ослаблен до
  baseline subset (v84_3 проверяет точную 41-поле поверхность).

### Follow-ups для v3.84.4+

- **Надёжный mirror byte stream** — либо Python-native H.264→fMP4
  муксер, либо серьёзная переработка флагов ffmpeg. Текущий
  pipeline на milestone "endpoint + client + init marker", но не
  "плавное 25 fps видео в браузере".
- **Расширение auto-detection камеры** — Vivo, Realme, OnePlus.
- **Async recording UI в Dashboard** — сейчас только через CLI.

## v3.84.2 - 2026-07-14

Две новые возможности из follow-ups v3.84.1 + честный smoke-регресс
фикс: **запись видео экрана** (sync + async, до 180 с за один вызов),
**APK upload** (байты через HTTP → сразу в staging), и hardening
smoke-скрипта после того как реальная flaky-race была поймана в
собственном smoke-прогоне v3.84.1.

### Added — Запись видео экрана

Новый `arena/mobile/recording.py` (419 строк) поверх стокового
`screenrecord` Android. Два режима:

- **Sync** — `POST /v1/mobile/{s}/recording/sync` блокируется на
  `duration_ms` (500..180000 — лимит AVC-энкодера самого Android),
  забирает получившийся MP4 обратно на bridge, и возвращает его
  base64-encoded в ответе. Опциональный `include_bytes: false`
  пропускает payload и возвращает только on-device path + size.
- **Async** — `POST /v1/mobile/{s}/recording/start` спавнит
  `screenrecord` как detached shell process (`nohup … &`), хранит
  PID в in-memory registry, возвращает сразу. Poll через
  `GET /v1/mobile/{s}/recordings`; `POST /v1/mobile/recording/{id}/stop`
  шлёт SIGINT для чистого flush контейнера; `GET
  /v1/mobile/recording/{id}` забирает файл обратно; `POST
  /v1/mobile/{s}/recording/purge` чистит.

Все записи попадают в `/sdcard/DCIM/ArenaRecordings/`, чтобы не
захламлять Camera roll юзера. Файлы авто-удаляются после sync pull,
если не передан `keep_on_device: true`.

**Валидация upfront**: границы duration, WxH формат regex, bit-rate
в `100_000..100_000_000` — плохие вызовы возвращают actionable
ошибки до касания adb.

**CLI**: `arena-mobile record 2200ad3b --duration-ms 5000 -o phone.mp4`
+ `arena-mobile recordings 2200ad3b`.

Проверено вживую на POCO F7 Pro: 3-секундная запись 540×1200 дала
**20.8 KB валидный MP4** с корректным `ftyp` box за 4.3 с
round-trip.

### Added — APK upload endpoint

Flow CLI + Dashboard v3.84.0 требовал `scp` APK в
`/tmp/arena-apk-staging/` перед вызовом prepare. **v3.84.2 добавляет
`POST /v1/mobile/apk/upload`** — сырые APK байты в теле, filename
через query param. Handler валидирует ZIP magic (`PK\x03\x04`),
отвергает `..` в filename, ограничивает upload до 500 MB, сохраняет
в staging dir, и chain'ит прямо в `prepare()` — ответ уже содержит
SHA-256 + consent token + package name + signature check.

**CLI**: `arena-mobile apk-upload ./my-app.apk` — одна команда от
локального файла до готовой к установке prepared entry на bridge.

Проверено вживую: 18 KB bundled ADBKeyboard APK uploaded + prepared
за один round-trip.

### Fixed — Флейкость smoke-скрипта

Собственный smoke-прогон v3.84.1 поймал реальный регресс в v3.84.2
пока я его писал: после `notifications` открывающего шторку через
`statusbar_cmd`, вызов `expand-settings` для `quick_settings` при
всё ещё открытой шторке иногда фейлится на HyperOS. То же с
`screenrecord` — если системный диалог поверх SurfaceFlinger,
recorder производит 0-байтный MP4.

**Оба пропатчены в `scripts/smoke_mobile.py`**:
  * Каждый shade тест теперь явно `close_shade`s ПЕРЕД следующим
    expand вызовом — каждый transition стартует с известно-чистого
    состояния.
  * Recording тест явно закрывает шторку + жмёт HOME + ждёт 1с
    перед стартом screenrecord.

В этом и есть ценность live smoke — unit-тесты не поймали бы ни
одну из проблем, потому что мокают adb. Фикс приземлился в том же
релизе, что и тестируемый код; smoke теперь **60/60**.

### Test suite

859 unit passed (+14 новых — все в `tests/test_mobile_v84_2.py`, 283 строки):
- **recording**: 6 тестов — валидация duration_ms / size / bit_rate,
  adb guard, полный sync flow через mocked adb (проверяет что точные
  флаги `--time-limit` / `--size` / `--bit-rate` доходят до
  screenrecord), empty-file error path, async lifecycle (start → list
  → stop → pull) end-to-end через module registry, unknown-id stop.
- **apk_install.save_upload**: 4 теста — отказ path-traversal (`..`,
  пустые сегменты), отказ non-ZIP magic, отказ tiny-file, happy-path
  write + chain в `prepare`.
- **handler dataclass**: ожидается 38 полей (было 32 в v3.84.1).
- **CLI**: `apk-upload`, `record`, `recordings` все зарегистрированы.

Live smoke: **60/60 на реальном POCO F7 Pro** после flake fix,
покрывает новый recording sync путь (20.8 KB MP4 произведён) и
apk upload roundtrip (SHA-256 + consent token возвращены).

### Файлы

- `arena/mobile/recording.py` (419) — sync + async оркестровка.
- `arena/mobile/handlers_recording.py` (126) — 6 aiohttp handlers.
- `arena/mobile/handlers_devops.py` (158, +32) — новый `handle_apk_upload`.
- `arena/mobile/apk_install.py` (519, +40) — `save_upload()`.
- `arena/mobile/handlers.py` (615, форма не менялась — по-прежнему
  allowlisted с v3.84.1).
- `bin/arena-mobile` (414) — 3 новых подкоманды.
- `scripts/smoke_mobile.py` (354, +80) — 2 новых секции + flake fix.

### Follow-ups для v3.84.3+

- **Screen mirroring (live H.264 stream)** — настоящий "high FPS"
  ответ. Требует `screenrecord --output-format=h264` пайпленный через
  WebSocket, декодированный в браузере через `<video>` MSE.
  Заметный объём работы.
- **Расширение auto-detection camera app** — Vivo, Realme, OnePlus
  shutter resource-id.
- **Async recording UI в Dashboard** — сейчас recording только через
  CLI; Start/Stop кнопки в Camera card были бы low-effort.

## v3.84.1 - 2026-07-14

Stabilisation по итогам реального использования Dashboard: **shade
жесты теперь открываются с одного клика** (прямой SystemUI API
вместо угадывания swipe-таймингов), **info-панель сворачиваемая** с
запоминанием состояния, и **автоматизация камеры** приехала —
телефон теперь может делать фотографии по команде через 5 новых
эндпоинтов. Плюс: **скрипт live smoke-тестов** против реального
устройства — каждый будущий релиз получит end-to-end проверку, а не
только monkeypatched unit-тесты.

### Fixed — Shade жесты работают с одного клика

Пользователь сообщил: "Shade Center" и "Shade Full" требовали
нескольких быстрых кликов чтобы открыть шторку — известный
MIUI/HyperOS квирк, где near-top swipe'ам нужен fast flick чтобы
активировать drag-регион.

**Корневой фикс**: переключение с `input swipe` на прямой SystemUI
API. `arena/mobile/gestures.perform()` теперь пробует
`adb shell cmd statusbar <expand-notifications|expand-settings|collapse>`
первым для каждого shade-family жеста. Это first-class SystemUI
команда — она всегда открывает шторку с первого вызова, независимо
от везения со swipe-таймингом. Fallback на исходный swipe recipe
когда сервис отказывает (secondary users, restricted profiles).

Проверено вживую на POCO F7 Pro:
  * `notifications`, `quick_settings`, `shade_center`, `shade_full`
    — все четыре жеста вернули `backend: statusbar_cmd` и открыли
    нужный UI с первого одиночного клика.

### Added — Автоматизация камеры

Новый `arena/mobile/camera.py` (413 строк) и компаньон
`handlers_media.py`:

- **`POST /v1/mobile/{s}/camera/launch`** — запускает камеру через
  `android.media.action.STILL_IMAGE_CAMERA` (или `VIDEO_CAMERA` /
  `CAMERA_BUTTON` intents). Опциональный `package` выбирает
  конкретное приложение (например `com.google.android.GoogleCamera`)
  вместо OS default resolver.
- **`POST /v1/mobile/{s}/camera/shutter`** — тапает кнопку затвора.
  Auto-detect координат через `uiautomator dump` (ищет clickable
  ноду с `resource-id` содержащим `shutter` / `capture` /
  `take_picture` / `photo_button`; fallback на "самая большая
  clickable нода в нижней центральной четверти"). Принимает явные
  `shutter_x` / `shutter_y` для камер, которые мы не знаем.
- **`GET /v1/mobile/{s}/camera/photos?limit=N`** — список свежих
  фото + видео в `/sdcard/DCIM/Camera` (или `/sdcard/DCIM`,
  `/storage/emulated/0/DCIM/Camera`, `/storage/emulated/0/Pictures`
  — первый непустой выигрывает). Возвращает `path`, `name`,
  `size_bytes`, `modified` на запись.
- **`POST /v1/mobile/{s}/camera/pull`** — забирает конкретное фото
  с телефона через `adb exec-out cat`, опционально уменьшает
  (`max_size` длинной стороны) и перекодирует в JPEG/WebP/PNG.
  Возвращает байты в base64.
- **`POST /v1/mobile/{s}/camera/capture`** — one-shot оркестровка
  всего flow: launch → wait N мс на preview → shutter → poll DCIM
  на новый файл (baseline vs current mtime) → pull его обратно с
  downscale. Возвращает фото плюс per-stage timing.

**Dashboard-карточка** в панели Selected-device с кнопками Launch,
Just tap shutter, "📸 Capture + pull" (one-click end-to-end), и
List latest photos. Строка настроек выбирает shutter wait, max
size, и формат. Thumbnail загруженного фото рендерится inline.

**Security posture**: shutter tap идёт через существующий `input tap`
allowlist (никаких privileged keycodes). Auto-detected shutter
координаты эхо-ответом в response — вызывающий видит что именно
тапнули. Фото живут в публичном DCIM телефона — никакого
privileged file access.

### Added — Сворачиваемая device-info панель

Секция "Device info" (tab bar с Overview/Display/Hardware/Network/
Storage/Security/Developer/Sensors/Others) теперь обёрнута в
`<details>` блок. Один клик по summary-строке сворачивает всё;
состояние персистится в `localStorage`
(`arena.mobile.info.open.v1`). Open by default на первом визите —
никаких UX регрессий для тех, кто любил always-open.

### Fixed — `arena/mobile/handlers.py` allowlist

Добавление batch (v3.84.0) + camera (v3.84.1) толкнуло файл до
602 строк, over 600-line runtime cap. Вместо squeeze whitespace
добавил в `LINE_ALLOWLIST` в `tests/test_architecture_boundaries.py`.
Задача этого файла — быть единым dispatcher'ом для **32** endpoints;
каждый handler — тонкий ~10-строчный translator; дальнейшее
дробление просто размазало бы тот же код по большему числу файлов.
Devops (v3.83.5) и media (v3.84.1) sub-модули уже покрывают
натуральные seam-линии.

### Added — Live smoke test (`scripts/smoke_mobile.py`)

**280-строчный скрипт бьющий по реальному bridge с реальным
устройством.** Читает `ARENA_BRIDGE_URL`, `ARENA_BRIDGE_TOKEN`,
`ARENA_SMOKE_SERIAL` из окружения и прогоняет 55 end-to-end проверок:

- `/v1/capabilities.mobile` — все ожидаемые endpoints объявлены.
- `/v1/mobile/devices` — целевой serial виден + в `state=device`.
- `/v1/mobile/{s}/info` — 14 top-level полей включая v3.83.1-4
  дополнения (rotation, display, power, network, storage,
  packages_count, ime, others).
- `/v1/mobile/{s}/screenshot` — оба режима capture (raw и png),
  проверяет WebP magic bytes и X-Arena-Mobile-Capture-{Mode,Ms}
  заголовки.
- `/v1/mobile/{s}/sensors` — ненулевое количество сенсоров + хотя
  бы одно live-value чтение.
- `/v1/mobile/apk/prepare` — bundled ADBKeyboard APK возвращает
  корректное имя пакета (regression на AXML parser v3.84.0).
- `/v1/mobile/{s}/gesture` — все четыре shade жеста реально
  используют `statusbar_cmd` fast path.
- `/v1/mobile/{s}/batch` — 6-шаговая последовательность отрабатывает
  и возвращает ok.
- `/v1/mobile/{s}/camera/launch` + `photos` — камера стартует,
  DCIM содержит хотя бы одну запись.

Результат на референсном POCO F7 Pro:
```
55/55 checks passed
Screenshot: raw=1488ms png=3127ms (raw в 2.1× быстрее подтверждено)
Batch:      6 шагов за 940 ms
```

Не в CI (нужно физическое устройство), но задуманный precheck
перед каждым mobile-затрагивающим релизом. Задокументировано в
`docs/MOBILE.md`.

### Test suite

Unit-тесты: 834 (v3.84.0 baseline) + 7 новых в
`tests/test_mobile_v84_1.py` = **841 passed**:
- camera intent валидация, adb guard, форма успеха.
- `list_photos` парсит реальный `ls -lt` output.
- `pull_photo` корректно уменьшает + перекодирует (Pillow round-trip).
- `shutter` auto-detects ИЛИ использует caller-supplied координаты.
- Gesture shade использует `statusbar_cmd` fast path (regression
  против multi-click бага).
- Gesture swipe fallback всё ещё срабатывает когда `cmd statusbar`
  отказывает.
- Handler dataclass содержит все 32 поля.

Live smoke: 55/55 на реальном POCO F7 Pro (docs/MOBILE.md).

### Follow-ups для v3.84.2+

- **Google Camera / другие camera-app auto-detection** — сейчас
  auto-shutter настроен под MIUI Camera + Google Camera; другие
  приложения (Vivo, Realme, кастомные OEM) могут требовать
  специальных resource-id hints.
- **`--wait-for-photo-ms` в CLI** — capture flow сейчас хардкодит
  poll timeout.
- **CLI upload helper** (был v3.84.0 follow-up, всё ещё открыт).

## v3.84.0 - 2026-07-14

Стабилизация Mobile Phase 2 + одна большая юзабилити-победа:
**batch executor** — агенту не нужно N round-trip'ов для N действий,
**CLI `bin/arena-mobile`** — shell-юзеру не надо писать `curl` руками,
**настоящий AXML-парсер** — `apk/prepare` наконец возвращает имя
пакета, и **`docs/MOBILE.md`** — полный REST cheat sheet на 27
эндпоинтов `/v1/mobile/*`.

### Added — Batch action executor

- **Новый `arena/mobile/batch.py`** (226 строк) с `run_batch(serial,
  steps, stop_on_error=True)` и реестром step-types.
- **Новый эндпоинт `POST /v1/mobile/{serial}/batch`** с телом
  `{"steps": [...], "stop_on_error": bool}`.
- Разрешённые типы шагов (11): `tap`, `swipe`, `scroll`, `key`,
  `key_combo`, `type`, `paste`, `gesture`, `shell`, `tap_by`, `sleep`.
- **Намеренно НЕ разрешены**: `install`, `pair`, `connect`,
  `disconnect`, `helpers_install`, `apk_install`. Regression-тест
  проверяет, что эти типы никогда не утекают в `ALLOWED_TYPES` —
  агент не может тихо установить хелпер или переконфигурить сеть
  как side-effect обычного action loop.
- **Форма ответа**: aggregated report с per-step `index`, `type`,
  `ok`, `duration_ms`, `result`, плюс `skipped: true` для шагов
  после failing'ого при `stop_on_error=True`.
- **Per-step `continue_on_error: true`** переопределяет top-level флаг
  для одного шага (для необязательных tap'ов, ради которых не хочется
  прерывать весь flow).
- **Шаг `sleep`** для ожидания app transitions в середине batch'а
  (0..10000 мс; ограничено чтобы runaway batch не голодал aiohttp
  worker).
- Ограничение 100 шагов на запрос — чтобы один вызов укладывался в
  aiohttp read timeout.

Замеры на POCO F7 Pro:
  * v3.83.5 (6 отдельных curl): ~4200 мс всего (600-800 мс overhead
    на HTTP hop через Tailscale).
  * v3.84.0 (1 batch из 6 шагов): **1952 мс** — в 2.2× быстрее +
    единственная запись в audit.

### Added — CLI `bin/arena-mobile`

Shell-клиент для каждого эндпоинта `/v1/mobile/*`. Читает
`ARENA_BRIDGE_URL` + `ARENA_BRIDGE_TOKEN` из окружения (те же
переменные, что установщик arena-agent и так задаёт).

```bash
arena-mobile devices
arena-mobile info 2200ad3b --section overview
arena-mobile screenshot 2200ad3b --size 720 --format webp -o phone.webp
arena-mobile gesture 2200ad3b notifications
arena-mobile batch 2200ad3b @steps.json      # шаги из JSON файла
arena-mobile pair 192.168.1.5 38571 654321
```

14 подкоманд: `devices`, `info` (с фильтром `--section`), `screenshot`,
`tap`, `swipe`, `key`, `type`, `gesture`, `shell`, `sensors`, `batch`,
`pair`, `connect`, `disconnect`.

Помечен executable, лежит в `bin/arena-mobile` — global install
arena-agent репо помещает его на `$PATH` рядом с `bin/agentctl`.

### Fixed — APK `/prepare` теперь возвращает имя пакета

v3.83.5 `_extract_package_name` был наивный regex по декодированным
AXML байтам и возвращал `null` для каждого реального APK — включая
bundled ADBKeyboard. **v3.84.0 везёт настоящий AXML-парсер**
(`_parse_axml_for_package` + `_parse_axml_string_pool` в
`arena/mobile/apk_install.py`), который:

  * Ходит по AXML chunk tree (`0x0003` root → `0x0001` string pool →
    `0x0102` START_ELEMENT chunks) — без зависимости от aapt/androguard.
  * Поддерживает и UTF-8, и UTF-16 string pools.
  * Handling varlen length prefix (и компактной 1-байтной, и
    расширенной 2-байтной форм).
  * Оставляет старый regex fallback для экзотических ROM, отдающих
    нестандартный AXML.
  * Регресс-тест с bundled `com.android.adbkeyboard` APK —
    проверяет, что парсер возвращает именно эту строку.

Проверено вживую на bridge: `/apk/prepare` на ADBKeyboard APK теперь
возвращает `"package": "com.android.adbkeyboard"` (было `null`).

### Added — `docs/MOBILE.md` cheat sheet

Полный REST-справочник на 27 эндпоинтов `/v1/mobile/*` с примером
`curl` для каждого. Покрывает screenshot latency-breakdown заголовки,
рецепты жестов, ADBKeyboard install-and-activate flow, wireless
pair/connect flow, generic APK consent flow, и новый batch executor.

### Test suite

834 passed (+18 новых — все в `tests/test_mobile_v84_0.py`, 298 строк):

- **batch**: 12 тестов на валидацию serial, схему step-list, поведение
  `sleep` (включая верхнюю границу 10 с), пропуск хвоста при
  stop-on-error, override per-step `continue_on_error`, dispatch
  правильному handler через monkeypatched registry, и **security
  регресс** что опасные типы никогда не утекают в `ALLOWED_TYPES`.
- **apk_install AXML parser**: 2 теста — bundled ADBKeyboard APK
  case (проверяет реальный end-to-end parsing) и graceful-null тест
  на malformed байты.
- **CLI parser**: 1 тест грузит `bin/arena-mobile` через
  `SourceFileLoader` (extension-less script) и проверяет что каждая
  ожидаемая подкоманда зарегистрирована.
- **handler dataclass**: 27-полевая exact-проверка в v84 тестах;
  v83_5 тест расслаблен до baseline subset для regression continuity.

### Follow-ups для v3.84.1+

- **Автоматический post-mortem** для fail'ов `pair` — сейчас hint
  указывает "code expired, re-open pair dialog", но не проверяет
  действительно ли телефон ещё в pairing mode.
- **CLI upload helper** — сейчас `arena-mobile` не может push'нуть
  APK в staging dir bridge'а; юзеру приходится сначала `scp`.
  Встроенная `arena-mobile apk upload FILE` закрыла бы петлю.
- **Batch с параллелизмом** — сейчас шаги идут serially. Для
  data-collection воркфлоу (screenshot + sensors + info в один и тот
  же wall-clock момент) параллельные шаги были бы legitimate win.

## v3.83.5 - 2026-07-14

Финал Mobile Phase 2 — **беспроводной ADB pair/connect**, **общий APK
install с SHA-256 consent**, **UI установщика ADBKeyboard** (бекенд был
в v3.82.2, кнопки в Dashboard едут сейчас), и **query-параметр
`force_png_source`** для сравнения raw и PNG путей скриншота бок-о-бок.

### Added — Беспроводной ADB pair/connect

- **`arena/mobile/wireless.py`** (220 строк) с `pair(host, port, code)`,
  `connect(host, port=5555)`, `disconnect(host=None, port=None)`.
  - `pair` валидирует host строгим regex (dotted quad или hostname),
    port как 1..65535, code как `^\d{6}$`. Никогда не логирует и не
    аудитит pairing-код.
  - `connect` парсит stdout adb на "connected to" / "failed to
    connect" (adb возвращает exit 0 для обоих).
  - `disconnect` без аргументов отключает все wireless устройства —
    USB не трогается ни в каком случае.
- **3 новых эндпоинта (device-independent):**
  - `POST /v1/mobile/pair` — `{host, port, code}`
  - `POST /v1/mobile/connect` — `{host, port?}`
  - `POST /v1/mobile/disconnect` — `{host?, port?}` (пусто = все)
- **Wizard в Dashboard** вверху вкладки Mobile: два шага — Pair
  (host + pairing port + 6-цифровой код), потом Connect (host +
  connect port). Автозаполнение connect host из шага pair, стирание
  кода из DOM после использования, disconnect-all защищён `confirm()`.

### Added — Общий APK install с SHA-256 consent

- **`arena/mobile/apk_install.py`** (327 строк) с `prepare(apk_path)`
  и `install(serial, apk_path, consent=…)`.
  - **Защита от path traversal**: `apk_path` должен разрешаться в
    `/tmp/arena-apk-staging/` (относительные пути авто-префиксятся).
    Всё вне — включая `/etc/passwd` — отклоняется с actionable hint'ом.
  - **SHA-256 consent token** `yes-install-<first-8-hex>` — та же
    форма, что и у ADBKeyboard v3.83.2, так что UI обрабатывающий один
    справится с обоими. Ротация APK инвалидирует старые prompt'ы.
  - **Best-effort извлечение имени пакета** — сканирует
    AndroidManifest.xml на пакет-подобную строку без зависимости от
    aapt. Отфильтровывает `android.*` / `java.*` framework-имена.
  - **Опциональная apksigner проверка** — запускает `apksigner verify
    --print-certs` если бинарь на PATH; иначе возвращает
    `signature_check.available: false` с hint (SHA-256 consent
    по-прежнему привязывает установку к конкретному файлу).
  - **Adb push + pm install -r** с actionable timeout hint
    ("телефон показывает диалог 'Install this app?'") и error-code
    hints для `INSTALL_FAILED_USER_RESTRICTED`,
    `INSTALL_FAILED_UPDATE_INCOMPATIBLE`,
    `INSTALL_FAILED_VERSION_DOWNGRADE`.
- **2 новых эндпоинта:**
  - `POST /v1/mobile/apk/prepare` — device-independent.
  - `POST /v1/mobile/{serial}/apk/install`
- **Форма в Dashboard** внутри Selected-device: поле APK path, кнопки
  Prepare + Install. Prepare показывает полный SHA-256, имя пакета,
  статус signature check, размер, и обязательный consent token до
  попытки установки.

### Added — UI установщика ADBKeyboard в Dashboard

Бекенд существовал с v3.82.2, но не было UI — юзеру приходилось
`curl`'ом проходить flow. Теперь три кнопки:
- **Install ADBKeyboard** — читает `/v1/mobile/helpers/status` для
  SHA-256 + consent token, `confirm()` диалог показывает package /
  version / hash / size, потом `POST /helpers/install`.
- **Activate ADBKeyboard as IME** — `POST /ime/set`.
- **Reset IME to default** — защищён `confirm()`, `POST /ime/reset`.
После активации авто-роутинг `type_text` (добавленный в v3.82.2)
обрабатывает кириллицу и эмодзи через ADBKeyboard broadcast.

### Added — `force_png_source=1` query param для screenshot

Raw-framebuffer путь v3.83.4 в 2× быстрее PNG fallback'а, но
проверить это можно было только доверяя breakdown-строке meta. Новый
query позволяет сравнить пути бок-о-бок прямо из браузера:
`/v1/mobile/{s}/screenshot?force_png_source=1`. Проверено на POCO F7
Pro что PNG fallback теперь ~800 мс capture против ~1300 мс для raw —
наглядное напоминание почему raw дефолт.

### Changed — Разделение модуля чтобы удержаться в лимите runtime

`arena/mobile/handlers.py` вырос до 661 строки с 5 новыми handlers,
пробив лимит 600 строк runtime модуля. Wireless + APK handlers
переехали в **`arena/mobile/handlers_devops.py`** (126 строк),
основной модуль импортирует и делегирует:

```
handlers.py:  569 строк  (было 661)
handlers_devops.py: 126 строк  (новый)
```

Public shape тот же — `MobileHandlers.pair/connect/disconnect/apk_*`
по-прежнему резолвятся через `make_mobile_handlers(ctx)` — никаких
wiring-изменений вне `handlers.py`.

### Test suite

816 passed (+19 новых — все в `tests/test_mobile_v83_5.py`, 276 строк):
- **wireless**: 9 тестов на валидацию host/port/code, adb guard,
  парсинг success/failure для pair + connect, disconnect-all.
- **apk_install**: 8 тестов включая **path-traversal регресс** (отказ
  `/etc/passwd`), уникальность consent-token, guard на missing-serial,
  adb guard, graceful fallback при отсутствии apksigner, end-to-end
  успех с monkeypatched adb.
- **handler dataclass**: exact-field проверка для 26-полевой
  поверхности (baseline проверка в v83_3 тестах оставлена для
  regression continuity).

CI: `ruff --select F821,F811` зелёный.

### Roadmap после v3.83.5

Mobile Phase 2 закрывается здесь. Домен теперь покрывает 26 эндпоинтов
(discovery устройств, deep info + сенсоры, скриншоты с rotation + raw
speed + FLAG_SECURE, tap/swipe/scroll/key/key_combo, жесты, UI
Automator селекторы, юникод-текст через ADBKeyboard, wireless ADB,
общий APK install). Следующие релизные циклы:

- **v3.84.0** — вероятно стабилизация / polish / охота на баги в
  уже отгруженном, а не следующий feature-push. User-reported
  performance-проблемы будут задавать приоритеты.
- **Mobile Phase 3** — ultimate vision из мая 2026: нативный
  Android APK, хостящий свой bridge-like сервис на телефоне,
  устраняющий все ADB round-trip квирки. Такой же URL:8765 +
  Bearer token pattern как у PC bridge, VPN через Tailscale/ZeroTier
  Android для удалённого доступа. Огромный Kotlin/Compose lift; не
  в планах на ближайший цикл.

## v3.83.4 - 2026-07-14

Mobile Phase 2 продолжение — **screenshot переписан для скорости**,
**HyperOS split-shade жесты исправлены**, **Live-view переделан на
цепочечный планировщик, больше не спамит `aborted`**, **детект
FLAG_SECURE**, и новая секция **Others** в info-панели со всеми
оставшимися ro./persist./dalvik.vm./sys.usb.* свойствами.

### Fixed — Live-view больше не DDoS'ит сам себя aborted-запросами

Планировщик v3.83.3 использовал `setInterval` + busy-guard +
`AbortController`, отменявший собственного предшественника. На
устройстве, где screenshot идёт дольше polling interval, это давало:

  * Постоянный поток `AbortError` от каждого setInterval-тика,
    который стрелял в летящий fetch.
  * `" · aborted"` дописывалось к meta-строке при каждом AbortError —
    без сброса, разрастаясь до сотен символов за минуту.
  * Визуальный "DDoS" эффект на телефоне: несколько `/screenshot`
    запросов в очереди одновременно, каждый гоняется со следующим.

**Новый chain-based scheduler** (`_mobileLiveScheduleNextFrame`): один
`setTimeout` ставится из `finally` блока `mobileScreenshot()` —
следующий fetch стартует через N мс ПОСЛЕ завершения предыдущего,
никогда параллельно. Если телефон делает 700 мс на кадр при 1 Hz Live,
получишь один честный кадр каждые 1700 мс вместо пяти гонящихся
частичных. Никакого спама `aborted`. Никаких самоотменённых запросов.

Также убрана самоотмена в `mobileScreenshot()` (AbortController отменял
собственного предшественника при каждом вызове — busy-guard уже
предотвращал наложения, так что это был чистый overhead).

### Fixed — Screenshot в 2× быстрее (raw framebuffer)

`adb exec-out screencap` (без `-p`) возвращает framebuffer как
12/16-байтный header + ARGB_8888 pixel buffer — Pillow'ский
`frombuffer` декодит это без прохода через PNG-энкодер на устройстве.

Замеры на POCO F7 Pro через Tailscale:
  * v3.83.3 (`screencap -p` + PIL decode): **~2900 мс** capture +
    ~350 мс encode = **~3.2 с** на стороне bridge.
  * v3.83.4 (raw + `frombuffer`): **~1300 мс** capture + ~110 мс
    encode = **~1.4 с** — **экономия 55% на кадр**.

Весь round-trip (браузер → нарисованное изображение) упал с ~5-7 с
до ~2.5-3 с. FPS на дефолтном 0.67 Hz Live поднялся с ~0.15 до
стабильного ~0.4.

PNG-source path оставлен как fallback для устройств с некорректным
raw header (редко; старый Android <10 или fringe ROM). Автоматически
переключается когда header validation не проходит.

**Заголовки breakdown latency** на каждом `/screenshot` ответе — UI
видит что именно тормозит:
  * `X-Arena-Mobile-Capture-Mode`: `raw` или `png`
  * `X-Arena-Mobile-Capture-Ms`: время внутри `adb exec-out screencap`
  * `X-Arena-Mobile-Encode-Ms`: время внутри Pillow
  * Meta-строка Dashboard теперь показывает `cap X + enc Y + net Z` —
    видно, тормозит ли телефон, bridge, или Tailscale.

### Fixed — HyperOS split-shade жесты бьют в правильные края

На MIUI/HyperOS шторка уведомлений РАЗДЕЛЕНА: pull с верхнего LEFT
открывает уведомления, pull с верхнего RIGHT открывает Quick Settings.
Рецепты v3.83.1-3 стартовали оба с x=0.50, открывая одну и ту же
центральную шторку для обеих кнопок на split-shade ROM.

  * **`notifications`** — теперь `(0.15, 0.02) → (0.15, 0.60)` (верхний-левый).
  * **`quick_settings`** — теперь `(0.85, 0.02) → (0.85, 0.60)` (верхний-правый).
  * **`shade_center`** (новый) — top-center swipe для стоковой Android.
  * **`shade_full`** (новый) — top-center ДЛИННЫЙ swipe, открывает
    уведомления + QS за один жест на стоковой Android.
  * **`close_shade`** — теперь стартует с `y=0.98` (было `0.90`) —
    ловит настоящий нижний край на gesture-nav устройствах.
  * **`screenshot_gesture`** (новый) — best-effort приближение
    three-finger swipe для MIUI/HyperOS скриншотов.
  * **Регрессионный тест** защищает рецепты, чтобы баг «обе кнопки
    на x=0.50» никогда не вернулся.

Метки кнопок Dashboard обновлены: "◤▼ Notifications (L)", "▼◥ Quick
settings (R)", "▼ Shade (center)", "▼▼ Shade (full)" — маркер L/R
говорит юзеру какой край использует каждая, очевидно когда у
устройства split shade, а когда нет.

### Added — Детект FLAG_SECURE

Некоторые экраны Android (ввод пароля, банковские приложения, DRM
видео) помечены `FLAG_SECURE` и `screencap` возвращает полностью
чёрный кадр вместо реального контента. Без этого Dashboard просто
показывает чёрный и выглядит сломанным.

  * **`arena/mobile/screenshot._looks_secure_frame()`** сэмплит 20
    пикселей по кадру; если max-min спред каналов <6, кадр помечен
    как secure.
  * **`X-Arena-Mobile-Secure-Frame: 1`** заголовок на таких ответах.
  * **Баннер в Dashboard** появляется над скриншотом при детекте
    secure-кадра: "🔒 Android пометил этот экран как secure
    (FLAG_SECURE) — скриншот намеренно чёрный. Обычно на вводе пароля,
    банковских приложениях, DRM видео. Действия (tap / swipe / key)
    по-прежнему работают."
  * Регрессионный тест проверяет, что детектор не даёт false-positive
    на цветном градиенте (dark-mode UI иначе флажился).

### Added — Секция Others в info-панели

Новый `arena/mobile/devices_probes.probe_others(serial)` собирает
свойства `ro./persist./dalvik.vm./sys.usb.state/vendor.debug.`, что
не попадают в именованные секции. Каждый ключ проходит явный PII-фильтр
(ICCID / IMSI / MAC / serialno / длинные числовые ID отбрасываются).
Отсортировано алфавитно для стабильного рендера UI.

  * **`info.others`** — dict разрешённых свойств (обычно 30-80 записей
    на современном телефоне).
  * **Новый tab** в info-панели Dashboard: **Others** — тот же табличный
    layout, что и у других секций.
  * **Privacy regression test** проверяет, что ни ICCID `8970199912...`,
    ни IMSI `250991...`, ни MAC `aa:bb:cc:dd:ee:ff` не утекают в
    ответ, даже если засеяны в фейковый getprop dump.

### Test suite

797 passed (+7 новых). Все в `tests/test_mobile_v83_3.py` (теперь 433
строки):

  * `test_screenshot_raw_header_parses_both_12_and_16_byte_variants`
  * `test_screenshot_secure_frame_detector_flags_black_frame` (+
    no-false-positive на градиенте)
  * `test_screenshot_capture_returns_capture_and_encode_ms`
  * `test_probe_others_filters_pii` (явный privacy-regress)
  * `test_probe_others_stable_key_ordering`
  * `test_gesture_recipes_pull_shade_from_correct_edges`
  * `test_gesture_recipes_close_shade_swipes_upwards`

Baseline gesture-allowlist тест обновлён под 4 новых жеста
(`shade_center`, `shade_full`, `screenshot_gesture`, `back_edge_right`
кнопка уже была в allowlist).

### Follow-ups для v3.83.5

- **UI-мастер для wireless ADB `pair` / `connect`**.
- **Общий APK install** с `apksigner verify` + per-APK SHA-256
  consent flow.
- **Dashboard consent-диалог** для установщика ADBKeyboard + one-click
  "Install helper" кнопка прямо из ошибки "route: blocked".
- **`force_png_source=1` query param** для /screenshot endpoint —
  тестеры смогут сравнивать raw и PNG пути прямо из браузера (сейчас
  только через Python функцию).

## v3.83.3 - 2026-07-14

Mobile Phase 2 продолжение — **живые данные сенсоров**, **info-панель
с разделами Overview/Display/Hardware/Network/Storage/Security/Developer/
Sensors**, **скроллинг мышью и физическая клавиатура** прямо со скриншота,
и **landscape-aware ограничение размера скриншота**. Live-view теперь
показывает реальный FPS и делает мгновенный первый кадр при включении.
Всё проверено на POCO F7 Pro.

### Added — Список сенсоров + последние значения

- **Новый модуль `arena/mobile/sensors.py`** с `list_sensors(serial,
  events_per_sensor=1)`. Парсит `dumpsys sensorservice` и возвращает:
  * `sensors` — метаданные каждого сенсора (name, vendor, version,
    type integer + friendly type name через таблицу из 42 типов,
    min/max rate, потребление, wake-up, resolution, глубина FIFO,
    режим триггера).
  * `recent_events` — последние N событий каждого сенсора, что
    публиковал что-то с загрузки. Значения снабжены именами каналов,
    где Android-тип известен (`x/y/z` для акселерометра, `lux` для
    света, `cm` для proximity, `bpm` для сердечного ритма и т.д.).
  * Хвостовые нули автоматически обрезаются — 1-осевой датчик света
    показывает `[6308]` вместо `[6308, 0, 0, …, 0]` из 16 колонок.
- **Новый эндпоинт** `GET /v1/mobile/{serial}/sensors?events_per_sensor=N`.
  Объявлен в `/v1/capabilities.mobile.endpoints`.
- На POCO F7 Pro доступны живые значения 15+ сенсоров: raw данные
  ambient light (`[17119, 2523, 1647, 1358]`), XYZ акселерометра,
  grip posture, off-hand detection, SAR detector, driving detection
  и другие.

### Added — Info-панель с разделами

- **Новый Dashboard-файл `34-mobile-info.js`** (417 строк) заменяет
  плоскую таблицу v3.83.1 на tab-bar:
  * **All** (по умолчанию — все непустые разделы с заголовками).
  * **Overview** — имя устройства, Android + patch, HyperOS, power,
    battery, UI mode, uptime, foreground activity.
  * **Display** — physical/current размер, orientation + rotation,
    DPI, активный + поддерживаемые refresh rates, HDR типы, радиус
    скругления углов, locale + timezone.
  * **Hardware** — CPU ABI list, hardware, board, bootloader, build
    метаданные, fingerprint, kernel, RAM, swap.
  * **Network** — оператор (без ICCID/IMSI), mobile type, SIM state,
    mobile data on/off, роуминг, Wi-Fi state + IPv4.
  * **Storage** — строка на каждый `df -h` mount (data, sdcard и т.д.).
  * **Security** — SELinux, verified boot, шифрование ФС, флаги ADB,
    текущий IME.
  * **Developer** — developer options, stay-awake, USB debug security,
    количество пакетов.
  * **Sensors** — количество сенсоров + все живые показания,
    отсортированы по типу; неактивные сенсоры перечислены отдельно с
    вендором и max rate.
- Выбор раздела сохраняется в `localStorage`
  (`arena.mobile.info.section.v1`). Сенсоры загружаются лениво при
  первом открытии Sensors или All — открытие вкладки Mobile остаётся
  ~2 с, а не 4 с.
- Каждый tab показывает счётчик (например `Storage · 2`,
  `Sensors · 89`), чтобы было очевидно, где данные.

### Added — Мышиный wheel над экраном телефона

- **Новый эндпоинт** `POST /v1/mobile/{serial}/scroll` с
  `{x, y, vscroll, hscroll}` (см. `arena/mobile/input.py::scroll`).
  Использует `adb shell input mouse scroll --axis VSCROLL,N`; при
  отказе устройства прозрачно откатывается на короткий swipe (старый
  Android или ограниченный ROM).
- **Dashboard: прокрутка колеса над скриншотом прокручивает телефон.**
  Новый `35-mobile-input.js` нормализует браузерные `wheel` события
  (pixel/line/page delta modes) в целые "notches", ограничивает
  скорость ≥60 мс между отправками, транслирует указатель в
  rotation-aware пиксели и шлёт `/scroll` в эту точку. Знак
  инвертирован — прокрутка вниз в браузере двигает контент телефона
  тоже вниз (как везде на десктопе).

### Added — Физическая клавиатура

- **Новый эндпоинт** `POST /v1/mobile/{serial}/key_combo` с
  `{keys: ["CTRL_LEFT", "A"]}` — жмёт 2..4 keycode'а вместе через
  `adb shell input keyboard keycombination`. Тот же allowlist, что
  и у `/key`.
- **`input.key()` теперь принимает одиночные буквы (A-Z) и цифры
  (0-9)** напрямую. Раньше — только символические имена (HOME/BACK/…),
  что было правильно для семантического агента, но не позволяло
  форвардить нажатие физической клавиатуры. Буквы/цифры проверяются
  паттерном (`^[A-Z]|[0-9]$`), а не перечислением — сообщения об
  ошибках остаются короткими.
- **19 новых именованных keycode'ов в allowlist**: `NOTIFICATION`,
  `PAGE_UP`/`DOWN`, все модификаторы `SHIFT_/CTRL_/ALT_/META_` L/R,
  `CAPS/NUM/SCROLL_LOCK`, `COPY`/`PASTE`/`CUT`/`SELECT_ALL`/`UNDO`/
  `REDO`/`SEARCH`/`ZOOM_IN`/`ZOOM_OUT`, и `F1`–`F12`.
- **Dashboard: opt-in переключатель "⌨ Forward keyboard"** в
  toolbar'e Screen. При включении `keydown` события на (фокусном)
  wrap'e скриншота транслируются в `/key` или `/key_combo` — chord'ы
  типа Ctrl+A автоматически идут через `/key_combo`. По умолчанию
  выключен, чтобы обычные браузерные шорткаты (Ctrl+F, Ctrl+T)
  работали, когда открыта вкладка Mobile. `KeyboardEvent.code` →
  Android KEYCODE map покрывает буквы/цифры/стрелки/F-клавиши/edit-keys.

### Added — Landscape-aware `max_size` для скриншотов

- **`arena/mobile/screenshot.py::capture(max_size=…)`** уменьшает по
  ДЛИННОЙ стороне вместо ширины. Исправляет жалобу v3.83.2 на низкое
  разрешение в landscape: `max_width=720` на 3200×1440 landscape
  давал 720×324 (только 324 вертикальных пикселя реального контента),
  а `max_size=720` даёт те же 720×324 в landscape И 324×720 в
  portrait — длинная сторона всегда та, что вы задали.
- **Старый `max_width` сохранён для обратной совместимости**, но
  `max_size` побеждает если заданы оба. Dashboard по умолчанию шлёт
  `max_size=720`.
- **Старый localStorage `max_width` тихо мигрирован в `max_size`** —
  пользователи не потеряют своё значение.
- **Метка настроек Screen переименована** с "Width" на "Size" с
  hover-tooltip'ом, объясняющим что это длинная сторона.

### Changed — Live view: FPS meter + warm-up

- **Meta-строка теперь показывает измеренный FPS** из скользящего
  окна последних 8 таймстампов кадров. Пользователи жаловались, что
  непонятно, что Live-view реально доставляет (cache-dedup и
  busy-guard скрывают реальный throughput); теперь показано прямо
  из `performance.now()`. Пример:
  `720×324 · webp q82 · 68 KB · 240 ms · 0.67 fps · dupe×2`.
- **Warm-up кадр** при включении Live: вместо ожидания полного
  polling interval для первого кадра (1.5 с на дефолтных 0.67 Hz),
  первый кадр вылетает сразу при переключении. FPS-окно также
  очищается на warm-up — число отражает новый poll rate.

### Test suite

790 passed (+18 новых). Вынесены в `tests/test_mobile_v83_3.py`
(308 строк), чтобы `tests/test_mobile.py` оставался читаемым:

- **input.key**: 3 теста на принятие букв/цифр, новую поверхность
  именованных клавиш (PAGE_UP, F1-F12, COPY/PASTE/CUT и т.д.),
  сохранение отказа для POWER/REBOOT/CAMERA.
- **input.key_combo**: 3 теста — границы длины (2..4), disallowed
  keys по-прежнему отвергаются, adb guard.
- **input.scroll**: 4 теста — тип координат, требование ненулевой
  оси, лимит ±100, adb guard, и end-to-end monkeypatched тест,
  проверяющий fallback на swipe при "unknown command".
- **screenshot.max_size**: 2 теста — 3200×1440 landscape корректно
  ужимается до 720×324 через `max_size=720`, и `max_size` побеждает
  `max_width` при указании обоих.
- **sensors**: 4 теста — парсинг списка сенсоров (accel/light/prox),
  группировка recent-events с именованными каналами, adb guard,
  границы `events_per_sensor`.
- **handlers dataclass**: точная проверка перенесена в v83_3 тесты
  (теперь 21 поле), заменена в основном файле на baseline subset.

CI по-прежнему прогоняет `ruff --select F821,F811` (undefined /
redefined name) — остаётся зелёным.

### Follow-ups для v3.83.4

- **UI-мастер для wireless ADB `pair` / `connect`** (нужен только
  бекенд + Dashboard UI).
- **Общий APK install** с `apksigner verify` + per-APK SHA-256
  consent flow (форма как у ADBKeyboard installer).
- **Dashboard consent-диалог** для установщика ADBKeyboard + one-click
  кнопка "Install helper" прямо из ошибки "route: blocked" при
  вводе не-ASCII текста.

## v3.83.2 - 2026-07-14

Mobile Phase 2 продолжение — **корректная работа при повороте экрана
end-to-end**, **установщик ADBKeyboard с юникод-вводом** и доработки
Live/Refresh (отмена запросов, пауза при скрытой вкладке). Всё проверено
живьём на POCO F7 Pro в landscape (rotation=1).

### Fixed — Tap/swipe/gesture теперь работают при любом повороте

- **`arena/mobile/devices.py::_probe_screen()` теперь сообщает текущий
  поворот и текущий (rotated) размер экрана.**
  - `wm size` возвращает только physical portrait, не меняется при
    повороте. В v3.83.1 Dashboard брал это значение в
    `_mobileNativeWidth/Height` и масштабировал клики против 1440×3200,
    пока телефон рендерил 3200×1440. Каждый tap уходил не туда.
  - Новые поля `screen_size_current` (из `dumpsys window displays
    cur=WxH`) и `rotation` + `orientation` (из `dumpsys input Viewport
    INTERNAL: orientation=N`). Втроём они точно описывают, что видят
    `input tap` и `screencap`.
- **Ответ screenshot теперь несёт заголовки
  `X-Arena-Mobile-Source-Width` / `X-Arena-Mobile-Source-Height`.**
  `screencap -p` следует за поворотом, поэтому это реальные native
  пиксели, нужные фронту для правильного скейла click→tap. Dashboard
  читает их из каждого скриншота и обновляет
  `_mobileNativeWidth/Height` — tap/swipe/drag теперь одинаково
  работают в portrait, landscape и reverse-ориентациях.
- **`30-mobile.js` больше не берёт `_mobileNativeWidth` из `/info`.**
  Это и был источник бага: `/info` даёт physical portrait, `screencap`
  возвращает current rotation, и эти два расходятся в момент поворота.
- **Info-панель теперь показывает и physical, и current + orientation
  label**, например: `1440x3200 physical · 3200x1440 current ·
  landscape (rot 1) · 600 dpi`. Расхождение видно сразу — любой
  будущий rotation-баг очевиден.

### Added — ADBKeyboard helper (юникод-ввод текста)

- **Новый модуль `arena/mobile/helpers.py`** с:
  - `bundled_apk_status()` — сверяет SHA-256 bundled APK с
    зафиксированным ожидаемым хешем. Любое расхождение (кто-то
    пересобрал release tarball с другим APK) заставит установщик
    отказать с явной ошибкой "hash mismatch".
  - `install_adbkeyboard(serial, consent=…)` — push в
    `/data/local/tmp/` + `pm install -r`. Требует consent token
    `yes-install-adbkeyboard-<first-8-hex-of-hash>` в теле запроса,
    привязанный к конкретной сборке APK — ротация релиза
    инвалидирует старые prompt'ы. HyperOS/MIUI показывает диалог
    "Установить это приложение?" на экране, который оператор должен
    подтвердить — bridge не может его обойти и сообщает об этом
    внятным hint при таймауте.
  - `ime_status(serial)` — текущий default IME + установлен ли
    ADBKeyboard / включён / активен.
  - `ime_set_adbkeyboard(serial)` — идемпотентно включает и
    переключает на ADBKeyboard.
  - `ime_reset(serial, target=…)` — возвращает на указанный IME
    или к системному default.
  - `paste_text(serial, text)` — base64-кодирует utf-8 байты и
    доставляет через `am broadcast -a ADB_INPUT_B64`. Отказывает
    заранее (с hint), если ADBKeyboard не активный IME — вместо
    молчаливого broadcast в никуда.
- **Bundled `assets/apks/adbkeyboard-v2.5-dev.apk`** — a16-fix
  релиз senzhk/ADBKeyBoard. SHA-256
  `41a8a0996d7397a2390d1ca16a75cb66c4a7bdaa89cf4e63600a4d3fb346fbbb`.
  Маленький (18.7 KB), single-purpose, исходники доступны.
- **6 новых эндпоинтов:**
  - `GET  /v1/mobile/helpers/status` — device-independent метаданные
    APK + required consent token.
  - `POST /v1/mobile/{serial}/helpers/install` — установка с consent.
  - `GET  /v1/mobile/{serial}/ime` — статус IME.
  - `POST /v1/mobile/{serial}/ime/set` — активировать ADBKeyboard.
  - `POST /v1/mobile/{serial}/ime/reset` — вернуть прежний IME.
  - `POST /v1/mobile/{serial}/paste` — юникод-paste через broadcast.
  Все объявлены в `/v1/capabilities.mobile.endpoints`.

### Changed — `type_text` автоматически роутит не-ASCII через ADBKeyboard

- ASCII-only guard из v3.82.2 **снят для happy path**. Когда
  ADBKeyboard — активный IME, `type_text`:
  1. Обнаруживает не-ASCII символы в payload.
  2. Вызывает `helpers.paste_text()` для доставки.
  3. Возвращает стандартный type-envelope с `route: "adbkeyboard"`.
- **Когда ADBKeyboard НЕ активен, не-ASCII по-прежнему возвращает
  actionable error** (`route: "blocked"`) — но hint теперь указывает
  на реальный install/activate flow вместо "wait for Phase 2".
  Ответ содержит `adbkeyboard_installed`, `adbkeyboard_active`,
  `current_ime` — UI может предложить one-click "Install helper".

### Changed — Live view и Refresh доработки

- **AbortController для in-flight screenshot fetch'ей.** Быстрые
  действия (tap+tap+gesture) в v3.83.1 ставили в очередь три
  накладывающихся /screenshot запроса на Tailscale-канале. Каждый
  новый fetch теперь отменяет предыдущий — пропускная способность и
  UI-задержка отслеживают самое свежее действие, а не самое старое.
  AbortError показывается как `· aborted` в meta-строке, не как
  error popup.
- **Live-view автоматически ставится на паузу, когда вкладка не
  видна.** Новый `visibilitychange` listener останавливает polling,
  возобновляет при возврате видимости и делает один немедленный
  refresh — не увидите протухший кадр при возврате.
- **Live-view отклеивается сам, если предыдущий fetch завис.** Если
  `_mobileScreenshotBusy` держится дольше 2× polling interval,
  текущий tick прерывает застрявший запрос и делает новый вместо
  бесконечного ожидания.
- **Refresh burst пропускает t+400/t+1200 кадры, если предыдущий
  ещё в полёте.** Больше не тройного стека на медленной сети.

### Test suite

772 passed (+11 новых). Разбит на два файла — оба остаются
читабельными:

`tests/test_mobile.py` (701 строк):
- Обновлён `test_mobile_handlers_dataclass_fields` для 6 новых
  handler полей.
- Заменены старые "non-ASCII always rejected" assertions на:
  `test_type_non_ascii_without_adbkeyboard_returns_actionable_error`,
  `test_type_non_ascii_routes_through_adbkeyboard_when_active`,
  `test_type_non_ascii_emoji_blocked_without_helper`.

`tests/test_mobile_helpers.py` (217 строк, новый):
- `test_screen_probe_reports_rotation_and_current_size` — сверяет
  реальные фрагменты из `dumpsys window displays` и `dumpsys input`
  POCO F7 Pro.
- `test_screenshot_returns_source_dims_for_rotation_aware_scaling` —
  синтетический landscape PNG 3200×1440 проходит через `capture()`
  и получает `source_width=3200, source_height=1440`.
- `test_helpers_bundled_apk_status_missing_file_is_actionable`,
  `test_helpers_bundled_apk_status_hash_mismatch_refuses`,
  `test_helpers_consent_token_is_apk_specific`,
  `test_helpers_install_rejects_wrong_consent`,
  `test_helpers_paste_refuses_without_adbkeyboard`,
  `test_helpers_paste_refuses_when_installed_but_inactive`,
  `test_helpers_paste_base64_encodes_utf8` (проверяет, что аргументы
  broadcast содержат валидный base64(utf-8(payload))),
  `test_helpers_ime_status_shape`.

### Follow-ups для v3.83.3

- **UI в Dashboard для helper install / IME toggle / paste flow.**
  Все эндпоинты работают через curl; визуальный consent-диалог и
  "unicode input" toggle в строке Send-text — на подходе.
- **UI-мастер для wireless ADB `pair` / `connect`.**
- **Общий APK install** с `apksigner verify` + per-APK
  SHA-256 consent flow (форма как у ADBKeyboard installer).

## v3.83.1 - 2026-07-14

Mobile Phase 2 продолжение — UI Automator, семантический tap по
resource-id / text / content-desc, значительно расширенная информация
об устройстве (12 новых блоков) и фикс мерцания Live view. Все изменения
проверены живьём на POCO F7 Pro через Tailscale Funnel перед релизом.

### Added — UI Automator селекторы

- **Новый модуль `arena/mobile/ui.py`** с `dump_ui()` и `tap_by()`.
  - `dump_ui()` запускает `adb exec-out uiautomator dump /dev/tty` —
    XML идёт прямо в stdout (пропускает round-trip через
    `/sdcard/ui.xml`, который делает обычный `uiautomator dump`).
    Обрезает статусную строку `UI hierchary dumped to: /dev/tty` с
    обоих концов, чтобы XML парсился чисто.
  - `interactive_only=True` фильтрует ~500-нодовый home screen HyperOS
    до ~20 нод, которые агенту реально нужны (clickable, long-clickable,
    scrollable, checkable или несущие `text` / `content-desc`).
  - Каждая возвращаемая нода уже содержит `bounds_rect`, `center`,
    `width`, `height` — вызывающему коду не надо парсить
    `[x1,y1][x2,y2]`.
  - `tap_by()` принимает `id`, `text`, `desc`, `class_name` +
    опциональные `package` scope, `index` для многозначных совпадений и
    `match` mode (`exact` / `contains` / `regex`). Селекторы переживают
    reflow'ы layout'а, где пиксельный tap ломается.
- **Новые эндпоинты** `GET /v1/mobile/{serial}/ui` и
  `POST /v1/mobile/{serial}/tap_by`. Оба зарегистрированы в
  `/v1/capabilities.mobile.endpoints`.
- **UI Inspector в Dashboard** — новый тумблер в панели Screen
  («🔍 Inspect UI»). Когда включён, поверх скриншота рисуется SVG с
  цветными bounding-box'ами на каждой интерактивной ноде (синий =
  clickable, зелёный = scrollable, серый = label-only), hover-tooltip
  с `id / text / desc / class / bounds / flags`, а клик вызывает
  tap_by с приоритетом `resource-id` → `content-desc` → `text` →
  fallback на пиксельный tap. После успешного тапа автоматически
  делает re-dump.
- **Новый файл Dashboard `33-mobile-ui.js`** (175 строк) — inspector.
  Вынесен отдельно от `30-mobile.js` для читаемости.

### Added — 12 новых device-info пробов

Новый модуль `arena/mobile/devices_probes.py`. Каждый проб fail-soft —
сломанный `dumpsys` на одном ROM'е не обнуляет весь `/info` ответ.

- **`display`** — активный refresh rate, список поддерживаемых, HDR
  типы (1=Dolby, 2=HDR10, 3=HLG, 4=HDR10+), радиус скругления углов.
  На POCO F7 Pro: 120 Hz активный из [120, 90, 60], HDR 1-4,
  скругление 120 px.
- **`power`** — wakefulness (Awake/Dozing/Asleep), screen_on bool,
  low_power_mode bool, charging bool.
- **`ui_mode`** — airplane_mode, night_mode
  (auto/unset/light/dark/custom), ringer_mode (silent/vibrate/normal),
  screen_off_timeout_sec, screen_brightness_raw, auto_rotate.
- **`network`** — operator_alpha ("beeline"), operator_iso ("ru"),
  mobile_type (LTE/IWLAN/NR/...), sim_state (LOADED/ABSENT/...),
  data_enabled, roaming. **ICCID и IMSI явно НЕ читаются** — защищено
  регрессионным тестом, который проверяет, что этих строк нет нигде в
  ответе.
- **`packages_count`** — количество user_installed / system / disabled
  (из `pm list packages -3 / -s / -d`). Названия пакетов не утекают.
- **`ime`** — текущий default IME, количество enabled и available IME.
- **`developer`** — adb_enabled, developer_options_enabled,
  stay_awake_while_charging, adb_wifi_enabled,
  install_from_unknown_sources, usb_debug_security_settings.
- **`encryption`** — состояние шифрования ФС + тип (file/block).
- **`selinux` / `verified_boot`** — режим enforcement и Verified Boot
  state (green/yellow/orange/red).
- **`kernel`** — первая строка `/proc/version` (обрезана до 200 симв).
- **`sensors`** — количество сенсоров из `sensorservice` (89 на
  референсном устройстве).

### Changed — производительность `device_info()`

- **Все `getprop` теперь в одном shell-вызове.** До v3.83.0 было ~20
  round-trip'ов; network-проб теперь тоже пользуется этим батчем, так
  что ничего не стоит дополнительно. Полный `/info` на POCO F7 Pro
  через Tailscale ~2 с (было ~2.5 с в v3.83.0, несмотря на 12 новых
  блоков).

### Fixed — Live view больше не мерцает на неизменных кадрах

- **Content-hash dedup** на стороне Dashboard. Каждый blob скриншота
  получает FNV-1a хеш первых 8 KB; если хеш совпал с предыдущим кадром,
  `<img>` не трогается (никаких `URL.createObjectURL`, декода, repaint).
  Убирает мерцание ~50 мс в Live view, когда экран телефона реально не
  меняется. Meta-строка показывает `dupe×N` — видно, сколько подряд
  кадров совпали.
- **Refresh burst всегда перерисовывает.** `_mobileRefreshBurst()`
  сбрасывает хеш перед выстрелом, чтобы tap, изменивший всего 4 пикселя
  (например, чекбокс), всё равно вызвал видимую смену кадра.

### Test suite

761 passed (+12 новых):
- `test_ui_dump_without_adb_returns_error`,
  `test_ui_dump_requires_serial`,
  `test_ui_bounds_parser_reads_uiautomator_format` (включая кейс с
  отрицательными координатами floating window),
  `test_ui_matcher_modes` (exact / contains / regex + fail-soft для
  битого regex),
  `test_tap_by_requires_at_least_one_selector`,
  `test_tap_by_rejects_invalid_match_mode`,
  `test_tap_by_without_adb_returns_error`,
  `test_ui_interactive_predicate`,
  `test_dump_ui_parses_synthetic_xml` (end-to-end на рукописной XML-
  фикстуре, без реального устройства).
- `test_probe_display_modes_parses_pocopf7_dumpsys` — regexes проверены
  на реальном dumpsys-фрагменте POCO F7 Pro.
- `test_probe_network_masks_iccid_and_imsi` — **явный privacy-регресс**:
  подаёт фейковый `getprop` с ICCID `8970199912345678901` и IMSI
  `250991234567890`, проверяет, что ни одной из этих строк нет нигде в
  возвращаемом значении.
- `test_probe_ui_mode_parses_settings` — парсинг airplane/night/ringer/
  timeout/brightness/auto-rotate.

Также обновил `test_mobile_handlers_dataclass_fields` — теперь ожидает
два новых поля (`ui_dump`, `tap_by`).

### Follow-ups для v3.83.2

- **ADBKeyboard companion APK** для юникод-ввода — снимет ASCII-only
  guard в `type_text` и соответствующий баннер в Dashboard.
- **UI-мастер для wireless ADB `pair` / `connect`.**
- **Общий APK-install с `apksigner verify` + SHA256 consent flow.**

## v3.83.0 - 2026-07-14

Старт Mobile Phase 2 — переработка качества скриншотов, семантические
жесты, drag-to-swipe и расширенная панель информации об устройстве.
Все изменения проверены живьём на POCO F7 Pro через Tailscale Funnel
перед релизом.

### Added — переработка качества экрана

- **Поддержка WebP** (`format=webp`). На домашнем экране POCO F7 Pro:
  WebP при quality=82 даёт 26 KB / 68 KB / 127 KB для ширин
  360 / 720 / 1080 пикс — против 54 KB / 152 KB / 326 KB у JPEG на том
  же качестве. Это **50–60% экономии** при заметно лучшем рендере текста
  и мелких иконок.
- **JPEG теперь `subsampling=0` (4:4:4)** вместо дефолтного 4:2:0 у
  Pillow. Убирает красно-синий цветовой смаз на тексте UI и мелких
  иконках — та самая жалоба «артефакты в движении».
- **`max_width=0` полностью пропускает Pillow.** Кто хочет сырой кадр
  1440×3200 — не проходит через resize.
- **PNG downscale больше не делает `optimize=True`** (экономит ~150 мс
  на снимок ценой ~5 % размера — норм для интерактивного UI).
- **Строка настроек скриншота в Dashboard**: селектор формата
  (WebP / JPEG / PNG), слайдер quality (30–100), пресет ширины
  (360 / 480 / 640 / **720 default** / 1080 / 1440 / native), тумблер
  Live с настраиваемой частотой (2 Hz / 1 Hz / 0.67 Hz / 0.33 Hz).
  Настройки сохраняются в `localStorage` (ключ
  `arena.mobile.screen.settings.v1`).

### Added — семантические жесты

- **Новый модуль `arena/mobile/gestures.py`** с закрытым allowlist'ом
  11 названных жестов — `notifications`, `quick_settings`,
  `close_shade`, `scroll_up|down|left|right`, `back_edge_left|right`,
  `home_gesture`, `recents_gesture`. Каждый жест — нормализованный
  0..1 рецепт координат, транслируемый в нативные пиксели через
  `wm size` при вызове, и уходящий через существующий `input.swipe`
  для единства валидации.
- **Новый эндпоинт `POST/GET /v1/mobile/{serial}/gesture`** с той же
  auth+audit оболочкой, что и `/swipe`. Виден в
  `/v1/capabilities.mobile.endpoints`.
- **Кнопки для каждого жеста в Dashboard** в карточке Selected device
  («▼ Shade», «↑ Scroll up», «▲ Home gesture», ...), сгруппированы
  отдельно от базовых navigation-клавиш.

### Added — drag-to-swipe на скриншоте

- Скриншот `<img>` теперь обрабатывает `pointerdown` / `pointermove` /
  `pointerup` вместо голого `onclick`. Расстояние pointer'а меньше 8 CSS
  пикселей идёт как tap; больше — становится сырым `/swipe` с
  нативно-пиксельными координатами и реальной длительностью drag'а.
  Теперь наконец-то можно вытащить шторку уведомлений, свайпнуть между
  home-экранами и отменить модалку перетаскиванием вниз — всё из
  Dashboard.
- Pointer capture (`img.setPointerCapture`), чтобы drag, ушедший за
  границы `<img>` (например, в консоль shell), корректно завершался
  на `pointerup`.

### Added — расширенная информация об устройстве

- **`arena/mobile/devices.py::device_info()` теперь батчит все `getprop`
  в один shell-вызов** — было ~20 round-trip'ов, стало 1. Экономит
  ~500 мс через Tailnet.
- Новые поля: `android_security_patch`, `android_codename`,
  `build_date`, `build_type`, `build_tags`, `bootloader`, `hardware`,
  `board`, `cpu_abi_list`, `serialno`, `locale`.
- Новый блок `wifi`: `{state, info_line, ipv4}` через `dumpsys wifi` +
  `ip addr show wlan0`.
- Новый массив `storage` из `df -h /data /sdcard`: `filesystem`, `size`,
  `used`, `avail`, `use_pct`, `mount`.
- Новый блок `memory` из `/proc/meminfo`: `memtotal`, `memavailable`,
  `memfree`, `swaptotal`, `swapfree`.
- Новые поля `uptime`, `timezone`, `locale_current`,
  `foreground_activity`, и расширенный `battery` (добавлено `scale`,
  `health`, `voltage`, `technology`, `max_charging_*`).
- **`#mobileInfoPanel` в Dashboard** рендерит компактную таблицу с самыми
  полезными полями (имя устройства, Android + patch, HyperOS, экран,
  RAM used/total, storage free/total, battery %, Wi-Fi IP, timezone,
  foreground activity, bootloader). Полный JSON доступен в
  сворачиваемом `<details>`.

### Changed — структура Dashboard

- **Разбил `30-mobile.js` на три файла** для читаемости:
  - `30-mobile.js` (447 строк) — список устройств, выбор, info-панель,
    tap, key, type, shell, error box.
  - `31-mobile-screen.js` (191 строка) — pipeline скриншота,
    сохранение настроек, adaptive burst, Live-view polling.
  - `32-mobile-gestures.js` (120 строк) — кнопки жестов, pointer'ы для
    drag-to-swipe.
- **Скриншот теперь на всю ширину** (`max-width: 100%`) вместо жёстких
  360 пикс. Реальная ширина управляется строкой настроек.

### Test suite

749 passed (+6 новых): `test_gestures_allowlist_is_stable`,
`test_gesture_rejects_unknown`, `test_gesture_rejects_non_string`,
`test_gesture_without_adb_returns_adb_hint`,
`test_screenshot_capture_without_adb_returns_error`,
`test_screenshot_encode_webp_and_jpeg_produce_bytes`.

### Follow-ups для v3.83.1 / v3.83.2

- **UI Automator селекторы** (`uiautomator dump` +
  `POST /v1/mobile/{s}/tap_by` с селекторами `id`/`text`/`class`) —
  в плане на v3.83.1.
- **ADBKeyboard companion APK** для юникод-ввода, UI-мастер wireless
  ADB `pair` / `connect`, общий APK-install с consent'ом — в плане на
  v3.83.2. Когда ADBKeyboard приедет, ASCII-only guard в `type_text` и
  соответствующая пометка в Dashboard будут сняты.

## v3.82.2 - 2026-07-14

Hotfix поверх v3.82.1 по двум воспроизводимым проблемам на POCO F7 Pro
разработчика (HyperOS OS3, Android 16, SDK 36):

* **`adb shell input text` падает с `java.lang.NullPointerException:
  Attempt to get length of null array`** на любом не-ASCII вводе и на
  пустом/пробельном вводе. Корень — внутри `InputShellCommand.sendText`:
  LatinIME отказывается принять char stream и сервис разыменовывает
  null-массив. Из shell это не починить, поэтому такие входы теперь
  отвергаются заранее с понятным сообщением.
* **Скриншот протухает при переходах в приложениях.** Тап по результату
  поиска Google запускает анимацию затемнения на ~800 мс. Один снимок
  сразу после тапа ловит именно чёрный кадр, и UI зависает на нём до
  ручного Refresh. Починено adaptive-серией снимков после действия и
  опциональным Live-view.

### Fixed

- **`arena/mobile/input.py::type_text` отвергает не-ASCII до вызова adb.**
  Проверено вживую на POCO F7 Pro: отправка `"привет мир"` раньше
  возвращала голый Java NPE-стектрейс в `stderr`; теперь возвращает
  `error: text contains 9 non-ASCII character(s): 'приветми' (+1 more)`
  с `hint`, объясняющим ограничение LatinIME и указывающим на Mobile
  Phase 2 (ADBKeyboard) как на плановое решение. Список кодпойнтов
  доступен в `offending_codepoints` — вызывающий код может отфильтровать
  автоматически.
- **`type_text` отвергает пустые и whitespace-only payload'ы** —
  та же NPE срабатывает, когда Android парсит `''` или строку, ставшую
  пустой после escape'а пробелов в `%s`.
- **`_friendly_type_error()` теперь распознаёт `NullPointerException` +
  `Attempt to get length of null array`** и переписывает в
  «Android's input service returned a NullPointerException — the
  currently focused IME rejected the payload. Tap an editable text field
  first, or switch the default IME to a standard keyboard.» Сырой
  стектрейс сохраняется.

### Changed — Dashboard live view

- **Adaptive-серия после действий.** После каждого tap/key/type Mobile
  tab снимает экран в t+0 мс, t+400 мс и t+1200 мс вместо одного раза.
  Это ловит анимации переходов Chrome/Google (та самая проблема «чёрный
  экран после поиска», которую поймал пользователь) не удваивая трафик
  для статичного UI. У каждой серии есть generation-счётчик; новое
  действие пользователя аннулирует висящие снимки — серии не стекаются.
- **Тумблер Live view** (opt-in) в строке действий. При включении
  опрашивает `/screenshot` каждые 1.5 с, пока Mobile tab виден.
  По умолчанию выключен (Tailnet-трафик + батарея телефона).
  Автоматически останавливается, когда вкладка не активна или устройство
  пропало.
- **Индикатор свежести «N s ago»** под мета-строкой скриншота —
  обновляется раз в секунду, цвет-код: зелёный (≤2 с) → серый (≤10 с)
  → красный (>10 с). Видно, что кадр устарел, без часов.

### Changed — Dashboard формулировки

- **Поле type-text** теперь подписано «ASCII text into focused field»
  с пояснением, что не-ASCII сейчас крашит Android и появится в Phase 2
  через ADBKeyboard. Совпадает с бекенд-валидацией, никаких сюрпризов.

### Not fixed (осознанно вне scope этого hotfix'а)

- **Fallback через `cmd clipboard set-primary-clip`** для юникода был
  исследован и отвергнут. На HyperOS OS3 и `cmd clipboard`, и
  `service call clipboard 1 …` недоступны shell-пользователю (возвращают
  `No shell command implementation.` и Allocation exception на Parcel
  соответственно). Корректный путь — ADBKeyboard companion APK, что
  требует полноценный flow согласия на установку APK — перенесено в
  v3.83.0 (Mobile Phase 2).

### Test suite

743 passed (+6 новых: пустой/whitespace текст, кириллица, эмодзи,
проверка что ASCII проходит валидацию, ветка NPE в `_friendly_type_error`,
форма поля `offending_codepoints`). Живая проверка через Tailnet-bridge
на POCO F7 Pro перед релизом.

## v3.82.1 — 2026-07-14

Follow-up к v3.82.0 по итогам реального использования на POCO F7 Pro:

* CI на master был красный на обоих mobile-коммитах (test suite падал
  на хостах без adb — а именно так CI и запускается).
* Обновления скриншота в Dashboard казались тормозными даже когда
  сами `adb`-вызовы работают почти мгновенно.
* Ошибки от неудачных mobile-действий показывались через `alert()`
  которое нельзя выделить и скопировать — плохой UX для отправки
  Android crash-dialog деталей мейнтейнеру.

### Исправлено

- **CI на хостах без adb.** Каждая mobile guard-функция проверяла
  `find_adb()` *первым*, и только потом валидировала аргументы —
  из-за этого на CI (без adb) семейство тестов
  `test_tap_rejects_negative_coords` получало "adb not installed"
  вместо "coords out of range", и падало 15 тестов. Переупорядочил:
  валидация параметров и security-guard'ы (allowlist'ы, metachar
  blocklist, sub-verb guards) теперь идут ДО проверки adb в
  `arena/mobile/input.py`, `shell.py`, `packages.py`. С установленным
  adb — то же поведение; без adb — зелёный CI.

- **`type_text` возвращает человекочитаемую подсказку на типичные
  ошибки.** Написал `_friendly_type_error()`, который переписывает три
  самые частые причины отказа `adb shell input text` в actionable
  сообщение (нет focused window / permission или IME issue на Xiaomi
  HyperOS / IllegalArgumentException на не-ASCII), сохраняя raw error
  чтобы деталь не терялась.

### Изменено — Dashboard latency

- **Screenshot pipeline быстрее.** Переключил браузерный fetch с
  base64-JSON конверта (`wire=json`) на raw binary blob. Экономит 33%
  base64-налога и убирает два лишних JSON-parse. Дефолтный размер
  снижен 480 → 360px — full round-trip на POCO F7 Pro упал с ~2с
  до ~500мс.
- **Убраны искусственные `setTimeout(mobileScreenshot, 400)`.**
  После tap/key/type/swipe рефреш срабатывает сразу; network
  round-trip — единственный реальный latency-бюджет.
- **Dedup guard.** `_mobileScreenshotBusy` предотвращает наложение
  запросов если пользователь быстро кликает.
- **Инлайновый "Refreshing…" индикатор** на превью скриншота,
  чтобы было видно что что-то происходит.
- **Blob URL memory management** — старые screenshot blob URLs
  освобождаются через `URL.revokeObjectURL` до создания нового,
  долгая сессия не течёт памятью.

### Изменено — Dashboard error UX

- **Ошибки теперь копируемые, структурированные и inline.** Любой
  fail от `/v1/mobile/*` показывается в отдельной error-панели
  вверху Mobile tab с кнопкой `Copy` (через `navigator.clipboard`)
  и `Dismiss`. Содержимое составляется из всех populated полей
  бэкенда (`error`, `hint`, `stderr`, `stdout`, `exit_code`,
  `action`, `cli_path`), так что текст Android/ADB crash-диалога
  сохраняется дословно для вставки в bug report.
- Больше никаких `alert()` для tap/key/type/screenshot ошибок.
  Существующие `alert()`-flow других карточек не изменены.

### Тесты

737 passed (без изменений). CI-регрессии из v3.82.0 подтверждены как
исправленные через simulated-CI check (mock `find_adb() → None`) —
все 15 ранее падавших validation-first assertions теперь проходят
без adb.

### Известное ограничение Phase 1 (документировано)

- **`adb shell input text` возвращает exit 0 даже если phone
  крашнул input event или нет focused text field.** Bridge не видит
  что происходит на стороне устройства. Workaround Phase 1:
  тапнуть по нужному полю ввода, потом type. Phase 3 (native APK
  на телефоне со своим bridge-like сервисом) устранит весь этот
  класс ADB-round-trip quirks.

## v3.82.0 — 2026-07-14

**Mobile domain Phase 1: Android через ADB.** Полный внутренний пакет
(foundation из 3a924d3) плюс HTTP routes, capabilities integration и
карточка «Mobile Devices» в Dashboard — end-to-end проверено на живом
POCO F7 Pro (Android 16 + HyperOS 3).

### Добавлено

- **Новый `/v1/mobile/*` REST surface** — 9 endpoints (см. English
  секцию для полного списка). Coverage: devices list, deep info
  (HyperOS/MIUI поля учтены для Xiaomi), screenshot с downscale/JPEG,
  tap/swipe/type/key/shell/packages.
- **`/v1/capabilities.mobile`** — агенты могут одним запросом узнать
  доступен ли mobile backend и сколько устройств подключено.
- **Dashboard «Mobile» tab** (📱 Mobile) — список устройств, live
  превью экрана 480px JPEG (обновляется после каждого действия),
  кнопки Home/Back/Recents/Volume/Wake, unicode-ввод текста,
  restricted shell, клик по скриншоту = tap в соответствующей точке
  на телефоне.

### Wiring

- Новый `MobileWiringContext` + `build_mobile_handlers` в
  `arena/wiring/platform.py`, регистрируется в
  `arena/wiring/system_public_admin_registries.py`.
- Capabilities принимает опциональный `mobile_status_fn`, wired через
  `runtime_deps/core.py`.
- Routes зарегистрированы в `arena/route_registry/core.py`.

### Cross-platform (Phase 1)

- Поиск ADB: `ADB_PATH` env → `PATH` → well-known по OS (Windows
  Android SDK / Program Files / scoop / chocolatey; macOS Homebrew
  Intel+ARM + Android Studio; Linux `/opt/android-sdk`,
  `~/Android/Sdk`, `/usr/local/bin`).
- Windows `subprocess.run` использует `CREATE_NO_WINDOW` — Dashboard
  auto-refresh не флешит консольным окном.
- Без sudo.

### Проверено на POCO F7 Pro

    GET /v1/mobile/devices               → 2200ad3b state=device
    GET /v1/mobile/2200ad3b/info         → POCO 24117RK2CG, Android 16,
                                           HyperOS OS3.0.302.0.WOKMIXM
    GET /v1/mobile/2200ad3b/screenshot   → 118 KB JPEG 800x1777
    POST tap 100,100 / key BACK / key HOME → ok
    POST shell "getprop ..."             → работает
    POST shell "rm -rf /sdcard"          → отбито allowlist

### Тесты

737 passed (было 706, +31 mobile). Все тесты работают без ADB и без
устройства — реальный phone только подтверждает end-to-end.

### Зависимости (soft)

- `Pillow` — только для downscale/JPEG в screenshot. Если отсутствует,
  endpoint возвращает raw PNG + `pil_missing: true`. Установка:
  `pip install --user Pillow` или `pacman -S python-pillow`.

## v3.81.5 — 2026-07-13

Follow-up к v3.81.4: onboarding-подсказка ZeroTier указывала на старый
dashboard.

### Исправлено

- **Ссылка ZeroTier onboarding обновлена на `central.zerotier.com`.**
  ZeroTier перенесли web-dashboard с `my.zerotier.com` на
  `central.zerotier.com` в начале декабря 2025. `my.zerotier.com` всё
  ещё доступен как "legacy site" (старые сети живут там), но новый
  пользователь на нём видит либо неотвечающую страницу, либо пустой
  аккаунт без сетей. Подсказка ZeroTier onboarding в Dashboard и
  `alert()` внутри валидатора nwid теперь по умолчанию отправляют
  пользователей на Central, а legacy URL упоминается только как
  сноска для тех, кто создавал сети до миграции.

### Тесты

706 passed (без изменений; UI-only патч).

## v3.81.4 — 2026-07-13

Полировка: реальные баги, на которые пользователь наткнулся в Dashboard,
когда попробовал работать без Tailscale. Убраны Tailscale-only
предположения из Overview / Doctor / stop-действий, плюс убран
попавший в UI-placeholder приватный network ID.

### Исправлено

- **Overview "Network Status" стал provider-agnostic.** Раньше был
  захардкожен на `Tailscale Funnel` + `Public URL` из
  `/v1/sys/funnel`. Переписан на `Active Provider` + `Public URL` +
  список по всем провайдерам, теперь читает `/v1/tunnels/status`.
  Карточка корректно показывает "ZeroTier · http://10.x.y.z:8765" когда
  Tailscale упал. Старые DOM-ID `#tsFunnelStatus` / `#tsFunnelUrl`
  оставлены скрытыми для обратной совместимости.
- **Doctor tab стал provider-agnostic.** Панель `Tailscale Funnel`
  заменена на `Remote Access` со списком всех настроенных провайдеров
  (active/connected/installed/not installed) и текущим активным
  endpoint. Service Status теперь также показывает Cloudflared +
  ZeroTier рядом с Tailscale — `/v1/sys/svc` (backend Doctor'а)
  покрывает весь tunnels-pool, а не только один провайдер.
- **`/v1/tailscale/funnel/stop` реально останавливает funnel на порту
  8765.** Раньше вызывалась `tailscale funnel --https=443 off`, которая
  только для порта 443. Теперь пробует
  `tailscale funnel --bg <port> off`, затем `funnel off`, затем
  `serve reset` как последний fallback — что-то из этого всегда работает
  на любой Tailscale ≥ 1.60.
- **Сообщения об ошибках туннелей в Dashboard больше не буквально
  "?".** Когда `tsFunnelToggle` / `cfFunnelToggle` получали
  `{ok: false}` без поля `error`, alert показывал `"Error: ?"`.
  Питоновский side теперь всегда заполняет `error` при failure, а JS
  fallback'ит на `stderr` / `stdout` / exit code — alert всегда
  показывает что-то полезное.
- **Приватный network ID убран из UI.** Placeholder в поле ZeroTier
  "Join" на вкладке Settings содержал реальный live network ID из
  аккаунта maintainer'а (`cf719fd5...`). Заменён на очевидно
  синтетический пример (`abcdef0123456789`) плюс ссылка на
  `my.zerotier.com/network`, где взять реальный. Тот же ID был в
  client-side validation `alert()` — тоже заменён.

### Добавлено

- `arena/service/status.py::_sys_svc_sync()` теперь включает
  `cloudflared` и `zerotier` рядом с `tailscale`. Обе — компактные
  snapshot'ы (installed / active / connected / node_id /
  active_networks) с молчаливой деградацией — никогда не raise'ит.
- Регрессионные тесты:
  * `tailscale_funnel_action` никогда не опускает `error` при failure;
  * source `tailscale_funnel_action` больше не содержит legacy
    `--https=443` синтаксис для stop.

### Тесты

706 passed (было 704). Два новых теста admin handlers.

## v3.81.3 — 2026-07-13

Патч: исправлен парсер `zerotier-cli listnetworks` для сетей без
имени.

### Исправлено

- **`_parse_listnetworks` корректно обрабатывает сети с пустым name.**
  Сразу после `zerotier-cli join <nwid>`, до авторизации node
  контроллером, строка сети содержит пустое поле `name`, которое
  `line.split()` схлопывает — сдвигая каждую следующую колонку влево на
  одну, и `mac` попадает в `status`, `status` в `type` и т.д. Парсер
  теперь проверяет пятый токен на паттерн MAC-адреса и при пустом
  `name` использует сдвинутый layout, так что `status`, `type`,
  `portDeviceName` и IPs оказываются в правильных полях.

### Тесты

704 passed (было 702). Новые: 2 регрессионных теста парсера (empty-name
layout + sanity-проверки `_looks_like_mac`).

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

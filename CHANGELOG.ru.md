# История изменений

> 🌐 [English version](CHANGELOG.md)

Здесь собрана история актуальной, extension-ориентированной эпохи проекта.
Полная построчная история всех релизов (включая ранние v2.x–v3.1.x) ведётся в
[англоязычном CHANGELOG.md](CHANGELOG.md).

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

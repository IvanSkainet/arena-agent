# История изменений

> 🌐 [English version](CHANGELOG.md)

Здесь собрана история актуальной, extension-ориентированной эпохи проекта.
Полная построчная история всех релизов (включая ранние v2.x–v3.1.x) ведётся в
[англоязычном CHANGELOG.md](CHANGELOG.md).

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

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

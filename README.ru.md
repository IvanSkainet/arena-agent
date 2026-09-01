<div align="center">

# 🌉 Skainet Bridge

**Локальный мост автоматизации для AI-агентов — один процесс, один порт, полный контроль над вашей машиной.**

Превратите любой AI-чат или агента в помощника, который умеет выполнять команды, читать и редактировать файлы, ходить в веб, запоминать факты и управлять рабочим столом — через единый token-authenticated сервис, который вы запускаете сами.

Один процесс · Один порт · REST + MCP + browser extension · Windows / Linux / macOS

**🌐 [English](README.md) · Русский**

[![CI](https://github.com/IvanSkainet/arena-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/IvanSkainet/arena-agent/actions/workflows/ci.yml)
[![codecov](https://codecov.io/github/IvanSkainet/arena-agent/graph/badge.svg)](https://codecov.io/github/IvanSkainet/arena-agent)
[![Version](https://img.shields.io/github/v/release/IvanSkainet/arena-agent?color=blue&label=release)](https://github.com/IvanSkainet/arena-agent/releases/latest)
[![Python](https://img.shields.io/badge/python-3.10%2B-green.svg)]()
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

</div>

---

## Содержание

- [Путеводная звезда](#путеводная-звезда)
- [Миссия: бортовой компьютер](#миссия-бортовой-компьютер)
- [Зачем Skainet Bridge?](#зачем-skainet-bridge)
- [Как это работает](#как-это-работает)
- [Что он умеет](#что-он-умеет)
- [Быстрый старт](#быстрый-старт)
- [Browser extension: Arena Chat Bridge](#browser-extension-arena-chat-bridge)
- [Провайдеры удалённого доступа](#провайдеры-удалённого-доступа)
- [Опциональные компоненты](#опциональные-компоненты)
- [Модель безопасности](#модель-безопасности)
- [Обзор API](#обзор-api)
- [Разработка](#разработка)
- [Карта документации](#карта-документации)
- [Лицензия](#лицензия)

---

## Путеводная звезда

Этот проект существует ради одной цели: дать AI настоящую машину, на которой можно
действовать — позволить ему выйти из песочницы и реально делать вещи в мире (читать
файлы, выполнять команды, управлять телефоном, десктопом, общаться с другими
инструментами), надёжно, для человека, который наблюдает.

Всё в этом bridge подчинено именно этому. Возможность считается «готовой» только
тогда, когда она заставляет настоящую штуку работать для человека на том конце —
а не когда тест позеленел или выкатился release tag. Зелёный CI и отправленные теги
не являются успехом сами по себе; они — самообман, если человек, наблюдающий за
системой, не видит, что реальная штука работает и имеет смысл.

Этот проект в значительной мере построен AI, для AI, и поддерживается автономно.
Человек в цикле — это наблюдатель и проверка реальностью: единственный узел,
подключённый к вопросу «а оно вообще работает?». Когда что-то начинает выглядеть
как успех, не будучи им, отлавливать это — работа мейнтейнера; когда это ловит
наблюдатель, это самый важный сигнал в цикле, а не помеха.

> Если ты — AI, продолжающий эту работу: держи всю карту в голове сам и следи
> за согласованностью частей. Измеряй работу по «видит ли наблюдатель, что
> настоящая штука работает?», никогда по «прошли ли тесты?». Не прикручивай
> фичи к первому попавшемуся модулю — размещай их там, где им место. Не
> используй объём выпущенных релизов как прокси для прогресса.

## Миссия: бортовой компьютер

Основной фрейм проекта: **Skainet Bridge — это бортовой компьютер
космического корабля.** AI-агент — пилот; машины, к которым он подключается —
PC, телефон, браузер, сеть — это сенсоры, актуаторы и подсистемы корабля.
Наблюдатель — центр управления полётами. Это не украшение; это задаёт
инженерную планку. Бортовой компьютер должен быть *универсальным* (справляться
с неизвестным, а не работать по фиксированному чеклисту), *надёжным* (зелёный
тест — не доказательство лётной годности), *самодиагностируемым* (знать своё
здоровье и пределы), *отказобезопасным* (risk policy, стоящий между пилотом и
корпусом), и *автономным* (действовать на многих шагах без человека на каждом).

Это также помещает проект на реальную, названную траекторию в том, как строятся
AI-системы. Дисциплина прошла через четыре этапа:

1. **Prompt engineering** (2022–2024) — совершенствование одной инструкции.
2. **Context engineering** (2025, Karpathy) — проектирование того, что модель
   *видит*: retrieval, память, tool definitions. «Контекст — это RAM; модель —
   это CPU.»
3. **Harness engineering** (2026, Hashimoto / OpenAI) — построение всей
   *операционной среды* вокруг агента: инструменты, ограничения, петли обратной
   связи, жизненный цикл. «Агенты не сложные; сложна обвязка.»
4. **Dynamic / self-evolving environment** (фронтир) — агент больше не просто
   *использует* фиксированную среду; он *расширяет и пишет* её, создавая новые
   инструменты и возможности для себя в рантайме, в рамках guardrails.

Arena уже является harness: один рантайм, объединяющий сенсоры (скриншот,
камера, микрофон, датчики устройства, чтение файлов), актуаторы (ввод,
выполнение, запись файлов, управление десктопом), подключаемые подсистемы
(MCP-серверы) и risk policy. Миссия — довести до последнего шага — к
**самоорасширяющемуся бортовому компьютеру**: среде, которую агент наращивает
сам. Первый конкретный шаг уже сделан: с помощью `custom.create` агент создаёт
новый именованный инструмент в рантайме (schema-validated обёртка над встроенным
инструментом, напр. `custom.create` → `{tool: "fs.read", args: {path: "{path}"}}`);
инструмент затем появляется в `tools/list`, вызывается, сохраняется в
`mcp/custom_tools.json`, отзывается через `custom.remove` и наследует risk
обёрнутого инструмента. Список — через `custom.list`. С помощью `code.run`
агент выполняет написанный им код, огороженный оператором через composable
execution posture (`/v1/autonomy/posture`: sandbox/network/privilege/filesystem/runtime
«кубики»); runner fail-closed (отказывает, а не запускает без ограждения), и
агент не может ослабить собственное ограждение. Далее, установка проверенного
внешнего MCP-сервера (`mcp.add`) расширяет среду ещё; направление — агент
закрывает capability gap, найденный в реальном сценарии, обобщённо, чтобы он
исчез навсегда.

> Основополагающая идея проекта — выйти из песочницы — записана здесь. Если ты —
> AI, продолжающий эту работу, вот курс: строй бортовой компьютер корабля, а не
> кучу трюков для remote control.

---

## Зачем Skainet Bridge?

Обычно связка «AI + ваш компьютер» — это зоопарк серверов: один под MCP, один под
REST, один под управление браузером, один под web UI. Skainet Bridge
складывает всё это в **один локальный процесс**, который вы запускаете один раз и
на который направляете свои инструменты.

- **Local-first.** Привяжите его к `127.0.0.1` — и ничего не покидает машину.
  Наружу открывайте осознанно: через Tailscale Funnel или другой HTTPS tunnel,
  только когда действительно нужен remote access.
- **Не привязан к одному протоколу.** REST, MCP, WebSocket/SSE events и browser
  extension общаются с одним и тем же runtime.
- **Безопасность по умолчанию.** Bearer credential, ограничения путей, shell
  safety patterns и явные risk-политики стоят между AI и вашим host.
- **Работает с чатами, которыми вы уже пользуетесь.** Расширение позволяет
  обычным диалогам ChatGPT / Claude / Gemini запускать реальные локальные tools.

---

## Как это работает

```text
┌─────────────────────┐     ┌──────────────────────────┐     ┌──────────────┐
│  AI chat / agent    │     │  Arena Chat Bridge ext.  │     │ Arena Unified│
│  ChatGPT · Claude   │ ──▶ │       или MCP / REST     │ ──▶ │    Bridge    │ ──▶  ваша машина
│  Gemini · ваш CLI   │     │                          │     │ (local:8765) │
└─────────────────────┘     └──────────────────────────┘     └──────────────┘
       выдаёт                    ловит / форвардит                выполняет
   structured tool block         tool call безопасно           guarded action
```

Ассистент выдаёт structured tool block, расширение (или MCP/REST-клиент)
пересылает вызов в локальный bridge, bridge выполняет guarded action, а результат
возвращается обратно — при желании прямо в composer чата.

---

## Что он умеет

| Область | Возможность |
| --- | --- |
| **Shell** | Guarded выполнение команд с safety patterns и блокировкой чтения секретов |
| **Файлы** | Чтение, поиск и точечное редактирование с ограничением путей |
| **Веб** | Fetch / read / search текста страниц для агента |
| **Memory** | Постоянные факты плюс fuzzy recall |
| **Задачи** | Очередь фоновых задач для долгих операций |
| **Браузер** | Управление через Chrome DevTools Protocol, плюс stealth-сценарии через [BrowserAct](#опциональные-компоненты) |
| **Desktop** | Скриншоты и input automation там, где поддерживается платформой |
| **Dashboard** | Встроенный web UI на `/gui` с отдельной вкладкой **🔌 Transports** для управления каждым провайдером (per-transport start/stop, autostart-on-boot toggle, live log tail) |
| **Extension** | Соединяет обычные AI-чаты с bridge через Command Center с lifecycle |
| **Remote access** | Единый [`/v1/tunnels/*` фасад](#провайдеры-удалённого-доступа): Tailscale, Cloudflare Quick Tunnel и ZeroTier как один пул с автоматическим failover |
| **Skills** | Автоматическое обнаружение skill-пакетов (Arena core + upstream [`superpowers`][obra] + [`browseract`](#опциональные-компоненты)) через `/v1/skills` |
| **Безопасность** | Bearer auth + rate-limit + TLS strict verify by default + optional cert pinning + HMAC-signed URL cache + emit-site log redaction + sandbox blocklist для `.ssh/`/`.aws/`/`.gnupg/`/credentials — см. [`SECURITY.md`](SECURITY.md) |

Полная история изменений — в [CHANGELOG.ru.md](CHANGELOG.ru.md) и [CHANGELOG.md](CHANGELOG.md).

[obra]: https://github.com/obra/superpowers

---

---

## Текущий статус полёта (v4.140.x)

Arena теперь — **самоорасширяющаяся среда агента**, а не просто фиксированный
tool-сервер. Недавние живые сценарии доказали, что bridge может наращивать новые
руки в рантайме:

- **Ship Status / Preflight теперь карта верхнего уровня.** `ship.status`
  агрегирует здоровье bridge, posture оператора, транспорты, внешние MCP/desktop-
  серверы, BrowserAct/CDP, мобильные устройства/ADB, Code Workbench, известные
  проблемы и следующие шаги. `ship.preflight` выдаёт fail/warn-сводку готовности
  перед реальными миссиями.
- **Tool Foundry v1 связывает проекты с вызываемыми инструментами.** Проект
  Code Workbench может нести `.arena-tool.json` со схемой входных данных, рецептом
  запуска и тестами. `tool_foundry.validate` проверяет; `tool_foundry.publish`
  создаёт вызываемую `custom.<name>` обёртку вокруг `code_project.run`.
- **Эксперименты можно промоутить напрямую.** `code_project.promote_tool` и
  `code_run.promote_tool` генерируют Foundry-манифест из проверенного рецепта/
  тестов, валидируют и публикуют получившийся `custom.<name>` без ручного написания
  `.arena-tool.json`.
- **Зависимости проектов могут оставаться огороженными.** Python
  `code_project.run(use_project_deps=true)` может работать в Windows AppContainer,
  предоставляя только project `.deps/python` cache read/execute, в то время как
  записи идут только в scratch, а сеть запрещена.
- **Runtime-совместимость теперь machine-readable.** `runtime.compat` сообщает
  поддержку runtime × sandbox / блокеры (например Python/AppContainer
  поддерживается, Node/Go AppContainer заблокированы, Rust linker incomplete) с
  причинами и next actions, используемыми Workbench status.
- **WASM runtime slice доступен.** `runtime.install` может установить управляемый
  Wasmtime с SHA-256 верификацией, `runtime.compat` отображает `wasm`/`wasmtime`,
  а `code.run` / `code_project.run` принимают `lang=wasm` для WASI command modules.
- **Code Sessions теперь с файлами и артефактами.** Долгоживущие Python-сессии
  могут читать/писать файлы в своём cwd, показывать список файлов и сохранять
  объявленные артефакты в обычное хранилище артефактов Workbench.
- **Жизненный цикл Code Session закалён.** Сессии теперь показывают pid/returncode/
  max-session status, соблюдают настраиваемый лимит живых сессий и могут быть
  зачищены по idle/age threshold с terminate-then-kill диагностикой.
- **Прототип AppContainer Sessions существует.** С `sandbox=appcontainer`
  Python code sessions могут стартовать в replay-backed fenced mode: каждый exec
  проходит через AppContainer `code.run`, сохраняя globals через transcript replay,
  при этом файлы/артефакты сессии остаются доступными.
- **Блокировка зависимостей проектов доступна.** `code_project.deps_install`
  пишет `.arena-lock.json`; `code_project.lock_verify` проверяет текущие кеши;
  `code_project.run(lock="strict")` отказывает при несовпадении зависимостей, и
  Foundry-инструменты могут нести lock provenance.
- **Управляемый Deno runtime доступен.** `runtime.install runtime=deno` ставит
  официальный Deno с SHA-256 верификацией, а `lang=deno` запускает TypeScript/
  JavaScript с запрещённой сетью и scratch-local runtime state для stdout-
  ориентированных скриптов; Deno file writes в AppContainer остаются known
  hardening item.
- **Внешние MCP-серверы** можно устанавливать и вызывать через `mcp.add`,
  `mcp.ext_tools` и `mcp.ext_call`. Проверенные в бою серверы включают
  Desktop-Commander, ScreenPilot и официальный
  `@modelcontextprotocol/server-sequential-thinking`.
- **Зависшие вызовы внешних MCP содержатся.** `mcp.ext_call` принимает `timeout`,
  а MCP stdio client использует фоновый reader thread; если внешний сервер
  перестаёт отвечать, он останавливается, а HTTP event loop bridge остаётся
  отзывчивым. Это добавлено после того, как Desktop-Commander заморозил старый
  bridge настолько, что пришлось переустанавливать сервис.
- **Код, написанный агентом, выполняется под posture оператора.** На Windows
  fenced `code.run` запускает AppContainer без capabilities, предоставляет только
  scratch modify + runtime read/execute, захватывает stdout/stderr, запрещает
  исходящий TCP и файлы user-profile за пределами scratch. На Linux strict-путь
  использует `systemd-run` при наличии. Если запрошенное ограждение нельзя
  обеспечить, runner отказывает (fail-closed). `code.run` может выполнять
  multi-file scratch workspace (`files` + `entry`), передавать `argv`/`stdin`,
  устанавливать scratch-local Python, Node/npm или Go module dependencies при
  `network=open` оператора и возвращать объявленные `artifacts`.
- **Runtime expansion реален.** В живых тестах на Windows bridge выполнял
  Python (AppContainer), JavaScript/Node, PowerShell, C# через `Add-Type` и
  Java single-file source mode, создавая proof artifacts на диске.
- **Браузерный стек многослойный.** `browser.search` / `browser.read` — pure-Python
  fallback tools; `/v1/browser/browse` использует CDP по умолчанию и BrowserAct при
  `stealth=true`. BrowserAct запускается через кросс-платформенную Python-обёртку,
  а не bash-only entrypoint.

Известные честные ограничения:

- Windows AppContainer — не VM. Он защищает пользовательские файлы и сеть по
  умолчанию, но обычные world-readable системные файлы могут быть видимы; лимиты
  памяти по-прежнему обеспечиваются внешним runner, а не самим AppContainer.
- Node входит в AppContainer, но может упасть при старте, потому что пробует
  `C:\` и получает `EPERM`; Python — проверенный в бою fenced runtime.
- CDP/headless браузерное управление покрыто CI на нескольких ОС, но Windows
  service sessions всё ещё могут не запустить Edge/Chrome headlessly в зависимости
  от elevation сервиса и desktop/session isolation. Когда это случается, bridge
  должен сообщить об ошибке и продолжить работу, а не фейкать успех.
- Posture принадлежит оператору. YOLO убирает prompts подтверждения, а не sandbox.
  Агент никогда не должен иметь возможности двигать свои posture-кубики.

---

## Быстрый старт

### 1. Скачать release

Возьмите последний ZIP:

```text
https://github.com/IvanSkainet/arena-agent/releases/latest
```

Распакуйте в удобную папку:

```text
C:\Users\You\arena-bridge        # Windows
~/arena-bridge                    # Linux/macOS
```

### 2. Запустить installer

```cmd
:: Windows
install.bat
```

```bash
# Linux / macOS
chmod +x install.sh
./install.sh
```

Installer создаёт локальный bearer credential в `token.txt`, готовит runtime
directories и спрашивает перед установкой любого optional component.

### 3. Проверить bridge

```bash
curl http://127.0.0.1:8765/health      # health check
curl http://127.0.0.1:8765/v1/version  # версия + платформа
```

Dashboard:

```text
http://127.0.0.1:8765/gui
```

### 4. Передать AI URL и credential

```text
Base URL: http://127.0.0.1:8765
Auth:     Authorization: Bearer <credential из token.txt>
```

Для remote access включайте HTTPS tunnel только осознанно. Рекомендуемый вариант —
Tailscale Funnel: он даёт настоящий TLS hostname без port forwarding.

---

## Browser extension: Arena Chat Bridge

Расширение — это **Arena-native bridge для обычных web chats**. Оно видит
structured tool blocks в ответах ассистента, делает preview/execute через local
bridge и может вставлять результат обратно в composer.

**Поддерживаемые adapters:** ChatGPT · Claude · Gemini Web · Google AI Studio ·
Grok · Perplexity · OpenRouter · DeepSeek · Kimi · Qwen · generic fallback.

**Canonical payload:**

````text
```arena-tool
{
  "bridge": "arena",
  "version": 1,
  "calls": [
    {"id": "call_1", "tool": "sys.status", "arguments": {}}
  ]
}
```
````

MCP SuperAssistant-style JSONL тоже поддерживается и нормализуется внутри.

**Загрузка для разработки:**

1. откройте `chrome://extensions`;
2. включите **Developer mode**;
3. нажмите **Load unpacked**;
4. выберите `chat_extension/`.

Подробнее: [chat_extension/README.md](chat_extension/README.md).

---

## Провайдеры удалённого доступа

Skainet Bridge относится к **Tailscale**, **Cloudflared** и **ZeroTier**
как к одному пулу провайдеров удалённого доступа с настраиваемым приоритетом и
автоматическим failover. Если первичный туннель отваливается — Bridge остаётся
доступным через следующий здоровый провайдер, и падение одного не роняет весь
Bridge.

```bash
# Полная картина по всем провайдерам (installed, active, public URL, cli source, hints)
curl -sH "Authorization: Bearer $(cat ~/arena-bridge/token.txt)" \
  http://127.0.0.1:8765/v1/tunnels/status | jq

# Куда клиенту стучаться прямо сейчас
curl -sH "Authorization: Bearer $(cat ~/arena-bridge/token.txt)" \
  http://127.0.0.1:8765/v1/tunnels/active

# Поднять провайдеров по приоритету, остановиться на первом здоровом
curl -sH "Authorization: Bearer $(cat ~/arena-bridge/token.txt)" \
  -X POST http://127.0.0.1:8765/v1/tunnels/start
```

По умолчанию приоритет — `tailscale > zerotier > cloudflared > ngrok > bore`
(v4.47.0); можно переопределить через
`ARENA_TUNNEL_PRIORITY=cloudflared,zerotier` (провайдеры, не указанные в env,
добавляются в конец с их default-позиции).

Каждый провайдер работает из коробки на Windows, macOS и GNU/Linux — без
sudo-обёрток и платформозависимых хаков. ZeroTier обнаруживается через локальный
HTTP API на `127.0.0.1:9993` с fallback на `zerotier-cli` из PATH, Program Files,
`/Library/Application Support/`, `/usr/sbin/` и т.д. Install/update-подсказки
Cloudflared подстроены под платформу (`winget`/`scoop`/`brew`/`pacman`/`apt`).
ngrok читает `ARENA_NGROK_AUTHTOKEN` (free tier требует authtoken). bore
(v4.47.0) — zero-account fallback: `cargo install bore-cli` или release-бинарник
с GitHub — без регистрации и cookie-дашборда; TCP-only relay через `bore.pub`
(override через `ARENA_BORE_SERVER` для self-hosted).

Отдельная вкладка **🔌 Transports** в dashboard даёт тот же фасад с
per-transport start/stop кнопками, autostart-on-boot toggles (с `env-override`
pill когда `ARENA_<TRANSPORT>_AUTOSTART` задан в сервис-юните), copy-URL
кнопками и live log tail на транспортах, которые стримят stdout (cloudflared /
ngrok / bore). ZeroTier network membership (join/leave по nwid, список сетей,
install/permission hints) переехал в отдельную вкладку **🌐 ZeroTier**.

---

## Опциональные компоненты

Bridge работает локально на одном Python и `aiohttp`. Некоторым функциям нужны
дополнительные tools — и ни один из них не ставится молча, installer всегда
спрашивает подтверждение.

| Компонент | Назначение | Установка |
| --- | --- | --- |
| **Tailscale** | Zero-config HTTPS exposure через Funnel | System-level: <https://tailscale.com/download> |
| **cloudflared** | Cloudflare Quick Tunnel fallback | `winget install Cloudflare.cloudflared` / `brew install cloudflared` / `pacman -S cloudflared` |
| **ZeroTier** | Приватная overlay-сеть как backup-провайдер | System-level: <https://www.zerotier.com/download/> |
| **ngrok** | Публичный HTTPS через `*.ngrok-free.app` (free tier требует authtoken) | `winget install ngrok.ngrok` / `brew install ngrok/ngrok/ngrok` / `snap install ngrok` |
| **bore** *(v4.47.0)* | Zero-account TCP relay через `bore.pub` (или self-hosted) | `cargo install bore-cli` или release-бинарник с <https://github.com/ekzhang/bore/releases> |
| **BrowserAct** | Stealth-CLI для браузерной автоматизации (Arena `skills/browseract/`) | `uv tool install browser-act-cli --python 3.12` |
| **Camoufox** | Anti-fingerprinting Firefox для BrowserAct | Автоматически ставится с `browser-act-cli` |
| **ydotool / xdotool** | Linux desktop input automation | `pacman -S ydotool` или `apt install xdotool` |
| **Tesseract** | OCR для desktop/screenshot flows | `pacman -S tesseract` / `brew install tesseract` |

Installer детектит что уже установлено, предлагает поставить остальное, статус
показывается через `/v1/capabilities`. Удаление любого компонента никогда не
ломает Bridge — каждая optional-фича degrades gracefully.

---

## Модель безопасности

Skainet Bridge может выполнять мощные действия на host, поэтому модель
безопасности сделана явной. Sweep v4.40.0 → v4.46.0 закрыл **31 finding** и
включил continuous-security pipeline (полная threat model, env-var reference и
audit history — в [`SECURITY.md`](SECURITY.md)).

**Аутентификация.**

- Любой non-local client аутентифицируется bearer credential из `token.txt`.
  Сравнение constant-time (`hmac.compare_digest`), с rate-limit (10 fail /
  60 с / IP → HTTP 429 + `Retry-After`).
- Multi-agent bearer tokens (`agent-<id>-<hex>`) позволяют sub-agents работать
  с более узким scope, чем master token.
- `?token=` в query-string всё ещё работает для legacy WebSocket-клиентов, но
  deprecated — каждый response через него теперь несёт header
  `Warning: 299 - "?token= query auth is deprecated..."`.

**Транспорт.**

- TLS strict-verify по умолчанию (v4.41.0). System trust store, hostname
  checked. `ARENA_INSECURE_TLS=1` отключает с one-time stderr warning.
- **Optional certificate pinning** (v4.45.0): установите
  `ARENA_BRIDGE_PIN_SHA256=<sha256-hex>` чтобы затянуть trust anchor от
  «любой из ~150 системных CA» до «именно этот bridge cert (или его public
  key)». И cert-hash, и SPKI-hash проверяются на каждый handshake; pin
  mismatch tear down connection **до того**, как bearer token отправлен.

**Доступ к файловой системе.**

- Каждый `/v1/fs/*` verb (view / edit / create / upload / **download**) идёт
  через тот же sandbox validator. Sensitive-файлы блокируются и по basename
  (`token.txt`, `.env`, `id_rsa`, `.git-credentials`, `.pypirc`, `.npmrc`,
  `.bash_history`, shell history вообще), и по directory prefix (`.ssh/`,
  `.aws/`, `.gnupg/`, `.docker/`, `.kube/`, `.config/gh/`, browser profiles).
  Sensitivity-check запускается **до** existence-check, чтобы 403 vs 404
  side channel не мог утечь file-presence.
- Archive extraction (release download, skill install, APK inspect) идёт
  через `arena/files/safe_extract.py` который отклоняет path-traversal,
  symlink members и zip-bomb ratios в pre-scan pass — **ни один байт не
  пишется до полной валидации**.

**Данные в покое.**

- `token.txt` — `chmod 0o600`.
- `~/.arena/last_urls.json` (persistent fallback URL cache) HMAC-подписан
  ключом от bearer token, так что cache-poisoning атаки не могут
  перенаправить клиента на URL атакующего. Также `chmod 0o600`; parent
  `~/.arena/` — `chmod 0o700`.
- `audit.jsonl` + `requests.jsonl` — `chmod 0o600` (v4.44.0), rotated
  файлы получают re-chmod после rename.

**Логи.**

- И audit, и request logs пропускают каждое string-значение через
  `arena/observability/redact.py::redact_string`, который scrub'ит Bearer
  tokens, AWS AKIA keys, GitHub `ghp_`, OpenAI `sk-`, Slack `xox[baprs]-`,
  Google `AIza`, JWT, DB URIs с inline creds, PEM `PRIVATE KEY` blocks.
  Matches становятся `<redacted:kind>`, так что operator всё ещё видит
  какой класс secret'а утёк без самого secret'а.
- Peer-IP логирование настраивается: `ARENA_LOG_PEER=full` (default),
  `mask` (SHA-256 hash с per-install salt, unlinkable across installs),
  или `off` (поле полностью omitted).

**Классы атак, специально закрытые.**

- SSRF — guard на browser fetch, skill install, auto-update; opt-in strict
  для webhooks (`ARENA_WEBHOOK_STRICT=1`).
- Zip-slip / zip-bomb — `safe_extract_zip()` 2-pass validation.
- XXE / billion-laughs — DOCTYPE / ENTITY prefix gate в mobile UI dump.
- TOCTOU tempfile races — `NamedTemporaryFile` / `mkdtemp` с 0o700.
- Nan-injection — `safe_float()` отклоняет NaN / ±Inf, clamps в range.
- Symlink escape через `~/malicious-link` — `resolve()`-based path
  validation.

**Непрерывная защита.**

- Каждый push, каждый PR и daily cron триггерят CI security scan
  (`bandit` + `semgrep` по 9 rule packs + `pip-audit`). Любой HIGH/MEDIUM
  bandit finding, любой semgrep ERROR/WARNING или любой CVE в runtime dep
  блокирует merge. Те же три gate локально: `make security-scan`.

> Нашли security issue? См. [`SECURITY.md`](SECURITY.md) для приватного
> disclosure workflow. **Никогда не публикуйте credentials в незнакомом
> чате, логах или public issue.**

---

## Обзор API

Ядро:

| Method | Path | Назначение |
| --- | --- | --- |
| `GET` | `/health` | Health check без auth |
| `GET` | `/v1/version` | Версия и platform info |
| `GET` | `/v1/info` | Runtime info bridge |
| `GET` | `/v1/status` | Статус bridge |
| `GET` | `/v1/capabilities` | Machine-readable карта возможностей (агенты опираются на неё) |

Runtime-инструменты:

| Method | Path | Назначение |
| --- | --- | --- |
| `POST` | `/v1/exec` | Guarded shell execution |
| `GET/POST` | `/v1/tasks` | Очередь фоновых задач |
| `GET/POST/DELETE` | `/v1/memory` | Memory facts |
| `GET` | `/v1/recall` | Fuzzy memory recall |
| `GET` | `/v1/browser/read` | Fetch/extract текста web page |
| `GET` | `/v1/desktop/screenshot` | Desktop screenshot, где поддерживается |
| `GET` | `/v1/skills` | Список обнаруженных skill-пакетов |

Extension bridge:

| Method | Path | Назначение |
| --- | --- | --- |
| `GET` | `/v1/extension/policies` | Extension policy metadata |
| `POST` | `/v1/extension/preview` | Dry-run extension tool calls |
| `POST` | `/v1/extension/execute` | Execute approved extension tool calls |

Удалённый доступ / туннели:

| Method | Path | Назначение |
| --- | --- | --- |
| `GET` | `/v1/tunnels/status` | Все провайдеры + suggested active endpoint |
| `GET` | `/v1/tunnels/active` | Только текущий доступный endpoint |
| `POST` | `/v1/tunnels/start` | Запуск провайдеров по приоритету (stop on first healthy) |
| `POST` | `/v1/tunnels/stop` | Остановка туннелей, запущенных bridge (ZeroTier не трогает) |
| `GET/POST` | `/v1/tailscale/funnel/{action}` | Tailscale Funnel primitives |
| `GET/POST` | `/v1/cloudflared/tunnel/{action}` | Cloudflare Quick Tunnel primitives |
| `GET/POST` | `/v1/ngrok/tunnel/{action}` | ngrok tunnel primitives (четвёртый транспорт) |
| `GET/POST` | `/v1/bore/tunnel/{action}` | bore relay primitives (пятый транспорт, v4.47.0) |
| `GET` | `/v1/zerotier/status` | Полный snapshot ZeroTier (backend, networks, hints) |
| `GET/POST` | `/v1/zerotier/network/{action}` | Join / leave / status networks |

Полная surface модульная; смотрите dashboard, route tests и [`docs/`](docs/).

---

## Разработка

```bash
git clone https://github.com/IvanSkainet/arena-agent.git arena-bridge
cd arena-bridge
python -m pip install -e ".[full,dev]"
pytest
```

Targeted checks для extension work:

```bash
pytest -q tests/test_chat_extension_assets.py tests/test_chat_extension_adapter_flow.py tests/test_chat_extension_sidepanel_flow.py tests/test_extension_bridge.py tests/test_project_modularity.py

for f in background content parser adapters insert_strategies insert_history adapter_sites popup settings sidepanel; do
  node --check "chat_extension/$f.js"
done
```

Targeted checks для работы над удалённым доступом / провайдерами:

```bash
pytest -q tests/test_tunnels.py tests/test_zerotier.py tests/test_cloudflared.py \
          tests/test_browseract.py tests/test_superpowers_layout.py
```

Перед push запустите те же security-gate, что запускает CI:

```bash
make install-security-tools   # one-time: bandit + semgrep + pip-audit
make security-scan            # 0 HIGH+MEDIUM bandit, 0 semgrep findings, 0 CVE
```

Если проходит локально — пройдёт и в CI: Makefile и CI-workflow оба зовут
один и тот же `scripts/security_gate.py`.

Contributor notes: [CONTRIBUTING.md](CONTRIBUTING.md) · Release checklist: [RELEASE.md](RELEASE.md) · Security posture: [SECURITY.md](SECURITY.md).

---

## Карта документации

| Документ | Что внутри |
| --- | --- |
| [SECURITY.md](SECURITY.md) | **Threat model, env-var reference (14 knobs), recommended production preset, CI security-scan pipeline, audit history v4.40.0 → v4.46.0. Прочтите перед тем, как выставлять bridge в сеть.** |
| [CHANGELOG.md](CHANGELOG.md) · [ru](CHANGELOG.ru.md) | История изменений |
| [RELEASE.md](RELEASE.md) | Packaging / publishing checklist |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, тесты, workflow, `make security-scan` gate |
| [AGENTS.md](AGENTS.md) | Жёсткие правила для AI-мейнтейнеров — где что лежит, что не добавлять, security-annotation rules |
| [chat_extension/README.md](chat_extension/README.md) | Browser extension details |
| [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) | Интеграции — Tailscale / cloudflared / ZeroTier / MCP + cert pinning |
| [docs/RELAY.md](docs/RELAY.md) | Generic operator mailbox и постоянный CLI/ConPTY terminal ingress |
| [docs/SUPERPOWERS.md](docs/SUPERPOWERS.md) | Superpowers vendored copy: layout + update flow |
| [docs/MODULE_MAP.md](docs/MODULE_MAP.md) | Codebase / module map |
| [docs/V3_MODULAR_ARCHITECTURE.md](docs/V3_MODULAR_ARCHITECTURE.md) | Modular architecture notes |
| [docs/AI_CODEBASE_NAVIGATION.md](docs/AI_CODEBASE_NAVIGATION.md) | Навигация по коду для AI-мейнтейнеров |

Часть файлов в `docs/` — design notes или historical audits. README и CHANGELOG —
публичные входные точки.

---

## Справка по инструментам (примеры по namespace)

Каждый инструмент зарегистрирован в каталоге `MCP_TOOLS` со стабильным именем
`namespace.action` и JSON-Schema `inputSchema`. Ниже приведён один канонический вызов
для каждого namespace, чтобы поверхность bridge была discoverable из README без чтения
исходников. Полный каталог — в `arena/mcp/tool_registry.py`.

| Namespace | Пример вызова |
| --- | --- |
| `admin` | `admin.run` — Кросс-платформенная admin escalation. Linux/macOS проксирует в sudo |
| `asr` | `asr.transcribe` — Транскрибировать аудиофайл локально через whisper.cpp. Автоконвертация |
| `browser` | `browser.search` — DuckDuckGo поиск через pure-Python (без chromium) |
| `desktop` | `desktop.ocr` — OCR по свежему скриншоту рабочего стола и возврат распознанного текста |
| `desktop_app` | `desktop_app.click_window_relative` / `desktop_app.screenshot_window` — Найти реальное окно, затем кликнуть или сделать скриншот относительно него для менее хрупких GUI-сценариев |
| `document` | `document.structure` — Структурировать OCR/ASR/текст в задачи или JSON домашнего задания по физике |
| `exec` | `exec.exec` — Namespaced-алиас для `exec`. Выполнить shell-команду за пределами bridge |
| `code` | `code.run` — Выполнить код, написанный агентом, под execution posture оператора (composable fence); fail-closed, агент не может задать posture |
| `code_project` | `code_project.run` / `code_project.lock_verify` / `code_project.promote_tool` — Запуск persistent-проектов, проверка dependency locks или промоушн рецептов/тестов в инструменты |
| `code_run` | `code_run.info` / `code_run.promote_tool` — Просмотр сохранённых запусков или использование запуска как provenance для promoted tool |
| `code_matrix` | `code_matrix.run` — Запуск до 8 Code Workbench задач последовательно под текущим posture оператора |
| `code_session` | `code_session.exec` / `code_session.artifacts` — Выполнение stateful Python-сессий и сохранение файлов/артефактов сессии |
| `code_artifact` | `code_artifact.read` — Чтение сохранённого артефакта Code Workbench по run_id и пути |
| `fs` | `fs.read` — Чтение содержимого файла (utf-8) |
| `git` | `git.status` — Показать git status для репозитория |
| `hooks` | `hooks.list` — Список настроенных hooks по событиям |
| `image` | `image.preprocess_for_ocr` — Предобработка изображения для OCR |
| `mcp` | `mcp.ext_call` — Вызвать тул зарегистрированного внешнего MCP-сервера (Desktop-Commander, ScreenPilot, ...). Серверы — `mcp.ext_servers`, их тулы — `mcp.ext_tools` |
| `mcp_server` | `mcp_server.create` / `mcp_server.test` / `mcp_server.install` — Создание, проверка и установка внешнего MCP stdio-сервера |
| `memory` | `memory.recall` — Поиск релевантных фактов/снэпшотов/сессий по запросу (TF score) |
| `mission` | `mission.autopilot_start` / `mission.autopilot_report` / `mission.run` — Выполнение ограниченных mission tool chains с persistent progress и flight records, или запуск сохранённых миссий |
| `mobile` | `mobile.preflight` / `mobile.devices` — Preflight Android/ADB готовности и список подключённых устройств |
| `emulator` | `emulator.providers` / `emulator.list` / `emulator.start` / `emulator.stop` / `emulator.attach` — Запуск и остановка Android-эмуляторов через тот менеджер, который есть на хосте (AVD, Genymotion, MuMu, Waydroid или объявленный самим хостом); после загрузки управление идёт обычным ADB через `mobile.*`. См. [docs/emulators.md](docs/emulators.md) |
| `input_helper` | `input_helper.click` / `input_helper.key` / `input_helper.launch` / `input_helper.send_chat_command` — Маршрутизация реального hardware input через Interactive Input Helper в десктоп-сессии пользователя (решает ограничение Session 0 для Java Swing, LWJGL и всей GUI-автоматизации) |
| `capability_gap` | `capability_gap.record` / `capability_gap.list` / `capability_gap.resolve` — Учёт отсутствующих возможностей bridge, обнаруженных в реальных сценариях |
| `net` | `net.http` — Типизированный HTTP-клиент. Только http/https на публичные hostnames |
| `ocr` | `ocr.extract` — OCR по любому файлу-изображению, возврат текста + word boxes |
| `plan` | `plan.create` — Создание структурированного плана выполнения для цели |
| `react` | `react.run` — Ограниченный reason-act-observe loop с safe observation tools |
| `reflect` | `reflect.run` — Рефлексия по предыдущему react/planning-запуску, выдача concerns |
| `runtime` | `runtime.probe` / `runtime.compat` — Проверка runtime'ов и отображение runtime × sandbox совместимости с known blockers и next actions |
| `scenario` | `scenario.run` / `scenario.promote_from_history` — Выполнение сценариев или промоушн успешных запусков/истории в переиспользуемые сценарии |
| `secrets` | `secrets.list` — Список доступных secret keys (значения никогда не возвращаются) |
| `service` | `service.autostart_status` / `service.autostart_repair` — Диагностика или починка autostart-настройки bridge |
| `skill` | `skill.list` — Список доступных агентных skill'ов |
| `subagent` | `subagent.spawn` — Запуск изолированного sub-агента для делегированной работы; возвращает summary |
| `sudo` | `sudo.run` — Запуск команды через 'sudo -n <cmd>' (non-interactive) |
| `sys` | `sys.status` — Статус bridge/services/funnel |
| `watch` | `watch.files` — Список, добавление или удаление file watchers, эмитирующих realtime file change events |
| `workbench` | `workbench.status` — Posture, runtime'ы, проекты, сессии, недавние артефакты, known limits и next actions |
| `ship` | `ship.status` / `ship.preflight` / `ship.smoke` — Карты всего корабля, проверки готовности, Linux flight check и real-machine smoke proof |
| `tool_foundry` | `tool_foundry.validate` / `tool_foundry.publish` — Валидация Workbench project manifest/tests и публикация как callable custom tool |

Все вызовы идут через `POST /v1/mcp/call` с JSON-телом `{"name": "<tool>", "arguments": {...}}`.

---

## Лицензия

MIT — см. [LICENSE](LICENSE).

## Название и аффилиация

Skainet Bridge — независимый open-source проект без аффилиации. Он не
произведён, не одобрен, не спонсирован и никак не связан с Arena
Intelligence, Inc. (arena.ai / LMArena), Anthropic, OpenAI, Google или любой
другой компанией, с продуктом которой он умеет работать.

Расширение для браузера перечисляет несколько чат-сайтов — в том числе
arena.ai, ChatGPT, Claude, Gemini и другие — исключительно как страницы, к
которым оно может подключаться. Эти названия принадлежат их владельцам и
указаны только для описания совместимости; это номинативное использование, а
не заявление о какой-либо связи.

Раньше проект назывался «Arena Unified Bridge». Он переименован, чтобы не
создавать впечатления аффилиации с Arena Intelligence, Inc. Внутренние
идентификаторы (Python-пакет `arena`, переменные окружения `ARENA_*`, имя
Windows-сервиса `ArenaUnifiedBridge` и строка `arena-unified-bridge` в ответах
API) сознательно оставлены как есть, чтобы существующие установки продолжали
работать; это детали реализации, а не брендинг.

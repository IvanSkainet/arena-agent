<div align="center">

# 🌉 Arena Unified Bridge

**Локальный мост автоматизации для AI-агентов — один процесс, один порт, полный контроль над вашей машиной.**

Превратите любой AI-чат или агента в помощника, который умеет выполнять команды, читать и редактировать файлы, ходить в веб, запоминать факты и управлять рабочим столом — через единый token-authenticated сервис, который вы запускаете сами.

Один процесс · Один порт · REST + MCP + browser extension · Windows / Linux / macOS

**🌐 [English](README.md) · Русский**

[![CI](https://github.com/IvanSkainet/arena-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/IvanSkainet/arena-agent/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/release/IvanSkainet/arena-agent?color=blue&label=release)](https://github.com/IvanSkainet/arena-agent/releases)
[![Python](https://img.shields.io/badge/python-3.10%2B-green.svg)]()
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

</div>

---

## Содержание

- [Зачем Arena Unified Bridge?](#зачем-arena-unified-bridge)
- [Как это работает](#как-это-работает)
- [Что он умеет](#что-он-умеет)
- [Быстрый старт](#быстрый-старт)
- [Browser extension: Arena Chat Bridge](#browser-extension-arena-chat-bridge)
- [Провайдеры удалённого доступа](#провайдеры-удалённого-доступа)
- [Optional components](#optional-components)
- [Security model](#security-model)
- [API overview](#api-overview)
- [Development](#development)
- [Карта документации](#карта-документации)
- [License](#license)

---

## Зачем Arena Unified Bridge?

Обычно связка «AI + ваш компьютер» — это зоопарк серверов: один под MCP, один под
REST, один под управление браузером, один под web UI. Arena Unified Bridge
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
| **Браузер** | Управление через Chrome DevTools Protocol, плюс stealth-сценарии через [BrowserAct](#optional-components) |
| **Desktop** | Скриншоты и input automation там, где поддерживается платформой |
| **Dashboard** | Встроенный web UI на `/gui` с карточкой **Tunnels & Remote Access** для управления всеми провайдерами сразу |
| **Extension** | Соединяет обычные AI-чаты с bridge через Command Center с lifecycle |
| **Remote access** | Единый [`/v1/tunnels/*` фасад](#провайдеры-удалённого-доступа): Tailscale, Cloudflare Quick Tunnel и ZeroTier как один пул с автоматическим failover |
| **Skills** | Автоматическое обнаружение skill-пакетов (Arena core + upstream [`superpowers`][obra] + [`browseract`](#optional-components)) через `/v1/skills` |

Полная история изменений — в [CHANGELOG.ru.md](CHANGELOG.ru.md) и [CHANGELOG.md](CHANGELOG.md).

[obra]: https://github.com/obra/superpowers

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

Arena Unified Bridge относится к **Tailscale**, **Cloudflared** и **ZeroTier**
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

По умолчанию приоритет — `tailscale > cloudflared > zerotier`; можно переопределить
через `ARENA_TUNNEL_PRIORITY=cloudflared,zerotier` (провайдеры, не указанные в
env, добавляются в конец с их default-позиции).

Каждый провайдер работает из коробки на Windows, macOS и Linux — без sudo-обёрток
и платформозависимых хаков по умолчанию. ZeroTier обнаруживается через локальный
HTTP API на `127.0.0.1:9993` с fallback на `zerotier-cli` из PATH, Program Files,
`/Library/Application Support/`, `/usr/sbin/` и т.д. Install/update-подсказки
Cloudflared подстроены под платформу (`winget`/`scoop`/`brew`/`pacman`/`apt`).

Карточка **Settings → Tunnels & Remote Access** в dashboard даёт тот же фасад с
кнопками Start-all / Stop-all и панелью управления ZeroTier-сетями (join/leave
по nwid, список подключённых сетей, install/permission hints inline).

---

## Optional components

Bridge работает локально на одном Python и `aiohttp`. Некоторым функциям нужны
дополнительные tools — и ни один из них не ставится молча, installer всегда
спрашивает подтверждение.

| Компонент | Назначение | Установка |
| --- | --- | --- |
| **Tailscale** | Zero-config HTTPS exposure через Funnel | System-level: <https://tailscale.com/download> |
| **cloudflared** | Cloudflare Quick Tunnel fallback | `winget install Cloudflare.cloudflared` / `brew install cloudflared` / `pacman -S cloudflared` |
| **ZeroTier** | Приватная overlay-сеть как backup-провайдер | System-level: <https://www.zerotier.com/download/> |
| **BrowserAct** | Stealth-CLI для браузерной автоматизации (Arena `skills/browseract/`) | `uv tool install browser-act-cli --python 3.12` |
| **Camoufox** | Anti-fingerprinting Firefox для BrowserAct | Автоматически ставится с `browser-act-cli` |
| **ydotool / xdotool** | Linux desktop input automation | `pacman -S ydotool` или `apt install xdotool` |
| **Tesseract** | OCR для desktop/screenshot flows | `pacman -S tesseract` / `brew install tesseract` |

Installer детектит что уже установлено, предлагает поставить остальное, статус
показывается через `/v1/capabilities`. Удаление любого компонента никогда не
ломает Bridge — каждая optional-фича degrades gracefully.

---

## Security model

Arena Unified Bridge может выполнять сильные действия на host, поэтому security
model сделана явной:

- любой non-local client аутентифицируется bearer credential из `token.txt`;
- upload / download / edit paths ограничены;
- опасные shell patterns и попытки чтения секретов блокируются;
- desktop automation имеет pause / resume / revoke controls;
- extension policies классифицируют каждый tool по risk перед auto-execution;
- public exposure должен идти через HTTPS и private credential;
- никогда не публикуйте credentials в незнакомом чате, логах или public issue.

> Нашли security issue? Пожалуйста, сообщите приватно, а не через public issue.

---

## API overview

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
| `GET` | `/v1/zerotier/status` | Полный snapshot ZeroTier (backend, networks, hints) |
| `GET/POST` | `/v1/zerotier/network/{action}` | Join / leave / status networks |

Полная surface модульная; смотрите dashboard, route tests и [`docs/`](docs/).

---

## Development

```bash
git clone https://github.com/IvanSkainet/arena-agent.git arena-bridge
cd arena-bridge
python -m pip install -r requirements.txt
python -m pip install -e ".[dev]"
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

Contributor notes: [CONTRIBUTING.md](CONTRIBUTING.md) · Release checklist: [RELEASE.md](RELEASE.md).

---

## Карта документации

| Документ | Что внутри |
| --- | --- |
| [CHANGELOG.ru.md](CHANGELOG.ru.md) · [en](CHANGELOG.md) | История изменений |
| [RELEASE.md](RELEASE.md) | Packaging / publishing checklist |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, тесты, workflow |
| [AGENTS.md](AGENTS.md) | Жёсткие правила для AI-мейнтейнеров |
| [chat_extension/README.md](chat_extension/README.md) | Browser extension details |
| [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) | Интеграции — Tailscale / cloudflared / ZeroTier / MCP |
| [docs/SUPERPOWERS.md](docs/SUPERPOWERS.md) | Superpowers vendored copy: layout + update flow |
| [docs/MODULE_MAP.md](docs/MODULE_MAP.md) | Codebase / module map |
| [docs/V3_MODULAR_ARCHITECTURE.md](docs/V3_MODULAR_ARCHITECTURE.md) | Modular architecture notes |
| [docs/AI_CODEBASE_NAVIGATION.md](docs/AI_CODEBASE_NAVIGATION.md) | Навигация по коду для AI-мейнтейнеров |

Часть файлов в `docs/` — design notes или historical audits. README и CHANGELOG —
публичные входные точки.

---

## License

MIT — см. [LICENSE](LICENSE).

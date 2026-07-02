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
| **Браузер** | Управление через Chrome DevTools Protocol |
| **Desktop** | Скриншоты и input automation там, где поддерживается платформой |
| **Dashboard** | Встроенный web UI на `/gui` |
| **Extension** | Соединяет обычные AI-чаты с bridge через Command Center с lifecycle |

Полная история изменений — в [CHANGELOG.ru.md](CHANGELOG.ru.md) и [CHANGELOG.md](CHANGELOG.md).

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

## Optional components

Bridge работает локально на одном Python и `aiohttp`. Некоторым функциям нужны
дополнительные tools — и ни один из них не ставится молча, installer всегда
спрашивает подтверждение.

| Component | Назначение | Примечание |
| --- | --- | --- |
| Tailscale | Рекомендуемый HTTPS exposure через Funnel | Optional, system-level install |
| cloudflared | Cloudflare Quick Tunnel fallback | Optional download, ~50 MB |
| BrowserAct / browser helpers | Rich browser automation | Optional |
| Camoufox | Stealth browser workflows | Optional |
| ydotool / xdotool | Linux desktop input automation | Optional / platform-specific |
| Tesseract | OCR для desktop/screenshot flows | Optional |

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

| Method | Path | Назначение |
| --- | --- | --- |
| `GET` | `/health` | health check без auth |
| `GET` | `/v1/version` | версия и platform info |
| `GET` | `/v1/status` | статус bridge |
| `POST` | `/v1/exec` | guarded shell execution |
| `GET/POST` | `/v1/tasks` | очередь фоновых задач |
| `GET/POST/DELETE` | `/v1/memory` | memory facts |
| `GET` | `/v1/recall` | fuzzy memory recall |
| `GET` | `/v1/browser/read` | fetch/extract текста web page |
| `GET` | `/v1/desktop/screenshot` | desktop screenshot, где поддерживается |
| `GET` | `/v1/extension/policies` | extension policy metadata |
| `POST` | `/v1/extension/preview` | dry-run extension tool calls |
| `POST` | `/v1/extension/execute` | execute approved extension tool calls |

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

Contributor notes: [CONTRIBUTING.md](CONTRIBUTING.md) · Release checklist: [RELEASE.md](RELEASE.md).

---

## Карта документации

| Документ | Что внутри |
| --- | --- |
| [CHANGELOG.ru.md](CHANGELOG.ru.md) | История изменений на русском |
| [CHANGELOG.md](CHANGELOG.md) | Release history на английском |
| [RELEASE.md](RELEASE.md) | Packaging / publishing checklist |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup, тесты, workflow |
| [chat_extension/README.md](chat_extension/README.md) | Browser extension details |
| [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) | Integration notes |
| [docs/MODULE_MAP.md](docs/MODULE_MAP.md) | Codebase / module map |
| [docs/V3_MODULAR_ARCHITECTURE.md](docs/V3_MODULAR_ARCHITECTURE.md) | Modular architecture notes |

Часть файлов в `docs/` — design notes или historical audits. README и CHANGELOG —
публичные входные точки.

---

## License

MIT — см. [LICENSE](LICENSE).

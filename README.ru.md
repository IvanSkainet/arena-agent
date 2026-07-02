<div align="center">

# 🌉 Arena Unified Bridge

**Локальный мост автоматизации для AI-агентов.**
Один процесс · Один порт · REST + MCP + browser extension · Windows / Linux / macOS

**🌐 [English](README.md) · Русский**

[![CI](https://github.com/IvanSkainet/arena-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/IvanSkainet/arena-agent/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/release/IvanSkainet/arena-agent?color=blue&label=release)](https://github.com/IvanSkainet/arena-agent/releases)
[![Python](https://img.shields.io/badge/python-3.10%2B-green.svg)]()
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

</div>

---

## Что это?

Arena Unified Bridge — локальный HTTP/MCP-сервер, через который AI-агенты могут работать с вашим компьютером через контролируемый token-authenticated интерфейс.

Он даёт инструменты для:

- выполнения shell-команд с guardrails;
- чтения, поиска и точечного редактирования файлов;
- browser fetch/read/search;
- memory и recall;
- очереди фоновых задач;
- управления браузером через Chrome DevTools Protocol;
- desktop automation там, где это поддерживается;
- web dashboard на `/gui`;
- browser extension, который соединяет обычные AI-чаты с локальным bridge.

Типичный поток:

```text
AI chat / agent → Arena Chat Bridge Extension или MCP/REST → local Arena Unified Bridge → ваш компьютер
```

Проект local-first. Его можно держать только на `127.0.0.1`, а наружу открывать только явно — например через Tailscale Funnel или другой HTTPS tunnel.

---

## Актуальные возможности

| Область | Статус |
| --- | --- |
| Runtime | Один Python service, default `http://127.0.0.1:8765` |
| Protocols | REST, MCP, WebSocket/SSE events, встроенный dashboard |
| Browser extension | Detect structured tool blocks в ChatGPT, Claude, Gemini, AI Studio и других web chats |
| Command Center | Sidepanel history с lifecycle cards: detected/preview/execute/insert/submit |
| Security | Bearer token, path restrictions, command safety patterns, explicit policy checks |
| Installers | Windows, Linux и macOS scripts; optional components только после подтверждения |
| Public HTTPS | Рекомендуется Tailscale Funnel; Cloudflare Quick Tunnels — optional fallback |
| Packaging | Release ZIP собирается из tracked files с проверками на sensitive files |

История изменений вынесена в [CHANGELOG.ru.md](CHANGELOG.ru.md) и [CHANGELOG.md](CHANGELOG.md).

---

## Быстрый старт

### 1. Скачать release

Скачайте последний ZIP:

```text
https://github.com/IvanSkainet/arena-agent/releases/latest
```

Распакуйте в папку, например:

```text
C:\Users\You\arena-bridge        # Windows
~/arena-bridge                    # Linux/macOS
```

### 2. Запустить installer

Windows:

```cmd
install.bat
```

Linux / macOS:

```bash
chmod +x install.sh
./install.sh
```

Installer создаёт локальный bearer credential в `token.txt`, готовит runtime directories и спрашивает перед установкой optional components.

### 3. Проверить bridge

Health check:

```bash
curl http://127.0.0.1:8765/health
```

Version endpoint:

```bash
curl http://127.0.0.1:8765/v1/version
```

Dashboard:

```text
http://127.0.0.1:8765/gui
```

### 4. Передать AI URL и credential

Для local tools и MCP clients:

```text
Base URL: http://127.0.0.1:8765
Auth:     Authorization: Bearer <credential из token.txt>
```

Для remote access включайте HTTPS tunnel только осознанно. Рекомендуемый вариант — Tailscale Funnel: он даёт настоящий TLS hostname без port forwarding.

---

## Browser extension: Arena Chat Bridge

Extension — Arena-native bridge для обычных web chats. Он видит structured tool blocks в ответах ассистента, делает preview/execute через local bridge и может вставлять результат обратно в composer.

Baseline adapters:

- ChatGPT;
- Claude;
- Gemini Web;
- Google AI Studio;
- Grok;
- Perplexity;
- OpenRouter;
- DeepSeek;
- Kimi;
- Qwen;
- generic fallback.

Canonical payload:

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

Загрузка extension для разработки:

1. откройте `chrome://extensions`;
2. включите **Developer mode**;
3. нажмите **Load unpacked**;
4. выберите `chat_extension/`.

Подробнее: [chat_extension/README.md](chat_extension/README.md).

---

## Optional components

Bridge работает локально на Python и `aiohttp`. Для некоторых функций нужны optional tools:

| Component | Назначение | Поведение installer |
| --- | --- | --- |
| Tailscale | Рекомендуемый HTTPS exposure через Funnel | Optional, system-level install |
| cloudflared | Cloudflare Quick Tunnel fallback | Optional download, около 50 MB |
| BrowserAct / browser helpers | Rich browser automation | Optional |
| Camoufox | Stealth browser workflows | Optional |
| ydotool / xdotool | Linux desktop input automation | Optional / platform-specific |
| Tesseract | OCR для desktop/screenshot flows | Optional |

Optional components не устанавливаются молча. Installer спрашивает подтверждение.

---

## Security model

Arena Unified Bridge может выполнять сильные действия на host, поэтому security model сделана явной:

- любой non-local client должен использовать bearer credential из `token.txt`;
- upload/download/edit paths ограничены;
- опасные shell patterns и попытки чтения секретов блокируются;
- desktop automation имеет pause/resume/revoke controls;
- extension policies классифицируют tools по risk перед auto-execution;
- public exposure должен идти через HTTPS и private credential;
- никогда не публикуйте credentials в issue, логах или незнакомом чате.

Если вы нашли security issue, сообщите приватно, а не через public issue.

---

## API overview

Основные endpoints:

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
node --check chat_extension/background.js
node --check chat_extension/content.js
node --check chat_extension/parser.js
node --check chat_extension/adapters.js
node --check chat_extension/insert_strategies.js
node --check chat_extension/insert_history.js
node --check chat_extension/adapter_sites.js
node --check chat_extension/popup.js
node --check chat_extension/settings.js
node --check chat_extension/sidepanel.js
```

Contributor notes: [CONTRIBUTING.md](CONTRIBUTING.md).
Release checklist: [RELEASE.md](RELEASE.md).

---

## Documentation map

- [CHANGELOG.ru.md](CHANGELOG.ru.md) — история изменений на русском.
- [CHANGELOG.md](CHANGELOG.md) — release history на английском.
- [RELEASE.md](RELEASE.md) — packaging/publishing checklist.
- [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) — integration notes.
- [docs/MODULE_MAP.md](docs/MODULE_MAP.md) — codebase/module map.
- [docs/V3_MODULAR_ARCHITECTURE.md](docs/V3_MODULAR_ARCHITECTURE.md) — modular architecture notes.
- [chat_extension/README.md](chat_extension/README.md) — browser extension details.

Часть файлов в `docs/` — design notes или historical audits. README и CHANGELOG — публичные входные точки.

---

## License

MIT. См. [LICENSE](LICENSE).

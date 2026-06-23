<div align="center">

# 🌉 Arena Unified Bridge

**Кроссплатформенный локальный мост автоматизации для AI-агентов.**
Один процесс · Один порт · Модульная Python-архитектура — управляет вашим компьютером из любого чата, любой AI, любой ОС.

**🌐 [English](README.md) · Русский**

[![CI](https://github.com/IvanSkainet/arena-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/IvanSkainet/arena-agent/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/release/IvanSkainet/arena-agent?color=blue&label=version)](https://github.com/IvanSkainet/arena-agent/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-green.svg)]()
[![License](https://img.shields.io/badge/license-MIT-yellow.svg)](#-лицензия)

</div>

---

## ✨ Что это такое?

Arena Unified Bridge — это маленький локальный HTTP/MCP-сервер, который позволяет любому AI — ChatGPT, Claude, Gemini, Grok, GLM, вашим собственным скриптам — **безопасно управлять вашим компьютером**. Выполнять команды, просматривать веб, сохранять память, делать скриншоты, запускать навыки (skills), управлять очередью фоновых задач, контролировать настоящий браузер через Chrome DevTools Protocol и даже автоматизировать рабочий стол кликами, вводом текста и нажатиями клавиш на Wayland и X11.

Мост открывает один защищённый URL вида `https://your-machine.tail-XXXXX.ts.net` (через Tailscale Funnel) и обслуживает REST API, протокол MCP, события WebSocket и встроенный веб-дашборд на `/gui`.

> **Цель:** *Распаковал папку, запустил один установщик — у вашего AI появились руки.*

---

## 🚀 Ключевые возможности

| Категория | Возможность |
|-----------|-------------|
| **Кроссплатформенность** | Установщик сам определяет Windows / Linux / macOS и выбирает правильную стратегию упаковки (NSSM-сервис, Scheduled Task, systemd user-юнит или launchd-агент) |
| **Единая архитектура** | REST API, MCP (HTTP/SSE/WebSocket), web-gateway, дашборд, async-задачник — всё на **одном порту** (по умолчанию `8765`) |
| **200+ method/path маршрутов** | Публичные REST, MCP, gateway, dashboard, observability, desktop, browser, admin и compatibility-поверхности на одном порту |
| **36 CDP-эндпоинтов** | Полная поддержка Chrome DevTools Protocol: навигация, клики, ввод, скриншоты, cookies, перехват сети, управление вкладками |
| **15 desktop + 4 control эндпоинта** | Автоматизация рабочего стола Wayland/X11: скриншот, display/output discovery, OCR, text-target detection, OCR-to-window resolution, high-level text actions, semantic click-by-text, клик, layout-safe ввод, нажатие клавиш, движение мыши, список окон, active window, focus, window actions, плюс pause/resume/revoke/status для control lease |
| **Токен-аутентификация** | 256-битный Bearer-токен, хранится в `token.txt`, можно горячо сменить из дашборда |
| **Авто-рестарт везде** | NSSM на Windows, Scheduled Task как fallback, `Restart=on-failure` на systemd, `KeepAlive` на launchd |
| **Публичный HTTPS в один клик** | Интеграция с Tailscale Funnel — без проброса портов, без DDNS, настоящий сертификат Let's Encrypt |
| **Дашборд на 16 вкладок** | Overview, Workspace, Terminal, Memory, Recall, Missions, Browser, Reports, Tasks, Skills, Hooks, Agents, Control, Doctor, Audit, Settings |
| **Глубокий инвентарь системы** | Материнская плата, BIOS, CPU по ядрам, GPU/VRAM, модули RAM с vendor/part-номерами, все диски, все сетевые интерфейсы, рантаймы, пакетные менеджеры, браузеры, дисплеи |
| **Встроенные AI-инструменты** | MCP-сервер с 60+ инструментами, интеграция BrowserAct, репозиторий навыков Superpowers (14 навыков), стелс-браузер Camoufox |
| **Защита диска в логах** | Многоуровневая ротация логов и мониторинг диска — больше никаких сюрпризов с заполненным диском (см. [Защита диска](#-защита-диска-v210)) |
| **Ноль внешних зависимостей** | Только `aiohttp` (и опционально `psutil`) — всё остальное из Python stdlib |
| **Удаление в один клик** | `uninstall.bat` / `uninstall.sh` — чистое удаление сервисов и файлов |

### 🆕 Что нового в v3.21.0

- **Появился mission lineage layer** — поверх catalog/recovery/follow-up/iteration/history/report/create/run/rerun у Arena теперь есть явные lineage surfaces.
- **Persisted missions теперь образуют inspectable parent/child chains** — агент может смотреть ancestors, descendants, siblings, root mission и сохранённую follow-up lineage через REST и MCP.
- **Workspace UI v3 стал реально полезным** — во вкладке Workspace появился mission loop studio для lineage inspection и follow-up/iterate действий, связывающий agentic planning с mission lifecycle в одной поверхности.
- **Mission/orchestration блок продолжает углубляться** — bridge двигается от «умеет запустить follow-up mission» к «умеет сопровождать многошаговые mission families и iteration chains».
- **625 тестов проходят**, без регрессий.

Полная история изменений — в [CHANGELOG.md](CHANGELOG.md).

---

## 📦 Быстрый старт

### 1. Скачать последний релиз

> ⚠️ **Всегда качайте из [Releases](https://github.com/IvanSkainet/arena-agent/releases).** В ветках могут быть незавершённые изменения во время активных релизов. Только тегированные релизы готовы к продакшену.

Зайдите на **[последний релиз](https://github.com/IvanSkainet/arena-agent/releases/latest)** и скачайте ZIP-архив. Распакуйте его в папку по выбору, например `C:\Users\You\arena-bridge` (Windows) или `~/arena-bridge` (Linux/macOS).

<details>
<summary>📦 Альтернатива: однострочные команды</summary>

**Windows (PowerShell):**
```powershell
Invoke-WebRequest -Uri "https://github.com/IvanSkainet/arena-agent/releases/latest/download/arena-agent.zip" -OutFile "arena-agent.zip"
Expand-Archive arena-agent.zip -DestinationPath arena-bridge
cd arena-bridge
```

**Linux / macOS:**
```bash
curl -fsSL https://github.com/IvanSkainet/arena-agent/releases/latest/download/arena-agent.zip -o arena-agent.zip
unzip arena-agent.zip -d arena-bridge
cd arena-bridge
```
</details>

### 2. Запустить установщик

**Windows (PowerShell или cmd):**
```cmd
install.bat
```

**Linux / macOS:**
```bash
chmod +x install.sh
./install.sh
```

Установщик сделает:
1. Найдёт Python >= 3.10
2. Установит `aiohttp` + `psutil`
3. Создаст все нужные поддиректории внутри папки моста (ничего не раскидывает по домашней папке)
4. Сгенерирует новый токен аутентификации (или сохранит существующий)
5. Спросит перед установкой каждого опционального компонента (Tailscale, SuperPowers, BrowserAct, Camoufox) — см. [Опциональные компоненты](#-опциональные-компоненты-и-где-они-устанавливаются)
6. Зарегистрирует фоновый сервис (NSSM на Windows, Scheduled Task как fallback, systemd-user на Linux, launchd на macOS)
7. Сделает ротацию раздутых логов от прошлых запусков
8. Запустит мост и проверит, что он здоров

> **Сам мост остаётся в одной папке.** Опциональные компоненты устанавливаются только после явного согласия; некоторые из них (Tailscale, BrowserAct, Camoufox) намеренно ставятся за пределами папки моста, потому что это системные инструменты. См. [Опциональные компоненты и где они устанавливаются](#-опциональные-компоненты-и-где-они-устанавливаются) для полной картины.

### 3. Обновление существующей установки

Повторный запуск установщика на существующей установке **безопасен и неразрушим**:

- **Никогда не понижает версию молча.** Установщик читает локально установленную версию и сравнивает её с remote-версией вашей текущей ветки. Если локальная новее или равна remote — ничего не меняется.
- **Никогда не переключает ветки.** Обновление делает fast-forward только *текущей* ветки. Никаких `git checkout -B` против захардкоженной ветки — пользователи, pinned на release-ветку, остаются на ней.
- **Спрашивает перед обновлением.** Если remote-версия новее, вы получите промпт (или установите `ARENA_ASSUME_YES=1` для автоматизации). Если `git merge --ff-only` упадёт (разошедшиеся ветки, локальные коммиты) — ваша работа сохранится, получите инструкции для ручного разрешения.
- **Аккуратно откатывается при сбое сети.** Если GitHub недоступен, установщик оставляет локальный код и продолжает установку зависимостей и регистрацию сервиса.

На Windows `install.bat` дополнительно опрашивает GitHub releases API и печатает строку `[INFO]` если доступна новая версия — он никогда не авто-обновляет, только информирует.

---

## 🧩 Опциональные компоненты и где они устанавливаются

Установщик спрашивает явное согласие перед установкой каждого опционального компонента. Часть компонентов живёт внутри папки моста; другие — системно, потому что иначе они не смогут работать из одной папки.

| Компонент | Куда ставится | Нужен для | Промпт согласия |
|-----------|---------------|-----------|-----------------|
| **Tailscale** | Системный пакет (`/usr/bin/tailscale` на Linux, `C:\Program Files\Tailscale` на Windows) | Рекомендуемый способ открыть мост в интернет через Tailscale Funnel (настоящий HTTPS, без проброса портов) | Да — установка через официальный скрипт (Linux/macOS) или `winget` (Windows); требует sudo/admin |
| **cloudflared** | Внутрь папки моста (`$INSTALL_DIR/cloudflared` или `%BRIDGE_DIR%\cloudflared.exe`) | Альтернатива Tailscale Funnel (Cloudflare Quick Tunnels, без аккаунта) | Да — скачивает ~40 МБ |
| **SuperPowers** | Внутрь папки моста (`skills/superpowers/`) | 14-навыковый агентский фреймворк (TDD, отладка, планирование) | Да — клонирует с GitHub |
| **BrowserAct** | **Глобально** через `uv tool` (в `~/.local/bin` или `%USERPROFILE%\.local\bin`, вне папки моста) | CLI автоматизации браузера (browse, click, формы, CAPTCHA) — мост вызывает `browser-act` через PATH | Да — глобальная установка обязательна, иначе не заработает |
| **Camoufox** | **Системный кэш** (`~/.cache/camoufox` на Linux, `%LOCALAPPDATA%\camoufox` на Windows, вне папки моста) | Стелс-браузер для BrowserAct (~300 МБ) | Да — требуется для Python-пакета camoufox |

### Настройка Tailscale Funnel для доступа из интернета

Tailscale Funnel — рекомендуемый способ открыть мост в интернет. Вы получаете настоящий HTTPS-URL (вида `https://your-pc.tail-XXXXX.ts.net`) с сертификатом Let's Encrypt, без проброса портов, без DDNS, без аккаунта Cloudflare.

**Если вы пропустили Tailscale при установке**, настройте его в три шага:

```bash
# 1. Установите Tailscale (Linux/macOS — использует ваш системный пакетный менеджер)
curl -fsSL https://tailscale.com/install.sh | sh
# На Windows:  winget install --id Tailscale.Tailscale

# 2. Войдите (открывает URL в браузере — войдите через Google, GitHub, Microsoft и т.д.)
sudo tailscale login         # Linux/macOS
tailscale login              # Windows

# 3. Опубликуйте мост (открывает http://127.0.0.1:8765 в интернет через HTTPS)
sudo tailscale funnel --bg 8765    # Linux/macOS
tailscale funnel --bg 8765         # Windows
```

После шага 3 ваш публичный URL будет вида `https://your-pc.tail-XXXXX.ts.net`. Используйте его (вместе с auth-токеном) в любом AI-чате, чтобы управлять компьютером удалённо.

> **Почему Tailscale, а не просто проброс портов?** Tailscale Funnel терминирует TLS настоящим сертификатом Let's Encrypt (никаких предупреждений о self-signed), работает за любым NAT/файрволом и даёт стабильное имя хоста, которое следует за машиной между сетями. Эндпоинт моста `/v1/sys/funnel` проверяет статус Funnel; в дашборде на вкладке Settings есть тумблер для него.

### Пропуск опциональных компонентов

Если вы ответите «N» на все промпты опциональных компонентов, мост всё равно полностью работает для:
- Локального выполнения команд (`POST /v1/exec`)
- Памяти и recall (`/v1/memory`, `/v1/recall`)
- Локального browser-fetch (`/v1/browser/read`, `/dump`, `/fetch`, `/head`)
- Автоматизации рабочего стола (`/v1/desktop/*`) — использует `ydotool`/`xdotool`, не BrowserAct
- Веб-дашборда на `http://127.0.0.1:8765/gui`

Опциональные компоненты нужны только для: удалённого доступа через интернет (Tailscale/cloudflared), агентских навыков-плейбуков (SuperPowers) или anti-detection-автоматизации браузера (BrowserAct + Camoufox). Любой из них можно установить позже, перезапустив установщик.

---

## 🧾 Прозрачность: фоновые процессы — это нормально (не вирус)

Arena Unified Bridge — это **локальный сервер автоматизации**. После установки он намеренно работает в фоне, чтобы ваши AI-инструменты могли продолжать общаться с вашей машиной после закрытия терминала.

Установщики (`install.bat` и `install.sh`) показывают это уведомление о прозрачности и спрашивают подтверждение перед регистрацией/обновлением фонового сервиса. Для автоматизации можно явно согласиться через `ARENA_ACCEPT_BACKGROUND=1`.

Это может выглядеть подозрительно, если вы не ожидали — особенно на Windows, где в Task Manager видны процессы `python.exe`. Эти процессы не скрыты и не предназначены быть стелс: это сервис моста, опциональные helper-серверы и/или legacy helper-скрипты из старых приватных сборок.

### Нормальные имена процессов, которые вы можете увидеть

| Процесс / содержит в командной строке | Зачем существует |
|----------------------------------------|------------------|
| `unified_bridge.py serve` | Текущий главный сервер моста (`http://127.0.0.1:8765`) |
| `local_bridge.py serve` | Старое pre-GitHub имя моста из приватных сборок |
| `mcp_ws_server.py` | Старый MCP/WebSocket-helper из ранних сборок |
| `web_gateway.py` | Старый web-gateway-helper из ранних сборок |
| `agentctl task-watch` | Worker фоновой очереди задач / legacy-helper |
| `cloudflared` или `tailscale` | Опциональный туннель/exposure-helper если вы включили удалённый доступ |
| `ydotoold` | Linux/Wayland-демон ввода для автоматизации рабочего стола |

### Windows: проверить, остановить и удалить

Проверить Arena-связанные Python/фоновые процессы:

```powershell
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
  Where-Object { $_.CommandLine -match 'arena|bridge|mcp_ws|web_gateway|agentctl|local_bridge' } |
  Select-Object ProcessId, ParentProcessId, CommandLine |
  Format-List
```

Проверить scheduled tasks/сервисы:

```powershell
schtasks /query /fo LIST /v | findstr /i "Arena Bridge arena local_bridge unified_bridge agentctl mcp_ws web_gateway"
sc query ArenaUnifiedBridge
```

Остановить текущую официальную установку:

```cmd
uninstall.bat
```

Если вы чистите **старую приватную/pre-GitHub сборку**, в которой не было uninstaller'а, остановите и удалите stale-задачи вручную:

```powershell
# Остановить совпадающие Python-helper процессы
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
  Where-Object { $_.CommandLine -match 'arena|bridge|mcp_ws|web_gateway|agentctl|local_bridge' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# Удалить известные имена scheduled tasks (игнорировать ошибки, если не существуют)
schtasks /Delete /TN "ArenaUnifiedBridge" /F
schtasks /Delete /TN "ArenaBridge" /F
schtasks /Delete /TN "ArenaLocalBridge" /F
```

### Linux/macOS: проверить и удалить

```bash
pgrep -af 'arena|bridge|unified_bridge|local_bridge|mcp_ws|web_gateway|agentctl'
systemctl --user status arena-bridge.service  # Linux systemd user-установка
./uninstall.sh
```

### Обещание по приватности

Мост **не** устанавливает себя молча, **не** скрывает имена процессов и **не** связывается с внешними серверами. Он предоставляет только локальную/API-функциональность, для которой вы его установили. См. [Модель безопасности](#-модель-безопасности) про auth, safety-фильтры, audit-логи и детали удаления.

Готово. Теперь у вас есть:

| URL | Что |
|-----|-----|
| `http://127.0.0.1:8765/health` | Health-check (публичный, без auth) |
| `http://127.0.0.1:8765/gui` | Веб-дашборд (вход по токену) |
| `https://YOUR-PC.tail-net.ts.net` | Публичный HTTPS (если Funnel включён) |

### 4. Передать AI URL + токен

В чате:

> *"Мой мост по адресу `https://YOUR-PC.tail-net.ts.net` с токеном `...`. Сделай, пожалуйста, X."*

Большинство современных AI-чатов (Claude.ai, ChatGPT custom GPTs, AnythingLLM, Open WebUI и др.) поддерживают кастомные HTTP-инструменты или MCP-серверы и могут вызывать ваши эндпоинты напрямую.

Готовый шаблон системного промпта для AI — в [`docs/AI_PROMPT_TEMPLATE.md`](docs/AI_PROMPT_TEMPLATE.md): скопируйте целиком и вставьте в начало нового чата с любым AI.

#### Рецепты интеграции

Готовые рецепты для популярных фронтендов и IDE-агентов лежат в [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md), включая:
- Arena Agent Mode
- Claude / generic custom-tools chats
- Cursor
- Cline
- Windsurf
- Open Interpreter
- локальные model backends (Ollama / OpenRouter / Groq / Together)

### 5. Обновление

Скачайте ZIP [последнего релиза](https://github.com/IvanSkainet/arena-agent/releases/latest) и распакуйте поверх существующей папки (или в новую). Затем перезапустите установщик:

**Windows:**
```cmd
cd /d "C:\Users\You\arena-bridge"
install.bat
```

**Linux / macOS:**
```bash
cd ~/arena-bridge
./install.sh
```

Установщик по умолчанию сохраняет существующий токен. Скажите `N`, когда спросит про регенерацию.

### 6. Удаление

**Windows:**
```cmd
uninstall.bat
```

**Linux / macOS:**
```bash
chmod +x uninstall.sh
./uninstall.sh
```

Удаляет сервис, scheduled task и все файлы моста. Токен и память тоже пропадают — сделайте бэкап заранее.

---

## 🏗️ Архитектура

```
                        ┌──────────────────────────────────────────────┐
                        │       Интернет (HTTPS, Let's Encrypt)         │
                        └──────────────────┬───────────────────────────┘
                                           │
                        ┌──────────────────▼───────────────────────────┐
                        │   Tailscale Funnel  →  https://pc.ts.net      │
                        └──────────────────┬───────────────────────────┘
                                           │
        ┌──────────────────────────────────▼──────────────────────────────────┐
        │                                                                     │
        │   localhost:8765   (один модульный Python-процесс, тонкий entry)     │
        │                                                                     │
        │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
        │   │ REST /v1/*   │  │ MCP /mcp     │  │ MCP /ws      │              │
        │   │ 200+ routes  │  │ Streamable   │  │ WebSocket    │              │
        │   └──────────────┘  └──────────────┘  └──────────────┘              │
        │                                                                     │
        │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
        │   │ /gui         │  │ /sse,        │  │ /gateway     │              │
        │   │ Дашборд      │  │ /messages    │  │ /run, /tool  │              │
        │   └──────────────┘  └──────────────┘  └──────────────┘              │
        │                                                                     │
        │   ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐      │
        │   │ CDP browser  │  │ Desktop API   │  │  Async Task Runner   │      │
        │   │ 36 эндпоинтов│  │ 15+4 эндпоинта│  │  + Log + Disk Mon.  │      │
        │   └──────────────┘  └──────────────┘  └──────────────────────┘      │
        │                                                                     │
        └─────────────────────────────────────────────────────────────────────┘
                                           │
                ┌──────────────────────────┼──────────────────────────┐
                ▼                          ▼                          ▼
        ┌──────────────┐         ┌──────────────┐           ┌──────────────┐
        │   memory/    │         │   missions/  │           │   skills/    │
        │ JSONL facts  │         │ scripted     │           │ AI-runnable  │
        │ + recall     │         │ workflows    │           │ playbooks    │
        └──────────────┘         └──────────────┘           └──────────────┘
```

---

## 📡 Справочник по API

### Основные эндпоинты

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/health` | Публичная проверка здоровья (без auth) |
| `GET` | `/v1/version` | Информация о версии |
| `GET` | `/v1/info` | Информация о мосте (auth) |
| `GET` | `/v1/status` | Статус моста (auth) |
| `GET` | `/v1/config` | Дамп конфигурации без токена |

### Система и диагностика

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/v1/sysinfo` | CPU, RAM, диск + **disk_usage_percent** |
| `GET` | `/v1/hardware` | Канонический богатый инвентарь оборудования/системы (нормализованный JSON из унифицированного сборщика) |
| `GET` | `/v1/hwinfo` | Backward-compatible алиас для `/v1/hardware` |
| `GET` | `/v1/inventory[?section=…]` | Глубокий инвентарь: рантаймы, браузеры, дисплеи, env, сервисы и т.д. |
| `GET` | `/v1/doctor` | 9 селфтестов (Python, директории, сеть, диск, звук…) |
| `GET` | `/v1/metrics` | Метрики производительности моста |
| `GET` | `/v1/logs?level=&lines=` | Просмотр структурированных логов с фильтром по уровню |
| `GET/POST` | `/v1/watchdog` | Статус health-watchdog (память/CPU/алёрты) |
| `GET` | `/v1/ps` | Список активных exec-процессов |

### Выполнение команд

| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/v1/exec` | Выполнить shell-команду. Body: `{"cmd": "..."}` (правила безопасности; команды input-injection блокируются, пока desktop-control на паузе/отозван) |
| `POST` | `/v1/kill` | Убить запущенный процесс. Body: `{"pid": N}` |
| `POST` | `/v1/batch` | Пакетные операции параллельно. Body: `{"operations": [{"method": "GET", "path": "/v1/status"}, ...]}` |
| `POST` | `/v1/restart` | Мягкий рестарт (использует NSSM/systemd respawn) |

### Файловые операции

| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/v1/upload?path=…` | Загрузить бинарный файл (`--data-binary`, путь должен быть внутри домашней папки) |
| `GET` | `/v1/download?path=…` | Скачать файл (путь должен быть внутри домашней папки) |
| `PATCH` | `/v1/fs/edit` | Find-and-replace в текстовом файле (хирургическое редактирование, без перезагрузки файла). Добавьте `"preview": true` для неразрушающего preview/confirm workflow. |
| `POST` | `/v1/fs/edit/apply` | Применить ранее подготовленный preview-редакт. Body: `{"preview_id": "..."}` |
| `POST` | `/v1/fs/edit/rollback` | Откатить ранее применённый safe edit. Body: `{"rollback_id": "...", "force": false}` |

> **Безопасность:** Пути upload, download и edit ограничены домашней директорией пользователя. Path traversal (`..`) блокируется. Сам бинарник моста нельзя перезаписать. Edit дополнительно блокирует чувствительные файлы (`token.txt`, `.env`, SSH-ключи, `users.json` и т.д.) и требует, чтобы `old_text` был уникален, если не установлен `replace_all=true`.

### Память и Recall

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/v1/memory` | Список фактов памяти для профиля (по умолчанию: `default`), пагинация: `?profile=&offset=&limit=`; для поиска по всем профилям используйте `profile=all` |
| `POST` | `/v1/memory` | Установить факт. Body: `{"profile": "default", "key": "...", "value": "...", "tags": [...]}` |
| `DELETE` | `/v1/memory` | Удалить факт по ключу внутри профиля. Body: `{"profile": "default", "key": "..."}` |
| `GET` | `/v1/recall?q=…&top=5&profile=` | TF-scored fuzzy-поиск с ограничением по профилю (или `profile=all`) |
| `GET` | `/v1/recall/digest?profile=` | Дайджест памяти для профиля (или `profile=all`) |

### Planner

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/plan` | Построить структурированный план выполнения из цели. Body: `{"goal": "...", "context": "...", "constraints": ["..."], "max_steps": 8, "memory_profile": "projects/<name>"}` |
| `POST` | `/v1/react` | Запустить bounded reason → act → observe цикл из цели. Body: `{"goal": "...", "context": "...", "constraints": ["..."], "max_iterations": 4, "memory_profile": "projects/<name>", "url": "https://..."}` |
| `POST` | `/v1/reflect` | Провести рефлексию по предыдущему run и вернуть positives, concerns, missing evidence, confidence и suggested next steps. |

### File Watchers

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/watch/files` | Список активных file watcher'ов |
| `POST` | `/v1/watch/files` | Добавить watcher. Body: `{"path": "...", "recursive": true, "patterns": ["*.py"], "label": "repo"}` |
| `DELETE` | `/v1/watch/files` | Удалить watcher. Body: `{"id": "..."}` |

> Изменения watcher'ов публикуются как `file_watch_change` события через `/v1/events`.

### Задачи и очередь

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/v1/tasks` | Список очереди задач |
| `POST` | `/v1/tasks` | Отправить фоновую задачу. Body: `{"cmd": "...", "title": "..."}` |
| `POST` | `/v1/tasks/clean` | Очистить завершённые задачи |

### Навыки (Skills) и хуки

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/v1/skills` | Список доступных AI-навыков |
| `POST` | `/v1/skills/run` | Запустить навык |
| `POST` | `/v1/skills/reload` | Принудительно перезагрузить кэш навыков |
| `GET` | `/v1/hooks` | Список pre/post-хуков |
| `GET` | `/v1/agents` | Список конфигов агентов |
| `GET` | `/v1/subagents` | Список сабагентов |
| `POST` | `/v1/subagents/spawn` | Запустить сабагента |

### Браузер и веб

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/v1/browser/search?q=…` | Поиск в DuckDuckGo |
| `GET` | `/v1/browser/read?url=…` | Readability-извлечение текста |
| `GET` | `/v1/browser/dump?url=…` | Полный дамп страницы со ссылками |
| `GET` | `/v1/browser/fetch?url=…` | Получить «сырой» контент |
| `GET` | `/v1/browser/head?url=…` | HTTP HEAD-запрос |
| `POST` | `/v1/browser/browse` | Умный просмотр с рендерингом (авто-выбор CDP или BrowserAct) |

### Chrome DevTools Protocol (36 эндпоинтов + `/v1/cdp/*` алиасы)

| Возможность | Эндпоинты | Что делает |
|-------------|-----------|------------|
| **Подключение** | `/v1/browser/cdp/connect`, `disconnect`, `status`, `diag`, `health`, `raw-info`, `test-launch`, `test-ws` (также поддерживаются алиасы `/v1/cdp/*`) | Запустить/подключиться к Chromium со стелс-профилем |
| **Навигация** | `cdp/navigate` | Перейти на URL, дождаться загрузки (30s timeout) |
| **Взаимодействие** | `cdp/click`, `cdp/type` | Кликнуть элементы, ввести текст с событиями |
| **Скриншоты** | `cdp/screenshot`, `cdp/stealth/shot` | Захват всей страницы или viewport PNG |
| **DOM** | `cdp/dom` | Запрос DOM-элементов по CSS-селектору |
| **JavaScript** | `cdp/eval` | Выполнить произвольный JS на странице (настраиваемый timeout) |
| **Вкладки** | `cdp/tabs`, `tabs/new`, `tabs/close`, `tabs/activate` | Управление мульти-вкладками |
| **Cookies** | `cdp/cookies` (GET/POST/DELETE), `cookies/clear`, `cookies/profiles` | Управление cookies с сохранением/загрузкой профилей |
| **Сеть** | `cdp/network/start`, `network/stop`, `network/requests`, `network/har` | Мониторинг сети и экспорт HAR |
| **Перехват** | `cdp/intercept/start`, `intercept/stop`, `intercept/rule` (POST/DELETE), `intercept/rules` | Перехват сети с кастомными правилами |
| **Стелс** | `cdp/stealth/extract`, `stealth/shot` | Anti-detection-автоматизация браузера |
| **Сессия** | `cdp/session/check` | Управление сессией и диагностика |

### Автоматизация рабочего стола (15 эндпоинтов + 4 control lease эндпоинта)

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/v1/desktop/screenshot` | Скриншот рабочего стола. Query: `format=png|jpeg|webp|base64`, опционально `display`, `scale`, `max_width`, `quality` |
| `GET` | `/v1/desktop/displays` | Список display/output с глобальной геометрией для multi-monitor aware автоматизации |
| `POST` | `/v1/desktop/click` | Клик по координатам. Body: `{"x": N, "y": N, "button": "left"}` |
| `POST` | `/v1/desktop/type` | Ввести текст. Body: `{"text": "...", "ensure_latin": true}` (по умолчанию: layout-safe ввод на KDE) |
| `POST` | `/v1/desktop/key` | Нажать клавишу. Body: `{"key": "Return"}` |
| `POST` | `/v1/desktop/mouse` | Двинуть мышь. Body: `{"action": "move", "x": N, "y": N}` |
| `GET` | `/v1/desktop/windows` | Список desktop-окон с опциональными фильтрами по title, class, pid, display и active-state; при возможности дополняет окна metadata о display |
| `GET` | `/v1/desktop/active_window` | Получить текущее активное окно desktop'а |
| `POST` | `/v1/desktop/focus` | Сфокусировать окно по id, semantic-фильтрам или OCR text query; поддерживает `dry_run` разрешение цели до реального focus |
| `POST` | `/v1/desktop/window_action` | Двигать, ресайзить, центрировать, снапать в типовые tiling-позиции, переносить на другой display, минимизировать, максимизировать, восстанавливать, закрывать или переключать fullscreen у окна, найденного по id, semantic-фильтрам или OCR text query; поддерживает `dry_run` |
| `POST` | `/v1/desktop/resolve_text_target` | Разрешить OCR text в click target и содержащее его окно, с опциональными display/window-фильтрами |
| `POST` | `/v1/desktop/text_action` | High-level OCR → target → action workflow, который умеет resolve/focus/click/semantic window action по видимому тексту |
| `POST` | `/v1/desktop/ocr` | Запустить OCR по свежему desktop screenshot и вернуть слова, полный текст, confidence и bounding boxes; можно ограничить named display |
| `POST` | `/v1/desktop/find_text` | Найти текст на текущем рабочем столе и вернуть ранжированные matching bounding boxes плюс click-ready center coordinates; можно предпочитать или ограничивать поиск активным окном или named display |
| `POST` | `/v1/desktop/click_text` | Найти текст на текущем рабочем столе, выбрать лучший ranked match и кликнуть по нему за один шаг; поддерживает active-window-aware и display-aware targeting |

> **Поддержка Wayland:** Установщик автоматически запускает `ydotoold` для автоматизации рабочего стола на Wayland. На X11 используется `xdotool` как fallback. Клик автоматически активирует целевое окно (v2.5.1+). Для vision-агентов предпочитайте `GET /v1/desktop/screenshot?format=jpeg&scale=0.5&quality=80` или `max_width=1280`, чтобы сильно уменьшить размер payload. OCR использует локально установленный `tesseract`, если он доступен.

### Аудит и логи

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/v1/audit?lines=N` | Хвост audit-лога |
| `GET` | `/v1/audit/stats` | Статистика аудита |
| `GET` | `/v1/audit/log?method=&path=&status=` | Лог запросов/ответов с фильтрами |

### Сервис и безопасность

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/v1/sys/svc` | Статус сервиса (NSSM/Scheduled Task/systemd) |
| `GET` | `/v1/service/info` | Подробная информация о сервисе + PID |
| `GET` | `/v1/sys/funnel` | Статус Tailscale Funnel |
| `POST` | `/v1/tailscale/funnel/{action}` | Старт/стоп Funnel |
| `POST` | `/v1/token/regenerate` | Сменить auth-токен |
| `GET/POST/DELETE` | `/v1/users` | Управление пользователями |
| `GET/POST` | `/v1/profiles` | Safety-профили (cautious / owner-shell) |
| `POST` | `/v1/profiles/{name}/load` | Загрузить именованный safety-профиль |
| `GET/POST` | `/v1/ratelimit` | Конфигурация rate limiter'а |

### Наблюдаемость и продвинутое

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/v1/events` | WebSocket real-time поток событий |
| `GET/POST` | `/v1/tracing` | Конфигурация OpenTelemetry-трассировки |
| `GET/POST` | `/v1/traces/export` | Экспорт трасс |
| `GET/POST` | `/v1/alerts` | Управление алёртами |
| `GET` | `/v1/tls` | Конфигурация TLS |
| `GET/POST` | `/v1/sandbox` | Конфигурация sandbox |
| `GET/POST` | `/v1/cluster` | Статус кластера |
| `GET` | `/metrics` | Prometheus-совместимые метрики (text format) |

### Отчёты и миссии

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/v1/reports` | Список скриншотов и отчётов |
| `GET` | `/v1/missions` | Список скриптов-миссий |
| `GET` | `/v1/mission/show?name=…` | Показать детали миссии |
| `GET` | `/v1/mission/templates` | Список встроенных mission templates, доступных для composition |
| `GET` | `/v1/mission/status?name=…` | Получить структурированный status сохранённой mission |
| `GET` | `/v1/mission/report?name=…` | Прочитать mission report, сгенерированный mission manager'ом |
| `GET` | `/v1/mission/history?name=…` | Посмотреть историю run'ов и summaries step-log'ов для сохранённой mission |
| `GET` | `/v1/mission/lineage?name=…` | Посмотреть parent/child lineage, ancestors, descendants и siblings для сохранённой mission |
| `GET` | `/v1/mission/catalog?q=&state=&template=&has_report=&limit=&offset=` | Отфильтровать сохранённые missions по lifecycle-метаданным и получить summary stats |
| `POST` | `/v1/mission/compose` | Скомпоновать planner-backed mission draft из goal, context и опционального template |
| `POST` | `/v1/mission/propose` | Запустить bounded agentic proposal flow и вернуть mission bundle с опциональным create/run |
| `POST` | `/v1/mission/create` | Сохранить скомпонованный mission draft в локальную директорию `missions/` |
| `POST` | `/v1/mission/run` | Запустить сохранённую миссию по mission id через встроенный mission manager |
| `POST` | `/v1/mission/rerun` | Перезапустить mission, опционально только последний failed step или выбранный step |
| `POST` | `/v1/mission/recover` | Собрать recovery bundle для mission с опциональным rerun и follow-up mission composition |
| `POST` | `/v1/mission/followup` | Собрать следующую mission из артефактов существующей mission с agentic analysis |
| `POST` | `/v1/mission/iterate` | Запустить mission iteration loop, который объединяет recovery с опциональным созданием и запуском follow-up mission |

### Протокол MCP

| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/mcp` | MCP Streamable HTTP (спецификация 2025-03-26) |
| `DELETE` | `/mcp` | Закрыть MCP-сессию |
| `GET` | `/sse` | MCP SSE legacy-транспорт |
| `POST` | `/messages` | MCP SSE peer-эндпоинт |
| `GET` | `/ws` | MCP WebSocket-транспорт |

### Web Gateway

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/gateway` | Информация о Web Gateway |
| `GET` | `/gateway/tools` | Доступные gateway-инструменты |
| `POST` | `/run` | Запустить whitelisted-команду |
| `POST` | `/tool` | Проксировать MCP-вызов инструмента |

### Звук и уведомления

| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/v1/beep` | Воспроизвести звук (`success`, `warning`, `error`, `attention`, `melody`) |

### Дашборд и документация

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/gui` | Веб-дашборд (single-file HTML/JS) |
| `GET` | `/api-docs` | Спецификация OpenAPI 3.0 (JSON) |
| `GET` | `/openapi.json` | Алиас OpenAPI 3.0 для инструментов, ожидающих этот конвенциональный путь |

> Полный список: `GET /` возвращает JSON-каталог всех маршрутов.

---

## 🖥️ Веб-дашборд

Дашборд на `/gui` имеет **16 вкладок** и работает в любом современном браузере без внешних зависимостей (single self-contained HTML-файл).

| Вкладка | Что делает |
|---------|------------|
| **Overview** | Метрики моста, карточка диагностики оборудования, drawer с полным инвентарём, использование диска |
| **Workspace** | Companion-style поверхность для активного profile context, planner output, bounded ReAct runs, reflection, управления file watcher'ами, profile notes, important lessons, recent activity и mission loop studio для lineage / follow-up / iterate flows |
| **Terminal** | Настоящая shell-сессия со slash-командами (`/shot`, `/read`, `/search`, ...) + история по стрелкам |
| **Memory** | Список, поиск, добавление, удаление key/value/tag фактов |
| **Recall** | Fuzzy TF-scored поиск по памяти и дайджест |
| **Missions** | Просмотр директории `missions/` |
| **Browser** | One-click `search`, `read`, `dump`, `fetch`, `HEAD`, скриншот |
| **Reports** | Просмотр и скачивание скриншотов / отчётов |
| **Tasks** | Очередь inbox / running / done / failed, отправка новой задачи, очистка |
| **Skills** | Core skills + Superpowers + BrowserAct |
| **Hooks** | Список pre/post-хуков |
| **Agents** | Реестр сабагентов |
| **Control** | Статус desktop control lease, pause/resume/revoke actions и обзор активного окна |
| **Doctor** | 9 селфтестов + статус сервиса/Funnel + проверка свободного места на диске |
| **Audit** | Все события, фильтр по категории, статистика |
| **Settings** | Токены, звуковые уведомления, тумблер Tailscale Funnel, рестарт, экспорт конфигурации |

---

## 🛡️ Защита диска (v2.1.0)

Предыдущие версии могли заполнить весь диск, потому что дефолтный AccessLogger aiohttp писал строку в stderr на каждый HTTP-запрос, и эти строки попадали в append-only файлы логов без ротации. **Это исправлено в v2.1.0** многоуровневой защитой:

| Уровень | Механизм | Детали |
|---------|----------|--------|
| **Источник устранён** | `access_log=None` | aiohttp больше не пишет access-логи вообще |
| **Структурированное логирование** | `RotatingFileHandler` | 5 MB × 5 файлов для `bridge.log` |
| **Ротация при старте** | `_rotate_all_logs_on_startup()` | Ротирует любой oversized-файл перед стартом сервера |
| **Периодическая очистка** | `_log_cleanup_loop()` | Фоновая задача каждые 30 мин, ротирует логи больше 10 MB |
| **Мониторинг диска** | `disk_usage_percent` | Warning на 80%, critical на 90%, виден в `/v1/sysinfo` |
| **Ротация на уровне скрипта** | `install.bat`, `install.sh` | Ротация при 10 MB перед стартом моста |
| **Ротация NSSM** | `AppRotateFiles=1` | 5 MB, 3 rotated-копии в Windows-сервисе |
| **Навык очистки** | `core/cleanup` | Покрывает старые сессии, отчёты, завершённые задачи |

Все файлы логов — `bridge.log`, `audit.jsonl` (лимит 50 MB), `requests.jsonl` (лимит 10 MB) — теперь корректно ротируются.

> **Результат:** После 50+ тестовых запросов `bridge.log` остался на **797 байтах**. Раньше он мог расти до гигабайтов в час.

---

## 🔧 Управление сервисом

### Windows (NSSM или Scheduled Task)

```powershell
# NSSM-сервис
nssm status ArenaUnifiedBridge
nssm restart ArenaUnifiedBridge
nssm stop ArenaUnifiedBridge

# Scheduled Task (используется, если NSSM не установлен)
schtasks /run /tn "ArenaUnifiedBridge"
schtasks /end /tn "ArenaUnifiedBridge"
schtasks /query /tn "ArenaUnifiedBridge" /fo LIST /v

# Удалить stale scheduled task вручную (обычно uninstall.bat это делает)
schtasks /delete /tn "ArenaUnifiedBridge" /f

# Ручной старт
start_bridge.bat

# Посмотреть структурированные логи
type %USERPROFILE%\arena-bridge\bridge.log
```

### Linux (systemd-user)

```bash
systemctl --user status   arena-bridge
systemctl --user restart  arena-bridge
journalctl  --user -u     arena-bridge -f
```

### macOS (launchd)

```bash
launchctl print           gui/$UID/com.arena.bridge
launchctl kickstart -k    gui/$UID/com.arena.bridge
```

---

## 📂 Структура проекта

```
arena-bridge/
├── unified_bridge.py     ← тонкий compatibility/CLI-entrypoint (<150 строк)
├── arena/                ← модульная реализация моста
│   ├── app.py            ← фабрика aiohttp-приложения
│   ├── routes.py         ← фасад реестра маршрутов
│   ├── route_registry/   ← группы маршрутов по доменам (core, CDP, desktop, v2, MCP)
│   ├── contexts/         ← dataclass-ы зависимостей обработчиков, сгруппированные по доменам
│   ├── wiring/           ← хелперы композиции/wiring и legacy-compatibility-настройка
│   ├── browser/          ← browser fetch, high-level browse и CDP-модули
│   ├── desktop/          ← скриншоты, ввод, окна, KWin/Wayland-хелперы
│   ├── service/          ← статус сервиса, capabilities, рестарт-хелперы
│   ├── system/           ← sysinfo, doctor, звук, legacy hwinfo-fallback
│   ├── memory/           ← SQLite/FTS-хранилище памяти и recall-обработчики
│   ├── skills/           ← реестр навыков, install/uninstall/run/cache
│   ├── tasks/            ← очередь задач и фоновый runner
│   ├── observability/    ← метрики, аудит, логи, алёрты, трассировка
│   ├── admin/            ← токен, Tailscale Funnel, cloudflared-туннели
│   ├── mcp/              ← MCP-инструменты и транспорты
│   └── ...               ← gateway, grpc, tls, sandbox, cluster, resources
├── token.txt             ← ваш auth-токен (генерируется автоматически)
├── install.bat           ← Windows-установщик (запустите это)
├── install.sh            ← Linux/macOS-установщик (запустите это; повторно — для обновления)
├── uninstall.bat/.sh     ← чистое удаление сервиса + файлов
├── docs/                 ← заметки по архитектуре, stress-test-гайд, шаблон AI-промпта
├── dev/                  ← инструменты релиза/stress-тестов (`stress-test-v4.py`)
├── bin/                  ← пользовательские CLI (agentctl, bridge-curl и т.д.)
├── scripts/              ← фоновые helper'ы (inventory, CDP, desktop и т.д.)
├── skills/               ← AI-runnable playbooks и интеграция BrowserAct
├── memory/               ← локальная БД/файлы памяти
├── missions/             ← скриптовые workflows
├── queue/                ← очередь задач (inbox/running/done/failed)
├── reports/              ← скриншоты, записи, выводы
├── hooks/                ← pre/post skill-хуки
├── agents/               ← конфигурации агентов
├── subagents/            ← spawn/track сабагентов
├── tools/                ← внешние инструменты
└── mcp/                  ← конфигурация MCP
```

См. [`AGENTS.md`](AGENTS.md), [`docs/AI_CODEBASE_NAVIGATION.md`](docs/AI_CODEBASE_NAVIGATION.md), [`docs/V3_MODULAR_ARCHITECTURE.md`](docs/V3_MODULAR_ARCHITECTURE.md), [`docs/MODULE_MAP.md`](docs/MODULE_MAP.md), [`docs/V3_RELEASE_CHECKLIST.md`](docs/V3_RELEASE_CHECKLIST.md), [`docs/MOBILE_SUPPORT_ROADMAP.md`](docs/MOBILE_SUPPORT_ROADMAP.md) — карты доменов, release gates, мобильное планирование и гайдансы для людей и AI-кодинг-агентов.

---

## ⚙️ Конфигурация

Все настройки — переменные окружения (установите перед запуском `install.*` или стартом сервиса):

| Переменная | По умолчанию | Назначение |
|------------|--------------|------------|
| `ARENA_HOME` | директория репо | Директория данных агента (та же, что и репо) |
| `BRIDGE_HOME` | директория репо | Директория моста (та же, что и репо) |
| `ARENA_PORT` | `8765` | Порт прослушивания |
| `ARENA_PROFILE` | `owner-shell` | Safety-профиль (правила в коде) |
| `ARENA_TASK_NAME` | `ArenaUnifiedBridge` | Windows Scheduled Task / Service |
| `ARENA_SERVICE_NAME` | `ArenaUnifiedBridge` | Имя NSSM-сервиса |
| `ARENA_TOKEN_FILE` | `<repo>/token.txt` | Файл токена |
| `ARENA_BRIDGE_TOKEN` | (нет) | Переопределить токен в рантайме |
| `ARENA_BRIDGE_URL` | `http://127.0.0.1:8765` | Базовый URL для `bridge-curl`/клиентов |

---

## 🧪 Протестированные платформы

| ОС | Способ установки | Сервис | Статус |
|----|------------------|--------|--------|
| Windows 10 LTSC (build 19044) | `install.bat` | Scheduled Task | daily-driver |
| Windows 11 | `install.bat` | NSSM | smoke-tested |
| Debian 13 (trixie) | `install.sh` | systemd-user | smoke-tested |
| Ubuntu 22.04 / 24.04 | `install.sh` | systemd-user | через контейнер |
| CachyOS (Arch) | `install.sh` | systemd-user | daily-driver |
| Fedora 40+ | `install.sh` | systemd-user | dnf-aware |
| macOS 13+ (Apple Silicon) | `install.sh` | launchd | нужна помощь |
| FreeBSD 14 | `install.sh` | rc.d / nohup | нужна помощь |

Кроссплатформенный установщик сам определяет `apt`, `dnf`, `pacman`, `apk`, `zypper`, `nix`, `brew`, `pkg`, `winget`.

---

## 🔒 Модель безопасности

- **Только токен-auth** по умолчанию. Токен — 256-битная base64-url-строка, хранится в `token.txt` (`chmod 600` на Linux).
- **Ни один запрос не без auth**, кроме `/health` и индекса `/`.
- **`/v1/exec` фильтрует команды** через заблокированные паттерны (`rm -rf /`, `sudo`, `su`, `format`, `mkfs`, `diskpart`, `bcdedit`, `reg delete`, `curl|sh`, encoded PowerShell, очевидные чтения секретов, reverse shells, ...) и `CAUTIOUS_ALLOW` allowlist для безопасных read-only команд. Кастомизируется в `unified_bridge.py`.
- **Control lease применяется к input injection** — когда активны `/v1/control/pause` или `/v1/control/revoke`, desktop-эндпоинты блокируются, а `/v1/exec` также отклоняет команды, которые инжектируют ввод клавиатуры/мыши (`ydotool`, `xdotool key/click/type`, `wtype` и т.д.). Общая shell-диагностика остаётся доступной, чтобы не залочить себя.
- **Файловые операции в sandbox** — пути upload/download должны быть внутри домашней директории пользователя. Path traversal (`..`) блокируется, перезаписать сам бинарник моста нельзя.
- **SSRF-защита browser fetch** — `/v1/browser/read`, `/dump`, `/fetch`, `/head` разрешают только HTTP(S) публичные цели. Валидатор блокирует localhost/private/link-local/reserved/multicast/unspecified-адреса, обфусцированные IPv4 (`127.1`, octal, hex, integer), IPv4-mapped IPv6 loopback, internal/metadata-имена хостов и DNS-имена, резолвящиеся во внутренние адреса.
- **Система профилей**: `owner-shell` (разрешительный) и `cautious` (ограниченный). Переключается через env-var `ARENA_PROFILE`.
- **Rate limiting**: 300 запросов в минуту на IP, настраивается через `/v1/ratelimit`. Auth-неудачи rate-limit'ятся отдельно — 10 попыток в минуту на IP.
- **CORS** включён на всех ответах (браузерные AI-дашборды могут вызывать вас).
- **Audit-лог** фиксирует каждый exec, каждый upload/download, каждое событие token/funnel/restart с автоматической ротацией на 50 MB.
- **Никакой телеметрии, никакой аналитики, никаких phone-home.** Единственные исходящие вызовы:
  - Пользовательские вызовы из эндпоинтов `/v1/browser/*`
  - Вызовы MCP-инструментов (exec, fs.read, fs.write, browser.search и т.д.)
  - Проверки статуса Tailscale
- **Не стелс-ПО.** Мост работает как видимый сервис/scheduled task с читаемыми командными строками и задокументированными именами процессов. Он спроектирован проверяемым и удаляемым, не скрытым.

Если сомневаетесь — начните с `unified_bridge.py`. Это тонкий compatibility-entrypoint, реализация лежит в сфокусированных модулях `arena/*`.

---

## 🐛 Устранение неполадок

### Я вижу `python.exe`, `local_bridge.py`, `mcp_ws_server.py` или `web_gateway.py` в Task Manager — это вирус?
Нет — это процессы моста Arena / фоновые helper'ы, особенно из старых приватных/pre-GitHub сборок. Они должны быть видны в Task Manager или PowerShell, и вы можете их удалить.

Проверьте так:

```powershell
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
  Where-Object { $_.CommandLine -match 'arena|bridge|mcp_ws|web_gateway|agentctl|local_bridge' } |
  Select-Object ProcessId, ParentProcessId, CommandLine |
  Format-List
```

Затем запустите `uninstall.bat` из папки моста. Если это старая сборка без uninstaller'а — остановите процессы и удалите stale scheduled tasks, как показано в [Прозрачность: фоновые процессы — это нормально](#-прозрачность-фоновые-процессы--это-нормально-не-вирус).

### Мост не поднимается после рестарта на Windows
Мост использует Scheduled Task (или NSSM, если установлен). Оба авто-рестартуют при failure. Проверьте:
```powershell
schtasks /query /tn "ArenaUnifiedBridge"
# или, если NSSM:
nssm status ArenaUnifiedBridge
```

### Диск заполнился файлами логов (v2.0.9 и ранее)
**Исправлено в v2.1.0.** Корневая причина — AccessLogger aiohttp писал каждый HTTP-запрос в stderr, попадавший в append-only файлы логов. Обновитесь до v2.1.0, и мост будет:
- Полностью отключать access-логи
- Делать ротацию всех файлов логов при старте
- Периодически проверять и ротировать oversized-логи (каждые 30 мин)
- Предупреждать, когда использование диска превышает 80%

### CDP WebSocket становится нестабильным на тяжёлых страницах
**Улучшено в v2.5.1.** Health-probe теперь использует лёгкий `Target.getTargetInfo` вместо `eval_js`, а проверка WebSocket-ping толерантна к случайным timeout'ам. Мост переподключится автоматически после 3 подряд неудач.

### Клик/нажатие клавиши на рабочем столе не доходит до целевого окна
**Исправлено в v2.5.1.** Клик теперь автоматически активирует целевое окно (через `kdotool`/`xdotool`) перед отправкой события клика, что гарантирует попадание ввода в правильное окно.

### PowerShell-окна всплывают на каждом обновлении дашборда
Bridge < v1.6.7 запускал `wmic`/`tailscale`/`schtasks` без `CREATE_NO_WINDOW`. Исправлено в v2.0+ — все subprocess-вызовы используют `_NO_WINDOW_FLAG` на Windows.

### Tailscale Funnel постоянно отваливается
Funnel периодически падает, если upstream-порт перестаёт принимать (например, когда мост рестартует). NSSM/Scheduled Task авто-респавнит мост; переактивируйте Funnel:
```powershell
tailscale funnel --bg 8765
```

### Команды desktop печатаются как абракадабра (например, `/time set day` → `.ешьу ыуе вфн`)
Это происходит, когда raw keycodes интерпретируются через нелатинскую активную раскладку клавиатуры. **Улучшено в v2.10.0:** `/v1/desktop/type` использует `ensure_latin: true` по умолчанию на KDE, переключаясь на первую/Latin-раскладку перед вводом.

### Скриншот слишком большой или медленный для vision-агентов
Используйте transforms скриншотов v2.10.0 вместо полноразмерного PNG:

```bash
GET /v1/desktop/screenshot?format=jpeg&scale=0.5&quality=80
# или
GET /v1/desktop/screenshot?format=jpeg&max_width=1280&quality=80
```

### "Token rejected (401)" после нажатия Regenerate
Новый токен записан на диск; запущенный процесс держит старый в памяти. Нажмите **Restart Bridge** в Settings или перезапустите сервис.

### Как удалить
Запустите `uninstall.bat` (Windows) или `uninstall.sh` (Linux/macOS). Это остановит сервис, удалит scheduled task / systemd-юнит и удалит все файлы моста.

---

## 📊 Похожие проекты

> **Дисклеймер:** В этом разделе перечислены другие open-source проекты в области AI-агентов / computer-use исключительно для сравнения. Arena Unified Bridge — независимый проект, не связанный с, не одобренный и не производный от каких-либо проектов ниже. Все товарные знаки принадлежат их владельцам. Количество звёзд приблизительное и было актуально на момент написания (июнь 2026) — проверяйте актуальные числа на GitHub каждого проекта.

Arena Unified Bridge занимает конкретную нишу: **кроссплатформенный локальный мост**, который позволяет **любому AI** (не только модели одного вендора) управлять вашим компьютером через **REST + MCP + WebSocket** на **одном порту** с **токен-аутентификацией + firewall команд + path sandbox**. Проекты ниже пересекаются по-разному — некоторые фокусируются на автоматизации рабочего стола, некоторые на кодинг-агентах, некоторые на чат-бот-ассистентах. Ни один из них не является прямой заменой; у каждого свои trade-offs.

### Автоматизация рабочего стола / computer-use агенты

| Проект | Звёзды | Язык | Что делает | Чем Arena отличается |
|--------|--------|------|------------|----------------------|
| [**Bytebot**](https://github.com/bytebot-ai/bytebot) | ~11k | TypeScript | Self-hosted AI desktop agent в Docker; управляет Linux-рабочим столом через мышь/клавиатуру | Bytebot только Docker (Linux), Arena работает нативно на Windows/Linux/macOS. У Bytebot нет REST/MCP API — Arena даёт 130+ эндпоинтов. |
| [**OpenClaw**](https://github.com/openclaw/openclaw) (ex-Clawdbot) | ~379k | TypeScript | Self-hosted персональный AI-ассистент через WhatsApp/Telegram/Discord/Slack | OpenClaw — чат-бот-ассистент (вы общаетесь через мессенджеры). Arena — API автоматизации (любой AI вызывает ваш компьютер через HTTP). Разные сценарии. |
| [**Open Interpreter**](https://github.com/OpenInterpreter/open-interpreter) | ~58k | Python | Позволяет LLM запускать код (Python, JS, shell) на вашей машине через чат | Open Interpreter — CLI-чат (одна модель, одна сессия). Arena — постоянный сервер (любой AI, любое число сессий, фоновые задачи, дашборд). |
| [**Agent S**](https://github.com/simular-ai/Agent-S) | ~2k | Python | Open agentic framework для автономного взаимодействия с компьютером (GUI) | Agent S фокусируется на восприятии GUI + клик-автоматизации. Arena — на автоматизации через API (exec, файлы, браузер). Разные слои абстракции. |
| [**Anthropic Computer Use**](https://www.anthropic.com/news/3-5-models-and-computer-use) | — | Python | Официальный Claude computer-use API (скриншот + мышь/клавиатура) | Работает только с Claude. Cloud-only, не self-hosted. Arena работает с любым AI и запускается на вашей машине. |

### AI кодинг-агенты (редактируют файлы, запускают shell)

| Проект | Звёзды | Язык | Что делает | Чем Arena отличается |
|--------|--------|------|------------|----------------------|
| [**Cline**](https://github.com/cline/cline) | ~63k | TypeScript | VS Code расширение: AI кодинг-агент с plan/act режимами, MCP | Cline живёт внутри VS Code. Arena — standalone сервер, доступный из любого инструмента. `str_replace_editor` от Cline вдохновил `fs.edit` в Arena — но Arena работает через REST и MCP, не только VS Code. |
| [**Desktop Commander MCP**](https://github.com/wonderwhy-er/DesktopCommanderMCP) | ~5k | TypeScript | MCP сервер для Claude: контроль терминала, поиск файлов, diff-редактирование | Одноцелевой MCP сервер (только Claude). Arena — мультипротокольный мост (REST + MCP + WS + SSE), работающий с любым AI. |

### Коллекции MCP серверов

| Проект | Звёзды | Язык | Что делает | Чем Arena отличается |
|--------|--------|------|------------|----------------------|
| [**Model Context Protocol servers**](https://github.com/modelcontextprotocol/servers) | ~87k | TypeScript | Официальные reference MCP серверы (filesystem, shell и т.д.) — каждый делает одно | Каждый MCP сервер — один инструмент. Arena включает 20+ MCP инструментов **плюс** 130+ REST эндпоинтов **плюс** дашборд **плюс** фоновые задачи — всё в одном процессе. |
| [**awesome-mcp-servers**](https://github.com/appcypher/awesome-mcp-servers) | ~3k | — | Кураторский список MCP серверов | Список, не продукт. Arena — запускаемый продукт со встроенным MCP сервером. |

### Браузерная автоматизация

| Проект | Звёзды | Язык | Что делает | Чем Arena отличается |
|--------|--------|------|------------|----------------------|
| [**browser-use**](https://github.com/browser-use/browser-use) | ~50k | Python | Делает сайты доступными для AI через браузерную автоматизацию | browser-use — только браузер. Arena — браузер **плюс** shell **плюс** файлы **плюс** desktop **плюс** память. |

### Где Arena Unified Bridge находится

Arena **не пытается заменить** перечисленные проекты. Она заполняет нишу: **единый, self-hosted, кроссплатформенный мост**, который любой AI может вызывать через стандартные HTTP/MCP, со встроенной безопасностью. Если вам нужен:
- **Персональный ассистент** для общения → используйте OpenClaw
- **Кодинг-агент в VS Code** → используйте Cline
- **GUI клик-автоматизацию** → используйте Bytebot или Anthropic Computer Use
- **Только браузерную автоматизацию** → используйте browser-use
- **Локальный API, который любой AI или скрипт может вызывать для управления компьютером** → это Arena

---

## 🗺️ Roadmap

- [x] **Cloudflare Tunnel** как альтернатива Tailscale Funnel (без аккаунта)
- [x] **Плагин-архитектура** для установки/удаления сторонних навыков
- [x] **Локальная семантическая RAG-память** через SQLite FTS5
- [x] **AppContainer-sandbox** на Windows для опциональной изоляции команд
- [x] Замена `wmic` (deprecated в Win11) на CIM-cmdlets в `_sys_*` helper'ах
- [x] Linux Wayland-запись в `mission-record` (раньше только x11grab)
- [ ] Рецепты интеграции AnythingLLM / Open WebUI в `skills/`
- [x] Webhook-уведомления о событиях
- [ ] Поддержка Android/mobile после стабильного v3.0.0 (см. `docs/MOBILE_SUPPORT_ROADMAP.md`)
- [ ] Очистка кода и репозитория (удалить неиспользуемые тест-файлы, старые конфиги)

---

## 🤝 Контрибьюшн

Issues и PR приветствуются. Пожалуйста:
- Держите `unified_bridge.py` **тонким compatibility-entrypoint**; новый код принадлежит сфокусированным `arena/<domain>/`-модулям.
- Прогоняйте stress-test через `pytest -q` и `dev/stress-test-v4.py` перед отправкой PR.
- Pure-ASCII PowerShell-скрипты (никаких unicode-дефисов/эмодзи — они ломают кириллические Windows-установки).
- Делайте снэпшот перед деструктивными операциями (используйте внешние backup-инструменты).

---

## 📄 Лицензия

MIT License

Copyright (c) 2025-2026 Ivan / IvanSkainet

Данная лицензия разрешает любому лицу, получившему копию данного программного обеспечения и сопутствующей документации (далее — «ПО»), безвозмездно использовать, копировать, изменять, сливать, публиковать, распространять, сублицензировать и/или продавать копии ПО, а также лицам, которым предоставляется ПО, делать это при следующих условиях:

Вышеуказанное уведомление об авторских правах и данное уведомление о разрешении должны быть включены во все копии или существенные части ПО.

ПО ПРЕДОСТАВЛЯЕТСЯ «КАК ЕСТЬ», БЕЗ КАКИХ-ЛИБО ГАРАНТИЙ, явных или подразумеваемых, включая, но не ограничиваясь, гарантиями товарности, пригодности для конкретной цели и ненарушения прав. Ни при каких обстоятельствах авторы или правообладатели не несут ответственности за какие-либо претензии, ущерб или иную ответственность, будь то в результате действия контракта, деликта или иного, возникающего из или в связи с ПО или использованием или иными сделками с ПО.

---

*Создано совместно Иваном и сменяющимися AI-ассистентами на [arena.ai](https://arena.ai/) — мост использовался для разработки моста. Рекурсия дружелюбного толка.*

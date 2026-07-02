# История изменений

> 🌐 [English version](CHANGELOG.md)

## v3.77.0 - 2026-07-02

- README.md переписан как чистая публичная landing page; история релизов вынесена из основного README.
- README.ru.md переписан как актуальная русская landing page с той же структурой.
- CONTRIBUTING.md и chat_extension/README.md обновлены под текущий unified bridge и extension workflow.

## v3.1.6 — 2026-06-17

### Исправлено
- **Установщик больше не понижает версию молча на существующих установках.** `install.sh` (Linux/macOS) теперь читает локально установленную версию, fetch'ит только *текущую* ветку из origin (никогда не переключает ветки), сравнивает локальную и remote-версии semver-aware и спрашивает перед обновлением. Обновления используют `git merge --ff-only`, так что локальные коммиты никогда не теряются. Деструктивный паттерн `git checkout -B <branch> FETCH_HEAD` убран.
- **Установщик больше не использует устаревшую ветку `v3-modular-core` по умолчанию.** Свежие установки теперь тянут `master` (текущая стабильная release-ветка). Переопределите через `ARENA_BRANCH=<name>`.
- **`install.bat` (Windows) теперь информирует о новых релизах на GitHub.** Мягкая проверка версии через GitHub releases API печатает строку `[INFO]`, если доступна более новая версия. Никогда не авто-обновляет и не переключает ветки — просто информирует пользователя.
- **Поставляемый `webhooks.json` больше не содержит мёртвый debug-URL.** Предыдущие релизы наследовали `http://127.0.0.1:9999/webhook` из репозитория, из-за чего каждая свежая установка спамила несуществующий эндпоинт (circuit breaker в v3.1.5 корректно делал backoff, но сам конфиг-шум не должен существовать). По умолчанию теперь `{urls: [], events: ["*"]}`.

### Отрефакторено
- Заменил `asyncio.get_event_loop()` на `asyncio.get_running_loop()` в 18 файлах (43 места). Все вызовы — внутри async-функций, которые сразу `await loop.run_in_executor(...)`, поэтому новый API возвращает тот же loop без `DeprecationWarning`, который Python 3.12+ испускает для `get_event_loop()` вне running loop. Поведенческих изменений нет.

### Тесты
- Добавлен `tests/test_installer_version_safety.py` (7 тестов), защищающий фикс инсталлятора: default-ветка — `master`, нет деструктивного `git checkout -B`, обновления только fast-forward, `_arena_version_lt()` проходит 12 semver-кейсов (равенство, v-prefix, double-digit patch, pre-release suffix, короткие версии), `install.bat` имеет мягкую проверку версии и не git-pull/git-checkout сам мост.

### Документация
- `README.md`: заменил статический badge `version-v3.1.5-blue` на динамический `shields.io/github/v/release/...`, который авто-обновляется при каждом релизе — больше не нужно править README вручную ради bump'а версии.
- `README.md`: добавил новую секцию **"### 3. Updating an existing installation"**, описывающую безопасное поведение обновления.
- `README.ru.md`: добавлен полный русский перевод README (782 строки). Шапки обоих файлов теперь содержат переключатель языков `🌐 English · Русский`.
- `RELEASE.md`: добавлен подробный playbook релиза с pre-/post-release чеклистами, объяснением зачем нужны два zip-ассета (versioned + unversioned alias `arena-agent.zip`), что включать/исключать из zip, где лежит версия, формат CHANGELOG.
- `scripts/make_release_zip.py`: скрипт, который auto-detect'ит версию из `arena/constants.py`, создаёт zip с правильными исключениями и печатает следующие команды для `gh release upload`.

### Релиз
- v3.1.6 — первый релиз с **двумя zip-ассетами**: `arena-agent-v3.1.6.zip` (по исторической конвенции) и `arena-agent.zip` (алиас без версии, чтобы one-liner из README работал). Раньше (v3.1.0–v3.1.5) существовал только versioned-файл, поэтому README-инструкция `curl releases/latest/download/arena-agent.zip` возвращала 404.

### Валидация
- Локальный `pytest -q`: PASS, 413 тестов (406 предыдущих + 7 новых installer-guardrails).
- Локальный `bash -n install.sh`: PASS.
- Локальный `python -m py_compile` по всем изменённым файлам: PASS.
- Live smoke-test `install.sh` на тестовом клоне: корректно сообщает `Local version: v3.1.6 / Remote version: v3.1.6 / Already up to date` и не переключает ветки.
- Bridge `/v1/doctor`: 10/10 проверок проходят.

## v3.1.5 — 2026-06-17

### Исправлено
- Добавлен per-URL circuit breaker/backoff для вебхуков — мёртвые webhook-таргеты больше не ретраятся и не логируются на каждое событие.
- Failure/recovery вебхуков теперь логируется при смене состояния вместо непрерывного флуда `bridge.log`.

### Тесты
- Добавлен `tests/test_webhooks_backoff.py`, покрывающий порог, cooldown, экспоненциальный retry, recovery, фильтрацию событий и логирование внутренних ошибок.

### Валидация
- Локальный `pytest -q`: PASS, 413 тестов.
- Локальный критический ruff и py_compile: PASS.

---

## Более ранние версии

Полная история изменений с v2.0.7 по v3.1.4 доступна в [англоязычном CHANGELOG.md](CHANGELOG.md).

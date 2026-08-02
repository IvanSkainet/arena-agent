# GitHub Apps / Actions — обзор рынка для arena-agent (2026-08-02)

Цель: посмотреть, что есть на рынке, и решить осознанно, что (если вообще)
добавлять. Критерии из нашей доктрины (AGENTS.md):

- **Зелёное ≠ работает** — инструмент полезен, только если его сигнал имеет
  маршрут (blocking gate или отдельная видимая метка), а не тонет в логах.
- Шум не должен забивать главный красный: новый сканер = новый класс
  false-positive triage. Каждый кандидат оценивается ещё и ценой шума.
- Ноль открытых security-алертов обязателен: всё, что пишет в Code Scanning
  (SARIF), увеличивает triage-доску.
- Бесплатно для public repo.

## Что УЖЕ стоит (не дублировать)

| Слой | Уже есть |
|---|---|
| SAST | CodeQL, Bandit, Semgrep, DevSkim |
| Секреты | TruffleHog, Gitleaks, GitHub secret scanning |
| Зависимости | Dependabot, dependency-review, pip-audit, OSV-Scanner, Syft+Grype (SBOM) |
| Supply chain | Scorecard, Socket Firewall, hash-locked installs везде, zizmor, actionlint |
| Качество | ruff (+ratchet), pyrefly (+ratchet), vulture (+ratchet), import-linter contracts, coverage gate 70% (pyproject, branch coverage) |
| Упаковка | packaging-e2e (build→twine→check-wheel-contents→install→import) |
| E2E | e2e-installed (живой сервер из wheel: auth/MCP/fs/jail/teardown) |
| AI review | CodeRabbit (app), DeepSource (12 FP), Sourcery (~260 FP) |
| Тесты | pytest-randomly + timeout, 4764 шт., contract/catalogue/legacy guards |

## Рынок по категориям

### AI code review
CodeRabbit (у нас), Copilot code review, Cubic, Qodo Merge, Greptile, Ellipsis, Bito.
Вывод: второй контур AI-review поверх CodeRabbit — только шум.
Sourcery и DeepSource уже доказали на нашей архитектуре ~100% false-positive.
**Решение: ничего не добавлять.**

### Дашборды качества (SonarCloud / Codacy / Qlty / CodeScene / Qodana)
SonarCloud (бесплатно для OSS, quality gates), Codacy ($15/user, all-in-one),
Qlty (ex-CodeClimate; cobertura coverage + smells + autofix), CodeScene
(behavioral hotspots), Qodana (JetBrains inspections).
Вывод: их детекторы дублируют ruff/pyrefly, а governance-слой рассчитан на
команду. Единственная реальная ценность — тренды покрытия снаружи.
**Решение: не добавлять карты детекторов; coverage-тренды — при желании Codecov
(P3, weak).**

### Runtime-безопасность раннера: StepSecurity Harden-Runner
Мониторинг/контроль egress, file integrity, процессов на runner'е (EDR для CI).
Бесплатен для OSS (community tier). Наш CI крутит PAT с push-доступом и ставит
сотни пакетов из PyPI — ровно его сценарий (кейсы: tj-actions compromise,
2026 PHP worm). Режим `egress-policy: audit` не блокирует — шум идёт в их
dashboard, а не в наш красный. **Кандидат P1** — добавить как первый step в
jobs с секретами (badge/release/push-путные).

### Обновления зависимостей: Dependabot (у нас) → Renovate
Renovate умеет группировки, lock-file maintenance и post-upgrade hooks —
теоретически может перегенерировать наши universal locks сам. Риск: любой
авто-regen lock-файлов должен проходить `check_ci_lock.py` + реальный install
(история py3.10 marker-drop). Пока pre-flight ручной, Renovate опаснее, чем
полезен. **P3: вернуться после автоматизации regen-пайплайна.**

### Coverage UIs: Codecov / Coveralls / qlty-sh
coverage.xml CI уже пишет; gate 70% свой. Codecov даст PR-комментарии с дельтой
покрытия — приятно, но наш ratchet-паттерн закрывает gate-cffect локально.
**P3, опционально.**

### Mutation testing (cosmic-ray / mutmut)
Отвечает на вопрос «а тесты вообще способны поймать регрессию?» — самый честный
искусственный сигнал качества suite. Дорого: на нашем объёме — только sampled
(по изменённым модулям) и только nightly. **Кандидат Tier-3 (P2 как nightly, не PR).**

### Dashboard/UI E2E: Playwright (+ actions/setup для браузеров)
У моста есть веб-dashboard (`/gui`). Playwright-E2E поверх живого сервера из
e2e-installed — естественное продолжение «продвинутого E2E». **Кандидат Tier-3 (P2).**

### Локальный воспроизводимый CI: nektos/act / dagger / pre-commit
- `pre-commit` (локальные hooks: ruff + ratchets) — дешёвый предохранитель долга
  до CI. **P2, опционально.**
- `act` — прогон workflow локально; наш sandbox-ритм (push→ожидание CI)
  выиграл бы. **P3.**

### Релиз/PyPI
`pypa/gh-action-pypi-publish` (trusted publishing), `hynek/build-and-inspect-python-package`.
Наш packaging-e2e покрывает больше (hash-locks + install из чистого env) и мы не
публикуемся в PyPI. **Не нужно.**

## Shortlist решений

| # | Что | Приоритет | Маршрут сигнала | Решение |
|---|---|---|---|---|
| 1 | StepSecurity Harden-Runner (audit) | P1 | их dashboard + insights, не наш красный | **ДОБАВЛЕН** 2026-08-02: 29 jobs (ci/version-badge/security-scan), SHA-pinned v2.20.0 |
| 2 | pre-commit hooks (ruff/ratchets локально) | P2 | локальный | опционально, конфиг в репо |
| 3 | Mutation testing sampled (cosmic-ray, nightly) | P2→Tier-3 | отдельный nightly workflow | позже |
| 4 | Playwright dashboard E2E | P2→Tier-3 | blocking e2e job | позже |
| 5 | Codecov | P3 | PR comment | **РАБОТАЕТ** 2026-08-02: codecov-action v7.0.0 SHA-pinned, token-auth, 15 legs upload, statuses informational-only. Первое покрытие: **52.75%** (20185/38261). Badge в обоих README |
| 6 | Renovate | P3 | PR queue | после автоматизации regen-lock |
| 7 | SonarCloud/Codacy/Qodana/CodeScene | — | — | не добавлять (дубль ruff/pyrefly) |
| 8 | Второй AI-review contour | — | — | не добавлять (FPS: DeepSource/Sourcery) |

Статус: P1 выполнен (harden-runner@bf7454d egress-policy: audit как первый
шаг 29 jobs). Остальное ждёт явного решения пользователя.

## Codecov: разбор инцидента (2026-08-02)

Подключение прошло не с первой попытки, и причина стоит того, чтобы её помнить.

**Симптом**: все uploads (OIDC, token, даже ручной 4-строчный XML) → `state: error`
за ~5 секунд, `errors: null`. Диагностика по кругу исключила auth, пути,
схему XML, валидность `codecov.yml` и статус их сервиса.

**Причина**: Codecov CLI по умолчанию **ищет файлы отчётов по всему дереву** и
находил два: свежий `coverage.xml` из корня и `scripts/_testdata/coverage.xml` —
закоммиченную тестовую фикстуру для `coverage_diff.py` с timestamp девятидневной
давности. Их воркер отбраковывает отчёты старше 12 часов и валил **весь upload
целиком** из-за протухшей фикстуры. Это же объясняло провал ручной загрузки:
CLI, запущенный из корня репо, подхватывал ту же фикстуру.

Найдено скачиванием реального payload из их storage и распаковкой zstd — в нём
оказалось два `<coverage>`-корня с разными timestamp.

**Урок для репозитория**: любой файл с именем, попадающим под glob-паттерны
Codecov (`coverage*.xml`, `cobertura*.xml`, `jacoco*.xml`, `*.lcov`), отравляет
upload независимо от того, где он лежит. Фикстуры отчётов держим под
нейтральными именами (`diff_report_fixture.xml`), артефакты покрытия — в
`.gitignore`, а сам upload сделан герметичным: `disable_search: true` в связке с
`files:` (по их `action.yml` параметр `files` только ДОБАВЛЯЕТ к найденному
поиском, поэтому одного его недостаточно).

### Разбор находок DeepSource по этим правкам (2026-08-02)

**SCT-1000 «hardcoded credential» на badge-токен в README — принято, исправлено.**
Codecov выдаёт markdown бейджа с `?token=<repo-badge-token>`, но проверка показала, что для
публичного репозитория токен не нужен: `graph/badge.svg` и `graph/badge.svg?token=…`
возвращают **байт-в-байт идентичный SVG** (2274 B, `53%`). Токен убран из обоих README —
меньше секретов в дереве, поведение не меняется. Правило: значение вида `?token=` в
URL не тащим в репозиторий, даже когда сервис сам его подсовывает.

**«Command injection from dynamic arguments in subprocess» в ratchet-скриптах — false positive.**
Проверено структурно (AST-обход всех вызовов `subprocess.run` в
`scripts/{lint_ratchet,quality_ratchet,f401_reexport_clean}.py`):
- `shell=` не передаётся нигде — значит шелл не участвует, и метасимволы
  (`;`, `|`, `$()`) интерпретировать некому;
- argv собирается из строковых литералов плюс `sys.executable`; параметров,
  приходящих извне (argv скрипта, env, сеть, содержимое файлов), в командной
  строке нет.

Рекомендация сканера («избегайте `shell=True`») уже выполнена — конструкции с
`shell=True` в этих файлах никогда не было. Правило репозитория остаётся прежним:
дочерние процессы запускаются только списком аргументов, без шелла.

## Ревизия каталога GitHub (2026-08-02): 78 security-workflow + Marketplace

Пользователь прислал полный каталог security-workflows и подборку Marketplace.
Прошёл весь список против нашего инвентаря. Итог: **из 78 предложенных workflow
для нас релевантны единицы, и главная находка — не инструмент, а дыра в проверках.**

### Что уже стоит (не рассматривать повторно)

CodeQL, Semgrep, Bandit, DevSkim, TruffleHog, Gitleaks, OSV-Scanner, Anchore
Syft+Grype (SBOM), Socket Firewall, pip-audit, Dependency Review, OSSF Scorecard,
zizmor, actionlint, harden-runner, Codecov. Плюс собственные ratchet-ворота
(ruff/pyrefly/vulture), import-linter contracts, packaging-e2e и e2e-installed.

### Отсечено сразу — не наш стек

Gosec (Go), Brakeman/RuboCop (Ruby), PHPMD/Psalm/njsscan (PHP/JS), Detekt (Kotlin),
Credo (Elixir), Flawfinder (C/C++), rust-clippy, lintr (R), PSScriptAnalyzer,
puppet-lint, clj-holmes/clj-watson (Clojure), Sobelow (Phoenix), pmd, ESLint,
SecurityCodeScan (.NET), Jscrambler, mobsf/Appknox/NowSecure/zScan (мобильные
бинарники — у нас Python-обвязка ADB, не APK), Datree/Kubesec/tfsec/Trivy/
Prisma/Zscaler/cloudrail/Policy Validator (K8s/Terraform/контейнеры — у нас их нет),
Haskell Dockerfile Linter (нет Dockerfile).

### Отсечено по стоимости шума или коммерции

Fortify, Checkmarx (CxSAST/One), Veracode, Black Duck, Synopsys, Endor Labs,
JFrog SAST/Frogbot, Snyk (Code/Container/IaC), Xanitizer, CodeScan, Contrast,
Debricked, Sysdig, StackHawk, APIsec/EthicalCheck, NeuraLegion, Mayhem, SOOS DAST,
Codacy, Microsoft Defender for DevOps, OSSAR (обёртка над тем, что уже стоит).
Причина одна и та же: платно либо дублирует существующий слой, добавляя третий
поток false positives. Сегодняшний улов DeepSource — 1 реальная находка на 4
ложных — показывает цену лишнего сканера.

### SonarQube / SonarCloud — НЕ добавлять

Community Edition (self-hosted, LGPLv3) не умеет ни branch analysis, ни
PR-декорацию, плюс требует сервер и PostgreSQL. SonarQube Cloud бесплатен для
публичных репозиториев и умеет PR-декорацию, но его детекторы дублируют
ruff + pyrefly + vulture + CodeQL + Semgrep + Bandit. Новой сигнальности ноль,
шум +1 источник.

### Pyre / Pysa (Meta) — НЕ добавлять, но по интересной причине

Pysa делает taint-анализ (source → sink), которого у pyrefly нет. Формально это
единственный кандидат с новым классом сигнала. Но: у нас уже есть CodeQL с
inter-procedural dataflow на тех же путях, а Pysa требует своих `taint.config` и
`.pysa`-моделей и даёт ложные срабатывания на непокрытых зависимостях (по их же
документации: если taint уходит в функцию без исходников, возвращаемое значение
считается заражённым). Ценность появится только если писать модели под наши
sink'и — это отдельный проект, не «включить action».

### AI-slop детекторы (anti-slop и родня) — НЕ добавлять

Заманчиво по профилю («репозиторий пишут ИИ-агенты»), но проверка показала:
`kjmagnan1s/anti-slop` — про текст, а не код, 3 коммита; `peakoss/anti-slop`
закрывает низкокачественные PR (у нас PR-потока от посторонних нет); остальные
(AI-SLOP-Detector, sloppylint, deslop) ищут ровно то, что у нас уже под
блокирующими воротами: мёртвый код (vulture=0), пустые заглушки, неиспользуемые
импорты (F401=0), bare except, star-imports (F405 — в ratchet), god-функции
(architecture guard 600/700 строк). Дублирование при нулевой зрелости проектов.

### Проверка attack surface: дыры нет, но нет и гарантии

Пока смотрел каталог, решил проверить не сканером, а исполнением: подняты живой
сервер и опрошены ВСЕ незашаблонённые маршруты без токена (по одному запросу на
путь, с переживанием per-path rate limit — первый заход дал ложные 429, потому
что лимитер срабатывает ДО аутентификации).

Результат: **107 маршрутов корректно отвечают 401/403**, 11 отвечают без токена.
Проверил каждый из 11 по содержимому ответа — **утечки нет**: Prometheus-метрики,
`/v2/health`, OpenAPI-спека (`/openapi.json`, `/api-docs`), HTML-страница логина
`/gui/v2`, корневой индекс, а `/sse` без токена просто висит и событий не отдаёт.
Всё это осознанно публичные поверхности.

Важная поправка к первому впечатлению: `arena/public/endpoints.py` —
это **каталог API для документации**, а НЕ список «доступных без токена»
(там значится `POST /v1/exec`). Использовать его как источник истины для
auth-проверок нельзя.

Чего у нас при этом действительно нет: **автоматической гарантии**. Аутентификация
вызывается внутри каждого handler'а (`require_auth`), а не middleware — забытый
вызов в новом обработчике ничего видимо не сломает, и ни один из 78 сканеров
каталога этого не поймает: это инвариант продукта, а не паттерн кода.
237 маршрутов, 272 handler-функции, а живой E2E проверяет auth на трёх точках.

**Кандидат в Tier-2.5 (ценнее любого нового сканера):** guard-тест, который
поднимает сервер, перебирает все зарегистрированные маршруты и требует 401/403
без токена для каждого, кроме явного allowlist публичных (новый файл — не
переиспользовать `PUBLIC_ENDPOINTS`). Fail-closed: новый маршрут без auth и без
записи в allowlist = красный CI. Стоимость: один тест, ~20 секунд прогона.

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
| 1 | StepSecurity Harden-Runner (audit) | P1 | их dashboard + insights, не наш красный | **добавить** в jobs с секретами |
| 2 | pre-commit hooks (ruff/ratchets локально) | P2 | локальный | опционально, конфиг в репо |
| 3 | Mutation testing sampled (cosmic-ray, nightly) | P2→Tier-3 | отдельный nightly workflow | позже |
| 4 | Playwright dashboard E2E | P2→Tier-3 | blocking e2e job | позже |
| 5 | Codecov | P3 | PR comment | по желанию |
| 6 | Renovate | P3 | PR queue | после автоматизации regen-lock |
| 7 | SonarCloud/Codacy/Qodana/CodeScene | — | — | не добавлять (дубль ruff/pyrefly) |
| 8 | Второй AI-review contour | — | — | не добавлять (FPS: DeepSource/Sourcery) |

Следующий шаг по этому документу: P1 (Harden-Runner audit) — один коммит,
ноль блокирующей нагрузки. Остальное ждёт явного решения пользователя.

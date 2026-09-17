# stage-1-bootstrap - Work Plan

## TL;DR (For humans)
<!-- Post-factum запись: план описывает уже выполненный и верифицированный Stage 1 Bootstrap. -->

**What you'll get:** Проект разворачивается и проверяется одной командой. Все будущие библиотеки (Телеграм-бот, ВК-бот, Телеграм-клиент, база, настройки, логи) зафиксированы под Python 3.14; три инструмента проверки (формат/линт, типы, тесты) настроены и зелёные; структура папок создана; продуктового кода нет.

**Why this approach:** Пакет объявлен устанавливаемым — иначе инструменты не видят код и тесты не смогут его импортировать. Версии заданы диапазонами в манифесте, а точный набор зафиксирован единым файлом блокировки — воспроизводимость у всех одна.

**What it will NOT do:** Никакой бизнес-логики: ни настроек из `.env`, ни логгера, ни точки входа, ни ботов, ни моделей БД, ни миграций, ни PM2. Никаких сетевых вызовов и README/CI/Docker.

**Effort:** Short
**Risk:** Low — главный риск (совместимость библиотек под Python 3.14 и пересечение версий общих зависимостей) снят фактическим прогоном: резолв сошёлся, эскалация не потребовалась.
**Decisions to sanity-check:** устанавливаемый пакет (uv_build); диапазоны версий + committed lock; `--cov-fail-under` отложен; smoke-тест-заглушка обязателен; e2e исключены из `make test`; полное дерево AGENTS.md; `pid/` не тронут; коммит не делался.

Your next move: Работа выполнена и верифицирована — это запись post-factum. При необходимости запросите коммит (один, от вашего имени). High-accuracy review не требовался (`review_required: false`). Full execution detail follows below.

---

> TL;DR (machine): Stage 1 Bootstrap DONE - 11 runtime + 5 dev deps locked под Py3.14, `make check` exit=0 (13 passed), skeleton + AGENTS.md tree + evidence; zero product code; commit pending explicit user request.

## Scope
### Must have
1. `[project].dependencies`: `aiogram`, `vkbottle`, `telethon`, `sqlalchemy[asyncio]`, `aiosqlite`, `alembic`, `pydantic-settings`, `loguru`, `aiohttp`, `aiohttp-socks`, `python-socks[asyncio]`.
2. `[dependency-groups].dev`: `ruff`, `basedpyright`, `pytest`, `pytest-asyncio`, `pytest-cov`.
3. `[build-system]` (uv_build) — проект ставится editable, пакет виден инструментам.
4. Сгенерированный и закоммиченный `uv.lock`; `uv lock --check` зелёный.
5. Ruff config в `pyproject.toml`: `target-version = "py314"`, `line-length = 100`, lint-select `E,F,I,UP,B,SIM,RUF`.
6. BasedPyright config в `pyproject.toml` (без пакета `pyright`): `standard`, `pythonVersion = "3.14"`, venv-резолв.
7. pytest config: `testpaths`, `asyncio_mode = "auto"`, strict-markers/strict-config, marker `e2e` + исключение из дефолтного прогона, coverage source `vk_topic_bridge` (без `--cov-fail-under`).
8. Минимальный smoke-test (импорт runtime-библиотек + пакета) — закрывает exit code 5 и требование smoke-import.
9. Skeleton: `src/vk_topic_bridge/__init__.py`; `tests/{unit,integration,acceptance,e2e}/`; `migrations/`, `scripts/`, `data/`, `logs/`, `runtime/telethon/` (+ `.gitkeep` где нужно).
10. `.gitignore`: покрытие `data/*`, `runtime/telethon/*`, логов, runtime DB, `.coverage.*`; placeholders не игнорируются.
11. `.env.example`: все будущие ключи (объединение docs/07 + docs/05, включая `LOG_DIR`), значения пустые, без секретов.
12. Makefile: bootstrap-таргеты без изменений; `make check` зелёный.
13. Compatibility-проверка и smoke-import под Python 3.14 — фактическим прогоном.
14. C6: дерево `AGENTS.md` в глубине проекта через скилл `agents-md` + Navigation корня + `docs/AGENTS.md`.
15. Evidence-артефакты (RED/GREEN/smoke/lock) и AC-аудит по `docs/07` §14.

### Must NOT have (guardrails, anti-slop, scope boundaries)
- `config.py` / `Settings` / чтение `.env`; `logger.py` / Loguru setup; `main.py` / lifecycle / composition root.
- Telegram Bot (handlers/FSM/middlewares/keyboards/routers), VK Bot (handlers/FSM/keyboards/sessions), Telethon-клиент, `authorize_telegram.py`, proxy resolver.
- SQLAlchemy models / `engine.py` / repositories; Alembic (`alembic.ini`, `migrations/env.py`, `script.py.mako`, `versions/`, миграции).
- Forwarding use cases, attachments/downloader, 50 МБ-политика, идемпотентность.
- `ecosystem.config.cjs`, `scripts/start.sh`, deployment-скрипты, PM2.
- Network calls в коде и тестах.
- Product-таргеты Makefile (`run`, `auth`, `migrate`, `pm2-*`, `test-e2e`).
- Exact-pins транзитивных зависимостей в `pyproject.toml`; пакет `pyright`; Black / isort / mypy.
- `README.md`, `LICENSE`, CI-конфиги, Docker.
- Удаление/изменение `pid/`; правки `docs/*.md` (вне scope bootstrap).

## Verification strategy
> Zero human intervention - all verification is agent-executed.
- Test decision: tests-after (у bootstrap нет поведения для TDD; RED→GREEN зафиксирован на уровне репозиторного гейта: `make check` был exit=2 до, exit=0 после) + pytest 9.1.1 / pytest-asyncio 1.4.0 / pytest-cov 7.1.0.
- Evidence: `.omo/evidence/stage-1-bootstrap/` — `red-make-check.txt`, `red-pytest.txt`, `smoke-import.txt`, `make-check-green.txt`, `lock-resolved-versions.txt`.
- Ключевые команды: `make lock`, `make sync`, `make check`, `uv run --locked python -c "import ..."`, `git check-ignore`.

## Execution strategy
### Parallel execution waves
- **Wave 1 — Baseline:** T1 (RED-бейзлайн), T2 (skeleton).
- **Wave 2 — Файлы манифеста и окружения:** T3 (pyproject.toml), T4 (smoke-test), T5 (.gitignore), T6 (.env.example).
- **Wave 3 — Резолв зависимостей:** T7 (`make lock`) → T8 (`make sync`) → T9 (прямой smoke-import).
- **Wave 4 — Гейты и документация:** T10 (`make check`), T11 (дерево AGENTS.md), T12 (evidence + AC-аудит + отчёт).

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1 | — | — | 2 |
| 2 | — | 3,4,5,6,11 | 1 |
| 3 | 2 | 7 | 4,5,6 |
| 4 | 2 (запись); 8 (запуск) | 10 | 3,5,6 |
| 5 | — | — | 3,4,6 |
| 6 | — | — | 3,4,5 |
| 7 | 3 | 8 | — |
| 8 | 7 | 9,10 | — |
| 9 | 8 | 12 | — |
| 10 | 4,8 | 12 | 11 |
| 11 | 2 | 12 | 10 |
| 12 | 1–11 | — | — |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->
- [x] 1. Repo: зафиксировать RED-бейзлайн до bootstrap — `make check` падает (exit=2, pytest отсутствует)
  What to do / Must NOT do: прогнать `make check` и `uv run --locked pytest` до изменений; сохранить вывод. Не менять ни один файл репозитория на этом шаге.
  Parallelization: Wave 1 | Blocked by: — | Blocks: — | Can parallelize with: 2
  References (executor has NO interview context - be exhaustive): `Makefile:24-25` (`test = uv run --locked pytest`); `docs/07-bootstrap-intent-draft.md:76-88` (цель «чистый checkout → sync → check»); `.omo/drafts/stage-1-bootstrap.md:56` (C5: сегодня `make check` не проходит).
  Acceptance criteria (agent-executable): `make check` → exit=2 с `Failed to spawn: pytest`; артефакт RED сохранён.
  QA scenarios: happy — `make check` exit=2, evidence `.omo/evidence/stage-1-bootstrap/red-make-check.txt`; failure-режим (сам факт) — `uv run --locked pytest` exit=2 `No such file or directory`, evidence `.omo/evidence/stage-1-bootstrap/red-pytest.txt`.
  Commit: N — артефакт сессии, не коммитится.
- [x] 2. Skeleton: создать структуру каталогов и package marker без runtime-модулей
  What to do / Must NOT do: `mkdir -p src/vk_topic_bridge tests/{unit,integration,acceptance,e2e} migrations scripts data runtime/telethon`; создать `src/vk_topic_bridge/__init__.py` (только docstring, без behavior); `.gitkeep` в `tests/{integration,acceptance,e2e}`, `migrations/`, `scripts/`, `data/`, `runtime/telethon/`. Не создавать speculative-модули (`entities.py`, `ports.py`, `forward_message.py`, `use_cases/`); не трогать `logs/` и `pid/` (уже существуют).
  Parallelization: Wave 1 | Blocked by: — | Blocks: 3,4,5,6,11 | Can parallelize with: 1
  References: `docs/07:280-296` (целевой skeleton); `docs/07:300-309` (запрет десятков пустых модулей); `docs/05:236-351` (будущая структура — ориентир, не для создания); `AGENTS.md:57-59` (bootstrap не добавляет runtime-модули в `src/`).
  Acceptance criteria: `find src tests migrations scripts data runtime -mindepth 1 | sort` показывает ровно объявленный набор; `src/vk_topic_bridge/__init__.py` существует; `find src -name '*.py'` = 1 файл.
  QA scenarios: happy — find-листинг (13 каталогов/файлов + `.gitkeep`), проверен в сессии; failure — `ls config.py logger.py main.py` → «No such file», проверено в сессии. Evidence: `.omo/evidence/stage-1-bootstrap/make-check-green.txt` (test collection подтверждает `tests/`), session output для find (не персистилось).
  Commit: N — уйдёт в единый коммит по запросу.
- [x] 3. pyproject.toml: заполнить manifest, build-system и tooling-конфиги
  What to do / Must NOT do: заполнить `[project].dependencies` (11 позиций из Must have), `[dependency-groups].dev` (5), `[build-system]` = `uv_build>=0.12.0,<0.13.0`; `[tool.ruff]` (`py314`, line 100, select `E,F,I,UP,B,SIM,RUF`); `[tool.basedpyright]` (`standard`, `3.14`, `venvPath="."`, `venv=".venv"`, `include=["src","tests"]`, `reportMissingTypeStubs="none"`); `[tool.pytest.ini_options]` (`testpaths`, `asyncio_mode="auto"`, `asyncio_default_fixture_loop_scope="function"`, `addopts="--strict-markers --strict-config -m 'not e2e' --cov"`, marker `e2e`); `[tool.coverage.run]` source + branch; `[tool.coverage.report]`. Не добавлять `pyright`, Black, isort, mypy; не пинить `==` транзитивные; не включать `--cov-fail-under`.
  Parallelization: Wave 2 | Blocked by: 2 | Blocks: 7 | Can parallelize with: 4,5,6
  References: `.omo/drafts/stage-1-bootstrap.md:212-231` (ranges), `:102` (range-стратегия), `:430-440` (Q1-Q11 принятые default'ы: 100, standard, uv_build, отложенный coverage-гейт); `docs/07:146-160` (runtime-набор), `:174-189` (dev-набор), `:199-218` (концепция manifest); `docs/05:136-191` (dependency policy, версионная стратегия), `:1176-1210` (Ruff/BasedPyright), `:1141-1153` (e2e отделены), `:1160-1172` (coverage).
  Acceptance criteria (agent-executable): `uv lock` exit=0; позже `uv lock --check` exit=0; `grep -c 'name = "pyright"' uv.lock` = 0; extras `[asyncio]` у sqlalchemy и python-socks присутствуют.
  QA scenarios: happy — `make lock` exit=0 «Added ... packages», evidence `.omo/evidence/stage-1-bootstrap/lock-resolved-versions.txt`; failure-сценарий R1 (не сработал) — если диапазоны pydantic/aiohttp не пересекаются, СТОП + эскалация заказчику, `requires-python` не ослаблять.
  Commit: N — уйдёт в единый коммит по запросу.
- [x] 4. tests/unit/test_smoke.py: обязательный smoke-тест импортов (13 модулей)
  What to do / Must NOT do: параметризованный тест по списку `RUNTIME_MODULES` (11 runtime-библиотек + `sqlalchemy.ext.asyncio` + сам пакет) через `importlib.import_module`; синхронный тест (работает в auto-asyncio режиме). Не писать product-тесты; не делать сетевых вызовов.
  Parallelization: Wave 2 | Blocked by: 2 (запись), 8 (запуск) | Blocks: 10 | Can parallelize with: 3,5,6
  References: `docs/07:266` (smoke-test разрешён и нужен для `make test`); `docs/07:449-484` (чек-лист smoke-import); `docs/07:509` (AC smoke-import); `.omo/drafts/stage-1-bootstrap.md:105` (обязательность из-за exit 5).
  Acceptance criteria: `uv run --locked pytest tests/unit/test_smoke.py` → `13 passed`, exit=0; `make test` exit=0 (не 5).
  QA scenarios: happy — `make test` «13 passed in 4.02s», evidence `.omo/evidence/stage-1-bootstrap/make-check-green.txt`; failure-режим (RED) — без установленных deps тест падал бы `ModuleNotFoundError` (in-session факт до sync).
  Commit: N — уйдёт в единый коммит по запросу.
- [x] 5. .gitignore: закрыть `data/`, `runtime/telethon/`, `.coverage.*`
  What to do / Must NOT do: добавить `.coverage.*`, `data/*` + `!data/.gitkeep`, `runtime/telethon/*` + `!runtime/telethon/.gitkeep`. Сохранить все существующие правила; не игнорировать `uv.lock`; не трогать правила `pid/`, `logs/` (уже корректны).
  Parallelization: Wave 2 | Blocked by: — | Blocks: — | Can parallelize with: 3,4,6
  References: `docs/07:359-394` (требуемые ignores + tracked placeholders); `docs/05:1382-1416` (§23 Git ignore); `.gitignore:30-34` (существующие logs/pid-правила).
  Acceptance criteria: `git check-ignore -q data/app.db runtime/telethon/session.session logs/app.log .coverage` → exit=0 (игнорируются); `git check-ignore -q data/.gitkeep runtime/telethon/.gitkeep logs/.gitkeep uv.lock` → exit=1 (tracked).
  QA scenarios: happy — проверено 9 путей: 4 «IGNORED-OK» + 5 «TRACKED-OK» (session output, не персистилось); failure — ни одно старое правило не сломано (`.env` на строке 21 остаётся).
  Commit: N — уйдёт в единый коммит по запросу.
- [x] 6. .env.example: полный набор будущих ключей без секретов
  What to do / Must NOT do: заполнить 18 ключей из объединения `docs/07:406-437` + `docs/05:453-469` (включая `LOG_DIR`), секции-комментарии, значения пустые. Не добавлять реальные секреты; не реализовывать чтение (Stage 2).
  Parallelization: Wave 2 | Blocked by: — | Blocks: — | Can parallelize with: 3,4,5
  References: `docs/07:406-437` (группы env); `docs/05:449-471` (поля Settings, `LOG_DIR`); `docs/03:63-79` (концептуальный набор); `.omo/drafts/stage-1-bootstrap.md:325-326` (V6: объединение наборов).
  Acceptance criteria: `grep -c '^[A-Z_0-9]*=' .env.example` = 18; все значения пустые (`grep -E '^[A-Z_0-9]+=.+'` → 0 matches).
  QA scenarios: happy — 18 ключей, полный список сверен (session output): BOT_TOKEN, OWNER_IDS, BOT_API_URL, API_ID, API_HASH, SESSION_PATH, MTPROXY_×3, SOCKS5_PROXY_URL, VK_GROUP_TOKEN, DATABASE_URL, LOG_×6; failure — непустых значений нет.
  Commit: N — уйдёт в единый коммит по запросу.
- [x] 7. uv.lock: `make lock` — резолв графа под Python 3.14 (точка R1)
  What to do / Must NOT do: `make lock`; при неразрешимом пересечении (pydantic у aiogram↔vkbottle, aiohttp) — СТОП и эскалация заказчику; не ослаблять и не понижать `requires-python`.
  Parallelization: Wave 3 | Blocked by: 3 | Blocks: 8 | Can parallelize with: —
  References: `.omo/drafts/stage-1-bootstrap.md:266-274` (риски C1-C4), `:295-296` (R1); `docs/05:170-176` (после изменения deps: lock → sync → lock-check).
  Acceptance criteria: exit=0; зафиксированы: aiogram 3.31.0, vkbottle 4.11.0, telethon 1.45.0, sqlalchemy 2.0.54, aiosqlite 0.22.1, alembic 1.20.0, pydantic-settings 2.15.0, loguru 0.7.3, aiohttp 3.14.3, aiohttp-socks 0.12.0, python-socks 2.8.2, pydantic 2.13.5, greenlet 3.5.6.
  QA scenarios: happy — `make lock` exit=0 (52 пакета добавлено), evidence `.omo/evidence/stage-1-bootstrap/lock-resolved-versions.txt`; failure-сценарий R1 не сработал — конфликт разрешился без эскалации (pydantic 2.13.5 удовлетворяет обоим SDK).
  Commit: N — уйдёт в единый коммит по запросу.
- [x] 8. .venv: `make sync` — установка всех групп + editable-пакет
  What to do / Must NOT do: `make sync` (`uv sync --all-groups`); убедиться, что проект поставлен editable строкой `vk-topic-bridge==0.1.0 (from file://...)`; не устанавливать пакеты вручную в обход uv/lock.
  Parallelization: Wave 3 | Blocked by: 7 | Blocks: 9,10 | Can parallelize with: —
  References: `Makefile:3-4` (`sync = uv sync --all-groups`); `docs/07:76-88`; `docs/05:170-176`.
  Acceptance criteria: exit=0; `.venv/bin/python --version` = 3.14.x; строка editable-установки присутствует в выводе.
  QA scenarios: happy — sync exit=0, все 52 пакета + `vk-topic-bridge==0.1.0 (from file:///...)` (session output); failure — порядок исключает сборку-до-пакета (T2 выполнен раньше).
  Commit: N — уйдёт в единый коммит по запросу.
- [x] 9. Smoke-import: прямая проверка поверхности импортов под Python 3.14.3
  What to do / Must NOT do: `uv run --locked python -c "import ..."` по 13 модулям с печатью версий; дополнительно `from vkbottle import Bot; from aiogram import Bot; from telethon import TelegramClient`. Только проверка, никаких изменений файлов.
  Parallelization: Wave 3 | Blocked by: 8 | Blocks: 12 | Can parallelize with: —
  References: `docs/07:467-484` (точный класс smoke-import); `.omo/drafts/stage-1-bootstrap.md:300` (список модулей включает `sqlalchemy.ext.asyncio` — проверка greenlet).
  Acceptance criteria: все 13 импортов OK; `python 3.14.3`; `vk_topic_bridge.__file__` указывает на `src/` (editable, не site-packages).
  QA scenarios: happy — вывод `OK <module> <version>` по всем модулям + SDK entrypoints OK, evidence `.omo/evidence/stage-1-bootstrap/smoke-import.txt`; failure — ошибки импорта нет ни по одному модулю.
  Commit: N — уйдёт в единый коммит по запросу.
- [x] 10. make check: полный гейт lock-check → format-check → lint → typecheck → test
  What to do / Must NOT do: прогнать `make check`; при падении — чинить причину, не отключать секции гейта и не ослаблять конфиг.
  Parallelization: Wave 4 | Blocked by: 4,8 | Blocks: 12 | Can parallelize with: 11
  References: `Makefile:27` (`check: lock-check format-check lint typecheck test`); `docs/05:1206-1220` (состав `make check`); `docs/07:594-601` (финальные команды этапа).
  Acceptance criteria: exit=0; ruff format «12 files already formatted»; ruff check «All checks passed»; basedpyright «0 errors, 0 warnings»; pytest «13 passed»; coverage видит `src/vk_topic_bridge/__init__.py`.
  QA scenarios: happy — полный зелёный прогон, evidence `.omo/evidence/stage-1-bootstrap/make-check-green.txt`; failure (RED зафиксирован) — до bootstrap exit=2, evidence `.omo/evidence/stage-1-bootstrap/red-make-check.txt`.
  Commit: N — уйдёт в единый коммит по запросу.
- [x] 11. AGENTS.md-дерево: инициализация в глубине проекта через скилл `agents-md`
  What to do / Must NOT do: загрузить скилл `agents-md`; создать `src/vk_topic_bridge/AGENTS.md` (слои: `presentation`/`infrastructure` → `application` → `domain`; запрет SDK-импортов в domain/application; markers без runtime behavior) и `tests/AGENTS.md` (стратегия: unit без сети/SQLite, e2e исключены из `make test`, naming по US/AC); обновить Navigation корневого `AGENTS.md`; наполнить `docs/AGENTS.md`. Не создавать AGENTS.md в `.git/`, `.venv/`, `.idea/`, `.serena/`, `.opencode/`, `.omo/`; не раздувать файлы (>100 строк).
  Parallelization: Wave 4 | Blocked by: 2 | Blocks: 12 | Can parallelize with: 10
  References: `.omo/drafts/stage-1-bootstrap.md:332-341` (V8 полный вариант); `AGENTS.md:44-50` (Navigation-правила); `docs/05:68-74` (главное правило зависимостей), `:195-231` (принципы слоёв); `docs/05:1122-1153` (тестовая стратегия/e2e).
  Acceptance criteria: существуют 4 файла (`src/vk_topic_bridge/AGENTS.md`, `tests/AGENTS.md`, обновлённые `AGENTS.md`, `docs/AGENTS.md`); Navigation содержит обе новые записи; в запрещённых каталогах AGENTS.md нет.
  QA scenarios: happy — чтение 4 файлов + `grep 'AGENTS.md' AGENTS.md` показывает `src/vk_topic_bridge/AGENTS.md` и `tests/AGENTS.md` (session output); failure — `ls .omo/AGENTS.md .venv/AGENTS.md` → отсутствуют (по определению).
  Commit: N — уйдёт в единый коммит по запросу.
- [x] 12. Evidence + AC-аудит (`docs/07` §14) + финальный отчёт
  What to do / Must NOT do: собрать `.omo/evidence/stage-1-bootstrap/` (RED×2, smoke-import, GREEN, lock-versions); пройтись по всем категориям AC (Repository / Dependencies / Tooling / Structure / Secrets / Scope protection) и зафиксировать результат; записать memory в Hindsight. Коммит не делать без явного запроса.
  Parallelization: Wave 4 | Blocked by: 1-11 | Blocks: — | Can parallelize with: —
  References: `docs/07:490-552` (AC-чеклист §14); `.omo/drafts/stage-1-bootstrap.md:466-476` (approval gate и что считать завершением).
  Acceptance criteria: `ls .omo/evidence/stage-1-bootstrap/` = 5 файлов; каждая категория AC подтверждена командой или фактом; отчёт сформирован.
  QA scenarios: happy — evidence-листинг + AC-таблица (сессия); failure — открытых/непроверенных AC нет.
  Commit: N — коммит отдельным явным запросом пользователя.

## Final verification wave
> Runs in parallel after ALL todos. ALL must APPROVE. Surface results and wait for the user's explicit okay before declaring complete.
- [x] F1. Plan compliance audit — все 15 пунктов Scope IN выполнены; AC `docs/07` §14 пройдены по всем 6 категориям (Repository / Dependencies / Tooling / Structure / Secrets / Scope protection). Evidence: `.omo/evidence/stage-1-bootstrap/` + AC-аудит T12.
- [x] F2. Code quality review — ruff format `12 files already formatted`; ruff check `All checks passed`; basedpyright `0 errors, 0 warnings, 0 notes`; `lsp_diagnostics` на `tests/unit/test_smoke.py` — 0 diagnostics. Evidence: `.omo/evidence/stage-1-bootstrap/make-check-green.txt`.
- [x] F3. Real manual QA — end-to-end `make check` exit=0; smoke-import 13 модулей под Python 3.14.3; editable-путь пакета `src/vk_topic_bridge/__init__.py` подтверждён; `git check-ignore` по 9 путям проверен. Evidence: `.omo/evidence/stage-1-bootstrap/smoke-import.txt`, `make-check-green.txt`.
- [x] F4. Scope fidelity — продуктовая логика отсутствует: `config.py` / `logger.py` / `main.py` / `authorize_telegram.py` не существуют; handlers/ORM/PM2 нет; network-тестов нет; Makefile не расширен; `pid/` не тронут; `docs/*.md` не менялись. Evidence: session audit + `git status` (6 modified, 6 new dirs).

## Commit strategy
- Коммит **не делался**: пользователь коммит не запрашивал (правило `AGENTS.md:18-19` + git-policy воркфлоу).
- Когда пользователь явно попросит: **один** коммит от его имени, без co-authored-by, сообщение в стиле истории репозитория (например: `feat(bootstrap): Развёрнут Stage 1 — зависимости, tooling, skeleton, AGENTS.md`).
- Состав коммита: `pyproject.toml`, `uv.lock`, `.gitignore`, `.env.example`, `AGENTS.md`, `docs/AGENTS.md`, `src/vk_topic_bridge/{__init__.py,AGENTS.md}`, `tests/**`, `migrations/.gitkeep`, `scripts/.gitkeep`, `data/.gitkeep`, `runtime/telethon/.gitkeep`.
- `.omo/evidence/` — служебные артефакты; включать в коммит или нет — решить при запросе коммита (по умолчанию: не включать).

## Success criteria
- [x] `uv lock --check` — exit=0, lock актуален.
- [x] `uv sync --all-groups` — exit=0 с чистого окружения, пакет editable.
- [x] smoke-import всех runtime-библиотек + пакета под Python 3.14.3 — OK.
- [x] `[project].dependencies` и `[dependency-groups].dev` заполнены; `basedpyright` есть, `pyright` отсутствует; `sqlalchemy[asyncio]` и `python-socks[asyncio]` объявлены.
- [x] Ruff format/lint зелёные (`py314`); BasedPyright `0 errors`; pytest `13 passed`; marker `e2e` зарегистрирован и исключён.
- [x] Структура каталогов соответствует `docs/07:280-296`; speculative-модулей нет.
- [x] `.env.example` — 18 пустых ключей без секретов; `.env`, runtime DB, логи, Telethon session игнорируются; `uv.lock` не игнорируется.
- [x] Scope protection: нет `config.py` / `logger.py` / API clients / ORM / handlers / PM2; нет network-dependent тестов.
- [x] `make check` — exit=0 (главный гейт Stage 1).
- [ ] Коммит — ожидает явного запроса пользователя (не входит в критерии завершения работ без запроса).


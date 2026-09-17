---
slug: stage-1-bootstrap
status: awaiting-approval
intent: clear
review_required: false
pending-action: write .omo/plans/stage-1-bootstrap.md
approach: Перенести Stage 1 из docs/07-bootstrap-intent-draft.md в decision-complete план без продуктового кода — dependency manifest (`[project].dependencies` + `[dependency-groups].dev` + committed uv.lock), tooling (Ruff/BasedPyright/pytest/pytest-asyncio/pytest-cov/coverage), directory skeleton, git hygiene, `.env.example`, зелёный `make check` из чистого checkout, плюс инициализация дерева AGENTS.md через скилл agents-md.
---

# Draft: stage-1-bootstrap

Этот draft — вход для следующей сессии (Ultrabrain) и для генерации `.omo/plans/stage-1-bootstrap.md`.
Источник intent — `docs/07-bootstrap-intent-draft.md` (готовый «bootstrap intent draft») плюс прямые указания заказчика из текущей сессии.

**Статус интервью:** интервью НЕ проводилось — заказчик явно отменил его (см. цитаты). Все развилки либо закрыты документами `docs/`, либо закрыты рекомендованным default'ом, зафиксированным в `## Open assumptions` и `## Open questions` (пропущенный вопрос = принят recommended default).

---

## Простыми словами (для быстрой проверки)

Проект пустой — это норма. Сейчас в нём лежат файлы-заготовки из других проектов, чтобы было видно, что заполнять. Реальная задача Stage 1: **сделать так, чтобы проект собирался и проверялся одной командой, но без единой строчки продуктового кода.**

**Что будет сделано:**

1. **Заказ на библиотеки.** В главный файл настроек впишем список библиотек (Телеграм-бот, ВК-бот, Телеграм-клиент, база данных, настройки, логи) и список инструментов проверки. Потом одной командой создадим файл с точными версиями — чтобы у всех было одинаково.
2. **Проверки.** Настроим 3 инструмента: форматирование и правила кода (Ruff), проверка типов (BasedPyright), тесты (pytest). Все три уже вызываются командами из `Makefile`.
3. **Папки.** Создадим каркас: где будет код, где тесты, где база данных, где логи, где файл авторизации Телеграма. Пустые папки — без кода внутри.
4. **Защита секретов.** Настроим `.gitignore`, чтобы в Git никогда не попали: пароли (`.env`), база данных, логи, файл авторизации Телеграма.
5. **Список будущих настроек.** В `.env.example` перечислим все будущие переменные (пустые, без секретов) — чтобы на следующем этапе было видно, что подключать.
6. **Правила для агентов.** Создадим инструкции `AGENTS.md` внутри папок с кодом и тестами (через специальный скилл `agents-md`), чтобы будущие сессии не нарушали архитектуру.

**Один обязательный тест-заглушка.** Команда тестов считает «нет тестов» ошибкой. Чтобы общая проверка была зелёной, добавим один крошечный тест (проверяет, что библиотеки ставятся и импортируются). Он же выполняет роль «проверки, что всё установилось».

**Что НЕ будет сделано:** никакого бота, никакой пересылки, никаких моделей базы данных, никаких настроек из `.env` — всё это следующие этапы. Сейчас только фундамент.

**Три решения, которые нужны от тебя** (если промолчишь — беру рекомендацию):
1. Подключать код как устанавливаемый пакет, чтобы инструменты видели его? → **Да, рекомендую.**
2. Насколько подробные `AGENTS.md` в папках? → **Полный набор (код + тесты + docs + корень).**
3. Что делать, если установка библиотек упадёт? → **Остановиться, сообщить тебе, Python не понижать.**

---

## Components (topology ledger)

<!-- id | outcome (one line) | status: active|deferred | evidence path -->

| id | outcome (one line) | status | evidence path |
| --- | --- | --- | --- |
| C1 | Runtime/dev зависимость-манифест разрешается под Python 3.14 и фиксируется committed `uv.lock` | active | `pyproject.toml:1-5`, `uv.lock:1-8`, `docs/07-bootstrap-intent-draft.md:449-484` |
| C2 | Tooling-конфиг (Ruff / BasedPyright / pytest / pytest-asyncio / coverage) живёт в `pyproject.toml` | active | `docs/07-bootstrap-intent-draft.md:224-268`, `docs/05-architecture-and-engineering.md:1176-1218` |
| C3 | Directory skeleton существует и НЕ содержит speculative runtime-модулей | active | `docs/07-bootstrap-intent-draft.md:273-309`, `docs/05-architecture-and-engineering.md:236-351` |
| C4 | Git hygiene: `.gitignore` покрывает `.env`, runtime DB, логи, Telethon session; `.env.example` содержит будущие keys без секретов | active | `.gitignore:1-36`, `.env.example` (пуст), `docs/07-bootstrap-intent-draft.md:359-437` |
| C5 | «Чистый checkout → `uv sync --all-groups` → `make check`» проходит зелёным | active | `Makefile:1-27`, `docs/07-bootstrap-intent-draft.md:76-88`, `:490-552` |
| C6 | Дерево `AGENTS.md` инициализировано в глубине проекта через скилл `agents-md` (добавлено заказчиком) | active | `AGENTS.md:44-59`, `docs/AGENTS.md:1`, цитата заказчика ниже |

Почему C5 отдельный компонент: сегодня `make check` на пустом репозитории **не проходит** — pytest возвращает exit code 5 («no tests collected»), а `uv lock --check` сломается сразу после добавления зависимостей до регенерации lock. Это независимо ломается и независимо проверяется.

---

## Прямые цитаты заказчика (verbatim)

Вводное ТЗ на этот draft:

> «Нужно составить draft с моим намерением и исследованием по проекту, с прямым цитированием меня в этом draft. Ты должен меня интервьювить для полной конкретизации задачи. Мы должны обсуддить все нюансы реализации, подводные камни. Так же ты должен говорить мне о несостыковках, если видишь что исходные данные не полны или противоречивы, либо не соответствуют чему либо. После изучения проекта по задаче - расскажи о ньюансах реализации, о которых стоит задуматься мне, чтобы придумать как реализовать лучше. Предлагай варианты, обосновывай их доступно и подробно, предлагай рекомендуемый вариант. Этот draft уйдет в другую сессию, к ultrabrain. В этой сессии только мой intent + interview + research. Для хорошего исследования проекта читай папку .omo/ в корне проекта. Ты возможно найдешь связанные планы и ньюансы разработки проекта там. Запускай explorer для исследования совпадений»

Скорректированное ТЗ (перекрывает предыдущее — интервью и explorer отменены):

> «Прочти все файлы в docs/»
> «Проект пустой, recall reflect не будут работать. Нужно написать bootstrap план из готового плана используя твои скиллы для написания плана.»
> «Интервью не будет - напиши сразу draft в .omo/drafts. Я его перепроверю.»
> «Использовать explorer не нужно. Читай файлы проекта сам.»
> «Добавь от меня - что нужно тебе загрузить скилл agents md для инициализации AGENTS.md в глубину проекта.»
> «Исследуй текущий проект сам. Но он пустой - в нем нет кода.»

Уточнения по процессу:

> «Я сказал не использовать рефлект и рекалл.»

> «Твоя одна конкретная задача - переписать весь bootstrap в своем формате в .omo/drafts»
> «Уже по факту все решено.»

> «Не обязательно отменять. Пусть продолжит выполнять если это необходимо планом.»
> «Продолай работу»

Выводы, зафиксированные в этом draft (это и есть intent):

1. Единственный deliverable = Stage 1 Bootstrap, перенесённый в мой формат.
2. Интервью не проводится; развилки закрываются документами + default'ами с правом вето.
3. Scope ограничен bootstrap'ом: **никакой продуктовой логики**, включая полный `config.py`/`logger.py`/`main.py`.
4. C6 (дерево `AGENTS.md` через скилл `agents-md`) — обязательное требование заказчика, добавленное сверх исходного `docs/07`.
5. `recall`/`reflect` не использовать (правило заказчика на эту сессию); traceability ведётся прямыми ссылками на файлы.

---

## Open assumptions (announced defaults)

<!-- assumption | adopted default | rationale | reversible? -->

| assumption | adopted default | rationale | reversible? |
| --- | --- | --- | --- |
| Installability пакета `src/vk_topic_bridge` | Объявить `[build-system]`, чтобы `uv sync` ставил проект editable в `.venv` | Иначе `basedpyright`/`pytest`/coverage не видят `vk_topic_bridge`; `uv.lock:7` сейчас `source = { virtual = "." }` | Да (одна секция pyproject) |
| Версии зависимостей | Флор `3.14`-aware ranges из ресёрча (`aiogram>=3.23,<4`, `vkbottle>=4.11,<5`, `telethon>=1.42,<2`, `sqlalchemy[asyncio]>=2.0.52,<3`, `alembic>=1.18.3,<2`, `pydantic-settings>=2.15,<3`, `loguru>=0.7.3,<1`, `aiohttp>=3.14.3,<4`, `aiohttp-socks>=0.11,<1`, `python-socks[asyncio]>=2.8.1,<3`, `aiosqlite>=0.22.1,<1`); exact graph фиксирует `uv.lock` | `docs/05:180-191` запрещает бездумные `==` pins; нижние границы взяты как earliest verified 3.14-совместимые (librarian-ресёрч, см. Findings). `aiohttp>=3.14.3` диктуется `vkbottle 4.11`; `pydantic>=2.13.4` диктуется `vkbottle`, но сам pydantic остаётся транзитивным | Да |
| `--cov-fail-under=80` | НЕ включать на Stage 1; включить, когда появится продуктовый код | На пустом `__init__.py` гейт мерит ничего и создаёт ложную зелень (`docs/05:1160-1170` требует его для проекта, не для bootstrap) | Да |
| `pytest-asyncio` режим | `asyncio_mode = "auto"` + `asyncio_default_fixture_loop_scope = "function"` | Auto убирает декораторы в тестах; второй ключ глушит deprecation-warning новых версий | Да |
| Минимальный smoke-test | Обязателен `tests/unit/...` smoke-test (imports + trivial assert) | Иначе `pytest` возвращает exit 5 и `make check` красный (`Makefile:24-25`) | Да (удаляется позже) |
| `e2e` в `make test` | Исключать через `-m "not e2e"` + регистрация marker `e2e` | `docs/05:1141-1151` — e2e требуют реальных credentials и запускаются явно | Да |
| Ruff line-length | 100 | Документы не задают значение; 100 — компромисс для длинных typing-сигнатур | Да |
| BasedPyright строгость | `typeCheckingMode = "standard"`, `pythonVersion = "3.14"`, `venvPath`/`venv` = `.venv`, `include = ["src", "tests"]` | `docs/05:1188-1196` — на bootstrap строгость без блокировки dynamic SDK; усиление слоёв позже | Да |
| `.env.example` значения | Только keys + комментарии-секции, значения пустые | `docs/07:439` — «Никаких реальных secrets»; чтение ключей появится в Stage 2 | Да |
| `pid/` | Задокументирован как место PID-файла PM2 (A1); каталог не трогать | Хотелка заказчика, зафиксирована правкой `docs/05` §5/§22/§23 и `docs/06` §12 | Да |
| `README.md` | Не создавать | Ни один документ не требует; без `readme` в pyproject сборка не сломается | Да |
| Нумерация артефакта | Оставить имя `stage-1-bootstrap` | Slug сгенерирован штатным скриптом скилла | Да |
| Ресёрч зависимостей | Выполнен librarian'ом по чек-листу `docs/07:449-484`; результат — вход для плана, обязательна перепроверка на исполнении | Заказчик: «Пусть продолжит выполнять если это необходимо планом» | Нет (обязательная проверка) |

---

## Findings (cited - path:lines)

### Состояние репозитория (проверено лично)

- `pyproject.toml:1-5` — только `[project]` name/version/`requires-python = ">=3.14"`/`dependencies = []`. Нет `[build-system]`, нет `[dependency-groups]`, нет `[tool.*]`.
- `uv.lock:1-8` — `version = 1`, `revision = 3`, `requires-python = ">=3.14"`, единственный пакет `vk-topic-bridge` со `source = { virtual = "." }` (строка 7). Проект **virtual**, значит `src/` не импортируется.
- `.python-version:1` — `3.14`.
- `Makefile:1-27` — `sync/lock/lock-check/format/format-check/lint/typecheck/test/check`; `typecheck` = `uv run --locked basedpyright`; `check` = `lock-check format-check lint typecheck test`.
- `.gitignore:1-36` — есть `.env`/`.env.*`/`!.env.example` (21-23), `logs/*` + `!logs/.gitkeep` (30-31), `pid/*` + `!pid/.gitkeep` (33-34), кэши и coverage (5-15), `*.db`/`*.sqlite`/`*.sqlite3` (26-28). **Отсутствуют** правила для `data/` и `runtime/`.
- `.env.example` — файл существует, полностью пуст (0 строк).
- `src/` — существует, но пуст: `src/vk_topic_bridge/` нет, `__init__.py` нет.
- `logs/.gitkeep` и `pid/.gitkeep` — существуют. `tests/`, `migrations/`, `scripts/`, `data/`, `runtime/` — не существуют.
- Git: ветка `main`, два коммита (`init commit`, затем amend) — рабочее дерево чистое по замыслу bootstrap'а.
- `.omo/`: `drafts/`, `plans/`, `evidence/` пусты; `.omo/.gitignore` игнорирует служебные каталоги harness'а; `run-continuation/ses_*.json` — служебный файл harness'а, вне scope.

### Правила проекта

- `AGENTS.md:3-15` — `uv` + Python 3.14 + committed `uv.lock`; bootstrap-команды определены в `Makefile`.
- `AGENTS.md:18-19` — коммиты от имени пользователя, без co-authored-by.
- `AGENTS.md:44-50` — Navigation: при создании содержательного каталога с отличающимися командами/ограничениями создать в нём краткий `AGENTS.md` и добавить путь в этот раздел; запрещено создавать `AGENTS.md` в `.git/`, `.venv/`, `.idea/`, `.serena/`, `.opencode/`, `.omo/`.
- `AGENTS.md:52-55` — Planning Traceability: draft обязан иметь раздел `## Связанные материалы`.
- `AGENTS.md:57-59` — Bootstrap: bootstrap-команды только из `Makefile`; product-команды — отдельным утверждённым планом; bootstrap НЕ добавляет runtime-модули в `src/`.
- `AGENTS.md:61-65` — комментарии только «почему», по умолчанию их нет.
- `docs/AGENTS.md:1` — файл содержит единственную строку `# Documentation Instructions`.

### Что задаёт исходный intent

- `docs/07-bootstrap-intent-draft.md:76-88` — целевое состояние: `uv sync --all-groups` + `make check` из чистого checkout.
- `docs/07:95-108` — In scope (14 пунктов).
- `docs/07:113-136` — Out of scope: `config.py`, `logger.py`, Settings, Loguru setup, Telegram Bot, handlers/FSM, VK Bot, Telethon client, `authorize_telegram.py`, SQLAlchemy models, repositories, Alembic config/migrations, forwarding use cases, attachments, PM2 `ecosystem.config.cjs`, deployment scripts, network calls, product tests.
- `docs/07:146-160` — целевой runtime-набор: `aiogram`, `vkbottle`, `telethon`, `sqlalchemy[asyncio]`, `aiosqlite`, `alembic`, `pydantic-settings`, `loguru`, `aiohttp`, `aiohttp-socks`, `python-socks[asyncio]`.
- `docs/07:164-170` — обоснование прямых зависимостей (`aiohttp`, `aiohttp-socks`, `python-socks[asyncio]`, extra `asyncio` у SQLAlchemy).
- `docs/07:174-189` — dev-набор `ruff`, `basedpyright`, `pytest`, `pytest-asyncio`, `pytest-cov`; запрет на Pyright/Black/isort/mypy без необходимости.
- `docs/07:280-296` — целевой skeleton: `src/vk_topic_bridge/`, `tests/{unit,integration,acceptance,e2e}`, `migrations/`, `scripts/`, `data/`, `logs/`, `runtime/telethon/`.
- `docs/07:363-394` — требуемые ignores + tracked placeholders.
- `docs/07:406-437` — ожидаемые группы `.env.example`.
- `docs/07:449-484` — обязательный compatibility-чек-лист перед фиксацией манифеста + smoke-import список.
- `docs/07:490-552` — Acceptance Criteria (Repository / Dependencies / Tooling / Structure / Secrets / Scope protection).
- `docs/07:576-603` — инструкции Ultrabrain и Sisyphus.

### Опора из архитектуры и roadmap

- `docs/05-architecture-and-engineering.md:142-156` — целевые runtime/dev наборы (совпадают с `docs/07`).
- `docs/05:180-191` — версионная стратегия: ranges в `pyproject.toml`, exact graph — в `uv.lock`; «не использовать бездумный набор `==` pins».
- `docs/05:236-351` — будущая файловая структура целиком (ориентир для skeleton, НЕ для создания всех файлов).
- `docs/05:453-482` — будущие поля `Settings`, включая `LOG_DIR` (в `docs/07` его нет).
- `docs/05:1141-1151` — e2e отделены и запускаются явно (`make test-e2e`).
- `docs/05:1160-1170` — coverage gate `--cov-fail-under=80` для проекта.
- `docs/05:1188-1202` — BasedPyright, config в `pyproject.toml`.
- `docs/05:1220-1270` — Makefile: bootstrap-команды сохраняются; product-таргеты добавляются позже.
- `docs/06-full-implementation-roadmap.md:46-79` — Stage 1 = bootstrap, без бизнес-логики.
- `docs/03-technical-requirements.md:63-79` — концептуальный набор env-ключей (совпадает с `docs/05`, отличается от `docs/07`).
- `docs/03:39-51` — SQLite как единственное хранилище изменяемой конфигурации (важно: `.env` не хранит business state).

### Ресёрч зависимостей (обязательный чек из `docs/07:449-484`)

Ресёрч выполнен `librarian` 2026-09-17 (PyPI metadata + GitHub releases/changelogs). Полный отчёт — в `.omo/evidence/` нет файла; отчёт передан в этой сессии и продублирован ниже тезисно.

#### Итоговая таблица (latest stable | earliest с поддержкой CPython 3.14 | extra | заметки)

| Package | Latest stable | Earliest CPython 3.14 | Extra | Заметки |
| --- | --- | --- | --- | --- |
| aiogram | 3.31.0 | **3.23.0** (issue #1719) | `aiohttp-socks` для SOCKS5 | Pydantic upper bound — проверить пересечение |
| vkbottle | 4.11.0 | **4.7.0** (fix `asyncio.get_event_loop()`) | — | Требует `pydantic>=2.13.4,<3`; требует `aiohttp>=3.14.3` |
| telethon | 1.44.0 | **1.42.0** (changelog «Fixed support for Python 3.14») | `python-socks[asyncio]` | PySocks НЕ нужен при python-socks |
| sqlalchemy | 2.0.52 | UNVERIFIED (exact) | `[asyncio]` | asyncio-расширение требует `greenlet` |
| greenlet | 3.5.6 | **3.3.0** (stable line) | — | 3.2.x — только alpha/beta 3.14; free-threaded 3.14 — известные ограничения |
| aiosqlite | 0.22.1 | UNVERIFIED | — | Нет известных конфликтов |
| alembic | 1.18.3 | UNVERIFIED (exact) | — | Держать совместимым с SQLAlchemy 2.x |
| pydantic | 2.13.4 | **2.13.0** | — | vkbottle требует `>=2.13.4` |
| pydantic-settings | 2.15.0 | UNVERIFIED | — | Только Pydantic 2.x |
| loguru | 0.7.3 | UNVERIFIED | — | Нет известных конфликтов |
| aiohttp | 3.14.3 | **3.14.0** (release notes) | — | vkbottle 4.11 требует `>=3.14.3`; stable-линия остаётся 3.x (4.x stable нет) |
| aiohttp-socks | 0.11.0 | UNVERIFIED | — | PyPI status Beta; совместимость с aiohttp 4.x не проверена |
| python-socks | 2.8.1 | UNVERIFIED | `[asyncio]` | Общий для Telethon и aiohttp-socks |
| ruff | 0.15.16 | 0.13.0+ (exact UNVERIFIED) | — | Standalone Rust-бинарь |
| basedpyright | 1.40.0 | UNVERIFIED | — | Dev-only |
| pytest | 9.0.3 | 8.4.2 (консервативный минимум) | — | pytest-asyncio 1.4 требует `pytest>=8.4,<10` |
| pytest-asyncio | 1.4.0 | UNVERIFIED | — | `pytest>=8.4,<10` |
| pytest-cov | 7.1.0 | UNVERIFIED | — | Нет известного конфликта с pytest 9 |

Ни один пакет из списка не объявляет `requires-python <3.14`. Явные официальные заявления о поддержке 3.14 не найдены для: `aiosqlite`, `alembic`, `pydantic-settings`, `loguru`, `aiohttp-socks`, `python-socks`, `basedpyright`, `pytest-asyncio`, `pytest-cov` — это **отсутствие подтверждения, а не доказанная несовместимость**.

#### Критичные выводы для плана

- **Q1 (vkbottle ↔ pydantic):** `vkbottle 4.11.0` пинит `pydantic>=2.13.4,<3`. С `pydantic-settings` 2.x конфликта нет, но **нижняя граница pydantic поднимается до `>=2.13.4`**.
- **Q2 (aiogram SOCKS5):** нужен пакет `aiohttp-socks`; API — `AiohttpSession(proxy="socks5://...")`, import `aiogram.client.session.aiohttp.AiohttpSession`. Отдельного extra у aiogram нет.
- **Q3 (Telethon):** `python-socks[asyncio]` достаточно, PySocks не нужен; MTProto-класс — `telethon.connection.ConnectionTcpMTProxyRandomizedIntermediate`, дополнительных пакетов не требует.
- **Q4 (SQLAlchemy asyncio):** `greenlet` обязателен, extra `[asyncio]` его притягивает; для CPython 3.14 консервативно `greenlet>=3.3`.
- **Q5 (aiohttp):** первая ветка с поддержкой 3.14 — **3.14.0**, не 4.x; stable aiohttp 4.x не существует. Использовать `>=3.14.3` (требование vkbottle 4.11).
- **Потенциальный конфликт верхних границ:** у `aiogram` есть upper bound на pydantic, у `vkbottle` — нижняя граница `>=2.13.4`. Пересечение обоих должно разрешиться в `uv lock`; если нет — это блокер R1 (эскалация заказчику), а не повод менять `requires-python`.
- **Ruff (`target-version`)**: актуальный ruff (0.15.x) поддерживает `py314`; при `py314`-конфиге fallback на V3 не потребуется, но проверить фактически на исполнении.

#### Рекомендованные консервативные ranges (вход для `pyproject.toml`, подтвердить `uv lock`'ом)

```toml
aiogram = ">=3.23,<4"
vkbottle = ">=4.7,<5"          # фактически >=4.11 из-за aiohttp>=3.14.3
telethon = ">=1.42,<2"
sqlalchemy = { version = ">=2.0.52,<3", extras = ["asyncio"] }
greenlet = ">=3.3,<4"
aiosqlite = ">=0.22.1,<1"
alembic = ">=1.18.3,<2"
pydantic = ">=2.13.4,<3"
pydantic-settings = ">=2.15,<3"
loguru = ">=0.7.3,<1"
aiohttp = ">=3.14.3,<4"
aiohttp-socks = ">=0.11,<1"
python-socks = { version = ">=2.8.1,<3", extras = ["asyncio"] }
ruff = ">=0.13,<1"
basedpyright = ">=1.40,<2"
pytest = ">=8.4.2,<10"
pytest-asyncio = ">=1.4,<2"
pytest-cov = ">=7.1,<8"
```

Замечание: `pydantic` и `greenlet` не входят в исходный целевой список `docs/07:146-160`/`docs/05:142-156` как прямые зависимости, но `pydantic` фактически требуется самому `pydantic-settings`, а `greenlet` — `sqlalchemy[asyncio]`. Рекомендация: **не добавлять их в direct dependencies**, если проект их не импортирует напрямую (это согласуется с `docs/05:168`); ranges выше — ориентир совместимости, а точные границы фиксирует `uv.lock`.

Правило для плана: считать любые версии/совместимости **неподтверждёнными до исполнения**; финальным доказательством совместимости служит успешный `uv lock` + `uv sync --all-groups` + smoke-import под Python 3.14. Не переносить непроверенные версии в требования.

---

## Расхождения и задачи (честный разбор)

**Рамка.** Проект пустой не «сломан», а by design: заказчик говорит — «текущий проект это нерабочий код в текущем состоянии. Я просто скопировал из других проектов готовые файлы, чтобы было проще понимать что нужно заполнить, исправить, сделать». Поэтому ниже — три разные категории, и только первая — настоящие расхождения. Остальное — работа плана.

### A. Реальные расхождения между документами / репозиторием (устранены или решены здесь)

| # | Что не так | Где | Статус |
| --- | --- | --- | --- |
| A1 | `pid/` существует в репозитории и `.gitignore:33-34`, но не описан ни в одном документе. Заказчик пояснил назначение: «а pid/ - я хочу чтобы pm2 там хранит pid процесса. Это моя хотелка не документиованная. Её нужно зафиксировать в исходном docs/ документе, изменив строки» | `.gitignore:33-34`, `docs/05:236-351` | **Выполнено**: правка `docs/05` §5 (дерево → `docs/05:251`), §22 (`docs/05:1314`), §23 (`docs/05:1408-1409`) + `docs/06` §12 (`docs/06:286`). Проверено grep'ом. Коммит не делался |
| A2 | `docs/06:79` ссылался на несуществующий `08-bootstrap-intent-draft.md` | `docs/06:79` | **Выполнено**: заменено на `07-bootstrap-intent-draft.md` (`docs/06:79`). Проверено grep'ом |
| A3 | `.env.example`: наборы ключей в трёх документах не совпадают (`docs/07:406-437` без `LOG_DIR`; `docs/05:453-469` с `LOG_DIR`; `docs/03:63-79` без logging-ключей) | три документа | Решение: в `.env.example` — объединение всех наборов (включая `LOG_DIR`), значения пустые; authoritative-набор зафиксирует `config.py` на Stage 2 |
| A4 | `docs/AGENTS.md` объявлен носителем правил документации (`AGENTS.md:48`), но содержит одну строку | `docs/AGENTS.md:1` | Наполнить в рамках C6 (скилл `agents-md`) |

### B. Не расхождения, а плановая работа пустого проекта (задачи плана)

Раньше в этом разделе ошибочно подавались как «конфликты»; на деле это ожидаемые задачи Stage 1 — проект пишется с нуля по `docs/`:

- **Импортируемость пакета.** `uv.lock:7` фиксирует проект как `virtual` (пакета ещё нет). План: объявить `[build-system]` и создать `src/vk_topic_bridge/__init__.py` — после этого `basedpyright`/`pytest`/coverage видят пакет. Варианты — V1.
- **Smoke-test.** `pytest` без тестов возвращает exit code 5 → `make test` (и `make check`) красные. Один маленький тест-заглушка обязателен; `docs/07:266` это разрешает.
- **Порядок шагов.** `make check` начинается с `lock-check`; после правки `pyproject.toml` до `make lock` он упадёт. Порядок: pyproject → `make lock` → `make sync` → проверки (V9).
- **Каталоги `data/`, `runtime/telethon/`** — создать + закрыть `.gitignore` (V7), это требования `docs/07:280-296`, `:363-394`.
- **`migrations/`, `scripts/`** — создать пустыми; содержимое (`env.py`, `script.py.mako`, `start.sh`) придёт на Stage 3/12 (`docs/05:236-351` — это финальная структура, `docs/07:128` ограничивает именно Stage 1).
- **`docs/07:280-309`** — единственный источник skeleton для Stage 1; создавать только его содержимое, без «сотен пустых модулей».
- **Coverage-гейт** `--cov-fail-under=80` (`docs/05:1160-1170`) — настроить coverage сейчас, включить гейт при появлении продуктового кода.
- **`e2e`-маркер** — зарегистрировать и исключить из `make test` (`docs/05:1141-1151`: e2e требуют credentials); `make test-e2e` появится на Stage 11 как product-таргет (`docs/05:1251-1270` явно разрешает добавлять их «по мере реализации»).
- **`[build-system]`** отсутствует и в `docs/07:199-218` — это не конфликт, а следствие того, что авторы заполняли концепцию, а не финальный манифест.

### C. Технические риски исполнения (не конфликты, решаются `uv lock`)

| # | Риск | Что делать |
| --- | --- | --- |
| C1 | `aiogram` и `vkbottle` обе зависят от общей библиотеки `pydantic`, но задают свои версии: `vkbottle` → `>=2.13.4,<3`; у `aiogram` возможен другой диапазон. Если диапазоны не пересекутся, установщик не сможет подобрать одну версию и `uv lock` упадёт | Первой командой после правки `pyproject.toml` — `uv lock`. Если не разрешается — остановиться и эскалировать заказчику; `requires-python` не ослаблять (Q7) |
| C2 | `vkbottle 4.11` требует `aiohttp>=3.14.3`; `aiohttp` stable — только 3.x | В ranges зафиксировать `aiohttp>=3.14.3,<4` (в таблице ресёрча) |
| C3 | Ruff должен знать `target-version = "py314"` (ресёрч: знает с 0.13.0+) | Явный `target-version = "py314"` + проверка `make lint`/`make format-check`; fallback `py313` только по факту, с пометкой |
| C4 | `greenlet` под CPython 3.14 стабилен с 3.3 | Не добавлять в direct deps; приходит через `sqlalchemy[asyncio]`; при проблемах сборки — зафиксировать, не понижать Python |

---

## Нюансы реализации: варианты, обоснование, рекомендации

### V1. Как сделать `src/vk_topic_bridge` импортируемым (самая важная развилка)

Проблема: сейчас проект `virtual` (`uv.lock:7`), а `src/` пуст. Пока пакет не импортируется, `basedpyright` не проверит код, `pytest` не увидит пакет, coverage не найдёт source, а будущие тесты не смогут делать `from vk_topic_bridge...`.

- **Вариант A (рекомендуемый): editable install через `[build-system]`.** Объявить `[build-system]` (uv build backend либо hatchling) и `[project]` name/version уже есть. Тогда `uv sync --all-groups` ставит сам проект в `.venv`, и импорт работает для typecheck/test/coverage без хаков.
  - Плюсы: единственный source of truth; соответствует `docs/05:1451-1456` (расширяемый пакет, `src/` layout); никаких `pythonpath`-костылей; `uv.lock` фиксирует проект как editable.
  - Минусы: нужен корректный backend и версия; `uv sync` начнёт собирать проект (требует, чтобы `src/vk_topic_bridge/` уже существовал — порядок шагов!).
  - Обратимость: высокая.
- **Вариант B: остаться virtual + `pythonpath = ["src"]` у pytest и `extraPaths` у BasedPyright.** Плюсы: ноль сборочной конфигурации. Минусы: два независимых места настройки, coverage-источник задаётся отдельно, `uv build`/упаковка позже всё равно потребуют `[build-system]`; расхождение поведений «pytest видит, импорт-скрипт не видит».
- **Вариант C: ничего не делать.** Нежизнеспособно: нарушает AC `docs/07:499` и делает C5 недостижимым.

**Рекомендация: A.** Порядок исполнения критичен: сначала skeleton (`src/vk_topic_bridge/__init__.py`), затем `[build-system]` в pyproject, затем `uv lock`, затем `uv sync --all-groups`.

### V2. Версии и разрешение lock под Python 3.14

Главный риск Stage 1: `uv lock` откажется разрешать пакет, чей `requires-python` не включает 3.14 (или чьи wheels не собираются под 3.14 — актуально для нативных зависимостей вроде `greenlet`, который обязателен для `sqlalchemy[asyncio]`).
- **Рекомендация:** range-based (нижняя граница = earliest verified 3.14-совместимая версия из таблицы выше), exact graph — в `uv.lock` (`docs/05:180-191`). Совместимость НЕ считать подтверждённой до фактического `uv lock` + `uv sync --all-groups` + smoke-import. Если конкретный пакет блокирует резолюцию — это блокер плана, а не повод ослабить `requires-python`. Эскалация: свежая версия пакета, затем отказ от пакета/замена (решение заказчика).
- **Найденный конкретный риск:** `vkbottle 4.11` требует `pydantic>=2.13.4,<3` и `aiohttp>=3.14.3`, у `aiogram` же есть верхняя граница на pydantic. Пересечение границ обязано разрешиться в `uv lock`; при провале — эскалация (R1). Этот пункт надо проверить **первым** после добавления зависимостей.
- **greenlet:** для CPython 3.14 консервативен `greenlet>=3.3` (3.2.x — только alpha/beta 3.14). Если wheels под 3.14 недоступны и начнётся сборка из исходников — фиксировать как риск, не как повод понижать Python.
- **aiohttp:** stable-линия — 3.x; `aiohttp 4.x` в стабильном виде не существует, не закладывать его в ranges.
- **PySocks не добавлять** (`docs/07:153-158` его не требует, `python-socks[asyncio]` достаточно для Telethon).
- Обязательно зафиксировать в плане smoke-import как отдельный исполняемый шаг: `aiogram`, `vkbottle`, `telethon`, `sqlalchemy`, `sqlalchemy.ext.asyncio`, `aiosqlite`, `alembic`, `pydantic_settings`, `loguru`, `aiohttp`, `aiohttp_socks`, `python_socks` (импорт `sqlalchemy.ext.asyncio` — фактическая проверка наличия `greenlet`).

### V3. Ruff `target-version` и Python 3.14

Ruff выводит `target-version` из `project.requires-python`. При `>=3.14` он попытается включить `py314`. Если установленная версия Ruff не знает `py314` — format/lint упадут на конфиге.
- **Resёрч:** актуальная Ruff (0.15.x, earliest 3.14-aware — 0.13.0+) поддерживает `py314`; fallback не требуется.
- **Рекомендация:** всё равно задать `target-version = "py314"` явно (не полагаться на вывод из `requires-python`) и подтвердить фактическим прогоном `make lint`/`make format-check`. Если конкретная версия Ruff всё же не знает `py314` — временный fallback `py313` + явная задача «поднять до py314» (решение фиксируется в плане).

### V4. BasedPyright: строгость и резолв venv

- Ключ конфигурации — `[tool.basedpyright]` (не `[tool.pyright]`), пакет `pyright` НЕ добавлять (`docs/07:500-501`).
- **Рекомендация:** `typeCheckingMode = "standard"`, `pythonVersion = "3.14"`, `include = ["src", "tests"]`, `exclude` для `.venv`/`.omo`/`migrations`, `venvPath = "."`, `venv = ".venv"`. Это гарантирует, что `uv run --locked basedpyright` видит установленный пакет и стабы.
- Нюанс: smoke-import тест с «сырыми» импортами чужих библиотек может дать диагностику об отсутствующих стабах. Решение — `reportMissingTypeStubs = "none"` на bootstrap (не глушить весь остальной анализ).
- Нюанс: per-directory строгость (`domain`/`application` строже, чем adapters) — это Stage 2+; на Stage 1 не проектировать.

### V5. pytest: exit code 5, asyncio, e2e, coverage

- Без тестов `pytest` возвращает 5 → `make check` красный (см. разбор B). Smoke-test обязателен.
- `asyncio_mode = "auto"` + `asyncio_default_fixture_loop_scope = "function"` (иначе новые pytest-asyncio печатают warning о незаданном scope).
- `markers = ["e2e: ..."]` + `addopts`, исключающий `e2e` из дефолтного прогона (см. разбор B).
- Coverage: завести `[tool.coverage.run] source = ["vk_topic_bridge"]` и `[tool.coverage.report]`, добавить `--cov` отчёты; `--cov-fail-under` **не включать** на Stage 1 (см. разбор B). Обоснование: гейт на пустом пакете ничего не измеряет и создаёт ложное ощущение защиты; при этом AC `docs/07:518` требует лишь доступность coverage.
- `testpaths = ["tests"]`.

### V6. `.env.example`: полный набор будущих ключей

Взять объединение `docs/07:406-437` + `docs/05:453-469`: Telegram Bot API (`TELEGRAM_BOT_TOKEN`, `OWNER_IDS`, `TELEGRAM_BOT_API_URL`), MTProto (`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_PATH`), MTProto Proxy (`TELEGRAM_MTPROXY_SERVER/PORT/SECRET`), SOCKS (`SOCKS5_PROXY_URL`), VK (`VK_GROUP_TOKEN`), DB (`DATABASE_URL`), Logging (`LOG_LEVEL`, `LOG_LEVEL_LIBS`, `LOG_DIR`, `LOG_ROTATION`, `LOG_RETENTION`, `LOG_COMPRESSION`).
- **Рекомендация:** значения пустые, только keys + секции-комментарии; никаких реальных секретов, никакого чтения (чтение — Stage 2).

### V7. Gitignore: чего не хватает

Добавить: `data/*` + `!data/.gitkeep`; `runtime/telethon/*` + `!runtime/telethon/.gitkeep`; при желании `.coverage.*`. Сохранить существующие правила. `uv.lock` НЕ игнорировать (сейчас не игнорируется — ок).

### V8. Инициализация дерева `AGENTS.md` через скилл `agents-md` (C6, требование заказчика)

- Обязательно: исполнитель плана должен **загрузить скилл `agents-md`** и работать по нему, а не писать `AGENTS.md` «на глаз».
- Ограничения из `AGENTS.md:44-50`: не создавать `AGENTS.md` в `.git/`, `.venv/`, `.idea/`, `.serena/`, `.opencode/`, `.omo/`; создавать только там, где каталог содержателен и имеет отличающиеся команды/ограничения.
- **Рекомендация по объёму на Stage 1 (не раздувать):**
  1. `src/vk_topic_bridge/AGENTS.md` — правило слоёв: `domain`/`application` не импортируют aiogram/VKBottle/Telethon/SQLAlchemy (`docs/05:70`, `:195-231`), package markers без runtime behavior (`docs/07:136`).
  2. `tests/AGENTS.md` — test strategy: unit без сети и реальной SQLite, e2e исключены из `make test`, acceptance-имена по US/AC (`docs/05:1122-1139`), никаких network-dependent тестов (`docs/07:551`).
  3. Апдейт корневого `AGENTS.md` → раздел Navigation: добавить пути новых вложенных `AGENTS.md`.
  4. Расширить пустой `docs/AGENTS.md` (A4) — краткие правила intent/feature backlog/документации.
- Альтернатива (если заказчик захочет минимум): только `tests/AGENTS.md` + Navigation. **Рекомендуется полный вариант 1-4** — он покрывает реально существующие после bootstrap содержательные каталоги и не создаёт пустых файлов.

### V9. Порядок исполнения (иначе `make check` будет красным по техническим причинам)

1. Создать skeleton (каталоги + placeholders + `src/vk_topic_bridge/__init__.py`).
2. Заполнить `pyproject.toml` (deps, dev group, `[build-system]`, `[tool.*]`).
3. `make lock` (перегенерировать `uv.lock`).
4. `make sync` (`uv sync --all-groups`).
5. Прогнать `uv lock --check`, `make format-check`, `make lint`, `make typecheck`, `make test`, `make check`.
6. Обновить `.gitignore` и `.env.example`.
7. C6: скилл `agents-md` → дерево `AGENTS.md`.
8. Один коммит (или логические коммиты) от имени пользователя.

### V10. Риски

- **R1 (высокий):** Python-3.14-несовместимость хотя бы одной целевой библиотеки, либо неразрешимое пересечение диапазонов `pydantic`/`aiohttp` у `aiogram` и `vkbottle` → `uv lock` не разрешается (C1). Митигация: проверять `uv lock` первым; эскалация заказчику, не ослаблять `requires-python`.
- **R2 (средний):** `[build-system]` выбран неверно / не создан пакет до `uv sync` → ошибка сборки. Митигация: жёсткий порядок V9.
- **R3 (средний):** Ruff не знает `py314` → падение lint/format. Ресёрч говорит, что знает (0.13.0+); митигация: явный `target-version = "py314"` + fallback на `py313` по факту.
- **R4 (низкий):** шум диагностик BasedPyright на чужих стабах → ложный красный `typecheck`. Митигация: V4.
- **R5 (низкий):** расширение scope «раз уж удобно» (создание `config.py`, моделей, handlers). Митигация: Scope OUT ниже + `AGENTS.md:57-59`.

---

## Decisions (with rationale)

1. **Stage 1 = только bootstrap.** Продуктовый код не пишется: ни `config.py`, ни `logger.py`, ни `main.py` (`docs/07:113-136`).
2. **`[build-system]` объявляется** (V1-A) — иначе C5 недостижим.
3. **Версии — range-based с 3.14-aware нижними границами** (см. таблицу ресёрча и Q-таблицу), exact graph в `uv.lock` (`docs/05:180-191`). `pydantic` и `greenlet` остаются транзитивными (см. разбор B).
4. **Coverage-гейт `--cov-fail-under` откладывается** до появления продуктового кода (см. разбор B).
5. **Smoke-test обязателен** (см. разбор B) — он же закрывает требование `docs/07:509` про smoke-import.
6. **e2e-маркер регистрируется и исключается** из `make test`; таргет `test-e2e` не добавляется (см. разбор B).
7. **Makefile не расширяется** product-таргетами (`docs/07:344-353`). Bootstrap-таргеты остаются как есть.
8. **Skeleton минимальный:** только каталоги, placeholders и пустой `__init__.py` пакета; никаких `entities.py`/`ports.py`/`use_cases` (`docs/07:300-309`, `AGENTS.md:59`).
9. **`migrations/` создаётся пустой** (см. разбор B); `alembic.ini` и `migrations/env.py` не создаются.
10. **`.env.example` = объединение ключей из `docs/07` и `docs/05`**, значения пустые, без чтения (V6).
11. **`.gitignore` расширяется** `data/*`, `runtime/telethon/*` + исключения placeholders (V7).
12. **C6 обязателен:** скилл `agents-md` загружается, дерево `AGENTS.md` инициализируется в глубине проекта; Navigation обновляется; `docs/AGENTS.md` наполняется по существу (V8).
13. **`pid/` — задокументированная хотелка заказчика** (A1): PID-файл PM2 живёт в `pid/`; правки внесены в `docs/05` и `docs/06`. Каталог уже в репозитории и `.gitignore` — не трогать.
14. **Никаких network calls** на Stage 1, кроме неизбежных `uv lock` / `uv sync` (PyPI) — `docs/07:132`.
15. **Коммиты от имени пользователя**, без co-authored-by (`AGENTS.md:18-19`).

---

## Scope IN

1. Заполнить `[project].dependencies`: `aiogram`, `vkbottle`, `telethon`, `sqlalchemy[asyncio]`, `aiosqlite`, `alembic`, `pydantic-settings`, `loguru`, `aiohttp`, `aiohttp-socks`, `python-socks[asyncio]`.
2. Заполнить `[dependency-groups].dev`: `ruff`, `basedpyright`, `pytest`, `pytest-asyncio`, `pytest-cov`.
3. Объявить `[build-system]` и сделать проект editable-installable.
4. Сгенерировать и закоммитить `uv.lock`; `uv lock --check` зелёный.
5. Настроить Ruff (`[tool.ruff]`: `target-version = "py314"`, `line-length = 100`, `[tool.ruff.lint].select` = Q9-набор, format) — config в `pyproject.toml`.
6. Настроить BasedPyright (`[tool.basedpyright]`) — без пакета `pyright`.
7. Настроить pytest (`testpaths`, `asyncio_mode`, markers, `addopts`) и coverage (`[tool.coverage.*]`), без `--cov-fail-under`.
8. Добавить минимальный smoke-test (imports runtime-библиотек + пакет `vk_topic_bridge`).
9. Создать skeleton: `src/vk_topic_bridge/__init__.py`; `tests/{unit,integration,acceptance,e2e}/`; `migrations/`, `scripts/`, `data/`, `logs/`, `runtime/telethon/` с `.gitkeep` где нужно.
10. Обновить `.gitignore` (V7).
11. Заполнить `.env.example` будущими keys (V6) — без чтения.
12. Синхронизировать bootstrap-таргеты Makefile (сохранить как есть; убедиться, что `make check` зелёный).
13. Выполнить compatibility-проверку и smoke-import под Python 3.14.
14. C6: загрузить скилл `agents-md`, инициализировать дерево `AGENTS.md` в глубине проекта, обновить Navigation корневого `AGENTS.md`, наполнить `docs/AGENTS.md`.
15. Зафиксировать изменения коммитами от имени пользователя.

---

## Scope OUT (Must NOT have)

- `config.py` / `Settings` / чтение `.env` / валидация env (`docs/07:117-118`, `:545-547`).
- `logger.py`, Loguru setup, intercept handler (`docs/07:119-120`, `:546`).
- `main.py`, lifecycle, composition root, startup checks (`docs/07:112-134`).
- Telegram Bot: bot instance, handlers, FSM, middlewares, keyboards, routers.
- VK Bot: handlers, FSM, keyboards, sessions.
- Telethon client, proxy resolver, `authorize_telegram.py`, получение topics.
- SQLAlchemy models, `engine.py`, repositories, pragmas, transactions.
- Alembic: `alembic.ini`, `migrations/env.py`, `script.py.mako`, `versions/`, миграции.
- Forwarding use cases, attachments/downloader, 50 МБ-политика, публикация, идемпотентность.
- `ecosystem.config.cjs`, `scripts/start.sh`, deployment-скрипты, PM2.
- Любые network calls в тестах и в коде (`docs/07:551`).
- Product-таргеты Makefile (`run`, `auth`, `migrate`, `pm2-*`, `test-e2e`) (`docs/07:344-353`).
- Exact-pins всех транзитивных зависимостей в `pyproject.toml`.
- Дополнительные инструменты (Black, isort, mypy, Pyright) без доказанной необходимости (`docs/07:182-189`).
- `README.md`, `LICENSE`, CI-конфиги, Docker — не запрошены.
- Удаление или изменение `pid/`.
- Правки `docs/*.md` — вне scope bootstrap (A1/A2 уже внесены отдельной правкой по прямому указанию заказчика).

---

## Open questions

Все вопросы имеют рекомендованный default — при отсутствии ответа принимается он (интервью не проводится по требованию заказчика).

1. **Q1. `[build-system]` — включаем editable install?** Рекомендация: **да** (V1-A). Если нет — потребуется `pythonpath`/`extraPaths` и coverage-источник настраивается отдельно.
2. **Q2. Ruff `line-length`.** Рекомендация: **100**. Альтернативы: 88 (дефолт Ruff), 120.
3. **Q3. Объём C6 (`AGENTS.md` в глубину).** Рекомендация: **полный вариант 1-4 из V8** (`src/vk_topic_bridge/AGENTS.md`, `tests/AGENTS.md`, обновление Navigation, наполнение `docs/AGENTS.md`). Альтернатива: только `tests/AGENTS.md` + Navigation.
4. **Q4. `--cov-fail-under=80` на Stage 1?** Рекомендация: **нет, отложить** (см. разбор B).
5. **Q5. `pid/` — теперь документированная фича (A1).** Заказчик подтвердил: здесь PM2 хранит PID-файл. Правки внесены в `docs/05` §5/§22/§23 и `docs/06` §12. Рекомендация: **каталог уже корректный — не трогать**.
6. **Q6. BasedPyright `typeCheckingMode`.** Рекомендация: **`standard`** (V4). Альтернативы: `basic`, `recommended`.
7. **Q7. Fallback при блокирующей несовместимости с Python 3.14 (R1).** Рекомендация: **остановиться и эскалировать заказчику** до ослабления `requires-python` или замены библиотеки.
8. **Q8. Ставить `uv python install 3.14`, если интерпретатор отсутствует?** Рекомендация: **да, автоматически** в рамках bootstrap (uv управляет Python).
9. **Q9. Ruff ruleset (`[tool.ruff.lint].select`).** Дефолт Ruff — почти ничего (E4/E7/E9/F). Рекомендация: **`["E","F","I","UP","B","SIM","RUF"]`**; **не** включать `ANN` и `D` — на bootstrap-skeleton без сигнатур и докстрингов они дадут шум и ложный красный `make lint`. Альтернативы: только дефолт; или дефолт + `I`,`UP`,`B`.
10. **Q10. Строгость pytest.** Рекомендация: `--strict-markers` и `--strict-config` **включить**; `filterwarnings = ["error"]` **не** включать (чужие библиотеки печатают собственные warning'и и ломают `make test`); вместо этого — адресные `ignore` по мере появления.
11. **Q11. Build backend для `[build-system]`.** Рекомендация: **`uv_build`** (родной бэкенд uv, ноль дополнительных зависимостей, ожидает ровно `src/<package>/__init__.py` — совпадает с layout). Альтернатива: **`hatchling`** (боевая проверенная классика, но +1 build-dependency). Выбор бэкенда делается один раз вместе с Q1.

---

## Связанные материалы

Раздел обязателен по `AGENTS.md:52-55`.

- `docs/07-bootstrap-intent-draft.md` — исходный «готовый план» Stage 1; главный источник intent, scope и AC для этого draft. Связь прямая: данный draft переносит его в формат `.omo/drafts` без расширения scope.
- `docs/05-architecture-and-engineering.md` — задаёт целевой стек, версии/extras, dependency policy, файловую структуру, strictness BasedPyright, Makefile и coverage-gate; без него нельзя валидировать ни одну развилку V1-V5.
- `docs/06-full-implementation-roadmap.md` — место Stage 1 в общей карте и правило «следующий этап только после завершения предыдущего»; фиксирует границу bootstrap ↔ Stage 2.
- `docs/03-technical-requirements.md` — концептуальный env-набор (используется для объединения в `.env.example`, A3) и правило «`.env` не хранит business state».
- `docs/01-product-spec.md` — продуктовый контекст; объясняет, почему Stage 1 не создаёт runtime-модули (пересылка VK→Telegram — это Stage 4+).
- `docs/02-user-stories.md` — US-26 (скрипт авторизации) объясняет будущую зависимость `runtime/telethon/`; на Stage 1 создаётся только каталог.
- `docs/04-fsm-and-ui.md` — будущие FSM/UI; подтверждает, что `tests/acceptance` будет наполняться по US/AC позже.
- `AGENTS.md` — Package Manager, Commands, Navigation, Planning Traceability, Bootstrap, Comments; источник ограничений C6 и запрета product-кода в bootstrap.
- `docs/AGENTS.md` — объявленный носитель правил документации; фактически пуст (A4), подлежит наполнению в C6.
- `Makefile` — существующие bootstrap-таргеты; `make check` = `lock-check format-check lint typecheck test`.
- `pyproject.toml`, `uv.lock`, `.gitignore`, `.env.example`, `.python-version` — текущее состояние, относительно которого считаются дельты bootstrap.
- `.omo/drafts/` и `.omo/plans/` — пусты; связанных прошлых планов/drafts нет (проект пустой, кода нет). Связи не найдены — указано явно.
- `.omo/evidence/` — пуст; на Stage 1 наполняется артефактами smoke-import/lock/check.

Внешний ресёрч: отчёт `librarian` от 2026-09-17 по совместимости Python 3.14 (PyPI metadata + GitHub releases/changelogs) — не является файлом репозитория; тезисы перенесены в `## Findings` выше, полные цитаты-источники — в исходном ответе `librarian` (session `ses_f52228129ffeq8iln8LxdSZoru`). Обязателен к перепроверке на исполнении через `uv lock`.

---

## Approval gate

status: awaiting-approval

Что сделано: прочитаны все 7 файлов `docs/`, корневой `AGENTS.md`, `docs/AGENTS.md`, `Makefile`, `pyproject.toml`, `uv.lock`, `.gitignore`, `.env.example`, `.python-version`, `.omo/` — исследование проведено лично, без explorer'ов (по требованию заказчика). Ресёрч совместимости Python 3.14 выполнен `librarian` и перенесён в Findings. Правки `pid/` в `docs/05`/`docs/06` и опечатки `08-...` внесены и проверены (A1, A2) — коммит не делался.

Что дальше по `pending-action_policy`: после явного одобрения заказчика → `write .omo/plans/stage-1-bootstrap.md` (decision-complete план Stage 1 в шаблонном формате ulw-plan, с задачами `- [ ] N.` и финальной волной `- [ ] F<n>.`), затем — при желании — dual high-accuracy review.

`review_required: false`: заказчик не запрашивал повышенную точность. Если требуется — сказать, и review будет включён.

Заказчик перепроверяет этот draft. Вопросов, блокирующих генерацию плана, нет: все развилки закрыты default'ами Q1-Q11 (пропущенный вопрос = принят recommended default).

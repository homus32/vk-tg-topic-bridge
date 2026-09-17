# VK Topic Bridge — Draft Intent: Stage 1 Bootstrap

> Первый draft intent для Prometheus / Ultrabrain / Sisyphus.
> Задача этапа — только инициализация проекта, зависимости, tooling и directory skeleton.
> Продуктовый код на этом этапе не реализуется.

## Оглавление

- [[#1. Контекст]]
- [[#2. Текущее состояние репозитория]]
- [[#3. Цель этапа]]
- [[#4. In scope]]
- [[#5. Out of scope]]
- [[#6. Зависимости]]
- [[#7. Pyproject и dependency groups]]
- [[#8. Tooling]]
- [[#9. Directory skeleton]]
- [[#10. Makefile]]
- [[#11. Gitignore и runtime paths]]
- [[#12. Env example]]
- [[#13. Проверки совместимости]]
- [[#14. Acceptance Criteria]]
- [[#15. Инструкции Prometheus]]
- [[#16. Инструкции Ultrabrain / Sisyphus]]

---

# 1. Контекст

Проект: `vk-topic-bridge`.

Runtime:

- Python 3.14;
- `uv`;
- один будущий modular-monolith process;
- архитектура из `05-architecture-and-engineering.md`.

Текущая задача **не реализует мост VK → Telegram**.

Она создаёт технически корректную основу, на которой следующие feature plans смогут писать runtime-код.

---

# 2. Текущее состояние репозитория

На момент draft в репозитории уже есть:

```text
AGENTS.md
docs/AGENTS.md
.env.example
.gitignore
Makefile
.omo/
pid/.gitkeep
pyproject.toml
.python-version
```

Уже приняты важные решения:

- `.python-version` = `3.14`;
- package manager — `uv`;
- проект называется `vk-topic-bridge`;
- `Makefile` уже содержит bootstrap quality commands;
- `typecheck` уже использует `basedpyright`;
- `AGENTS.md` запрещает реализацию product/runtime code в bootstrap без отдельного утверждённого плана.

Существующие правила `AGENTS.md` обязательны и имеют приоритет при реализации этого этапа.

---

# 3. Цель этапа

После выполнения bootstrap должно быть возможно:

```bash
uv sync --all-groups
make check
```

из чистого checkout проекта.

Dependency graph должен быть разрешён и зафиксирован `uv.lock`.

Будущая структура проекта должна быть подготовлена, но продуктовая логика отсутствует.

---

# 4. In scope

Этап включает:

1. исследование актуальной совместимости libraries с Python 3.14;
2. заполнение runtime dependencies;
3. заполнение dev dependency group;
4. создание/обновление `uv.lock`;
5. настройку Ruff;
6. настройку BasedPyright;
7. настройку pytest;
8. настройку coverage config;
9. обновление `.gitignore`;
10. заполнение `.env.example` только названиями будущих settings и безопасными example/default values;
11. создание directory skeleton;
12. минимальную настройку Makefile bootstrap commands;
13. smoke-import runtime libraries;
14. документацию только если она необходима для понимания bootstrap.

---

# 5. Out of scope

На этом этапе **не реализовывать**:

- `config.py` logic;
- `logger.py` logic;
- реальные Settings;
- Loguru setup;
- Telegram Bot;
- Telegram handlers/FSM;
- VK Bot;
- VK handlers/FSM;
- Telethon client;
- `authorize_telegram.py`;
- SQLAlchemy models;
- repositories;
- Alembic configuration/migrations;
- forwarding use cases;
- attachments;
- PM2 `ecosystem.config.cjs`;
- deployment scripts;
- network calls;
- product tests.

Если для будущей структуры создаются Python package markers, они не должны содержать runtime behavior.

---

# 6. Зависимости

Prometheus обязан перед финализацией intent проверить официальную документацию и актуальные releases.

## Runtime dependencies

Целевой список:

```text
aiogram
vkbottle
telethon
sqlalchemy[asyncio]
aiosqlite
alembic
pydantic-settings
loguru
aiohttp
aiohttp-socks
python-socks[asyncio]
```

### Зачем direct dependencies

`aiohttp` объявляется явно, потому что проект планирует собственный asynchronous media/download layer и не должен зависеть от того, что пакет случайно установлен как dependency aiogram.

`aiohttp-socks` объявляется явно для SOCKS transport aiogram.

`python-socks[asyncio]` объявляется явно для Telethon SOCKS support.

`sqlalchemy[asyncio]` используется с extra `asyncio`, а не голый `sqlalchemy`.

## Dev dependencies

```text
ruff
basedpyright
pytest
pytest-asyncio
pytest-cov
```

Не добавлять:

- Pyright;
- Black;
- isort;
- mypy;

если Prometheus не найдёт конкретной необходимости: их функции в текущем design уже закрываются Ruff/BasedPyright.

---

# 7. Pyproject и dependency groups

`pyproject.toml` должен стать canonical manifest.

Ожидаемая концепция:

```toml
[project]
name = "vk-topic-bridge"
version = "0.1.0"
requires-python = ">=3.14"
dependencies = [
    # runtime
]

[dependency-groups]
dev = [
    # tooling/tests
]
```

Не требуется вручную exact-pin всех transitive dependencies.

Exact resolved graph фиксируется `uv.lock`.

Prometheus/Ultrabrain должны определить разумные compatible version ranges после исследования актуальных releases.

---

# 8. Tooling

## Ruff

Ruff используется одновременно для:

- format;
- lint;
- import sorting;
- базовых correctness checks.

Существующие Makefile commands сохраняются:

```text
make format
make format-check
make lint
```

## BasedPyright

Использовать только `basedpyright`.

Не добавлять пакет `pyright`.

Config хранить в `pyproject.toml`.

На bootstrap выбрать режим, который:

- реально проверяет проект;
- проходит на пустом/skeleton code;
- не требует ослаблений уровня `ignore everything`.

Строгость domain/application будет усилена после появления этих слоёв.

## pytest

Настроить:

- async test support;
- test discovery;
- markers как минимум для будущего `e2e`;
- coverage source для будущего `vk_topic_bridge`.

На bootstrap pytest может содержать минимальный smoke test, если он нужен для того, чтобы `make test` проверял фактическую работоспособность test environment.

Не писать product tests.

---

# 9. Directory skeleton

Целевая будущая структура задаётся `05-architecture-and-engineering.md`.

Bootstrap должен создать только разумный skeleton, не сотни пустых speculative modules.

Минимально подготовить:

```text
src/
└── vk_topic_bridge/

tests/
├── unit/
├── integration/
├── acceptance/
└── e2e/

migrations/
scripts/
data/
logs/
runtime/
└── telethon/
```

Для пустых operational directories использовать `.gitkeep`, если каталог должен существовать в Git.

Не создавать на bootstrap десятки файлов вида:

```text
entities.py
ports.py
forward_message.py
...
```

Их создаст Ultrabrain вместе с конкретными feature intents, когда станут известны реальные signatures.

---

# 10. Makefile

Существующие bootstrap targets сохранить:

```text
sync
lock
lock-check
format
format-check
lint
typecheck
test
check
```

Ключевые свойства:

```makefile
sync:
	uv sync --all-groups

typecheck:
	uv run --locked basedpyright

check:
	lock-check format-check lint typecheck test
```

Все команды проверки, кроме `format`, должны быть read-only относительно исходников.

На bootstrap не добавлять product targets:

```text
run
auth
migrate
pm2-start
```

до появления соответствующего runtime.

---

# 11. Gitignore и runtime paths

Сохранить текущие ignores и дополнить при необходимости.

Обязательно игнорируются:

```text
.env
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
.basedpyright/
.pyright/
.coverage
coverage.xml
htmlcov/

*.db
*.sqlite
*.sqlite3

logs/*
runtime/telethon/*
data/*
```

Для tracked placeholders:

```text
!logs/.gitkeep
!runtime/telethon/.gitkeep
!data/.gitkeep
```

Telethon session никогда не коммитится.

`uv.lock` наоборот должен быть committed.

---

# 12. Env example

`.env.example` сейчас пустой — bootstrap должен подготовить список будущих keys.

Не реализовывать их чтение.

Ожидаемые группы:

```text
# Telegram Bot API
TELEGRAM_BOT_TOKEN=
OWNER_IDS=
TELEGRAM_BOT_API_URL=

# Telegram MTProto
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_SESSION_PATH=

# MTProto Proxy
TELEGRAM_MTPROXY_SERVER=
TELEGRAM_MTPROXY_PORT=
TELEGRAM_MTPROXY_SECRET=

# SOCKS
SOCKS5_PROXY_URL=

# VK
VK_GROUP_TOKEN=

# Database
DATABASE_URL=

# Logging
LOG_LEVEL=
LOG_LEVEL_LIBS=
LOG_ROTATION=
LOG_RETENTION=
LOG_COMPRESSION=
```

Никаких реальных secrets.

Можно добавить безопасные documented defaults там, где они действительно определены архитектурой.

---

# 13. Проверки совместимости

До фиксации dependency manifest Prometheus должен проверить:

- Python 3.14 support;
- aiogram current 3.x;
- VKBottle current 4.x;
- Telethon current stable 1.x;
- `python-socks[asyncio]` requirement Telethon proxy;
- `aiohttp-socks` requirement aiogram proxy;
- SQLAlchemy async install extra;
- current Alembic compatibility;
- Pydantic / pydantic-settings compatibility;
- BasedPyright Python 3.14 parsing/type support.

После lock:

```bash
uv sync --all-groups
uv lock --check
```

Выполнить smoke-import примерно такого класса:

```text
aiogram
vkbottle
telethon
sqlalchemy
sqlalchemy.ext.asyncio
aiosqlite
alembic
pydantic_settings
loguru
aiohttp
aiohttp_socks
python_socks
```

Если import path конкретного package отличается — использовать реальный documented import.

---

# 14. Acceptance Criteria

## Repository

- [ ] `.python-version` остаётся `3.14`;
- [ ] `[project].name` остаётся `vk-topic-bridge`;
- [ ] нет случайной замены `uv` другим package manager;
- [ ] правила существующего `AGENTS.md` соблюдены.

## Dependencies

- [ ] runtime dependencies объявлены в `[project].dependencies`;
- [ ] dev dependencies объявлены в `[dependency-groups].dev`;
- [ ] `basedpyright` присутствует;
- [ ] `pyright` отсутствует;
- [ ] `sqlalchemy` установлен с `asyncio` extra;
- [ ] `aiohttp-socks` объявлен;
- [ ] `python-socks[asyncio]` объявлен;
- [ ] generated `uv.lock` committed;
- [ ] `uv lock --check` успешен;
- [ ] clean `uv sync --all-groups` успешен;
- [ ] smoke-import runtime dependencies успешен под Python 3.14.

## Tooling

- [ ] Ruff format настроен;
- [ ] Ruff lint настроен;
- [ ] BasedPyright настроен в `pyproject.toml`;
- [ ] pytest настроен;
- [ ] pytest-asyncio настроен;
- [ ] pytest-cov доступен;
- [ ] marker `e2e` зарегистрирован;
- [ ] `make typecheck` вызывает BasedPyright;
- [ ] `make check` проходит.

## Structure

- [ ] существует `src/vk_topic_bridge/`;
- [ ] существуют `tests/unit`;
- [ ] существуют `tests/integration`;
- [ ] существуют `tests/acceptance`;
- [ ] существуют `tests/e2e`;
- [ ] существуют `migrations/`, `scripts/`, `data/`, `logs/`, `runtime/telethon/`;
- [ ] bootstrap не создаёт лишние speculative runtime modules;
- [ ] bootstrap не реализует product logic.

## Secrets / runtime

- [ ] `.env.example` заполнен только безопасными placeholders/defaults;
- [ ] `.env` игнорируется;
- [ ] runtime DB игнорируются;
- [ ] `logs/*` игнорируются кроме placeholder;
- [ ] Telethon sessions игнорируются;
- [ ] `uv.lock` не игнорируется.

## Scope protection

- [ ] не реализован `config.py`;
- [ ] не реализован `logger.py`;
- [ ] не реализованы API clients;
- [ ] не реализованы ORM models/migrations;
- [ ] не реализованы Telegram/VK handlers;
- [ ] не создан production PM2 deployment;
- [ ] нет network-dependent tests.

---

# 15. Инструкции Prometheus

Перед созданием финального intent:

1. прочитать корневой `AGENTS.md`;
2. прочитать `docs/AGENTS.md`;
3. прочитать все product artifacts;
4. прочитать `05-architecture-and-engineering.md`;
5. прочитать `07-full-implementation-roadmap.md`;
6. исследовать реальное состояние репозитория;
7. проверить актуальную официальную документацию dependencies;
8. не задавать вопрос пользователю, если ответ однозначно следует из artifacts/repository/docs;
9. вопросы задавать только для решений, реально влияющих на bootstrap;
10. не расширять scope в product implementation.

Отдельно проверить, не появились ли новые несовместимости Python 3.14 после создания этого draft.

---

# 16. Инструкции Ultrabrain / Sisyphus

Ultrabrain:

- проверить dependency choices;
- проверить directory skeleton;
- не проектировать signatures будущих product use cases на bootstrap;
- создать decision-complete `.omo/plans/` только для Stage 1;
- указать точный список файлов create/modify;
- указать команды проверки после каждого meaningful шага.

Sisyphus:

- исполняет только approved Stage 1 plan;
- не начинает Stage 2;
- не добавляет product code «раз уж удобно»;
- не делает drive-by refactoring;
- сохраняет существующие repository conventions;
- завершает работу только после успешного:

```bash
uv lock --check
make format-check
make lint
make typecheck
make test
make check
```

После реализации Ultrabrain проводит review до явного `APPROVE`.

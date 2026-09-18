# VK Topic Bridge — Architecture & Engineering Specification

## Оглавление

- [[#1. Название и формат проекта]]
- [[#2. Архитектурный стиль]]
- [[#3. Полный стек]]
- [[#4. Принципы зависимостей]]
- [[#5. Предлагаемая файловая структура]]
- [[#6. Runtime и жизненный цикл приложения]]
- [[#7. Конфигурация через pydantic-settings]]
- [[#8. Логирование через Loguru]]
- [[#9. База данных и ORM]]
- [[#10. Миграции Alembic]]
- [[#11. Модель данных]]
- [[#12. Telegram Bot API]]
- [[#13. Telethon и MTProto]]
- [[#14. VK]]
- [[#15. FSM]]
- [[#16. Пересылка и обработка вложений]]
- [[#17. Идемпотентность]]
- [[#18. Обработка ошибок]]
- [[#19. Автотесты]]
- [[#20. Статический анализ и качество]]
- [[#21. Makefile]]
- [[#22. PM2]]
- [[#23. Git ignore и runtime-данные]]
- [[#24. Что намеренно не используется]]
- [[#25. Архитектурные критерии приёмки]]

---

# 1. Название и формат проекта

Рабочее название репозитория и PyCharm-проекта:

`vk-topic-bridge`

Python package:

`vk_topic_bridge`

Тип приложения:

- один Python-процесс;
- модульный монолит;
- один event loop `asyncio`;
- Telegram Bot API polling и VK Long Poll работают параллельно;
- Telethon используется как отдельный MTProto-клиент внутри того же процесса;
- SQLite — единственная рабочая БД.

Проект не разбивается на отдельные сервисы VK и Telegram.

Причина: бизнес-операция одна — перенос события из VK в Telegram и управление этой интеграцией. Разделение на два приложения создало бы лишние сетевые границы, синхронизацию состояния и дублирование моделей.

---

# 2. Архитектурный стиль

Используется комбинация:

- **Clean Architecture** — зависимости направлены внутрь, к бизнес-логике;
- **Ports & Adapters / Hexagonal Architecture** — внешние SDK и API находятся за интерфейсами;
- **SOLID** — применяется практически, без дробления проекта на бессмысленные классы;
- **DDD-lite** — доменные сущности, политики, value objects и use cases, но без тяжёлой enterprise-модели агрегатов, bounded contexts и domain events там, где они не дают пользы;
- **Dependency Injection** — ручная сборка зависимостей в composition root, без DI-контейнера.

Главное правило:

> `domain` и `application` ничего не знают об aiogram, VKBottle, Telethon, SQLAlchemy, SQLite и Loguru.

SDK-модели преобразуются в собственные DTO / domain-модели на границе приложения.

---

# 3. Полный стек

## Runtime

- Python 3.14;
- `asyncio`;
- `uv` — управление Python, зависимостями и lock-файлом.

## Telegram

- `aiogram 3.x` — Telegram Bot API, административный Telegram-бот, FSM и публикации;
- `Telethon 1.x` — пользовательский MTProto-клиент для чтения Telegram-топиков;
- `aiohttp-socks` — SOCKS5 transport для aiogram;
- `python-socks[asyncio]` — SOCKS5 transport для Telethon.

## VK

- `vkbottle 4.x` — VK Bot API / Long Poll / VK API.

## База данных

- SQLite;
- `SQLAlchemy[asyncio]` 2.x ORM;
- `aiosqlite`;
- Alembic — миграции.

`SQLAlchemy[asyncio]` указывается именно с extra `asyncio`, чтобы гарантированно установить runtime-зависимость `greenlet`, необходимую async extension.

## Конфигурация

- Pydantic 2;
- `pydantic-settings`.

## HTTP

- `aiohttp` — прямой dependency проекта, если используется собственный downloader внешних вложений;
- не полагаться на то, что `aiohttp` случайно подтянулся транзитивно через aiogram.

## Логирование

- Loguru;
- корневой `logger.py`;
- bridge стандартного `logging` → Loguru.

## Тесты

- `pytest`;
- `pytest-asyncio`;
- `pytest-cov`.

## Quality tools

- Ruff — formatter + lint;
- BasedPyright — статическая проверка типов.

## Process manager

- PM2;
- установленный на сервере модуль `pm2-logrotate`.

## Dependency policy

Runtime-зависимости объявляются в `[project].dependencies`.

Инструменты разработки объявляются в `[dependency-groups].dev`.

Целевой набор runtime dependencies:

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

Целевой dev group:

```text
ruff
basedpyright
pytest
pytest-asyncio
pytest-cov
```

Нельзя добавлять direct dependency только потому, что она уже транзитивно присутствует у другой библиотеки: если проект импортирует пакет напрямую либо опирается на его optional feature, он должен быть объявлен явно.

После изменения зависимостей обязательно:

```bash
uv lock
uv sync --all-groups
uv lock --check
```

И отдельный smoke-import ключевых библиотек под Python 3.14.

## Версионная стратегия

В `pyproject.toml` задаются поддерживаемые диапазоны major/minor там, где это оправдано архитектурой, а точный воспроизводимый dependency graph фиксирует committed `uv.lock`.

Не использовать бездумный набор `==` pins в `pyproject.toml`, если exact versions уже фиксирует lock-файл.

Перед первоначальным добавлением зависимостей агент обязан проверить:

1. поддержку Python 3.14;
2. актуальный install extra;
3. известные несовместимости между выбранными версиями;
4. что lock успешно разрешается на целевой платформе.

# 4. Принципы зависимостей

Направление зависимостей:

```text
presentation ─┐
              ├─> application ─> domain
infrastructure┘
```

`domain`:

- не импортирует ничего из остальных слоёв;
- содержит бизнес-правила.

`application`:

- знает `domain`;
- объявляет ports — интерфейсы, которые нужны use cases;
- не знает конкретных SDK и SQLAlchemy.

`infrastructure`:

- реализует ports;
- содержит SQLAlchemy, aiogram Bot API client, Telethon, VK API, HTTP.

`presentation`:

- принимает пользовательские события;
- превращает их в команды use case;
- форматирует UI;
- не содержит бизнес-правила пересылки.

`bootstrap`:

- создаёт объекты;
- связывает реальные реализации ports с use cases;
- запускает приложение.

---

# 5. Предлагаемая файловая структура

```text
vk-topic-bridge/
├── .env
├── .env.example
├── .gitignore
├── .python-version
├── config.py
├── logger.py
├── main.py
├── authorize_telegram.py
├── Makefile
├── pyproject.toml
├── uv.lock
├── alembic.ini
├── ecosystem.config.cjs
├── pid/
│   └── .gitkeep
│
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
├── scripts/
│   └── start.sh
│
├── data/
│   └── .gitkeep
│
├── logs/
│   └── .gitkeep
│
├── runtime/
│   ├── telethon/        # Telethon session (gitignored)
│   ├── vk_cursor/       # VK Long Poll cursor (gitignored)
│   └── media/           # временные скачанные вложения (gitignored)
│
├── src/
│   └── vk_topic_bridge/
│       ├── __init__.py
│       ├── __main__.py
│       │
│       ├── domain/
│       │   ├── entities.py
│       │   ├── enums.py
│       │   ├── errors.py
│       │   ├── value_objects.py
│       │   └── policies/
│       │       ├── alias_policy.py
│       │       ├── forwarding_policy.py
│       │       └── attachment_policy.py
│       │
│       ├── application/
│       │   ├── dto/
│       │   ├── ports/
│       │   │   ├── repositories.py
│       │   │   ├── telegram.py
│       │   │   ├── vk.py
│       │   │   └── media.py
│       │   ├── forwarding/
│       │   │   ├── forward_message.py
│       │   │   ├── forward_wall_post.py
│       │   │   └── manual_forward.py
│       │   ├── topics/
│       │   │   ├── refresh_topics.py
│       │   │   └── select_destination.py
│       │   ├── aliases/
│       │   └── admin/
│       │       ├── register_chat.py
│       │       ├── change_chat.py
│       │       └── toggle_settings.py
│       │
│       ├── infrastructure/
│       │   ├── db/
│       │   │   ├── base.py
│       │   │   ├── engine.py
│       │   │   ├── models.py
│       │   │   └── repositories/
│       │   ├── telegram/
│       │   │   ├── bot_api.py
│       │   │   ├── bot_api_factory.py
│       │   │   ├── mtproto.py
│       │   │   └── proxy.py
│       │   ├── vk/
│       │   │   ├── api.py
│       │   │   └── mapper.py
│       │   ├── media/
│       │   │   └── downloader.py
│       │
│       ├── presentation/
│       │   ├── telegram/
│       │   │   ├── routers/
│       │   │   │   ├── root.py          # /start, /cancel, catch-all подсказка
│       │   │   │   ├── registration.py  # мастер регистрации (private /start + group /register)
│       │   │   │   ├── settings.py      # тогглы, топики, обновление, диагностика, смена чата
│       │   │   │   └── destinations.py  # wizard'ы выбора destination (General + named)
│       │   │   ├── keyboards.py         # ReplyKeyboardMarkup-фабрики
│       │   │   ├── commands.py          # определения команд и их скоупов
│       │   │   ├── filters.py           # chat-type, directed-command, тексты кнопок
│       │   │   ├── middlewares.py       # OwnerOnlyMiddleware
│       │   │   └── states.py            # aiogram StatesGroup
│       │   └── vk/
│       │       ├── handlers.py          # VkUiDispatcher: Help/алиасы/ручная пересылка
│       │       ├── keyboards.py         # VK JSON-клавиатуры
│       │       └── states.py            # эфемерные per-user сессии (ключ from_id)
│       │
│       ├── infrastructure/
│       │   └── telegram/
│       │       └── command_menu.py      # CommandMenuSynchronizer (setMyCommands/deleteMyCommands)
│       │
│       └── bootstrap/
│           ├── container.py
│           ├── startup.py
│           └── shutdown.py
│
└── tests/
    ├── unit/
    │   ├── domain/
    │   └── application/
    ├── integration/
    │   ├── db/
    │   ├── telegram/
    │   └── vk/
    ├── acceptance/
    ├── e2e/
    ├── fixtures/
    └── conftest.py
```

## Почему не `src/vk/` + `src/telegram/`

Такое разделение кажется естественным только по названию платформ.

Но одна операция может одновременно использовать:

1. VK event;
2. VK API;
3. правила фильтрации;
4. БД;
5. Telegram Bot API;
6. Telegram topic;
7. fallback;
8. VK reaction.

При структуре `vk/` + `telegram/` непонятно, где должна жить сама операция пересылки.

В предложенной структуре:

- VK и Telegram UI находятся отдельно;
- SDK находятся отдельно;
- use case пересылки один;
- бизнес-правила не принадлежат ни VK, ни Telegram.

---

# 6. Runtime и жизненный цикл приложения

Корневой `main.py` должен быть тонким entrypoint.

Концептуально:

```text
main.py
  ↓
load Settings
  ↓
configure Loguru
  ↓
create DB engine/session factory
  ↓
startup checks
  ↓
create adapters
  ↓
create use cases
  ↓
register Telegram/VK handlers
  ↓
asyncio.TaskGroup
  ├── aiogram polling
  └── VKBottle polling
```

Telethon создаётся один раз и доступен как инфраструктурный adapter.

Используется `asyncio.TaskGroup`, потому что проект работает на Python 3.14.

Если критическая задача polling неожиданно завершается, приложение не должно молча продолжать работать наполовину.

## Graceful shutdown

При остановке:

1. прекращаются pollers;
2. закрывается aiogram HTTP session и общий aiohttp-сеанс загрузки медиа;
3. отключается Telethon;
4. закрываются HTTP clients;
5. выполняется `AsyncEngine.dispose()`;
6. Loguru завершает очередь логов.

---

# 7. Конфигурация через pydantic-settings

## Обязательное решение

В корне проекта существует:

`config.py`

Это canonical configuration module.

Он:

- содержит `Settings(BaseSettings)`;
- читает `.env`;
- валидирует environment;
- преобразует типы;
- реализует cross-field проверки;
- не содержит бизнес-состояние.

Примерные поля:

```text
TELEGRAM_BOT_TOKEN
OWNER_IDS

TELEGRAM_BOT_API_URL

TELEGRAM_API_ID
TELEGRAM_API_HASH
TELEGRAM_SESSION_PATH

TELEGRAM_MTPROXY_SERVER
TELEGRAM_MTPROXY_PORT
TELEGRAM_MTPROXY_SECRET

SOCKS5_PROXY_URL

VK_GROUP_TOKEN

DATABASE_URL

LOG_LEVEL
LOG_DIR
```

## Валидация

`OWNER_IDS` преобразуется в `frozenset[int]`.

MTProto Proxy проверяется как атомарный блок:

- либо заданы server + port + secret;
- либо не задано ничего;
- частичная конфигурация → `ValidationError` и приложение не запускается.

`TELEGRAM_BOT_API_URL` нормализуется.

Должен существовать helper:

```python
settings = get_settings()
```

с кэшированием одного immutable Settings instance на процесс.

## `.env`

`.env` содержит только секреты и инфраструктурные параметры.

Изменяемые настройки продукта не хранятся в `.env`.

---

# 8. Логирование через Loguru

## Корневой `logger.py`

В корне проекта обязательно существует:

`logger.py`

Это canonical logging setup проекта.

Файл строится по предоставленному reference и сохраняет его основные идеи:

- `LOG_DIR` / `LOG_FILE`;
- отдельные форматы console и file;
- `_InterceptHandler(logging.Handler)`;
- перенаправление стороннего `stdlib logging` в Loguru;
- возможность подавлять шумные library prefixes ниже заданного уровня;
- возможность подавлять отдельные известные log patterns;
- `logger.remove()` перед настройкой;
- `logger.configure(...)`;
- console sink в `stderr`;
- file sink;
- `enqueue=True` для file sink;
- rotation / retention / compression из `config.py`;
- `logging.basicConfig(..., force=True)` для установки intercept handler;
- итоговый startup-log с фактическими logging settings.

Reference используется как шаблон поведения, но не копируется буквально:

- старое имя `rwxrayservice.log` заменяется на `logs/app.log`;
- старые project-specific module prefixes и suppression patterns не переносятся;
- набор шумных библиотек определяется уже для VK Topic Bridge;
- формат extra/context определяется потребностями этого проекта.

## Безопасность traceback

В production нельзя допускать утечки токенов, `.env`, session и других секретов через расширенную диагностику.

Поэтому production-конфигурация Loguru должна использовать безопасную диагностику исключений (`diagnose=False` либо эквивалентную безопасную политику).

`backtrace=True` допустим, если он не приводит к сериализации чувствительных locals.

## Контекст

Для диагностически важных операций использовать `logger.bind()`.

Примеры полей:

```text
component=vk
component=telegram
component=mtproto
component=db

vk_peer_id=...
vk_message_id=...
telegram_chat_id=...
telegram_topic_id=...
use_case=...
```

Не логировать:

- Telegram Bot Token;
- Telegram API Hash;
- Telethon session contents;
- VK token;
- MTProto Proxy secret;
- пароли и authorization codes.

## Сторонний `logging`

Aiogram, VKBottle, Telethon, SQLAlchemy, Alembic и другие библиотеки могут писать через стандартный `logging`.

Их записи должны попадать в единый Loguru pipeline через intercept handler, без monkey-patch сторонних библиотек.

## Два независимых файла логов

Используются два разных файла с разными владельцами:

```text
logs/app.log   ← Loguru
logs/pm2.log   ← PM2
```

### `logs/app.log`

Основной application log.

Пишется напрямую Loguru и ротируется самим Loguru по настройкам из `config.py`.

### `logs/pm2.log`

Process-level log.

PM2 захватывает stdout/stderr процесса в один PM2-managed файл.

Так как console sink Loguru пишет в `stderr`, значимая часть application logs будет присутствовать и здесь. Это намеренная копия process console output.

Ротацией `logs/pm2.log` занимается установленный модуль `pm2-logrotate`.

### Запрет

PM2 и Loguru никогда не должны писать в один и тот же файл.

Нельзя:

```text
Loguru -> logs/app.log
PM2    -> logs/app.log
```

Иначе два независимых writer/rotation mechanism будут конкурировать.

## PM2 timestamps

PM2 не должен добавлять второй timestamp поверх форматированного Loguru console output.

Если `logger.py` уже формирует timestamp, `time` / `log_date_format` PM2 для app console log не включаются без отдельной причины.

# 9. База данных и ORM

Используется:

- SQLAlchemy 2.x;
- declarative ORM;
- `Mapped[...]`;
- `mapped_column(...)`;
- `AsyncEngine`;
- `async_sessionmaker`;
- `AsyncSession`;
- SQLite через `sqlite+aiosqlite`.

Repository implementations находятся в `infrastructure/db/repositories`.

Use cases не получают `AsyncSession` напрямую.

## SQLite pragmas

При создании соединения:

```text
PRAGMA foreign_keys = ON
PRAGMA journal_mode = WAL
PRAGMA busy_timeout = 5000
```

WAL снижает вероятность ненужных блокировок при параллельных async-задачах.

## Транзакции

Один application use case — одна контролируемая transaction boundary там, где меняется БД.

Не делать `commit()` внутри каждого repository method.

---

# 10. Миграции Alembic

Миграции обязательны с первой версии БД.

Запрещено использовать `Base.metadata.create_all()` как production-механизм обновления схемы.

Структура:

```text
alembic.ini
migrations/
  env.py
  versions/
```

Alembic использует metadata SQLAlchemy models.

## Создание миграции

```bash
make migration m="create bridge settings"
```

Эквивалент:

```bash
uv run alembic revision --autogenerate -m "create bridge settings"
```

Каждая autogenerated migration обязательно просматривается человеком / review-agent до применения.

## Применение

```bash
make migrate
```

Эквивалент:

```bash
uv run alembic upgrade head
```

## Production startup

`scripts/start.sh`:

1. выполняет `alembic upgrade head`;
2. если миграция неуспешна — завершается;
3. только после успеха запускает `main.py`.

Таким образом приложение не начинает polling на неизвестной схеме.

## Downgrade

Поддерживается технически:

```bash
make downgrade
```

Но production rollback БД не должен выполняться автоматически PM2.

---

# 11. Модель данных

Минимальный набор таблиц.

## `bridge_settings`

Singleton row.

Пример:

```text
id = 1
telegram_chat_id nullable
telegram_chat_title nullable

auto_forward_all bool default true
auto_forward_hashtags bool default true
auto_forward_wall bool default true

vk_messages_topic_id nullable
vk_wall_topic_id nullable

created_at
updated_at
```

## `telegram_topics`

```text
id
telegram_chat_id
topic_id
title
is_general
is_active
last_seen_at
```

Ограничение уникальности:

```text
UNIQUE(telegram_chat_id, topic_id)
```

Удалённый Telegram topic можно сначала отмечать inactive, чтобы сохранить диагностику.

Не предполагать в domain, что General topic всегда имеет конкретный числовой ID.

## `vk_topic_aliases`

```text
id
vk_user_id
topic_id
alias
alias_normalized
created_at
updated_at
```

Ограничения:

```text
UNIQUE(vk_user_id, alias_normalized)
UNIQUE(vk_user_id, topic_id)
```

Это соответствует правилу: у одного пользователя один текущий alias на topic.

## `delivery_records`

Техническая таблица идемпотентности.

```text
id
source_type
source_key
status
telegram_chat_id
telegram_topic_id nullable
telegram_message_ids nullable/json
created_at
completed_at nullable
```

Ограничение:

```text
UNIQUE(source_type, source_key)
```

---

# 12. Telegram Bot API

Используется aiogram.

Aiogram отвечает за:

- admin bot;
- `/start`;
- registration command;
- keyboards;
- owner middleware;
- FSM;
- публикацию VK-контента;
- уведомления owners.

## Command scopes

Подсказки команд синхронизирует `CommandMenuSynchronizer` (`infrastructure/telegram/command_menu.py`):

- all-users скоупы (`Default`, `AllPrivateChats`, `AllGroupChats`) очищаются при старте;
- приватный скоуп каждого owner из `OWNER_IDS` настраивается при старте;
- временный `BotCommandScopeChatMember` для пары owner/группа ставится при входе в режим регистрации и очищается после успеха или отмены.

Скоупы — только UX: авторизация выполняется `OwnerOnlyMiddleware` и хендлерами независимо. Ошибка синхронизации меню логируется и не прерывает старт (best-effort, после фатальных проверок).

## Custom Bot API

Если задан `TELEGRAM_BOT_API_URL`, создаётся `TelegramAPIServer.from_base(...)`.

## Proxy

Если Bot API endpoint loopback:

- `localhost`;
- `127.0.0.1`;
- `::1`;

то `AiohttpSession` создаётся без SOCKS5.

Если endpoint remote и `SOCKS5_PROXY_URL` задан — proxy применяется.

Эта логика находится только в `bot_api_factory.py`.

---

# 13. Telethon и MTProto

Telethon используется только для возможностей, требующих пользовательского MTProto-клиента.

Основное назначение проекта:

- получить / обновить Telegram topics;
- проверить доступ пользовательской session к Telegram chat.

Telethon не публикует VK-контент.

## Proxy resolver

Отдельная функция / объект возвращает настройки transport.

Приоритет строго:

```text
MTProto Proxy
    ↓
SOCKS5
    ↓
direct
```

Если MTProto Proxy задан частично — startup error.

Для MTProto Proxy используется соответствующий MTProxy connection class Telethon.

Для SOCKS5 — proxy config через python-socks.

## Session

Persistent session:

```text
runtime/telethon/
```

Папка полностью исключена из Git.

---

# 14. VK

Используется VKBottle.

VKBottle отвечает за:

- VK Long Poll;
- входящие сообщения;
- события стены;
- пользовательский VK UI;
- VK API.

Presentation handler не должен сам реализовывать пересылку.

Правильно:

```text
VKBottle event
  ↓
mapper
  ↓
application DTO
  ↓
use case
```

Вызовы VK API, необходимые use case, выполняются через port.

## Fan-out raw-событий

Единый raw Long Poll consumer классифицирует событие до любого guard'а:

```text
wall_post_new                  → pipeline стены (ForwardWallPost)
peer_id < 2_000_000_000        → VK UI (VkUiDispatcher: Help/алиасы/ручная пересылка)
peer_id >= 2_000_000_000       → автоматическая пересылка сообщений (scoped conversation guard)
```

Guard первого conversation-peer применяется только к автоматическому conversation-потоку: DM разных пользователей не блокируют друг друга и не занимают guard-слот. Переменная `VK_SOURCE_PEER_ID` не используется.

## Persistent cursor

Long Poll работает в персистентном режиме: `RuntimePathBotPolling` (наследник `BotPolling`) с `skip_old_events=False` и курсором в контролируемом runtime-пути `runtime/vk_cursor/` (gitignored). События `failed=1`/`failed=3` трактуются как history gap: WARNING в лог + однократное уведомление owners; точное число пропущенных событий не заявляется, ручной реплей не выполняется. Курсор не хранится в SQLite: атомарности между VK-курсором и Telegram-публикацией не существует.

---

# 15. FSM

## Telegram

Aiogram FSM.

Для данного single-process проекта достаточно in-memory storage.

FSM-стратегия — `FSMStrategy.GLOBAL_USER`: мастер регистрации живёт поперёк чатов (private `/start` открывает режим, group `/register` его завершает), поэтому ключ состояния привязан к user_id, а не к chat_id.

FSM — временное UI-состояние, а не бизнес-конфигурация.

После рестарта незавершённый wizard может быть отменён и начат заново.

Scenes/Wizard-фреймворк не используется: достаточно обычных `StatesGroup`.

## VK

Для ручной пересылки и aliases используется собственный небольшой session/state abstraction (`presentation/vk/states.py`).

Ключ состояния — `from_id` (VK-пользователь), целевой чат/payload хранится в сессии.

Принцип тот же:

- pending message и шаг wizard — ephemeral;
- aliases и настройки — persistent в SQLite.

Никакая незавершённая FSM-операция не должна частично менять БД.

## Readiness

Линейный `InMemoryReadinessGate` (`CORE_READY`→`CHAT_REGISTERED`→`TOPICS_READY`→`DESTINATION_CONFIRMED`→`FORWARDING_ENABLED`) сохранён для стартовых фаз и registration/selection flows, но решения о пересылке принимаются по feature-specific readiness (`application/readiness_features.py`): `messages_auto_ready`, `wall_auto_ready`, `manual_forwarding_ready`. Ненастроенный destination — нормальное состояние продукта (silent no-op / понятная ошибка VK), а не операционный сбой.

---

# 16. Пересылка и обработка вложений

Центральный use case работает с собственной нормализованной моделью:

```text
SourceMessage
Author
Attachment[]
Destination
PublicationResult
```

Типы вложений:

```text
Photo
Video
Document
UnsupportedAttachment
```

Каждое вложение обрабатывается независимо.

Ошибка вложения превращается в warning item, а не exception всей публикации.

Лимит 50 МБ — domain/product rule, а не значение `.env`.

---

# 17. Идемпотентность

Даже если один внешний event будет доставлен повторно, мост не должен создавать случайные дубликаты.

Для автоматических операций формируется `source_key`.

Примеры:

```text
vk-message:{peer_id}:{conversation_message_id}
vk-wall:{owner_id}:{post_id}
```

Перед публикацией use case регистрирует delivery attempt.

Повторно успешно обработанный `source_key` не публикуется.

Это не заменяет правило:

> `@all` + hashtag в одном сообщении → одна публикация.

Оно защищает уже на уровне повторной доставки внешнего события.

Ручная пользовательская пересылка не обязана дедуплицироваться по тому же ключу: повторное ручное действие считается новым намеренным действием.

---

# 18. Обработка ошибок

Ошибки разделяются.

## Domain / validation

Например:

```text
InvalidAlias
TopicNotFound
UnsupportedAttachment
```

## Recoverable infrastructure

Например:

```text
AttachmentDownloadFailed
TargetTopicUnavailable
VKProfileLookupFailed
```

Use case принимает решение о fallback / partial success.

## Fatal startup

Например:

```text
invalid Settings
MTProto session missing
MTProto authentication invalid
Bot API unreachable
DB migration failed
DB unavailable
```

При fatal startup polling не запускается.

Presentation слой преобразует пользовательские ошибки в понятный текст.

Никакой raw traceback пользователю не показывается.

---

# 19. Автотесты

Тестовая пирамида проекта.

## 19.1 Unit tests

Самые многочисленные.

Без сети и реальной SQLite.

Проверяют:

- `@all`;
- hashtags;
- одновременное совпадение;
- alias validation;
- destination selection;
- General fallback decision;
- attachment 50 MB rule;
- partial attachment success;
- publication composition;
- reaction only after successful Telegram publication;
- reset settings;
- owner checks на уровне application policy, где применимо;
- proxy resolution logic.

Ports заменяются fakes/stubs.

## 19.2 Application tests

Тестируются use cases целиком с fake ports.

Пример:

```text
ForwardVkMessage
  fake settings repository
  fake VK gateway
  fake Telegram publisher
  fake delivery repository
```

Проверяется не устройство SDK, а бизнес-сценарий.

## 19.3 DB integration tests

Используется отдельная временная SQLite БД.

Проверяются:

- SQLAlchemy mappings;
- repository queries;
- unique constraints aliases;
- transactions;
- rollback;
- migration `base -> head`;
- текущая schema revision.

Не использовать обычный `:memory:` DB как единственный integration mode для конкурентного async-кода.

## 19.4 Adapter tests

Telegram / VK adapters тестируются без реальной production-сети.

Проверяются:

- mapping SDK model → DTO;
- mapping DTO → SDK calls;
- local Bot API proxy decision;
- MTProto/SOCKS/direct resolver;
- правильные arguments Bot API.

## 19.5 Acceptance tests

Отдельная папка:

```text
tests/acceptance/
```

Тесты именуются по User Story / Acceptance Criteria.

Пример:

```text
test_us07_ac073_all_and_hashtag_create_one_publication
test_us22_ac221_missing_topic_uses_general
```

Acceptance tests используют реальные application use cases + test doubles внешних API.

## 19.6 E2E smoke

`tests/e2e/` не запускаются обычным `make test`.

Они требуют реальные test credentials.

Запускаются явно:

```bash
make test-e2e
```

Минимум:

- Bot API `getMe`;
- Telethon authorized session + `get_me`;
- получение topics test chat;
- VK API identity / group access.

## Coverage

Coverage — guardrail, а не цель.

Начальный gate:

```text
--cov-fail-under=80
```

Критические domain/application правила должны иметь тесты независимо от общего процента.

---

# 20. Статический анализ и качество

## Ruff

Ruff отвечает за:

```text
format
lint
import sorting
common bug patterns
unused imports / variables
```

## BasedPyright

Используется именно **BasedPyright**, не Pyright.

Конфигурация хранится в `pyproject.toml`.

На bootstrap-этапе типизация должна быть достаточно строгой, чтобы ловить реальные ошибки, но не должна блокировать проект из-за dynamic typing сторонних SDK.

После появления `domain` и `application` для этих слоёв допускается более строгий режим, чем для adapter-кода.

Команда:

```bash
uv run --locked basedpyright
```

Главная quality gate:

```bash
make check
```

Она должна выполнять:

```text
uv lock --check
ruff format --check
ruff check
basedpyright
pytest
```

# 21. Makefile

Текущий bootstrap Makefile уже содержит правильную базовую поверхность:

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

Эти команды сохраняются.

`typecheck` использует BasedPyright:

```makefile
typecheck:
	uv run --locked basedpyright
```

`check` остаётся агрегирующей проверкой без изменения файлов:

```makefile
check: lock-check format-check lint typecheck test
```

По мере реализации проекта отдельными утверждёнными планами добавляются product/infrastructure targets, например:

```text
run
auth
migration
migrate
downgrade
db-current
test-unit
test-integration
test-acceptance
test-e2e
pm2-start
pm2-reload
pm2-stop
pm2-logs
```

Не добавлять Make-target заранее, если вызываемый им runtime/tooling ещё не существует: `make check` и bootstrap-команды всегда должны оставаться зелёными.

# 22. PM2

В корне проекта на deployment-этапе создаётся:

`ecosystem.config.cjs`

Приложение запускается одним процессом в `fork` mode через `scripts/start.sh`.

Концептуальная конфигурация:

```js
module.exports = {
  apps: [
    {
      name: "vk-topic-bridge",
      cwd: __dirname,
      script: "./scripts/start.sh",
      interpreter: "none",

      autorestart: true,
      watch: false,
      restart_delay: 5000,
      max_restarts: 10,
      kill_timeout: 15000,

      log_file: "./logs/pm2.log",
      time: false,

      env: {
        PYTHONUNBUFFERED: "1",
      },
    },
  ],
};
```

`log_file` объединяет stdout и stderr приложения в один PM2-managed файл.

Loguru при этом отдельно пишет в `logs/app.log`.

PID-файл процесса PM2 хранится в каталоге `pid/` (например, `pid/vk-topic-bridge.pid`). Каталог присутствует в Git через `pid/.gitkeep`; всё остальное содержимое каталога игнорируется `.gitignore`.

## `scripts/start.sh`

Production entrypoint:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

uv run --locked alembic upgrade head
exec uv run --locked python main.py
```

Миграции выполняются до запуска pollers.

## `pm2-logrotate`

На сервере модуль уже установлен, поэтому проект:

- не устанавливает его автоматически;
- не добавляет его в Python/Node dependencies;
- на deployment-проверке убеждается, что модуль доступен;
- проверяет его текущую конфигурацию через `pm2 conf`;
- при необходимости документирует команды настройки `pm2 set pm2-logrotate:<param> <value>`.

Поддерживаемые параметры, которые необходимо учитывать:

```text
max_size
retain
compress
dateFormat
workerInterval
rotateInterval
rotateModule
TZ
```

Базовая разумная policy для небольшого сервиса:

```text
max_size      = 20M
retain        = 14
compress      = true
workerInterval= 30
rotateInterval= 0 0 * * *
rotateModule  = true
```

Это baseline, а не жёсткая бизнес-конфигурация приложения. Если на сервере уже установлена сознательно выбранная policy, deployment не должен молча её перезаписывать.

## Автозапуск

После первого deployment:

```bash
pm2 start ecosystem.config.cjs
pm2 save
pm2 startup
```

Команда, которую выведет `pm2 startup`, выполняется оператором на конкретном сервере.

После этого выполняется `pm2 save`.

# 23. Git ignore и runtime-данные

Обязательно игнорировать:

```gitignore
.env

.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
.mypy_cache/
.pyright/

.idea/

data/*.db
data/*.sqlite
data/*.sqlite3

runtime/telethon/*
!runtime/telethon/.gitkeep

runtime/vk_cursor/
runtime/media/

logs/*
!logs/.gitkeep

pid/*
!pid/.gitkeep

coverage.xml
.coverage
htmlcov/
```

Telethon session никогда не должна попадать в Git.

`.env.example` должен содержать все ключи без реальных секретов.

---

# 24. Что намеренно не используется

## Не нужен FastAPI

У проекта нет собственного HTTP API.

VK Long Poll и Telegram polling достаточно.

## Не нужен Redis

Один процесс, одна SQLite БД, нет distributed state.

## Не нужны Celery / RabbitMQ / Kafka

Нагрузка и topology этого проекта не оправдывают message broker.

## Не нужен DI framework

Ручной composition root проще, прозрачнее и достаточно масштабируем.

## Не нужен full DDD

Проект мал.

DDD используется там, где помогает выразить правила, но не ради количества файлов и классов.

## Не нужны два отдельных приложения VK и Telegram

Это один bounded problem и один deployable unit.

---

# 25. Архитектурные критерии приёмки

## Структура

- [ ] Python package называется `vk_topic_bridge`;
- [ ] используется `src/` layout;
- [ ] VK и Telegram не являются двумя независимыми приложениями;
- [ ] Telegram/VK SDK-код изолирован в adapters/presentation;
- [ ] application use cases общие и не принадлежат конкретной платформе;
- [ ] `domain` и `application` не импортируют aiogram, VKBottle, Telethon и SQLAlchemy.

## Dependencies / tooling

- [ ] Python version — 3.14;
- [ ] package/dependency manager — `uv`;
- [ ] runtime и dev dependencies разделены;
- [ ] declared все direct dependencies, на которые проект опирается напрямую;
- [ ] SQLAlchemy установлен с `asyncio` extra;
- [ ] SOCKS dependencies объявлены явно;
- [ ] `uv.lock` committed;
- [ ] `uv lock --check` проходит;
- [ ] `uv sync --all-groups` проходит с чистого окружения;
- [ ] ключевые runtime packages импортируются под Python 3.14;
- [ ] используется Ruff;
- [ ] используется **BasedPyright**, не Pyright;
- [ ] `make check` выполняет lock-check + format-check + lint + BasedPyright + pytest.

## Configuration

- [ ] в корне существует `config.py`;
- [ ] `.env` читается через `pydantic-settings`;
- [ ] `OWNER_IDS` валидируется и преобразуется в typed collection;
- [ ] partial MTProto Proxy config блокирует startup;
- [ ] `.env` не содержит изменяемое business state;
- [ ] `.env.example` перечисляет все обязательные/опциональные keys без секретов.

## Logging

- [ ] в корне существует `logger.py`;
- [ ] его архитектура основана на предоставленном reference logger;
- [ ] настроены console + file Loguru sinks;
- [ ] основной application file — `logs/app.log`;
- [ ] stdlib logging сторонних библиотек перехватывается в Loguru;
- [ ] есть configurable filtering noisy library logs;
- [ ] rotation / retention / compression берутся из settings;
- [ ] file sink использует `enqueue=True`;
- [ ] production diagnostics не раскрывает locals/secrets;
- [ ] токены/session/proxy secret не логируются;
- [ ] PM2 пишет отдельно в `logs/pm2.log`;
- [ ] PM2 и Loguru никогда не ротируют один и тот же файл;
- [ ] PM2 не добавляет ненужный второй timestamp поверх Loguru console format.

## Database

- [ ] SQLite + SQLAlchemy AsyncIO + aiosqlite;
- [ ] схема управляется Alembic с первой версии;
- [ ] production не использует `metadata.create_all()` как migration strategy;
- [ ] production startup выполняет `alembic upgrade head` до polling;
- [ ] DB repositories скрыты за application ports;
- [ ] transaction boundaries контролируются use cases / unit of work boundary, а не случайными `commit()` внутри каждого repository method.

## Telegram / VK

- [ ] aiogram используется для Telegram Bot API;
- [ ] VKBottle используется для VK bot / events;
- [ ] Telethon используется только за infrastructure adapter;
- [ ] есть отдельный `authorize_telegram.py` в корне;
- [ ] Telethon session хранится вне Git;
- [ ] Telethon proxy priority: MTProto Proxy → SOCKS5 → direct;
- [ ] local Bot API не проксируется через SOCKS5;
- [ ] Bot API proxy logic не влияет на Telethon proxy logic.

## Tests

- [ ] существуют unit tests;
- [ ] существуют application/use-case tests;
- [ ] существуют DB integration tests;
- [ ] существуют adapter tests;
- [ ] существуют acceptance tests, сопоставимые с US/AC;
- [ ] E2E smoke tests отделены и запускаются явно;
- [ ] повторно доставленное автоматическое VK-событие не создаёт duplicate publication.

## PM2 / deployment

- [ ] существует `ecosystem.config.cjs`;
- [ ] существует migration-aware `scripts/start.sh`;
- [ ] PM2 запускает один fork-process;
- [ ] configured `autorestart`;
- [ ] configured graceful `kill_timeout`;
- [ ] `watch=false`;
- [ ] PM2 app log — отдельный `logs/pm2.log`;
- [ ] установленный `pm2-logrotate` проверяется на deployment;
- [ ] deployment не перезаписывает глобальную pm2-logrotate policy без явной причины;
- [ ] `pm2 save` / `pm2 startup` задокументированы;
- [ ] graceful shutdown закрывает pollers, HTTP sessions, Telethon и DB engine.

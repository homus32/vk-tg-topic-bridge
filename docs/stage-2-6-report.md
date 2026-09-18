# Stage 2–6 — Отчёт о реализации vertical slice

> Отчёт составлен по итогам исполнения плана `.omo/plans/stage-2-6-vertical-slice.md`
> и intent `.omo/drafts/stage-2-6-vertical-slice.md`, на основе evidence-каталога
> `.omo/evidence/stage-2-6-vertical-slice/`, истории коммитов, notebook'а исполнителя
> и ручных прогонов владельца.
>
> Статус на дату отчёта (2026-09-18): текстовый vertical slice живьём подтверждён владельцем;
> медиа и стена не реализованы (deferred Stage 9); evidence ручных гейтов заполнены,
> `make test-e2e` — 4 passed; независимый review (F5) решено не выполнять.

---

## 1. Краткое резюме (мнение)

Stage 2–6 выполнены как задумано — приложение реально запускается, подключается к Telegram Bot API,
Telethon и VK Long Poll, принимает живое VK-событие, публикует его в выбранную Telegram-тему,
ставит 👍 в VK и не создаёт дублей при повторной доставке события.

Главный результат: владелец вручную прошёл цепочку
`/register → /topics → /set_topic 2 → VK-сообщение с @all/#хештег → публикация в теме «Важное» → 👍`,
и подтвердил, что она работает.

Главная проблема цикла — низкое качество первого ручного прогона. Три класса дефектов
(HTML parse_mode, выбор General, форма VK payload) не ловились тестами, потому что тесты
использовали неправильные fixtures и не проверяли реальные контракты Bot API/VK.
Это системный урок: фейковые тесты без live-гейта давали ложный GREEN.

Оценка готовности Stage 2–6: **~98%**. Осталось: прогон новых живым владельцем после
любых будущих изменений VK-слоя и заполнение evidence при новых ручных проверках.
Fresh-review (F5) признан владельцем избыточным и не выполняется.

---

## 2. Что сделано (по workstream'ам C1–C6 и этапам roadmap)

| Roadmap stage | Содержание | Статус | Ключевые артефакты |
|---|---|---|---|
| **Этап 2** — Config, logger, lifecycle | `config.py` (immutable Settings, atomic MTProxy, cached `get_settings`), `logger.py` (Loguru + stdlib interception), startup/shutdown, composition root | ✅ Готово | `config.py`, `logger.py`, `main.py`, `bootstrap/{startup,shutdown,container}.py` |
| **Этап 3** — Database и migrations | SQLAlchemy AsyncIO + aiosqlite, PRAGMA (WAL, foreign_keys, busy_timeout), 4 таблицы, Alembic `0001_initial`, repositories, UnitOfWork, CAS-доставка | ✅ Готово | `infrastructure/db/**`, `migrations/versions/0001_initial.py` |
| **Этап 4** — Telegram infrastructure | aiogram Bot + custom Bot API URL + независимая SOCKS5 policy, Telethon (MTProxy→SOCKS5→direct), persistent session, `authorize_telegram.py`, topics через `GetForumTopicsRequest` | ✅ Готово | `infrastructure/telegram/**`, `authorize_telegram.py` |
| **Этап 5** — VK infrastructure | VKBottle Long Poll, identity из токена (`groups.getById({})`), mapper (`is_cropped`, author, attachments, reaction) | ✅ Готово* | `infrastructure/vk/**`, `bootstrap/vk_consumer.py` |
| **Этап 6** — Forwarding core | `@all`/hashtag → одна публикация, автор-гиперссылка, `#извк`/`#извкважно`, fail-closed delivery ledger, 👍 только после подтверждённой публикации | ✅ Готово | `domain/policies/forwarding_policy.py`, `application/forwarding/forward_message.py` |
| Временный провижининг (pre-Stage 7) | `/start`, `/register`, темы через Telethon, `/topics`, `/set_topic` | ✅ Готово, с TODO(stage-7) | `presentation/telegram/routers/**`, `application/admin/**` |

\* Wall: распознавание событий заявлено в Stage 5, но фактически реализованы только
`SourceType.VK_WALL` и поля настроек; нормализации `wall_post_new` в коде нет (см. §8).

Все 22 пункта плана `stage-2-6-vertical-slice.md` отмечены `[x]` (коммит `aa4a39f`).

### Ключевые архитектурные решения (реализовано)

- **Contract-first**: Settings/DTO/ports/UoW/схема/state machine заморожены до параллельных адаптеров.
- **Fail-closed delivery**: `reserved → send_started → published`, ambiguous — терминальный статус,
  авто-повтор после `send_started` запрещён; CAS-claim с `claim_token`; 👍 никогда не вызывает Telegram republish.
- **Слои**: `domain`/`application` не импортируют SDK/ORM; SDK-модели конвертируются на границе
  (`FirstPeerGuard`, mapper, `normalize_event`).
- **Lifecycle**: `asyncio.TaskGroup` с двумя critical pollers; неожиданный выход → отмена sibling,
  координированный shutdown, non-zero exit; SIGTERM — не ошибка.
- **Readiness-гейт**: `CORE_READY → CHAT_REGISTERED → TOPICS_READY → DESTINATION_CONFIRMED → FORWARDING_ENABLED`;
  VK-события до последнего состояния consume-and-skip с логом.
- **Идемпотентность**: `source_key = "{group_id}:{peer_id}:{conversation_message_id}"`,
  `UNIQUE(source_type, source_key)`.

---

## 3. Дерево файлов проекта (src + ключевые файлы в корне)

> Скрытые директории, `node_modules`, тесты и runtime-артефакты исключены по запросу.
> Тесты (`tests/**`, ~409 тестовых функций) в дерево не включены.

```text
vk-topic-bridge/
├── AGENTS.md
├── Makefile
├── alembic.ini
├── authorize_telegram.py
├── config.py
├── logger.py
├── main.py
├── pyproject.toml
├── uv.lock
├── .python-version
├── .gitignore
├── .env.example
├── docs/
│   ├── 01-product-spec.md
│   ├── 02-user-stories.md
│   ├── 03-technical-requirements.md
│   ├── 04-fsm-and-ui.md
│   ├── 05-architecture-and-engineering.md
│   ├── 06-full-implementation-roadmap.md
│   ├── 07-bootstrap-intent-draft.md
│   ├── AGENTS.md
│   └── stage-2-6-report.md          ← этот отчёт
├── migrations/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_initial.py
├── data/
│   └── .gitkeep
├── logs/
│   └── .gitkeep
├── pid/
│   └── .gitkeep
├── scripts/
│   └── .gitkeep
├── runtime/
│   └── telethon/                    (runtime, gitignored)
└── src/
    └── vk_topic_bridge/
        ├── __init__.py
        ├── __main__.py
        ├── AGENTS.md
        ├── domain/
        │   ├── __init__.py
        │   ├── enums.py
        │   ├── errors.py
        │   ├── value_objects.py
        │   └── policies/
        │       ├── __init__.py
        │       ├── alias_policy.py
        │       ├── attachment_policy.py
        │       ├── delivery_policy.py
        │       └── forwarding_policy.py
        ├── application/
        │   ├── __init__.py
        │   ├── errors.py
        │   ├── readiness.py
        │   ├── admin/
        │   │   ├── __init__.py
        │   │   ├── refresh_topics.py
        │   │   ├── register_chat.py
        │   │   ├── select_destination.py
        │   │   └── toggle_settings.py
        │   ├── dto/
        │   │   ├── __init__.py
        │   │   ├── delivery.py
        │   │   ├── infrastructure.py
        │   │   ├── readiness.py
        │   │   └── settings.py
        │   ├── forwarding/
        │   │   ├── __init__.py
        │   │   └── forward_message.py
        │   └── ports/
        │       ├── __init__.py
        │       ├── readiness.py
        │       ├── repositories.py
        │       ├── telegram.py
        │       ├── unit_of_work.py
        │       └── vk.py
        ├── infrastructure/
        │   ├── __init__.py
        │   ├── db/
        │   │   ├── __init__.py
        │   │   ├── base.py
        │   │   ├── engine.py
        │   │   ├── models.py
        │   │   └── repositories/
        │   │       ├── __init__.py
        │   │       ├── bridge_settings.py
        │   │       ├── delivery.py
        │   │       ├── telegram_topics.py
        │   │       ├── unit_of_work.py
        │   │       └── vk_aliases.py
        │   ├── telegram/
        │   │   ├── __init__.py
        │   │   ├── bot_api_factory.py
        │   │   ├── mtproto.py
        │   │   ├── proxy.py
        │   │   └── publisher.py
        │   └── vk/
        │       ├── __init__.py
        │       ├── api.py
        │       └── mapper.py
        ├── presentation/
        │   ├── __init__.py
        │   └── telegram/
        │       ├── __init__.py
        │       ├── keyboards.py
        │       ├── middlewares.py
        │       └── routers/
        │           ├── __init__.py
        │           ├── destination.py
        │           ├── register.py
        │           └── start.py
        └── bootstrap/
            ├── __init__.py
            ├── container.py
            ├── shutdown.py
            ├── startup.py
            └── vk_consumer.py
```

---

## 4. Полный файл `.env.example`

```dotenv
# Telegram Bot API
TELEGRAM_BOT_TOKEN=1234567890:AAInvalidTelegramBotToken_DoNotUse
OWNER_IDS=123456789
TELEGRAM_BOT_API_URL=http://127.0.0.1:8081

# Telegram MTProto
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=0123456789abcdef0123456789abcdef
TELEGRAM_SESSION_PATH=runtime/telethon/vk_topic_bridge.session

# MTProto Proxy
TELEGRAM_MTPROXY_SERVER=127.0.0.1
TELEGRAM_MTPROXY_PORT=1443
TELEGRAM_MTPROXY_SECRET=dd00000000000000000000000000000000

# SOCKS
SOCKS5_PROXY_URL=socks5://127.0.0.1:10809

# VK
VK_GROUP_TOKEN=vk1.a.invalid_test_token_do_not_use

# Database
DATABASE_URL=sqlite+aiosqlite:///data/vk_topic_bridge.db

# Logging
LOG_LEVEL=INFO
LOG_LEVEL_LIBS=WARNING
LOG_DIR=logs
LOG_ROTATION="10 MB"
LOG_RETENTION="14 days"
LOG_COMPRESSION=zip
```

Примечания:

- `TELEGRAM_SESSION_PATH` и `DATABASE_URL` имеют дефолты в `config.py`
  (`runtime/telethon/vk_topic_bridge.session`, `data/vk_topic_bridge.db`),
  поэтому в `.env` их можно не задавать.
- `VK_GROUP_ID` — опциональный override, в `.env.example` отсутствует намеренно:
  identity выводится из токена.
- MTProxy-блок атомарный: частичная конфигурация → `ValidationError`.
- `TELEGRAM_BOT_API_URL` отсутствует → официальный Bot API; loopback-адрес → SOCKS5 не применяется.

---

## 5. Что было не так (проблемы цикла)

### 5.1 Баг `parse_mode=HTML` (найден владельцем, коммит `e828bd3`)

`create_bot()` задавал `DefaultBotProperties(parse_mode=ParseMode.HTML)` глобально, из-за чего
ответы владельцу уходили в HTML-режиме. Команда `/topics` падала с
`TelegramBadRequest: Unsupported start tag "номер" at byte offset 246`: литерал `<номер>`
интерпретировался как HTML-тег.

- Evidence: `red-html-parse-mode.txt`, `parse-mode-green.txt` (65 passed).
- Фикс: глобальный parse_mode убран; HTML применяется **только** для VK-публикаций
  (`publisher.publish` → `parse_mode=ParseMode.HTML`), ответы владельцу — plain text.
- Урок: любой будущий handler, вставляющий пользовательский текст, обязан либо не включать
  HTML, либо экранировать его. Это прямой риск для Stage 7 (Admin UI).

### 5.2 Баг «General как тема назначения» (найден владельцем, коммит `e828bd3`)

General адресуется отсутствием `message_thread_id`; в схеме `NULL` означает «не настроено».
Если бы владелец выбрал General, `set_messages_topic(None)` записал бы `NULL`, и после
перезапуска forwarding тихо остался бы выключенным, хотя тестовый send прошёл.

- Evidence: `red-general-topic.txt`, `red-destination.txt`, `destination-green.txt`.
- Фикс: `SelectDestination` отклоняет `topic_id=None`, `/topics` помечает General как
  «служебная тема, не выбирается», `/set_topic` отвечает пользователю объяснением.
- Это осознанное отклонение от примера в draft (`1. General (id: ...)`), см. §7.

### 5.3 Баг формы VK payload `message_new` (найден при ручном E2E, исправлен)

Живой VKBottle Long Poll присылает сообщение вложенно:

```text
update["object"]["message"]["peer_id"]
update["object"]["message"]["from_id"]
update["object"]["message"]["conversation_message_id"]
```

А consumer читал `update["object"]["peer_id"]` напрямую, поэтому **все** живые события
отбрасывались с warning `vk update has no integer peer_id for group ...` — до forwarding,
без публикации и без реакции. Именно это владелец видел как «в телеграме пустота, реакции нет».

- Root cause: и consumer, и fixtures тестов использовали неверную (плоскую) форму payload;
  draft (`stage-2-6-vertical-slice.md:146`) прямо указывал `object.message.*`.
- Evidence: `red-vk-payload.txt`, `red-vk-forwarding-shape.txt`,
  `green-vk-live-payload.txt` (3 passed), `green-vk-payload-chain.txt` (33 passed).
- Фикс: общий extractor `extract_message_payload()` в `infrastructure/vk/mapper.py`,
  используется и consumer'ом, и gateway (`normalize_event`); поддержаны обе формы
  (вложенная и плоская) для совместимости с тестовыми doubles.
- Тесты: `test_normalize_event_maps_nested_message_object`,
  `test_nested_trigger_publishes_and_reacts[#хештег/@all]`.
- Урок: fixtures должны повторять реальный контракт внешней системы, иначе тесты дают
  ложный GREEN; live-гейт обязателен.

### 5.4 Замечания независимого review (round 1, `7b65c76`)

Ревьюер (oracle, session `ses_f4ed3fdddffec6QIq34Kb8d1fW`) вернул `REQUEST CHANGES`: 6 находок.
Все 6 признаны реальными и исправлены, 1 находка отклонена как противоречащая frozen draft
(publication probe на `/register` создал бы спам в чате до выбора темы — real-send proof
намеренно на TG-TOPIC):

1. потерянный CAS `mark_published` всё ещё ставил 👍 — P0, исправлено;
2. `ConnectionResetError` пробрасывался сырым вместо `ambiguous` — P0, исправлено;
3. persisted `telegram_messages_topic_id` не валидировался при старте — P0, исправлено;
4. `/register` принимал личку владельца как целевой чат — P0, исправлено
   (`group`/`supergroup` only);
5. publication probe на `/register` — отклонено (см. rationale в `final-review.md`);
6. абсолютный `TELEGRAM_SESSION_PATH` мог выйти за `runtime/telethon/` — P1, исправлено;
7. сырой текст исключений без redaction секретов — P1, исправлено (`redact_secrets`).

Плюс регрессия, внесённая фиксом №6: `with_suffix()` обрезал dotted session names
(`owner.account` → `owner.session`); исправлено helper'ом `_with_session_suffix()`.

### 5.5 Прочие технические проблемы (устранены в ходе цикла)

- Портирование портов на async (`332574e`) — реальные адаптеры не совпадали с sync-сигнатурами.
- Readiness не доходил до `FORWARDING_ENABLED` без ручного `/set_topic` (`0ce0fb9`).
- Дефолты путей `config.py` (коммит `97d6d24`) — добавлены `TELEGRAM_SESSION_PATH`/`DATABASE_URL` дефолты,
  `.env.example` согласован.
- Dev-особенности: `--cov` в `addopts` «съедает» путь в pytest-командах (использовать `--no-cov`/`-o addopts=""`),
  `PIPESTATUS` работает только в bash.

---

## 6. Что проверено живьём (human gates) и что нет

| Проверка | Статус | Доказательство |
|---|---|---|
| MT-AUTH (Telethon session) | ✅ Владелец авторизовал | e2e-smoke до авторизации показывал `UNAUTHORIZED`; после — вручную |
| TG-REG (`/register`) | ✅ Пройден владельцем | «Найдено тем: 5»; в БД chat `-1002132607181` |
| TG-TOPIC (`/set_topic 2`) | ✅ Пройден владельцем | `destination check for run 20260917T232400-0d1b8693 (topic 21)`, message_id 36 |
| VK→Telegram E2E (текст) | ✅ Подтверждён владельцем | Публикация в «Важное» + 👍; после фикса payload |
| Дубль при повторной доставке | ✅ Автотесты + владелец | `duplicate-replay.txt` (15 passed); повтор того же события не публикуется |
| `LIKE_REACTION_ID = 1` | ✅ Подтверждён живым 👍 | Единственная константа без официальной доки; подтверждена ручным прогоном |
| `make test-e2e` (после авторизации) | ✅ 4 passed | `e2e-smoke.txt`, 2026-09-18 (прогон на копии session: живой файл держит запущенное приложение) |
| Заполнение evidence `tg-register.txt`, `tg-topic-mapping.txt`, `vk-tg-e2e.txt`, `mt-auth.txt` | ✅ Заполнено | Read-only probe из БД + Bot API, 77 файлов в evidence-каталоге |
| F5 — свежий независимый review после live E2E | ➖ Признан избыточным владельцем | `final-review.md`: round 1 закрыт, findings исправлены и покрыты тестами |

Живой E2E выявил **три класса багов** (5.1–5.3) — это доказывает, что human gate был необходим,
и что фейковые тесты без него недостаточны.

### Медиа и стена (вопрос владельца)

- **Фото/видео/документы** — не реализованы: есть только `Attachment`/`AttachmentKind`,
  `MAX_ATTACHMENT_BYTES = 50 MB`, классификация и warning-строки. Нет downloader,
  нет media-публикации. Deferred **Stage 9** (D8).
- **Стена VK** — forwarding не реализован. Deferred **Stage 9** (D9); поля
  `auto_forward_wall`/`telegram_wall_topic_id` подготовлены, но неактивны (`NULL`).
  NB: в коде нет даже нормализации `wall_post_new` — есть только enum `SourceType.VK_WALL`
  (см. §8, риск для Stage 9).
  Тестировать это сейчас не нужно — не баг, а запланированная граница.

---

## 7. Отклонения от первоначального замысла

### 7.1 `/register wall` / `/register messages` → `/register` + `/topics` + `/set_topic`

В ранних итерациях draft (и в исходном вопросе владельца) звучала идея
`/register <command>` с ролями `messages`/`wall`. В ходе reconciliation-интервью владелец
сам скорректировал модель, и **frozen draft** зафиксировал:

- D11/D16: `/register` регистрирует только чат и не принимает ролевые аргументы
  («It must not use temporary `/register messages`/`/register wall` roles»);
- выбор темы сообщений выполняется отдельным human gate TG-TOPIC;
- временная команда выбора темы несёт `TODO(stage-7)`.

Фактически реализованы:

- `/register` — регистрация чата (group/supergroup only, capability-проверки, refresh тем);
- `/topics` — нумерованный список тем из БД;
- `/set_topic N` — выбор темы **сообщений** с real-send proof (`send_test_into_topic`).
- Тема стены (`telegram_wall_topic_id`) не выбирается вообще и остаётся `NULL`.

Это отклонение **от исходной идеи ролей**, но следование **финальному frozen draft**.
Найденные ограничения: `/set_topic` одноразовый test-scaffold; в Stage 7 его заменят
Admin UI (маркеры уже стоят в 5 местах: `select_destination.py` ×2, `destination.py`,
`register.py`, `start.py`).

### 7.2 General в списке тем

Вместо примера draft `1. General (id: ...)` вывод сделан в виде
`1. General (служебная тема, не выбирается)` — следствие фикса 5.2.

### 7.3 Прочие мелкие отклонения

- Глобальный HTML parse_mode убран (см. 5.1) — это архитектурное изменение поведения
  относительно первого коммита адаптера; закреплено в docstring `bot_api_factory.py`.
- Round-1 review №5 отклонён (не исправлен) — сознательно, с обоснованием.
- `parse_mode` и `link_preview_options` применяются по-разному: публикация — HTML + выключенный
  preview; owner-ответы — plain text; тестовый send в тему — plain text без preview-настройки.

---

## 8. Риски и наблюдения для будущих этапов

### Stage 7 — Telegram Admin UI / FSM

1. **TODO(stage-7) в 5 местах** — при реализации UI их нужно снять и заменить на реальный
   выбор темы; текущие `/topics`/`/set_topic` — временный контракт, но use cases
   (`RegisterChat`, `RefreshTopics`, `SelectDestination`, `ToggleSettings`) переиспользуемы.
2. **Клавиатура намеренно пустая** (`keyboards.py`): Stage 7 обязан наполнить её и
   реализовать AC-20.3 («`/start` всегда отправляет актуальную клавиатуру»).
3. **Уведомления owners** (AC-20.4) не реализованы — сейчас бот отвечает только в чат;
   Stage 7 потребуется broadcast всем `OWNER_IDS`.
4. **`ToggleSettings.reset()`** (полный сброс) существует, но нет handler'а смены чата
   (US-21: подтверждение + сброс + удаление привязок топиков).
5. **parse_mode ловушка**: не возвращать глобальный HTML; любой пользовательский текст —
   либо plain text, либо escaped HTML (см. 5.1).
6. Не забыть ограничение «General нельзя выбирать» при построении UI —
   иначе вернётся баг 5.2 в новом обличье.

### Stage 8 — VK FSM и ручная пересылка

1. `vk_topic_aliases` (таблица, policy, repository) уже есть — нужны только handlers и VK FSM.
2. Ручная пересылка **не должна** использовать авто-dedup `source_key` (D4: повторное ручное
   действие — новое намеренное действие); порт есть, но логика не написана.
3. Нужны: Help-триггеры, кнопки, «ровно одно сообщение за операцию», отмена, unknown-alias flow.
4. VK FSM — ephemeral (in-memory); нельзя частично менять БД в незавершённой операции.

### Stage 9 — Wall и медиа

1. **Wall: сейчас нет нормализации `wall_post_new`** — только enum `SourceType.VK_WALL` и
   настройки. `VkEventConsumer._handle` обрабатывает только `message_new`; для Stage 9 нужно
   добавить ветку wall (owner_id/post_id как source_key) и активировать `telegram_wall_topic_id`.
2. **Публикация только текстовая**: `Publication.html_text` + `publish()` → `sendMessage`.
   Для медиа потребуется расширение publication-модели (медиагруппы, caption ≤1024, сплит
   длинного текста) и новой ветки error-handling'а (частичный успех, warning-строки US-10..12).
   Схема `delivery_records.telegram_message_ids` (JSON-массив) уже поддерживает несколько id — это плюс.
3. **Таксономия ошибок publisher'а** рассчитана на одно сообщение; при медиа надо различать
   «публикация не создана» и «часть вложений не перенесена» (реакция всё равно ставится, AC-13.2).
4. **Лимит 50 МБ** — domain-константа уже есть (`attachment_policy.MAX_ATTACHMENT_BYTES`).
5. **Перенос файлов из VK**: нужен downloader (aiohttp уже в зависимостях) и загрузка в Telegram;
   осторожно с размерами и таймаутами, ID документов VK требуют прав доступа.

### Stage 10 — Reliability / General fallback

1. Сейчас при перезапуске недоступная persisted destination-тема — **fatal startup**
   (`TOPICS_UNAVAILABLE`); Stage 10 заменит это на General fallback + уведомление владельцам.
2. `ambiguous` записи остаются в БД с `review_required=1`; reconciliation через историю
   Telethon — только ручная диагностика, автоматики нет (и по draft её не будет).
3. Нужна политика обработки `failed_permanent` и повторных VK-доставок.

### Общие наблюдения/риски

1. **Сообщения, отправленные пока приложение выключено, не пересылаются**: BotPolling
   запускается с `skip_old_events=True` и без restore ts, поэтому после рестарта Long Poll
   начинает с «сейчас», а не с последнего обработанного события. Для текущего продукта это,
   возможно, приемлемо, но стоит зафиксировать как осознанное поведение или решить в Stage 10.
2. **FirstPeerGuard — in-memory**: после рестарта привязка к первому peer теряется;
   второй не-первый peer в одном процессе отбрасывается с warning. Это defense-in-depth,
   а не гарантия (draft D15).
3. **Два пути к БД**: дефолт `data/vk_topic_bridge.db`, но в корне остались артефакты
   `vk_topic_bridge.db*` от более ранней конфигурации (добавлены в `.gitignore`).
   Рекомендуется не путать и удалить вручную, когда не нужны.
4. **Telethon session перезаписывается при повторной авторизации** (US-26) — при смене
   аккаунта старые топики в БД могут стать невалидными; startup-валидация это поймает
   (fatal), но UX-восстановления пока нет.
5. **e2e-smoke был `UNAUTHORIZED`** во время прогона; после авторизации владельцем
   `make test-e2e` стоит перепрогнать — это единственный пропущенный (skip) тест.
6. **`vk_consumer.py` покрытие 73%** (`VkPollingRuntime` живьём не тестировался —
   только через fakes), `api.py` 81%, `mapper.py` 91% — при следующих изменениях VK-слоя
   есть смысл добрать тестами.
7. **Pytest warning**: `ResourceWarning: unclosed database` в тестах — шум, не блокер,
   но в Stage 11 стоит прибрать (лишние unclosed sqlite-соединения в fixtures).

---

## 9. Quality gates и метрики

- `make check` (последний, с фиксом VK payload): `501 passed, 4 deselected`, Ruff — clean,
  BasedPyright — `0 errors`, coverage **92%** (`make-check-vk-payload-fix.txt`, `EXIT=0`).
- Миграции: `base → head` (`0001`), повторный `upgrade head` идемпотентен, 4 таблицы
  (`migration-final.txt`).
- Duplicate/replay/concurrency/lost-CAS: `15 passed` (`duplicate-replay.txt`).
- Полная цепочка на реальном SQLite: `tests/integration/test_forwarding_chain.py` —
  6+2 новых тестов, включая replay-без-дубля и оба триггера с вложенным payload.
- Всего в evidence-каталоге: **77 файлов** (RED/GREEN по задачам, `final-review.md`,
  `e2e-collect.txt`, `e2e-smoke.txt`, `mt-auth.txt`, `tg-register.txt`, `tg-topic-mapping.txt`,
  `vk-tg-e2e.txt`, `make-check-*`).
- Коммитов в цикле Stage 2–6: **19** (от `2c6f4f5` «контракты и фундамент» до git-хука `bd3f017`).

## 10. Что осталось сделать (рекомендации)

1. Заполнить evidence ручных гейтов: `tg-register.txt`, `tg-topic-mapping.txt`, `vk-tg-e2e.txt`
   (включая подтверждение 👍 и отсутствие дубля) — **выполнено**.
2. Перепрогнать `make test-e2e` (Telethon теперь авторизован) — **выполнено, 4 passed**.
3. При старте Stage 7 первым делом снять/заменить TODO(stage-7) маркеры и реализовать
   клавиатуру + уведомления owners, сохранив запрет General.

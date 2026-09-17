---
slug: stage-2-6-vertical-slice
status: frozen
intent: clear
review_required: false
pending-action: frozen draft only; plan intentionally not created in this session
approach: contract-first vertical slice: freeze configuration, lifecycle, persistence, normalized Telegram/VK ports and delivery semantics before parallel adapter/application work; prove the result with deterministic tests plus explicitly opt-in real Telegram/VK E2E.
---

# Draft: stage-2-6-vertical-slice

## User intent (direct quotes)

> «Теперь я хочу спроектировать одним intent сразу Stage 2–6 из `docs/06-full-implementation-roadmap.md`».

> «Целевой результат этого большого цикла разработки: приложение должно реально запускаться с моей конфигурацией, подключаться к SQLite, Telegram и VK, принимать настоящее событие из тестового VK, применять правила автоматической пересылки, публиковать сообщение в нужный Telegram topic, обеспечивать idempotency и после успешной доставки ставить 👍 в VK».

> «Это должен быть первый законченный vertical slice продукта, а не просто набор отдельных адаптеров».

> «Отдельно исследуй, как правильно разделить архитектуру и контракты так, чтобы последующий Sisyphus мог максимально распараллелить работу между субагентами».

> «В конце разработки Sisyphus должен иметь возможность фактически доказать цепочку: VK real event → приложение получает event → forwarding logic → Telegram реально получает публикацию в нужный topic → delivery сохраняется → VK получает 👍 → повтор того же event не создаёт вторую публикацию».

> «`VK_GROUP_ID`: не хочу вводить новую обязательную `.env` переменную без технической необходимости. Исследуй, можно ли надёжно получить identity сообщества из токена/API. Если можно — предпочитаю derivation».

> «Технические детали реализации, которые не меняют observable behavior, не нужно выносить мне на выбор — их делегируем Sisyphus и его архитектурным субагентам».

Тестовая инфраструктура и реальные credentials уже подготовлены пользователем и находятся в локальном `.env`; secrets и `.env` намеренно не читались.

## Связанные материалы

- [`docs/01-product-spec.md`](../../docs/01-product-spec.md) — первичный источник topology, product behavior, forwarding rules, attachments, wall, fallback и owner responsibilities.
- [`docs/02-user-stories.md`](../../docs/02-user-stories.md) — User Stories и Acceptance Criteria, по которым построена Stage 2–6 traceability matrix.
- [`docs/03-technical-requirements.md`](../../docs/03-technical-requirements.md) — первичный источник environment, Telegram/VK/Telethon contracts, startup checks, proxy policy, storage и non-functional requirements.
- [`docs/04-fsm-and-ui.md`](../../docs/04-fsm-and-ui.md) — граница Stage 7 UI, Telegram `/start`/registration flow, topic refresh/selection и будущие FSM contracts.
- [`docs/05-architecture-and-engineering.md`](../../docs/05-architecture-and-engineering.md) — modular-monolith architecture, layer boundaries, lifecycle, database, adapters, tests и architectural acceptance criteria.
- [`docs/06-full-implementation-roadmap.md`](../../docs/06-full-implementation-roadmap.md) — границы Stage 2–6 и deferred Stage 7–12 requirements.
- [`docs/07-bootstrap-intent-draft.md`](../../docs/07-bootstrap-intent-draft.md) — Stage 1 bootstrap boundaries и фактическая преемственность текущего цикла.
- [`.omo/drafts/stage-1-bootstrap.md`](stage-1-bootstrap.md) — исторический Stage 1 intent, сохранён для traceability; его stale approval metadata явно отмечена ниже.
- [`.omo/plans/stage-1-bootstrap.md`](../plans/stage-1-bootstrap.md) — исторический Stage 1 execution plan и evidence context.

Связанный Stage 2–6 plan намеренно отсутствует: пользователь запросил freeze и commit только этого draft; новый plan не создаётся в рамках текущего handoff.

## Components (topology ledger)

| id | outcome | status | evidence |
|---|---|---|---|
| C1 | Typed settings, safe Loguru pipeline, composition root, startup checks and coordinated graceful shutdown | active | `docs/06-full-implementation-roadmap.md:83-100`; `docs/05-architecture-and-engineering.md:381-620` |
| C2 | Async SQLite schema, Alembic head, repositories and explicit transaction/unit-of-work contract | active | `docs/06-full-implementation-roadmap.md:102-123`; `docs/05-architecture-and-engineering.md:621-812` |
| C3 | Telegram Bot API publisher/topic adapter plus Telethon topic/session connectivity adapter with independent proxy policies | active | `docs/06-full-implementation-roadmap.md:127-142`; `docs/05-architecture-and-engineering.md:816-892` |
| C4 | VK Long Poll/API adapter, normalized event DTOs, cropped-message completion, author lookup and reaction port | active | `docs/06-full-implementation-roadmap.md:144-158`; `docs/05-architecture-and-engineering.md:894-922` |
| C5 | Domain/application forwarding policy, publication composition, delivery ledger/idempotency and reaction ordering | active | `docs/06-full-implementation-roadmap.md:161-176`; `docs/05-architecture-and-engineering.md:949-1049` |
| C6 | Unit/application/DB/adapter tests plus isolated opt-in real integration/E2E proof and failure-path harness | active | `docs/05-architecture-and-engineering.md:1052-1172`; user acceptance chain above |

Владелец подтвердил C1–C6 без изменений; компоненты — не шесть независимых приложений, а параллельные workstreams одного modular monolith.

## Open assumptions (announced defaults)

| assumption | adopted default | rationale | reversible? |
|---|---|---|---|
| Архитектурная форма | Один asyncio modular monolith; `domain`/`application` не импортируют SDK/ORM; ручной composition root | Уже зафиксировано спецификацией и нужно для параллельной работы без платформенной связности | нет, это базовая архитектура |
| Contract-first порядок | Сначала freeze Settings, DTO/ports, repository/UoW и publication/delivery result; затем adapters и use case | Убирает главный риск параллельной реализации — несовместимые сигнатуры | да, до реализации |
| Внешние вызовы и БД | Telegram/VK calls не выполняются внутри DB transaction; транзакция короткая, commit контролируется use case/UoW | SQLAlchemy/SQLite transaction не может атомарно включить внешний API | нет для production semantics |
| Delivery engineering | Конкретные keys, states, schema, reservation, reconciliation и retry выбирает Sisyphus/архитектурные субагенты; owner фиксирует только обязательные no-duplicate/order/crash guarantees | Это инженерная реализация без owner-visible выбора, пока не меняет observable behavior | да, до реализации |
| Telegram routing identity | Хранить Bot API `chat_id + message_thread_id`; не использовать topic name или `reply_to_message_id` как routing key | Подтверждено Bot API; Telethon topic identifiers — отдельный MTProto контракт | нет |
| Proxy separation | Bot API proxy resolver и Telethon proxy resolver — разные компоненты; Telethon priority MTProxy → SOCKS5 → direct; local Bot API не идёт через SOCKS5; configured transport failure не делает silent fallback на weaker route | Явно зафиксировано `docs/05`, `docs/03` и подтверждено владельцем | нет |
| Default test safety | Обычный `pytest` не ходит в сеть; real E2E только явным marker/Make target, с уникальным run ID; тестовые сообщения можно оставлять; destructive live failure tests запрещены | Пользовательская test infrastructure не повреждается и остаётся аудируемой | да |
| VK identity derivation | `VK_GROUP_TOKEN` обязателен; `VK_GROUP_ID` не обязателен; без override identity выводится через `groups.getById({})`, затем проверяются Long Poll settings/server; один token/community invariant | VKBottle 4.x сама получает group ID token-only; отдельный обязательный env key не нужен без технической причины | да, optional override |
| Historical `.omo` metadata | Не переписывать историю Stage 1 без отдельного решения; в новом draft явно пометить stale status/claims как несоответствие | Старый draft/plan противоречит фактическим коммитам, но это не причина удалять или менять чужие артефакты сейчас | да |

## Findings (cited - path:lines)

### Фактическое состояние после Stage 1

- Bootstrap фактически завершён: committed `uv.lock`, Python 3.14, `src/` layout, quality tooling и skeleton; `make check` подтверждён как зелёный (`.omo/evidence/stage-1-bootstrap/make-check-green.txt:1-29`).
- Product/runtime implementation пока отсутствует: нет `config.py`, `logger.py`, `main.py`, Alembic configuration, ORM, repositories, Telegram/VK adapters, ports, use cases и lifecycle (`src/vk_topic_bridge/__init__.py` — только package marker; `migrations/.gitkeep`; `tests/unit/test_smoke.py`). Поэтому Stage 2–6 — первый большой runtime цикл, а не инкремент существующего кода.
- Git working tree по исследованию чистый; `.env` существует, но не читался из-за secrets. Неожиданные ignored IDE/cache/runtime файлы не удалялись.

### Уже зафиксированные архитектурные решения

- Один процесс, один asyncio event loop, aiogram polling и VK Long Poll параллельно, Telethon как отдельный infrastructure client, SQLite как единственная рабочая БД (`docs/05-architecture-and-engineering.md:33-72`).
- Направление зависимостей `presentation/infrastructure → application → domain`; SDK models преобразуются на границе; application ports скрывают SQLAlchemy и внешние SDK (`docs/05-architecture-and-engineering.md:193-231`).
- Целевая структура уже задаёт root-level `config.py`, `logger.py`, `main.py`, `authorize_telegram.py`, package layers и test layers (`docs/05-architecture-and-engineering.md:234-352`).
- Lifecycle концептуально строится через `asyncio.TaskGroup`, а shutdown закрывает pollers, aiogram HTTP session, Telethon, HTTP clients, `AsyncEngine` и Loguru queue (`docs/05-architecture-and-engineering.md:381-425`).

### Settings, `.env` и startup

- Текущий `.env.example` содержит 18 ключей (`.env.example:1-31`): `TELEGRAM_BOT_TOKEN`, `OWNER_IDS`, `TELEGRAM_BOT_API_URL`, `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_PATH`, `TELEGRAM_MTPROXY_SERVER`, `TELEGRAM_MTPROXY_PORT`, `TELEGRAM_MTPROXY_SECRET`, `SOCKS5_PROXY_URL`, `VK_GROUP_TOKEN`, `DATABASE_URL`, `LOG_LEVEL`, `LOG_LEVEL_LIBS`, `LOG_DIR`, `LOG_ROTATION`, `LOG_RETENTION`, `LOG_COMPRESSION`.
- Документы требуют typed `OWNER_IDS`, immutable cached Settings, cross-field validation, atomic MTProxy triplet, normalized Bot API URL и отсутствие mutable business state в `.env` (`docs/05-architecture-and-engineering.md:428-499`).
- Startup checks должны проверять обязательную env-конфигурацию, authorized Telethon session/API credentials, выбранный transport, Bot API endpoint, SQLite/migrations; при зарегистрированном chat — доступ и topics (`docs/03-technical-requirements.md:228-261`).
- Proxy rules: complete MTProxy block → SOCKS5 → direct; partial MTProxy block is fatal; Bot API endpoint loopback (`localhost`, `127.0.0.1`, `::1`) bypasses SOCKS5 independently of Telethon (`docs/03-technical-requirements.md:188-224`).
- Canonical full-slice contract теперь строгий: infrastructure/secrets из `.env`, product state только SQLite, `extra="forbid"`, blank values absent/validated, omitted `TELEGRAM_BOT_API_URL` means official Bot API. `VK_GROUP_ID` не является обязательным: identity выводится из единственного `VK_GROUP_TOKEN`; optional override допустим только с equality check. Путь `TELEGRAM_SESSION_PATH` должен нормализоваться в persistent ignored session path (`docs/03:57-81,180-184`; `.env.example:9`).
- Contradiction: Stage 1 draft/plan описывают empty `.env.example`, но текущий файл содержит safe placeholders/defaults; это не secret leak (`.omo/drafts/stage-1-bootstrap.md:323-327`; `.omo/plans/stage-1-bootstrap.md:33-35`; `.env.example:2-30`).

### Logging

- Root `logger.py` должен объединять Loguru console/file sinks и stdlib interception, с `enqueue=True`, configurable rotation/retention/compression, filtering noisy libraries и `diagnose=False`/без secret locals (`docs/05-architecture-and-engineering.md:501-575`). `logs/app.log` принадлежит Loguru, `logs/pm2.log` — будущему PM2; writers/rotation не смешивать (`docs/05:577-619`).
- External research confirms `logging.Handler` interception, `logger.opt(...).log(...)`, `enqueue`, rotation/retention/compression и риск secret leakage через `diagnose=True`; exact retention/format остаются owner/config decisions. Источники: Loguru docs `https://loguru.readthedocs.io/en/stable/overview.html`, `https://loguru.readthedocs.io/en/stable/api/logger.html`.

### Database, migrations и transaction boundaries

- SQLAlchemy 2 AsyncIO + `aiosqlite`; per-connection `foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout=5000`; repositories do not expose `AsyncSession` to use cases; one controlled transaction boundary per mutating use case (`docs/05-architecture-and-engineering.md:621-656`).
- Alembic required from first schema; no production `metadata.create_all`; migration before polling; initial tables: `bridge_settings`, `telegram_topics`, `vk_topic_aliases`, `delivery_records` (`docs/05:658-812`).
- External research confirms AsyncSession is not shareable across concurrent tasks, SQLite PRAGMAs must be applied per physical connection, async Alembic uses `run_sync`, and external API calls must remain outside DB transactions. Sources: SQLAlchemy asyncio/dialect docs, Alembic asyncio cookbook.
- Current `delivery_records` sketch has unique `(source_type, source_key)` and message IDs but does not fully define lifecycle, operation identity, payload/reconciliation marker, retry/error metadata, or duplicate-claim reservation. These are delegated engineering architecture decisions, not owner-approved product semantics.

### Telegram infrastructure

- aiogram owns Bot API, publication and future admin UI; custom server via `TelegramAPIServer.from_base`; Bot API proxy logic belongs only in `bot_api_factory.py` (`docs/05-architecture-and-engineering.md:816-849`).
- Bot API topic routing uses `message_thread_id` (target thread identifier); `can_manage_topics` is for topic management, while ordinary sends need send permission. Store `chat_id + message_thread_id`; do not derive routing from title or use reply IDs. Source: Bot API `sendMessage`/`ChatMember`, aiogram send types.
- Telethon uses a persistent session and is limited to topic discovery/access checks, not VK publication (`docs/05:851-892`). MTProxy requires Telethon MTProxy connection class plus `(host, port, secret)`; SOCKS5 uses `python-socks`; direct is no proxy. Compatibility or mapping between MTProto topic identity and Bot API `message_thread_id` must not be assumed without SDK/API evidence and a real Bot API test send; raw `messages.getForumTopics`/`channels.getForumTopics` may be unavailable for some bot accounts. Source: Telethon v1 docs/raw API and issue #4160.
- The requested real E2E requires confirming that the local `.env` points to an authorized Telethon user session, not merely the prepared Telegram bot. Secret values are not inspected.

### VK infrastructure and forwarding rules

- VKBottle handles Long Poll/API; handler → mapper → own DTO → use case; `is_cropped=true` requires complete message retrieval before filtering (`docs/05:894-922`; `docs/01:128-144`; `docs/02:183-201`).
- Stage 5 includes VK event normalization, full message, author and reaction; wall event infrastructure is mentioned in technical requirements, but wall forwarding, wall topic and `#изстенывк` are explicitly Stage 9 (`docs/06:144-158,218-233`).
- Conversation forwarding semantics already fixed: independent `@all` and hashtag toggles, one shared message topic, both matches produce one publication, preserve original text/order/tags, add `#извк` and `#извкважно`, author as VK-profile hyperlink, successful publication (including the future General fallback/partial-success behavior) precedes 👍, no publication means no reaction (`docs/01-04` relevant ranges; see traceability matrix). General fallback implementation is deferred to Stage 10.
- Current bridge settings contain wall-forwarding fields from the eventual product model even though Stage 9 owns wall publication; Stage 2–6 must use `telegram_messages_topic_id` and `telegram_wall_topic_id`, leaving the wall destination `NULL` and inactive.
- There is no Stage 7 admin UI yet, while `bridge_settings.telegram_chat_id` and destination topic IDs are mutable DB state and nullable in the target schema. The agreed pre-Stage-7 path is human-in-the-loop: real `/register` saves the chat, Telethon refreshes topics, the owner selects the messages topic, and a temporary provisioning use case/fixture confirms the selection by a real Bot API send before persisting it.
- VK official schema confirms `messages.sendReaction(peer_id, cmid, reaction_id)`, but does not establish retry idempotency or toggle semantics; concrete reaction/delivery handling is delegated engineering. VK Group Long Poll exposes identifiers including `group_id`, `event_id`, `peer_id` and `conversation_message_id`; implementation may use them according to the delegated identity strategy, but this intent selects no concrete dedup/source key. Sources: `https://dev.vk.ru/ru/api/bots-long-poll/getting-started`, `https://dev.vk.ru/ru/api/community-events/json-schema`, VK API schema and VKBottle `Message.get_full_message()` source.

### Human-in-the-loop provisioning

- Source requirements require a minimal owner-facing `/start` flow before chat registration: authorized owner starts the bot in private chat, receives an instruction to add the bot to the target Telegram chat and execute registration there; unauthorized users receive no response. Full permanent keyboard/UI remains Stage 7, but owner middleware and this minimal onboarding behavior are part of the Stage 2–6 bootstrap needed for US-01/US-02.
- Telegram chat provisioning is deliberately not an `.env`/seed/SQL operation. Before topic selection, the running application must expose the product-semantic `/register` handler through the real Telegram Bot API. An owner sends `/register` in the target Telegram chat; the handler checks the common `OWNER_IDS` gate, extracts `chat.id`, verifies the bot is a member and satisfies the US-03 capability checks, and commits the registered chat through application/repository ports. It must not use temporary `/register messages`/`/register wall` roles.
- US-03 capability checks cover at minimum text, photo, video, document and publication in the used topics; implementation must report missing capabilities clearly without requiring `can_manage_topics` unless a concrete operation needs it and without creating unwanted chat spam.
- `/register` is the existing product command, not a temporary role command. It is temporary only in the sense that Stage 7 will provide the complete UI around the same application capabilities.
- After `/register`, the user-account Telethon client must verify an authorized session, successful `get_me()`, access to the same numeric chat entity and expected forum supergroup, then retrieve the complete forum-topic list with pagination and refresh `telegram_topics` through application/repository ports. Empty topic results when the user is not a member are a provisioning/startup error, not a valid empty list.
- Bot API `chat_id` and Telethon entity must be linked by canonical numeric identity/access verification, never by title or username. MTProto topic identifiers must not be assumed compatible with Bot API `message_thread_id`.
- The implementation plan must contain **HUMAN GATE TG-REG** after DB/migrations, app startup, Bot API connection and `/register` handler are verified. It must then contain **HUMAN GATE TG-TOPIC**: Sisyphus presents `index + title + stable topic identifier`, stops, asks the owner to choose the messages destination, performs a real Bot API test send to the selected `message_thread_id`, and persists `telegram_messages_topic_id` only after that send creates a message in the intended topic. The worker may not claim Telegram provisioning complete or start final real VK→Telegram E2E before owner confirmation and machine evidence show registered chat, refreshed topics and confirmed destination. Wall destination remains `NULL`.
- The topic-selection use case/fixture carries `TODO(stage-7): remove temporary destination-topic provisioning when Telegram Admin UI provides destination selection.`
- **HUMAN GATE MT-AUTH is conditional:** if the existing Telethon session is already authorized and passes `get_me()`/chat verification, no gate is needed; if it is absent or invalid, Sisyphus stops and asks the owner to run `authorize_telegram.py`, complete interactive authorization, and then resumes after verification without recording secrets.

### Requirements traceability corrections

- The temporary `/start`/`/register` flow is traced to US-01 AC-01.1/AC-01.2, US-02 AC-02.1/AC-02.2 and US-03 AC-03.1–AC-03.3. US-02 AC-02.3's permanent keyboard and the complete Admin UI remain Stage 7 deferred.
- US-04 topic refresh and temporary US-05 messages-topic selection use the same application contracts that Stage 7 will later invoke from its UI; the HUMAN GATE is a development/E2E provisioning path, not a second product semantics.
- US-10–US-12 attachments and US-14 wall forwarding remain final-product requirements deferred to Stage 9; the Stage 2–6 DTO/port boundary is compatibility work, not cancellation.
- US-22 General fallback and owner notification remain final-product requirements deferred to Stage 10; Stage 2–6 must preserve a result/error contract that will allow that behavior without redesign.
- US-15–US-19 VK manual UI/aliases and US-20–US-21 complete Telegram admin UI remain deferred to Stages 7–8 as specified by the roadmap.
- US-23/US-24 proxy behavior, US-25 no edit/delete synchronization and US-26 authorization script are in the current slice; US-26 includes interactive phone/code/2FA input, persistent ignored session storage and replacement of prior authorization on successful re-authorization.

### VK single-chat topology research

- VK Bots Long Poll `message_new` contains `group_id`, `event_id`, `object.message.peer_id`, `conversation_message_id`, `from_id` and text. `peer_id` identifies the conversation; `ts` is a stream cursor and must not become a business ID. Sources: VK Bots Long Poll/community event schemas and VKBottle polling/deduplicator source.
- A group bot receives target conversation events when community messages, Bots Long Poll and `message_new` are enabled and the community is present in the conversation. No mention or VK registration command is required.
- Product Spec topology is a deliberate external deployment invariant: one community, one VK chat, one Telegram chat, no multi-tenant/source configuration. The application therefore consumes all normalized conversation `message_new` events and uses the event's transient `peer_id` for VK API calls where needed; it does not persist `peer_id`, does not expose `/register-source`, does not use `VK_OWNER_IDS`/nonce, and does not create `vk_sources`.
- Research found no documented group-bot API guarantee that the application can enumerate all conversations and prove at startup that exactly one exists. If a second peer is observed, the least-complex defense is an in-memory first-peer binding for the current process: keep the first conversation peer, do not forward a different peer, emit a topology-violation error/metric, and do not replace the binding. This is defense-in-depth only; after restart the external one-chat invariant remains the source of truth and accidental multi-chat topology is unsupported.
- `group_id`, `event_id`, `peer_id` and `conversation_message_id` remain normalized event input identifiers; the concrete deduplication/source identity strategy is delegated under D20 and must not be inferred from this draft.

### VK community identity derivation

- External VK/VKBottle research confirms that one valid community token is sufficient to derive the community identity: `groups.getById({})` returns the token's community object with numeric `id`; VKBottle 4.x `BotPolling.get_server()` uses this token-only call when `group_id` is absent, then calls `groups.getLongPollServer(group_id=...)`.
- `VK_GROUP_ID` therefore must not be a new required `.env` variable. It may exist as an optional diagnostic/override field only; if present, it must equal the ID derived from the token or startup fails. Multiple tokens/communities are out of topology and must not be silently cycled through one polling instance.
- Startup VK handshake: derive identity, validate Long Poll settings are enabled, obtain Long Poll server/key/ts, and classify invalid token, missing permissions, disabled Long Poll and invalid identity as explicit startup errors. Sources: VK `groups.getById`, `groups.getLongPollSettings`, `groups.getLongPollServer` docs/schema and VKBottle `bot_polling.py` source.

### Idempotency, ordering and failure paths

- Architecture gives illustrative `source_key` examples (`vk-message:{peer_id}:{conversation_message_id}` / `vk-wall:{owner_id}:{post_id}`), but they are not selected by this intent and do not solve crash ambiguity (`docs/05-architecture-and-engineering.md:978-1001`).
- A Telegram send response and a SQLite commit cannot be one atomic transaction; Bot API has no generic idempotency-key argument. If Telegram accepts a message and a process crashes before recording it, a retry can duplicate it. Concrete at-least-once/state/reconciliation mechanics are delegated engineering choices; the product intent makes no unsupported exactly-once promise and imposes the guarantees below.
- The owner deliberately delegates concrete engineering choices — deduplication keys, delivery states, reservation/concurrency strategy, schema fields, reconciliation and retry implementation — to Sisyphus and architectural subagents.
- Mandatory observable guarantees for the implementation are: repeated delivery of one VK event does not create a duplicate Telegram publication; concurrent handling of one message does not duplicate publication; a confirmed Telegram publication is not republished after restart; no SQLite write transaction remains open across network I/O; VK 👍 occurs only after confirmed Telegram publication; reaction failure never triggers Telegram republish; ambiguous Telegram results are not blindly retried when that risks duplicates; crashes between network and DB operations are handled explicitly and as safely as possible; crash/replay/concurrency tests prove these properties.
- The implementation team must document the selected technical rationale in the plan/code. Any choice that changes observable product behavior beyond these guarantees requires a separate HUMAN GATE to the owner.

### Fatal startup and lifecycle policy

- Before Telegram/VK polling starts, core dependencies must be ready: Settings validation; accessible DB at Alembic migration head; successful Telegram Bot API `getMe()`; authorized Telethon user session with successful `get_me()`; VK token-derived community identity, enabled Long Poll settings and Long Poll initialization. A plainly absent optional proxy is not fatal; an explicitly configured invalid or unavailable selected transport is a startup error with no silent fallback to a weaker route.
- Registered-chat/entity/topic checks are post-`/register` provisioning readiness checks because a clean DB has no Telegram `chat_id`. They are not a reason to block the initial `/register` polling startup.
- During first-time `/register` provisioning on a clean/unregistered DB, if Telethon cannot resolve/access the same numeric chat entity, the entity is not the expected forum supergroup, topic discovery fails, or topic verification fails: provisioning is `failed/not ready`, forwarding remains disabled, no General fallback is silently used, and the Telegram bot remains alive for a clear owner-facing error and retry.
- On a later process startup where `telegram_chat_id` is already persisted, failure to revalidate the same numeric Telethon entity/chat access or required topic readiness is a fatal startup revalidation error; polling must not start in a partially configured state, in accordance with Technical Requirements §7.2 and §16.
- Telegram Bot API polling and VK Long Poll are critical tasks. Unexpected completion of either cancels sibling critical tasks, performs coordinated shutdown of pollers, Bot API/HTTP clients, Telethon, DB engine and logging resources, and exits non-zero. Stage 2–6 does not hide failures in permanent degraded mode or infinite internal retry loops.
- The lifecycle therefore has separate readiness concepts: process/core-ready before polling; Telegram-chat-registered; Telethon-same-entity/topic-ready; destination-confirmed; forwarding-ready. Forwarding is enabled only at the last state.

### Tests and real E2E

- Existing tests are only import smoke; integration/acceptance/e2e dirs are empty except `.gitkeep`. Architecture requires unit/application tests with fakes, DB/migration integration tests, adapter tests, acceptance tests and explicit E2E (`docs/05:1052-1172`).
- Real E2E should use a dedicated marker/command, credentials from env only, the prepared test SQLite/session/log paths as appropriate, unique run ID, and the agreed real message shape: one VK message containing `@all` plus a unique hashtag. Test messages may remain for audit. Default `pytest` must never call real services.
- Failure paths should be proven with fakes/injected integration adapters: malformed settings, explicitly configured proxy failure, migration failure, missing topic/fallback contract, cropped VK event, author lookup failure, Telegram timeout/ambiguous acceptance, DB contention, reaction failure, crash after external send, graceful shutdown, and duplicate event. Destructive permission/topic deletion or other infrastructure-damaging failure injection is prohibited against the real test environment.

### `.omo` traceability / stale metadata

- `.omo/drafts/stage-1-bootstrap.md` and `.omo/plans/stage-1-bootstrap.md` still say `awaiting-approval`/“no commit”, although Stage 1 commits `abcd88c` and `4313f76` exist and evidence is green. This new draft treats them as historical stale metadata and preserves links; it does not delete or silently rewrite them.

## Decisions (with rationale)

- **D0 — One Stage 2–6 intent:** plan one vertical slice, not five unrelated adapter implementations, because the acceptance chain crosses config → DB → VK event → application policy → Telegram topic → delivery ledger → VK reaction.
- **D1 — Contract-first parallelism:** C1–C6 are separated by ports/DTOs and a dependency matrix; downstream workers may implement independent adapters only after shared contracts are frozen.
- **D2 — No SDK leakage inward:** normalized own DTOs and application ports are mandatory; aiogram/VKBottle/Telethon/SQLAlchemy types remain infrastructure details.
- **D3 — No DB transaction around network calls:** external calls occur outside SQLite transaction; repository methods do not commit autonomously.
- **D4 — No unsupported exactly-once claim:** the plan must name the crash ambiguity and implement a durable delivery state/reconciliation policy appropriate to the available Telegram/VK APIs.
- **D5 — Separate Bot API and MTProto identity/config:** Bot API routing and Telethon topic discovery are separate adapter concerns; compatibility/mapping between their topic identifiers must be proven by SDK/API evidence and real send, never assumed. Proxy choices remain independent.
- **D6 — E2E opt-in and non-destructive:** real tests are explicit, isolated by run ID/resources, and never part of default quality gates.
- **D7 — Remaining owner decisions:** any observable product-behavior changes remain interview items; delivery internals, permission probes, VK identity derivation and topic mapping are engineering decisions constrained by the requirements below, with BLOCKED/HUMAN GATE if a required guarantee cannot be proven.
- **D8 — Attachment boundary confirmed:** Stage 2–6 defines an attachment-neutral DTO/port compatible with Stage 9, but does not implement downloader, media transfer, size policy or full attachment publication. The first real E2E is text/author/tags.
- **D9 — Wall boundary confirmed:** Stage 5 recognizes and normalizes wall events as infrastructure capability, but no wall forwarding is executed; `auto_forward_wall` remains inactive and `telegram_wall_topic_id` remains `NULL` until Stage 9.
- **D10 — Topology confirmed:** C1–C6 remain the six workstreams and will be used for the dependency/parallelization matrix.
- **D11 — Telegram provisioning corrected:** do not take chat/topic IDs or destination topic IDs from `.env`, seed files or manual SQL. Product-semantic `/register` only registers the owner-authorized Telegram chat and verifies bot permissions; Telethon then refreshes topics; a separate human gate asks the owner to select the messages topic, and a temporary provisioning use case/fixture persists that selection before E2E.
- **D12 — Conditional Telethon authorization gate:** user-account session is mandatory; an already authorized and verified session proceeds without HUMAN GATE MT-AUTH, while an absent/invalid session requires `authorize_telegram.py` and an interactive owner gate before full-slice startup/E2E.
- **D13 — Strict Settings confirmed:** full-slice infrastructure/secrets are canonical `.env` inputs; product state remains SQLite; `extra="forbid"`; blank values are absent and validated; omitted `TELEGRAM_BOT_API_URL` means official Bot API. `VK_GROUP_TOKEN` is required; `VK_GROUP_ID` is not required and is derived from the token unless an optional matching override is deliberately supplied; authorized Telethon session path remains required for the full slice.
- **D14 — VK topology corrected:** no VK source registration flow, `VK_OWNER_IDS`, nonce, `vk_sources` table or persisted peer configuration. Consume events from the one supported conversation under the Product Spec deployment invariant; use transient normalized `peer_id` for technical API calls.
- **D15 — Unsupported extra VK peers:** a current-process in-memory first-peer guard may fail closed on a second observed peer and log a topology violation, but it is not a persisted source policy and cannot compensate for a deployment that violates the one-chat invariant across restarts.
- **D16 — Canonical Telegram provisioning:** `/register` registers only the owner-authorized Telegram chat; Telethon verifies the same numeric chat/entity, paginates and stores topic metadata; the owner selects the messages destination through HUMAN GATE TG-TOPIC; real Bot API send confirmation is required before persisting `telegram_messages_topic_id`; `telegram_wall_topic_id` remains `NULL`.
- **D17 — Core startup gate:** Settings, DB-at-head, Bot API `getMe`, authorized Telethon `get_me`, token-derived VK identity, enabled VK Long Poll settings and Long Poll initialization are fatal before polling. Missing optional transports are allowed; invalid/unavailable explicitly configured transports are fatal with no silent weaker-route fallback.
- **D18 — Provisioning/revalidation split:** first-time `/register` provisioning failures leave forwarding disabled and keep the Telegram bot alive for clear diagnostics/retry; startup revalidation failures for an already persisted Telegram chat/entity/topics are fatal and prevent polling. Empty topics and silent General fallback are invalid.
- **D19 — Critical task lifecycle:** Telegram and VK pollers are critical; unexpected completion triggers sibling cancellation, coordinated resource shutdown and non-zero process exit, without hidden infinite poller retries or permanent half-running mode.
- **D20 — Delivery engineering delegation:** Sisyphus/architecture subagents choose delivery keys, state machine, reservation, schema, reconciliation and retries. They must satisfy the explicit no-duplicate/order/crash guarantees, keep network calls outside DB write transactions, add crash/replay/concurrency tests, document rationale, and request a HUMAN GATE if a choice changes observable product behavior.
- **D21 — Minimal Telegram bootstrap contract:** Stage 2–6 includes `/start` onboarding, common silent owner gate and product-semantic `/register`; full permanent keyboard/FSM remains Stage 7. `/register` checks text, photo, video, document and publication-in-used-topics capabilities, reports missing capabilities, and does not require `can_manage_topics` unless a concrete operation needs it.
- **D22 — Authorization script contract:** `authorize_telegram.py` must satisfy all US-26 criteria, including phone/code/2FA input, persistent ignored session and successful re-authorization replacing the previous account/session.
- **D23 — Requirements deferral is not cancellation:** US-10–12/14, US-15–22 as applicable, General fallback and full Admin/VK UI are explicitly mapped to roadmap stages; Stage 2–6 preserves compatible contracts and does not claim those criteria complete.
- **D24 — Acceptance traceability:** Stage 2–6 verification is named against existing US/AC identifiers, with real E2E only for the in-scope subset and deferred criteria kept visible.
- **D25 — Proxy and E2E policy:** configured MTProxy → configured SOCKS5 → direct by presence; selected transport failure is fatal without silent fallback; real E2E uses unique run ID and may leave messages, while destructive failures use fakes/integration adapters.

### Sisyphus execution ownership

- After handoff, Sisyphus owns the complete Stage 2–6 execution cycle, not merely isolated todo execution.
- Sisyphus builds and maintains the dependency graph; freezes Settings, DTOs, ports, repository/UoW and other shared contracts before dispatching dependent parallel work.
- Sisyphus maximally delegates independent C1–C6 workstreams to suitable subagents, integrates their results, and preserves the layer/dependency boundaries.
- Sisyphus runs quality gates after logical implementation waves, invokes architecture/review agents, and routes discovered failures back for correction without returning implementation-detail questions already delegated by this intent.
- Sisyphus may create logical commits only after green checkpoints and keeps the execution moving autonomously between explicitly defined HUMAN GATEs.
- Sisyphus stops only at a listed HUMAN GATE, when a choice changes observable product behavior, or when a required technical proof is genuinely blocked; otherwise it chooses and documents implementation details.
- Sisyphus must not declare Stage 2–6 complete before the final real `VK → Telegram` E2E proof, duplicate/replay evidence, quality gates and final architecture/review approval.

## Scope IN

- Stage 2–6 only: config/settings, logger/interception, lifecycle/composition root/startup policy; SQLite/SQLAlchemy/Alembic/models/repositories; Telegram Bot API and Telethon infrastructure; VK Long Poll/API/DTO mapping; automatic conversation-message forwarding; delivery idempotency and VK reaction ordering; unit/application/adapter/DB/acceptance tests; explicit opt-in real integration/E2E smoke and safe failure-path verification.
- Temporary Stage 2–6 development provisioning required before Stage 7: minimal owner-gated `/start`, product-semantic Telegram `/register`, complete US-03 capability checks, same-chat Telethon access verification, paginated topic refresh, owner-selected messages destination, real Bot API mapping confirmation, full-criteria `authorize_telegram.py`, token-derived VK identity/Long Poll checks, and explicit owner-controlled human gates with machine-verifiable evidence.
- Contracts needed for future Stage 7+ compatibility may be defined where they affect current ports or persisted schema, but no admin UI/FSM implementation is included.

## Stage 2–6 US/AC traceability matrix

| workstream / proof | source criteria covered now | proof mode |
|---|---|---|
| C1 config, owner gate, lifecycle | US-01 AC-01.1/AC-01.2; US-02 AC-02.1; US-23; US-24; US-26; Technical Requirements §7 and §16 | unit/application tests, adapter tests, conditional MT-AUTH plus TG-REG/TG-TOPIC gates, startup/shutdown tests |
| C2 database/migrations | Technical Requirements §2; Architecture DB/migration criteria; persisted state required by US-02/04/05/20/21/25 | DB integration tests, migration base→head, repository/UoW tests |
| C3 Telegram infrastructure/provisioning | US-02 AC-02.2; US-03 AC-03.1–AC-03.3; US-04 AC-04.1; temporary US-05 AC-05.1/AC-05.2; US-23 ACs; US-24 ACs | adapter/application tests plus real opt-in TG-REG/TG-TOPIC mapping probe |
| C4 VK infrastructure | US-08 AC-08.1/AC-08.2; US-09 AC-09.1/AC-09.2; US-13 API prerequisite; Technical Requirements §9–10; normalized wall event contract only | mapper/adapter tests, fake API tests, VK identity/Long Poll opt-in smoke |
| C5 forwarding core | US-06 AC-06.1–AC-06.4; US-07 AC-07.1–AC-07.3; US-08; US-09; US-13 AC-13.1–AC-13.3; US-25; Roadmap Stage 6 | pure domain/application tests, fake ports, one real VK message with `@all` + unique hashtag |
| C6 end-to-end proof | Combined in-scope chain: US-02/03/04 temporary provisioning → US-06/07/08/09/13 forwarding; architecture duplicate guarantee | explicit E2E run with unique run ID, retained messages, DB evidence and no duplicate Telegram publication |

The following are visible deferrals, not deletions: US-10–US-12 and US-14 to Stage 9; US-15–US-19 to Stage 8; full US-20–US-21 and permanent UI portions of US-02/04/05 to Stage 7; US-22 fallback behavior to Stage 10. Their future-compatible DTO/ports/schema fields may be created now but their acceptance criteria must not be claimed complete in this slice.

## Scope OUT (Must NOT have)

- Stage 7 Telegram Admin UI/FSM and owner wizard implementation.
- Production-grade registration/admin UX beyond the temporary bootstrap handlers; Stage 7 remains responsible for the normal lifecycle of registration, topic refresh, toggles and owner notifications.
- Stage 8 VK UI/manual forwarding/aliases UI/FSM.
- Stage 9 wall publication, wall attachments downloader, media size/format pipeline and full attachment delivery implementation. Wall-event recognition/normalization and attachment-neutral contracts are explicitly IN, but their product effects remain inactive until later stages.
- Stage 10/11/12 broad reliability hardening, acceptance-wide audit, PM2/deployment/reboot automation, except the owner-promoted delivery crash/replay/concurrency guarantees, their tests, startup/shutdown and test hooks strictly required for this vertical slice.
- FastAPI, Redis, Celery/RabbitMQ/Kafka, DI framework, separate VK/Telegram services, or unrequested persistence/distributed infrastructure.
- Secrets in draft/plan/logs/tests, reading or copying `.env`, real credentials, Telethon session, runtime DB, or destructive cleanup of the existing test chat/topics/community.

Deferred source requirements remain in the roadmap and traceability matrix; “OUT” here means not implemented in Stage 2–6, not removed from the product.

## Open questions

### First interview block — scope topology and vertical-slice boundary (answered)

1. **Topology lock:** owner confirmed C1–C6 unchanged.
2. **Attachments:** owner selected contract-only boundary; no downloader/media pipeline; first E2E is text/author/tags.
3. **Wall:** owner selected event recognition/normalization without wall forwarding; wall settings remain inactive until Stage 9.

### Next interview block — provisioning and canonical settings (answered)

- **Pre-Stage-7 provisioning:** owner corrected and finalized the mechanism: `/register` only registers the Telegram chat; Telethon verifies the same numeric entity and refreshes paginated topics; Sisyphus presents `index + title + stable ID`, stops at HUMAN GATE TG-TOPIC, performs a real Bot API send using the selected `message_thread_id`, and only then persists `telegram_messages_topic_id`. No role arguments, `.env` IDs, seed file or manual SQL; `telegram_wall_topic_id` remains `NULL`.
- **Canonical `.env` contract:** owner selected strict full-slice contract: infrastructure/secrets in `.env`, product state only SQLite, `extra="forbid"`, blank values absent/validated, omitted Bot API URL means official Bot API. Required-field details from the recommended list are recorded in D13.
- **Telethon identity:** owner selected mandatory user-account session; HUMAN GATE MT-AUTH is conditional — existing verified session skips it, absent/invalid session requires `authorize_telegram.py` and owner authorization.

### Next interview block — VK topology and Telegram bootstrap details (answered)

- **VK source registration:** owner finalized the external one-community/one-chat invariant, no source registration/configuration; in-memory first-peer guard is allowed only as defense-in-depth and second peers are not forwarded.
- **Telegram bootstrap:** `/register` is the product-semantic owner command; it checks `OWNER_IDS`, chat membership, text/photo/video/document/topic-publication capabilities and reports missing capabilities; `can_manage_topics` is not required unless a concrete operation needs it.
- **Topic mapping:** Telethon pagination presents index/title/stable ID; owner chooses messages destination; real Bot API send confirms the mapping; only `telegram_messages_topic_id` is persisted and wall remains `NULL`.

### Engineering-delegated block (resolved as owner policy)
- Delivery state machine, deduplication keys, reservation race, schema fields, reconciliation and retry strategy are not product-intent decisions. They are delegated to the implementation architecture, constrained by the mandatory guarantees in the Idempotency section and D20; any observable behavior change returns as a HUMAN GATE.

### Requirements reconciliation block (answered)

- Added minimal `/start` onboarding and a common silent owner gate for Telegram presentation handlers.
- Added US-03 capability-check requirement for text/photo/video/document/topic publication without making `can_manage_topics` mandatory by default.
- Split first-time provisioning failure (bot remains alive, forwarding disabled) from fatal startup revalidation of an already persisted Telegram chat/entity/topics.
- Recorded the complete US-26 authorization-script contract.
- Removed concrete delivery state-machine choices from owner-adopted defaults; retained only mandatory observable guarantees and delegated internals.
- Marked final-product requirements deferred by roadmap rather than cancelled.
- Added the Stage 2–6 US/AC traceability matrix.
- Standardized destination fields as `telegram_messages_topic_id` and `telegram_wall_topic_id`.
- Resolved VK identity without a new required env field: derive from one `VK_GROUP_TOKEN`, optionally validate an override, and fail explicitly on VK identity/Long Poll errors.
- Resolved proxy policy and real-E2E safety: configured route failure is fatal without silent weaker-route fallback; real tests use unique run IDs and may retain messages; destructive live failures use fakes/integration adapters.

### Remaining owner-level product decisions

None identified after the reconciliation and current interview answers. General fallback, wall forwarding, attachments, Admin UI, VK UI and aliases are source-defined roadmap deferrals, not open product choices for this intent.

### Remaining implementation gates (not interview questions)

- Telethon-to-Bot-API topic identifier mapping must be proven by SDK/API evidence and real Bot API send; if it cannot be proven, implementation is `BLOCKED` and requires a HUMAN GATE rather than a silent assumption.
- Permission probing, VK token/API error classification, delivery internals, DTO signatures, schema details, retry/reconciliation and test fixture mechanics are delegated implementation decisions; an observable behavior change returns to HUMAN GATE.
- HUMAN GATE TG-REG/TG-TOPIC are required runtime/operator gates; HUMAN GATE MT-AUTH is conditional on the existing session failing authorization/verification, not an unconditional stop.

## Sisyphus execution contract

- After handoff, Sisyphus owns the complete Stage 2–6 execution cycle, not merely isolated todo execution.
- Sisyphus builds the dependency graph, freezes shared contracts before dependent parallel work, maximally delegates independent C1–C6 workstreams, integrates results and runs quality gates after logical waves.
- Sisyphus invokes architecture/review agents, routes discovered problems back for correction, creates logical commits only after green checkpoints, and continues autonomously between named HUMAN GATEs.
- Sisyphus does not return implementation-detail questions already delegated here; it stops only at a named HUMAN GATE, a genuinely blocked technical proof or a choice changing observable product behavior.
- Completion requires final real VK → Telegram E2E proof, duplicate/replay evidence, all quality gates and final review approval.

## Approval gate
status: frozen
approach: contract-first Stage 2–6 vertical slice with explicit temporary Telegram provisioning gates, token-derived single-community VK identity, source-traceable acceptance coverage, roadmap-visible deferrals and delegated delivery engineering constrained by mandatory guarantees.
pending-action: frozen draft only; create a separate plan only when explicitly requested
<!-- When exploration is exhausted and unknowns are answered, set status: awaiting-approval. -->
<!-- That durable record is the loop guard: on a later turn read it and resume at the gate instead of re-running exploration. -->

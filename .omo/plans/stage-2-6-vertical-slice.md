# stage-2-6-vertical-slice — Work Plan

## TL;DR (For humans)

**What you'll get:** Работающий вертикальный срез продукта: приложение стартует с твоим `.env`, поднимает SQLite+Alembic, подключается к Telegram Bot API, Telethon (топики) и VK Long Poll; вручную (через `/register` + human gate выбора топика) настраивается один Telegram-топик; затем настоящее VK-сообщение с `@all` и хештегом реально публикуется в этот топик, факт доставки сохраняется в SQLite, VK-сообщению ставится 👍, а повторная доставка того же события не создаёт второй публикации. Плюс набор тестов: domain/application/adapter/DB/acceptance и opt-in real E2E.

**Why this approach:** Сначала замораживаем контракты (Settings, DTO, ports, UoW, схема БД, state machine доставки), затем параллельно пишем адаптеры и use cases. Это единственный способ распараллелить 6 workstream'ов без rework. Доставка построена fail-closed: после фиксации намерения отправки Telegram-публикация автоматически не повторяется, неоднозначный исход становится `ambiguous` и видимым владельцу.

**What it will NOT do:** Stage 7 Telegram Admin UI/FSM, Stage 8 VK UI/алиасы, Stage 9 wall publication + downloader/вложения > 50 МБ, Stage 10 General fallback, Stage 11–12 PM2/deployment hardening. Никаких FastAPI/Redis/Celery/DI-контейнера. Не читаем и не коммитим `.env`, session, runtime DB.

**Effort:** XL (Stage 2–6)
**Risk:** High — главные риски: (1) не доказанный маппинг Telethon topic id → Bot API `message_thread_id` (доказывается реальным send на gate TG-TOPIC), (2) crash-window между Bot API accept и SQLite commit (закрывается fail-closed `ambiguous`), (3) numeric `reaction_id` для 👍 не подтверждён официальной докой VK (проверяется живым вызовом на E2E).
**Decisions to sanity-check:** fail-closed delivery (никакого auto-republish после `send_started`); General topic адресуется отсутствием `message_thread_id` (`None`), а не `1`; `VK_GROUP_ID` — опциональный override, identity выводится из токена; provisioning только через `/register` + human gate, без seed/SQL/`.env`; reconciliation через историю Telethon — только диагностика, не автоматика.

Your next move: Подтвердить план; далее исполнение волнами через `sisyphus-junior` (categories `unspecified-low`/`unspecified-high`) с quality gates после каждой волны.

---

> TL;DR (machine): Stage 2–6 vertical slice plan. Contract-first: Wave 1 {domain, config, db-models+migration} → Wave 2 {logger, ports+repos} → FREEZE → Wave 3 {telegram, telethon, vk adapters; forwarding + provisioning use cases; authorize script} → Wave 4 {bootstrap/lifecycle, integration/acceptance/e2e tests, human gates, real VK→TG E2E}. Fail-closed delivery ledger with CAS claim. No plan subagent available; authored by orchestrator, reviewed by Momus.

## Source intent

- Frozen draft: `.omo/drafts/stage-2-6-vertical-slice.md` (status: frozen, intent: clear). All decisions D0–D25 are binding.
- Product/eng sources: `docs/01-product-spec.md`, `docs/02-user-stories.md`, `docs/03-technical-requirements.md`, `docs/04-fsm-and-ui.md`, `docs/05-architecture-and-engineering.md`, `docs/06-full-implementation-roadmap.md`.
- Execution contract: Sisyphus owns Stage 2–6, stops only at named HUMAN GATEs, observable-behavior changes, or genuine blockers.
- Related material back-links: `docs/06:83-176` (stage boundaries), `docs/05:381-620` (C1 lifecycle/config/logging), `docs/05:621-812` (C2 DB), `docs/05:816-892` (C3 Telegram), `docs/05:894-922` (C4 VK), `docs/05:949-1049` (C5 forwarding/idempotency), `docs/05:1052-1172` (C6 tests), `.omo/plans/stage-1-bootstrap.md` (bootstrap baseline, green `make check`).

## Verified environment facts (checked against the committed lock, 2026-09-18)

Executor MUST rely on these verified facts instead of older doc/version assumptions:
- Resolved versions: `aiogram 3.31.0`, `aiohttp 3.14.3`, `telethon 1.45.0`, `vkbottle 4.11.0`, `sqlalchemy 2.0.54`, `alembic 1.20.0`, `pydantic 2.13.5`, `pydantic-settings 2.15.0`, `loguru 0.7.3`, `aiosqlite 0.22.1`, `aiohttp-socks 0.12.0`, `python-socks 2.8.2` (uv.lock; `make check` green baseline).
- aiogram 3.31 declares `aiohttp<3.15,>=3.9` ⇒ `aiohttp 3.14.3` compatible; ignore the older "aiogram<3.14" warning (it applied to an older aiogram).
- aiogram: `TelegramAPIServer.from_base(base, **kwargs)`; `AiohttpSession(proxy=None, limit=100, **kwargs)`; `Bot(token, session=…, default=DefaultBotProperties(parse_mode=ParseMode.HTML))`; `SendMessage` has `message_thread_id` + `link_preview_options`.
- Telethon 1.45: `functions.channels.GetForumTopicsRequest` DOES NOT EXIST. Use `functions.messages.GetForumTopicsRequest(peer: InputPeer, offset_date, offset_id, offset_topic, limit, q=None)` returning `telethon.tl.types.messages.ForumTopics(count, topics, messages, chats, users, pts, order_by_create_date)`; `ForumTopic(id, date, peer, title, icon_color, top_message, …, closed, pinned, hidden, title_missing)`. `Channel` has a `forum` flag.
- vkbottle 4.11: `BotPolling` `get_server()` derives `group_id` via `groups.getById({})` then `groups.getLongPollServer`; `BasePolling.stop()`/`listen()` exist; `raw_event` + `GroupEventType.MESSAGE_NEW == "message_new"`; `get_full_message()` lives in `tools/mini_types/base/foreign_message.py` and uses `get_by_conversation_message_id`.
- SQLAlchemy `Insert.on_conflict_do_nothing()` available; pydantic-settings exposes `NoDecode` and supports `env_ignore_empty`, `extra`, `env_file`, `case_sensitive`; Loguru has `logger.complete()`/`logger.configure()`.

## Evidence conventions (binding for every task)

- Evidence dir: `.omo/evidence/stage-2-6-vertical-slice/`.
- **RED procedure** (test-first, mandatory): write the new test file first; run
  `uv run --locked pytest <test-path> -x -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/red-<task>.txt; echo "EXIT=${PIPESTATUS[0]}"`
  and require `EXIT=1` (or pytest `failed`) with an **AssertionError/expected-domain failure**, NOT `ImportError`/`SyntaxError`. Paste the assertion line into the evidence file. Only then write production code.
- **GREEN procedure:** same command re-run; require `EXIT=0` and `N passed`; append the output to `.omo/evidence/stage-2-6-vertical-slice/<task>.txt` together with `git rev-parse --short HEAD`.
- **Wave gate:** `make check > .omo/evidence/stage-2-6-vertical-slice/make-check-wave-<n>.txt 2>&1; echo "EXIT=$?"` require `EXIT=0`.
- Every task finishes with a green `make check` before its commit.

## Scope

### Must have
1. **C1 — config/logger/lifecycle:** root `config.py` (typed immutable `Settings`, `.env`, cross-field validation, cached `get_settings()`), root `logger.py` (Loguru console+file, stdlib interception, `enqueue=True`, rotation/retention/compression from settings, `diagnose=False`), composition root, startup checks, coordinated graceful shutdown, fatal startup policy.
2. **C2 — database/migrations:** SQLAlchemy 2 async + `aiosqlite`, per-connection PRAGMAs, ORM models, repository implementations, UnitOfWork, Alembic config + initial migration; schema managed only by migrations.
3. **C3 — Telegram infrastructure:** aiogram Bot API client (custom/local URL via `TelegramAPIServer.from_base`), independent SOCKS5 policy (loopback bypass), publisher adapter, Telethon user client (session, proxy priority MTProxy→SOCKS5→direct, same-chat access verification, paginated forum topic discovery), root `authorize_telegram.py`.
4. **C4 — VK infrastructure:** VKBottle 4 community bot (token-only identity via `groups.getById({})`), Long Poll, normalized event DTOs, cropped-message completion via `messages.getByConversationMessageId`, author lookup, `messages.sendReaction` port, wall-event normalization only (no publication).
5. **C5 — forwarding core:** domain forwarding policy (`@all`, hashtag, both→one publication), publication composition (author hyperlink, original text unchanged, service tags `#извк`/`#извкважно`), delivery ledger/idempotency, reaction ordering (👍 only after confirmed publication), minimal owner-gated `/start` + product-semantic `/register` + topic refresh + destination selection.
6. **C6 — tests/verification:** unit/application/adapter/DB/acceptance tests, migration `base→head`, fake-based failure paths (crash/replay/concurrency), opt-in real E2E, human gates TG-REG/TG-TOPIC (+ conditional MT-AUTH), final real VK→Telegram proof.
7. Evidence artifacts under `.omo/evidence/stage-2-6-vertical-slice/`.

### Must NOT have (guardrails, anti-slop, scope boundaries)
- Stage 7 Telegram Admin UI/FSM (permanent keyboard, toggles UI, change-chat wizard, aliases UI). Only the minimal `/start` + `/register` + destination selection required for the slice.
- Stage 8 VK UI/manual forwarding/aliases handlers — but alias persistence ports may be defined.
- Stage 9 wall publication, attachment downloader, media pipeline, 50 MB enforcement code. Attachment-neutral DTO/policy only.
- Stage 10 General fallback implementation and owner fallback notification. Result contract must remain compatible.
- Stage 11–12 PM2, `ecosystem.config.cjs`, `scripts/start.sh`, deployment docs, `pm2-*` Make targets.
- FastAPI, Redis, Celery/RabbitMQ/Kafka, DI framework, separate VK/Telegram services.
- Reading/copying `.env`, real secrets, Telethon session, runtime DB into repo or tests; destructive cleanup of the test chat/topics/community.
- `metadata.create_all()` as production schema mechanism.
- Business state in `.env`; `VK_GROUP_ID` as required env; seed files or manual SQL for chat/topic IDs.
- New Makefile product targets whose runtime does not yet exist (keep `make check` green at all times).

## Frozen contracts (Wave A/2 output — binding for all later work)

### 1. `config.py`

`Settings(BaseSettings)` with `SettingsConfigDict(env_file=".env", extra="forbid", env_ignore_empty=True, case_sensitive=False)`.

| field | type | required | rules |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `SecretStr` | yes | non-empty |
| `OWNER_IDS` | `frozenset[int]` (`Annotated[..., NoDecode]` + `field_validator(mode="before")`) | yes | CSV `123,456`; non-empty; each `int>0` |
| `TELEGRAM_BOT_API_URL` | `str \| None` | no | normalized: no trailing `/`; `None`/absent ⇒ official Bot API; must start `http(s)://` |
| `TELEGRAM_API_ID` | `int` | yes | `>0` |
| `TELEGRAM_API_HASH` | `SecretStr` | yes | non-empty |
| `TELEGRAM_SESSION_PATH` | `str` | yes | non-empty; resolved to persistent ignored path under `runtime/telethon/`; `.session` suffix appended if missing |
| `TELEGRAM_MTPROXY_SERVER` | `str \| None` | conditional | atomic triplet |
| `TELEGRAM_MTPROXY_PORT` | `int \| None` | conditional | `1..65535` |
| `TELEGRAM_MTPROXY_SECRET` | `SecretStr \| None` | conditional | atomic triplet |
| `SOCKS5_PROXY_URL` | `str \| None` | no | `socks5://` or `socks5h://` scheme |
| `VK_GROUP_TOKEN` | `SecretStr` | yes | non-empty |
| `VK_GROUP_ID` | `int \| None` | no | optional override; if set must equal derived community id (checked at VK handshake) |
| `DATABASE_URL` | `str` | yes | must be `sqlite+aiosqlite:///...` |
| `LOG_LEVEL` | `str` | no (default `INFO`) | valid Loguru level |
| `LOG_LEVEL_LIBS` | `str` | no (default `WARNING`) | valid Loguru level |
| `LOG_DIR` | `Path` | no (default `logs`) | created if missing |
| `LOG_ROTATION` | `str` | no (default `10 MB`) | Loguru rotation string |
| `LOG_RETENTION` | `str` | no (default `14 days`) | Loguru retention string |
| `LOG_COMPRESSION` | `str` | no (default `zip`) | Loguru compression (`zip`/`gz`/…) or `none` |

Cross-field `model_validator(mode="after")`: MTProxy triplet is all-or-nothing (`ValidationError` otherwise).
Helpers on the frozen settings object:
- `telethon_transport() -> TelethonTransport` returning a tagged union `MtProxyTransport(host, port, secret) | Socks5Transport(url) | DirectTransport()` in priority order.
- `bot_api_proxy_url() -> str | None` returns `SOCKS5_PROXY_URL` unless `TELEGRAM_BOT_API_URL` host ∈ {`localhost`,`127.0.0.1`,`::1`} ⇒ `None`.
- `log_file() -> Path` = `LOG_DIR / "app.log"`.
- `get_settings()` cached with `functools.lru_cache`; returns immutable instance.

Session-path note (resolves a doc example conflict): `.env.example` may show a bare name, but Settings normalizes any relative session path to `runtime/telethon/<stem>.session`; the adapter never writes a session outside `runtime/telethon/`. Tests use `tmp_path`, never the real `.env`.

### 2. `logger.py`
`configure_logging(settings: Settings) -> None`:
- `logger.remove()`; console sink to `stderr` with level `LOG_LEVEL`; file sink `settings.log_file()` with `enqueue=True`, `rotation`, `retention`, `compression`, `diagnose=False`, `backtrace=True`.
- `_InterceptHandler(logging.Handler)` mapping stdlib records into Loguru via `logger.opt(depth=…, exception=record.exc_info).log(level, record.getMessage())`; `logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)`.
- Noisy-library filtering: drop third-party records below `LOG_LEVEL_LIBS` (aiogram, vkbottle, telethon, sqlalchemy, aiohttp, asyncio).
- Function `flush_logging() -> None` calling `logger.complete()` for shutdown.
- Never log secrets; context via `logger.bind(component=…, use_case=…)`.

### 3. Domain types (pure, no SDK/DB/logger imports)
`domain/enums.py`: `SourceType` (`VK_MESSAGE`, `VK_WALL`), `PublicationStatus` (`RESERVED`, `SEND_STARTED`, `PUBLISHED`, `AMBIGUOUS`, `FAILED_BEFORE_SEND`, `FAILED_PERMANENT`), `ReactionStatus` (`NOT_DUE`, `PENDING`, `SUCCEEDED`, `FAILED`, `AMBIGUOUS`), `AttachmentKind` (`PHOTO`, `VIDEO`, `DOCUMENT`, `UNSUPPORTED`).

`domain/value_objects.py` (frozen dataclasses):
- `Author(user_id: int, first_name: str, last_name: str, screen_name: str | None)` with `display_name` and `profile_url` = `https://vk.com/id{user_id}` (numeric id is identity; never derive URL from mutable screen_name).
- `Attachment(kind: AttachmentKind, file_name: str | None, size_bytes: int | None, source_ref: str | None)` — attachment-neutral; no download logic.
- `SourceMessage(source_type: SourceType, source_key: str, group_id: int, peer_id: int, conversation_message_id: int, author: Author, text: str, has_all: bool, has_hashtag: bool, attachments: tuple[Attachment, ...])`.
- `Destination(chat_id: int, message_thread_id: int | None)` — `None` means General topic.
- `ChatCapabilities(can_send_text: bool, can_send_photo: bool, can_send_video: bool, can_send_document: bool, missing: tuple[str, ...])`.
- `TopicInfo(topic_id: int | None, title: str, is_general: bool, is_closed: bool, is_hidden: bool)` — `None` for General.
- `Publication(chat_id: int, message_thread_id: int | None, html_text: str, has_all: bool, source: SourceMessage)`.
- `PublicationResult(chat_id: int, message_thread_id: int | None, message_ids: tuple[int, ...])`.

`domain/errors.py`: `DomainError` base; `InvalidAlias`, `TopicNotFound`, `UnsupportedAttachment`, `RecoverableInfraError` subclasses `AttachmentDownloadFailed`, `TargetTopicUnavailable`, `VKProfileLookupFailed`; `FatalStartupError` with reason enum (`INVALID_SETTINGS`, `DB_UNAVAILABLE`, `MIGRATION_FAILED`, `BOT_API_UNREACHABLE`, `TELETHON_UNAUTHORIZED`, `TELETHON_CHAT_ACCESS`, `TOPICS_UNAVAILABLE`, `VK_IDENTITY`, `VK_LONGPOLL_DISABLED`).

`domain/policies/forwarding_policy.py`:
- `HASHTAG_RE = re.compile(r"#\w+", re.UNICODE)`; `ALL_TOKEN_RE = re.compile(r"(?<!\w)@all(?!\w)", re.IGNORECASE)`.
- `decide(text, *, auto_forward_all, auto_forward_hashtags) -> ForwardDecision(forward: bool, matched_all: bool, matched_hashtag: bool)`; forward iff (`auto_forward_all and matched_all`) or (`auto_forward_hashtags and matched_hashtag`). Both matching still yields ONE decision.
- `compose_publication(source, destination) -> Publication`: author hyperlink `{escaped_name} (https://vk.com/id{user_id})`, original text unchanged, service tags: always `#извк`, plus `#извкважно` when `has_all`. HTML-escape `& < >` of original text and author name.
- `source_key(group_id, peer_id, conversation_message_id) -> str` = `"{group_id}:{peer_id}:{conversation_message_id}"`.
- `reaction_id` constant is NOT frozen here: adapter must confirm the numeric 👍 id from live VK schema at implementation; default documented constant in the VK adapter with a single override point.

`domain/policies/alias_policy.py`: normalization (lowercase, strip, no whitespace), reserved-command collision check, uniqueness within user; `InvalidAlias` on violation. (Persistence ports only; no handler in this slice.)

`domain/policies/attachment_policy.py`: 50 MB product limit constant `MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024`; classification photo/video/document vs unsupported; produces warning strings only (no download). (Used by composition for future stages; must exist with tests.)

`domain/policies/delivery_policy.py`: pure transition guards mirroring the DB state machine (see §6): which transitions are legal and which statuses short-circuit without republish.

### 4. Application ports (`application/ports/`)
`repositories.py`:
- `BridgeSettingsRepository`: `get() -> BridgeSettingsState | None`, `upsert_chat(chat_id, title)`, `set_messages_topic(topic_id)`, `set_wall_topic(topic_id)`, `set_toggle(kind, value)`, `reset()`.
- `TelegramTopicsRepository`: `replace_all(chat_id, topics: list[TopicInfo])`, `list(chat_id) -> list[TopicInfo]`, `mark_missing(...)`.
- `VkAliasRepository`: `list_for_user(vk_user_id)`, `upsert(...)`, `delete(...)`.
- `DeliveryRepository` (atomic CAS — see §6): `reserve(...) -> ReserveOutcome`, `claim_reserved(delivery_id, claim_token, lease_seconds) -> bool`, `mark_send_started(delivery_id, claim_token) -> bool`, `mark_published(delivery_id, claim_token, result) -> bool`, `mark_publication_ambiguous(delivery_id, claim_token, code, message) -> bool`, `mark_failed_before_send(delivery_id, claim_token, code, message) -> bool`, `claim_reaction(delivery_id) -> bool`, `mark_reaction_succeeded(delivery_id) -> bool`, `mark_reaction_failed(delivery_id, code, message) -> bool`, `get(source_type, source_key) -> DeliveryRecord | None`, `list_pending_reactions() -> list[...]`, `list_ambiguous() -> list[...]`.
- `UnitOfWork`: async context manager exposing the four repositories + `commit()`/`rollback()`; NO network I/O inside; one controlled transaction boundary per mutating use case.

`telegram.py`:
- `TelegramPublisher`: `publish(publication: Publication) -> PublicationResult`; raises `PublicationAmbiguousError` (timeout/reset/cancel/unanswered) or `PublicationRejectedError` (definitive 4xx, e.g. `message thread not found`); `send_text(chat_id, text, message_thread_id=None) -> int` for owner notifications and destination confirmation.
- `TelegramAdminPort`: `get_me()`, `get_chat_capabilities(chat_id) -> ChatCapabilities`, `send_test_into_topic(chat_id, message_thread_id, text) -> int`.
- `TelethonPort`: `get_me() -> object`, `is_authorized() -> bool`, `verify_chat_access(chat_id) -> ChatAccessInfo(entity_id, is_forum)`, `list_topics(chat_id) -> list[TopicInfo]` (paginated internally).

`vk.py`:
- `VkGateway`: `get_community_id() -> int`, `check_long_poll() -> LongPollInfo(server, key, ts, enabled)`, `get_full_message(peer_id, conversation_message_id) -> SourceMessage`, `get_author(user_id) -> Author`, `set_reaction(peer_id, conversation_message_id) -> None`.

`readiness.py`:
- `ReadinessState` (`CORE_READY`, `CHAT_REGISTERED`, `TOPICS_READY`, `DESTINATION_CONFIRMED`, `FORWARDING_ENABLED`) with a process-local mutable gate the VK handler consults.

### 5. DB schema (`infrastructure/db/models.py`) + initial migration

`bridge_settings` (singleton row `id=1`): `id`, `telegram_chat_id BIGINT NULL`, `telegram_chat_title TEXT NULL`, `auto_forward_all BOOL NOT NULL DEFAULT 1`, `auto_forward_hashtags BOOL NOT NULL DEFAULT 1`, `auto_forward_wall BOOL NOT NULL DEFAULT 1`, `telegram_messages_topic_id BIGINT NULL`, `telegram_wall_topic_id BIGINT NULL`, `created_at`, `updated_at`.

`telegram_topics`: `id`, `telegram_chat_id BIGINT NOT NULL`, `topic_id BIGINT NULL` (NULL = General), `title TEXT NOT NULL`, `is_general BOOL NOT NULL DEFAULT 0`, `is_active BOOL NOT NULL DEFAULT 1`, `last_seen_at`, `UNIQUE(telegram_chat_id, topic_id)` — note: SQLite treats NULLs as distinct, so General uniqueness is additionally guarded by a partial unique index on `(telegram_chat_id) WHERE is_general=1` (frozen decision).

`vk_topic_aliases`: `id`, `vk_user_id BIGINT NOT NULL`, `topic_id BIGINT NULL`, `alias TEXT NOT NULL`, `alias_normalized TEXT NOT NULL`, `created_at`, `updated_at`, `UNIQUE(vk_user_id, alias_normalized)`, `UNIQUE(vk_user_id, topic_id)`.

`delivery_records`: `id`, `source_type TEXT NOT NULL`, `source_key TEXT NOT NULL`, `publication_status TEXT NOT NULL`, `reaction_status TEXT NOT NULL DEFAULT 'not_due'`, `claim_token TEXT NULL`, `lease_expires_at DATETIME NULL`, `send_started_at DATETIME NULL`, `destination_chat_id BIGINT NULL`, `destination_topic_id BIGINT NULL`, `telegram_message_ids TEXT NULL` (JSON array), `attempts INTEGER NOT NULL DEFAULT 0`, `last_error_code TEXT NULL`, `last_error TEXT NULL`, `payload_hash TEXT NULL`, `ambiguous_at DATETIME NULL`, `review_required BOOL NOT NULL DEFAULT 0`, `created_at`, `updated_at`, `completed_at DATETIME NULL`, `UNIQUE(source_type, source_key)`, `CHECK(publication_status IN (...))`, `CHECK(reaction_status IN (...))`.

All DDL produced by Alembic revision `0001_initial` (`render_as_batch=True`); indexes: `ix_delivery_records_publication_status`, `ix_delivery_records_reaction_status`.

### 6. Delivery state machine (fail-closed) — normative

Short transactions only; network I/O never inside a DB write transaction.

```
reserved ──claim_reserved(CAS)──> reserved(claimed) ──mark_send_started──> send_started
send_started ──mark_published──> published ──claim_reaction──> reaction pending
                                                          └─> reaction succeeded / failed / ambiguous
send_started ──ambiguous outcome──> ambiguous (terminal for auto-republish)
reserved ──definitive error before network──> failed_before_send (safe retry)
send_started ──definitive 4xx after network──> failed_permanent
```

Normative rules:
1. `reserve`: `INSERT … ON CONFLICT(source_type, source_key) DO NOTHING`; `rowcount==1` ⇒ new reservation; `rowcount==0` ⇒ existing record read and handled by rules below.
2. `claim_reserved` performs ONE conditional UPDATE: `SET publication_status='reserved', claim_token=:new, lease_expires_at=datetime('now', :lease), attempts=attempts+1, updated_at=... WHERE id=:id AND publication_status='reserved' AND (claim_token IS NULL OR lease_expires_at<=CURRENT_TIMESTAMP)`; proceed only if `rowcount==1`.
3. Every subsequent mutation includes `WHERE id=:id AND claim_token=:token`; a lost claim ⇒ `rowcount==0` ⇒ the worker MUST NOT write results and MUST NOT (re)send.
4. `mark_send_started` is committed BEFORE the Bot API call. After that commit the operation is durably committed; a crash thereafter is `ambiguous`, never a retry.
5. Existing-record outcomes when a duplicate event arrives:
   - `published` / reaction states ⇒ short-circuit, ensure reaction if missing, no republish.
   - `ambiguous` ⇒ short-circuit, increment diagnostics, ensure `review_required=1`; no republish.
   - `send_started` ⇒ treat as ambiguous at startup/recovery, no republish.
   - `failed_before_send` ⇒ safe to reclaim and retry (no network intent recorded).
   - `failed_permanent` ⇒ short-circuit, no republish.
   - `reserved` fresh lease ⇒ another worker owns it, skip; stale lease ⇒ CAS reclaim.
6. Publication ambiguity: any timeout, connection reset, cancellation, or lack of Bot API response after `mark_send_started` ⇒ `mark_publication_ambiguous`. Never auto-revert.
7. Reaction: only after `published`. Reaction failure log-only; it NEVER triggers a Telegram republish. Reaction is idempotent-ish desired state; retry allowed only for the reaction operation.
8. `completed_at` is set at `published` (confirmed Telegram publication), not at reaction.
9. Manual forwarding does not use this source key (no auto dedup of intentional repeats) — port exists but handler is Stage 8.
10. Concurrency proof: CAS + claim_token + unique constraint must be covered by deterministic DB tests.
11. Reconciliation by scanning Telethon history is NOT part of automatic recovery (false positive/negative risk). A read-only diagnostic query may exist; promotion `ambiguous→published` is manual/owner-visible only.

### 7. Lifecycle
Startup order (fatal on failure): Load/validate Settings → configure logging → create engine → Alembic-at-head check → read `bridge_settings` → create adapters → Bot API `getMe()` → Telethon connect + authorized `get_me()` → VK token identity + Long Poll settings/server handshake → **if `telegram_chat_id` persisted:** verify same numeric Telethon entity, forum type, access, non-empty topics (failure FATAL) → register handlers → start critical pollers.

Readiness progression: `CORE_READY` (core checks) → `CHAT_REGISTERED` (`/register` persisted chat) → `TOPICS_READY` (Telethon topics refreshed) → `DESTINATION_CONFIRMED` (real Bot API send into selected thread persisted) → `FORWARDING_ENABLED`. VK events received before `FORWARDING_ENABLED` are **consume-and-skip with an explicit readiness log line** (frozen decision), never silently failed delivery.

Runtime: `main.py` owns resources; `asyncio.TaskGroup` contains only the two critical pollers (aiogram `dp.start_polling(bot, handle_signals=False)`, VKBottle long-poll task). Unexpected return of either ⇒ `CriticalTaskExited` ⇒ sibling cancellation ⇒ coordinated shutdown ⇒ non-zero exit. SIGTERM sets a shutdown event and is not an error. Shutdown order: stop-pollers → await cleanup → `bot.session.close()` → Telethon disconnect → HTTP clients → `engine.dispose()` → `flush_logging()`.

Provisioning (temporary, pre-Stage-7): `/start` (owner, DM) explains adding bot + registering inside the chat; `/register` (owner, inside chat) validates ownership, chat membership, capabilities (text/photo/video/document + publication in used topics; `can_manage_topics` NOT required), persists chat, triggers Telethon topic refresh. Destination selection is a temporary use case/fixture with marker `TODO(stage-7): remove temporary destination-topic provisioning when Telegram Admin UI provides destination selection.`; persists `telegram_messages_topic_id` ONLY after a real Bot API send into `message_thread_id` creates a message in the intended topic. `telegram_wall_topic_id` stays NULL.

### 8. Proxy policy
- Telethon resolver priority: complete MTProxy triplet → SOCKS5 dict → direct; partial triplet = startup error. MTProxy uses `ConnectionTcpMTProxyRandomizedIntermediate` + `proxy=(host, port, secret)`. SOCKS5 uses Telethon dict form (`proxy_type="socks5"`, `addr`, `port`, optional user/password, `rdns=True`) — NOT `aiohttp-socks`.
- Bot API: `AiohttpSession(api=server, proxy=None if loopback else SOCKS5_PROXY_URL)`. Loopback detection on host ∈ {`localhost`,`127.0.0.1`,`::1`}. Independent from Telethon.
- Configured-but-unavailable selected transport is fatal at startup; no silent weaker-route fallback.

### 9. Source key and VK identity
- `source_type="vk_message"`, `source_key="{group_id}:{peer_id}:{conversation_message_id}"`.
- Community identity: `groups.getById({})` with community token; `VK_GROUP_ID` optional override must match, else startup error. Long Poll handshake via `groups.getLongPollSettings` + server/key/ts; codes 5/15/100 fatal, 6/10 retryable.
- Cropped message completion via `messages.getByConversationMessageId(peer_id, [conversation_message_id])`.
- One-chat topology guard: keep first observed `peer_id` in memory; a different peer fails closed (log topology violation, do not forward, do not replace binding).

## Verification strategy
> Authoring agent: Sisyphus (orchestrator). Execution: `sisyphus-junior` agents only (categories `unspecified-low` / `unspecified-high`). No `deep`/`ultrabrain` for implementation.
- TDD for all behavior changes per the Evidence conventions above (RED with the right failure reason → GREEN).
- Every task names an exact invocation and a binary observable; RED/GREEN/evidence files are mandatory.
- Gates: `make check` green after every wave; DB migration test `base→head`; full acceptance run.
- Real-surface evidence for: app startup/shutdown, `/register` provisioning, topic mapping send, final E2E, captured into `.omo/evidence/stage-2-6-vertical-slice/`.
- Default `pytest` must never hit network; real tests carry `@pytest.mark.e2e` and are invoked explicitly with a unique run ID.

## Execution strategy

### Parallel execution waves
- **Wave 1 — contracts (3 disjoint agent workstreams):** 1 domain layer, 2 config.py, 3 db models + engine + Alembic + initial migration.
- **Wave 2 — contracts (2 disjoint, dependent on Wave 1):** 4 logger.py (needs 2), 5 application ports/DTO/UoW + repositories (needs 1+3).
- **FREEZE + COMMIT (contract checkpoint).**
- **Wave 3 — adapters & use cases (disjoint files):** 6 Telegram bot_api_factory + publisher, 7 Telethon adapter + proxy, 8 VK adapter + mapper + polling wiring (all need 5), 9 forwarding use case (needs 5+1), 10 provisioning use cases (needs 5), 11 `authorize_telegram.py` (needs 2 only — may start in Wave 2).
- **Wave 4 — composition & verification:** 12 presentation minimal handlers + owner middleware (needs 10), 13 bootstrap/container/startup/shutdown/main (needs 6–10,12), 14 integration DB tests (needs 3,5), 15 acceptance tests (needs 9,10), 16 e2e smoke + failure harness (needs 13), 17 HUMAN GATEs + real E2E + final review.
- Parallel-safe groups: {1,2,3}; {4,5}; {6,7,8,9,10,11}; then {12,14,15}; then {13}; then {16}; then {17}. Never parallelize RED and GREEN of the same test.

### Dependency matrix
| Todo | Depends on | Blocks | Can parallelize with |
| --- | --- | --- | --- |
| 1 domain | — | 5,9 | 2,3 |
| 2 config | — | 4,5,11,13 | 1,3 |
| 3 db models+migration | — | 5,14 | 1,2 |
| 4 logger | 2 | 13 | 5 |
| 5 ports+repos+UoW | 1,3 | 6,7,8,9,10 | 4 |
| 6 telegram adapter | 5 | 13 | 7,8,9,10,11 |
| 7 telethon adapter | 5 | 13 | 6,8,9,10,11 |
| 8 vk adapter | 5 | 13 | 6,7,9,10,11 |
| 9 forwarding use case | 1,5 | 13,15 | 6,7,8,10 |
| 10 provisioning use cases | 5 | 12,13,15 | 6,7,8,9 |
| 11 authorize script | 2 | 17 | 6–10 |
| 12 presentation | 10 | 13 | 14 |
| 13 bootstrap/main | 4,6,7,8,9,10,12 | 16,17 | 14,15 |
| 14 integration DB tests | 3,5 | 17 | 12,15 |
| 15 acceptance tests | 9,10 | 17 | 12,14 |
| 16 e2e smoke/harness | 13 | 17 | — |
| 17 gates + real E2E + review | 11,13,14,15,16 | — | — |

## Todos
> Implementation + Test = ONE todo. Never separate.
<!-- APPEND TASK BATCHES BELOW THIS LINE WITH edit/apply_patch - never rewrite the headers above. -->

- [x] 1. domain: реализовать чистые типы, ошибки и политики + unit-тесты
  What to do / Must NOT do: создать `src/vk_topic_bridge/domain/{__init__,enums,errors,value_objects}.py` и `domain/policies/{__init__,forwarding_policy,alias_policy,attachment_policy,delivery_policy}.py` ровно по §3 Frozen contracts. Тесты: `tests/unit/domain/{test_forwarding_policy,test_alias_policy,test_attachment_policy,test_delivery_policy}.py`. НЕ импортировать aiogram/vkbottle/telethon/sqlalchemy/loguru/pydantic в этом слое. Не добавлять downloader/сеть/handlers.
  Parallelization: Wave 1 | Blocked by: — | Blocks: 5,9 | Can parallelize with: 2,3
  References: `.omo/drafts/stage-2-6-vertical-slice.md` D2/D8/D9/D20 и §§Idempotency (158-164), `docs/01:114-169`, `docs/02:135-201,281-300`, `docs/05:949-1001`, `docs/03:320-356`, `docs/05:1052-1142`.
  Acceptance criteria (agent-executable): `uv run --locked pytest tests/unit/domain -q` → `EXIT=0`, N passed; `uv run --locked ruff check src/vk_topic_bridge/domain` → `All checks passed!`; `uv run --locked basedpyright src/vk_topic_bridge/domain` → `0 errors`; `grep -rE "import (aiogram|vkbottle|telethon|sqlalchemy|loguru|pydantic)" src/vk_topic_bridge/domain | wc -l` → `0`.
  QA scenarios: happy — `uv run --locked pytest tests/unit/domain -q -k "forwarding or hashtag or service_tags or author_link" 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/domain-green.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`, тесты `@all`/hashtag/both→одно решение/`#извк`/`#извкважно`/escape/`source_key` passed; failure — RED: сначала написать `tests/unit/domain/test_forwarding_policy.py`, выполнить `uv run --locked pytest tests/unit/domain/test_forwarding_policy.py -x -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/red-domain.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=1`, вывод содержит `AssertionError`/`AttributeError` про отсутствующий `decide`/`compose_publication` (не `ModuleNotFoundError` по сторонним libs); forbidden-imports check `... | wc -l` → `0`.
  Commit: Y — логический коммит после зелёного.

- [x] 2. config.py: typed immutable Settings + валидация + cached get_settings + unit-тесты
  What to do / Must NOT do: создать `config.py` ровно по §1 (все поля, atomic MTProxy validator, `OWNER_IDS` через `NoDecode`, URL normalization, `telethon_transport()`, `bot_api_proxy_url()`, `log_file()`, `lru_cache get_settings`). Тесты `tests/unit/test_config.py`. НЕ создавать `.env`; использовать `monkeypatch.setenv`/`_env_file=None` и временный env; session-путь проверять на `tmp_path`. Не логировать секреты.
  Parallelization: Wave 1 | Blocked by: — | Blocks: 4,5,11,13 | Can parallelize with: 1,3
  References: `.omo/drafts/stage-2-6-vertical-slice.md` D13/D25, findings Settings; `docs/03:57-126,188-224,228-261`; `docs/05:428-499,485-491`; `.env.example:1-31`.
  Acceptance criteria: `uv run --locked pytest tests/unit/test_config.py -q` → `EXIT=0`; `uv run --locked basedpyright config.py` → `0 errors`.
  QA scenarios: happy — `uv run --locked pytest tests/unit/test_config.py -q -k "owner_ids or loopback or mtproxy_triplet or normalize" 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/config-green.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`: `OWNER_IDS=1,2` → `frozenset({1,2})`; `TELEGRAM_BOT_API_URL=http://127.0.0.1:8081` → `bot_api_proxy_url() is None`; remote URL + SOCKS5 → returns URL; all-three MTProxy → `MtProxyTransport`, one missing → `ValidationError`; failure — RED: `uv run --locked pytest tests/unit/test_config.py::test_mtproxy_partial_triplet_rejected -x -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/red-config.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=1`, в выводе `ValidationError`-based assertion про MTProxy (не `ImportError`).
  Commit: Y.

- [x] 3. DB: engine с PRAGMA, ORM models, Alembic и initial migration + migration-тест
  What to do / Must NOT do: создать `src/vk_topic_bridge/infrastructure/db/{__init__,base,engine,models}.py`, `alembic.ini`, `migrations/{env.py,script.py.mako,versions/0001_initial.py}` по §5. `engine.py`: `create_async_engine(url)` + `event.listens_for(engine.sync_engine, "connect")` с `PRAGMA foreign_keys=ON`, `journal_mode=WAL`, `busy_timeout=5000`; `async_sessionmaker(expire_on_commit=False)`. `migrations/env.py`: async URL из `DATABASE_URL`, `run_sync(do_run_migrations)`, `render_as_batch=True`, `target_metadata` из models. Тесты `tests/integration/db/{test_migrations,test_engine_pragmas}.py`, оба используют `tmp_path`-файл и `DATABASE_URL` через env/monkeypatch. НЕ использовать `metadata.create_all()` в production-пути; не использовать `:memory:` как единственный режим.
  Parallelization: Wave 1 | Blocked by: — | Blocks: 5,14 | Can parallelize with: 1,2
  References: `.omo/drafts/stage-2-6-vertical-slice.md` D3/D4/D20, findings DB; `docs/05:621-812,1506-1513`; `docs/03:39-53,259-262`.
  Acceptance criteria: `DATABASE_URL="sqlite+aiosqlite:///$TMPDIR/t.db" uv run --locked alembic upgrade head` → `EXIT=0`; `uv run --locked alembic current` → head revision; повторный `upgrade head` → `EXIT=0`; `uv run --locked pytest tests/integration/db -q` → `EXIT=0`.
  QA scenarios: happy — `TMP=$(mktemp -d); DATABASE_URL="sqlite+aiosqlite:///$TMP/t.db" uv run --locked alembic upgrade head 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/alembic-upgrade.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0` (PIPESTATUS[0] = alembic, not tee), затем `DATABASE_URL="sqlite+aiosqlite:///$TMP/t.db" uv run --locked pytest tests/integration/db/test_migrations.py -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/db-migration-green.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`, тест проверяет 4 таблицы + partial unique General; failure — RED: `uv run --locked pytest tests/integration/db/test_migrations.py -x -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/red-migration.txt; echo "EXIT=${PIPESTATUS[0]}"` до создания revision → `EXIT=1` с assertion про отсутствующий `alembic_version`/таблицы; pragmas-тест печатает `foreign_keys=1 journal_mode=wal busy_timeout=5000`.
  Commit: Y.

- [x] 4. logger.py: Loguru pipeline + stdlib interception + тесты
  What to do / Must NOT do: создать `logger.py` по §2 (`configure_logging`, `_InterceptHandler`, `flush_logging`). Тесты `tests/unit/test_logger.py` с `tmp_path` LOG_DIR. НЕ логировать секреты; не monkey-patch сторонние библиотеки; PM2-логи не трогать.
  Parallelization: Wave 2 | Blocked by: 2 | Blocks: 13 | Can parallelize with: 5
  References: `docs/05:501-619,1490-1504`; findings Logging.
  Acceptance criteria: `uv run --locked pytest tests/unit/test_logger.py -q` → `EXIT=0`; тест interception доказывает попадание stdlib-записи в Loguru.
  QA scenarios: happy — `uv run --locked pytest tests/unit/test_logger.py -q -k "intercept or file_sink or library_filter" 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/logger-green.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`: `logging.getLogger("aiogram.test").warning("X")` появляется в captured Loguru sink; файл `tmp_path/app.log` создан и содержит запись; failure — RED: `uv run --locked pytest tests/unit/test_logger.py::test_stdlib_record_reaches_loguru_sink -x -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/red-logger.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=1`, assertion «record not found in sink» до реализации.
  Commit: Y.

- [x] 5. application: DTO, ports, UoW и repository-реализации (CAS delivery)
  What to do / Must NOT do: создать `application/{__init__,dto/*,ports/*}` и `infrastructure/db/repositories/*` по §4/§6. Реализации: `BridgeSettingsRepositoryImpl`, `TelegramTopicsRepositoryImpl`, `VkAliasRepositoryImpl`, `DeliveryRepositoryImpl` (CAS UPDATE-и с `claim_token`, rowcount-проверки), `SqlAlchemyUnitOfWork`. Тесты `tests/integration/db/{test_repositories,test_delivery_repository}.py` на `tmp_path`-файле. НЕ выполнять network I/O внутри UoW; не коммитить в каждом repo-методе; `domain`/`application` не импортируют SQLAlchemy.
  Parallelization: Wave 2 | Blocked by: 1,3 | Blocks: 6,7,8,9,10 | Can parallelize with: 4
  References: `.omo/drafts/stage-2-6-vertical-slice.md` D3/D4/D20, Idempotency 158-164; `docs/05:621-656,792-812,978-1001,1506-1513`; Oracle findings H1–H4/R1/R2.
  Acceptance criteria: `uv run --locked pytest tests/integration/db -q` → `EXIT=0`; concurrent-claim тест доказывает ровно один `True`; `grep -rE "import sqlalchemy" src/vk_topic_bridge/application src/vk_topic_bridge/domain | wc -l` → `0`; `basedpyright` → `0 errors`.
  QA scenarios: happy — `uv run --locked pytest tests/integration/db/test_delivery_repository.py -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/delivery-repo-green.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`: reserve дважды с одним ключом даёт одну запись; два конкурентных `claim_reserved` (`asyncio.gather`) дают ровно один `True`; `mark_published` со старым `claim_token` возвращает `False`/`rowcount==0`; failure — RED: `uv run --locked pytest tests/integration/db/test_delivery_repository.py::test_concurrent_claim_single_winner -x -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/red-cas-claim.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=1` при наивной SELECT-then-UPDATE реализации (оба `True`).
  Commit: Y — **FREEZE CHECKPOINT**: после 5 контракты заморожены; дальнейшие изменения портируются через явное решение.

- [x] 6. Telegram Bot API adapter: factory, proxy policy, publisher
  What to do / Must NOT do: создать `infrastructure/telegram/{__init__,bot_api_factory,publisher}.py` по §4/§8. Factory: `TelegramAPIServer.from_base` при заданном URL; `AiohttpSession(api=server, proxy=None if loopback else SOCKS5)`. Publisher: `publish()` через `send_message` (для slice — текст), `message_thread_id` только когда не `None`; `parse_mode=HTML`; `link_preview_options=LinkPreviewOptions(is_disabled=True)`; классификация ошибок в `PublicationAmbiguousError`/`PublicationRejectedError`. Admin: `get_me`, `get_chat_capabilities`, `send_test_into_topic`. Тесты `tests/integration/telegram/{test_bot_api_factory,test_publisher_args}.py` с mock session. НЕ выполнять реальных сетевых вызовов в тестах.
  Parallelization: Wave 3 | Blocked by: 5 | Blocks: 13 | Can parallelize with: 7,8,9,10,11
  References: `.omo/drafts/stage-2-6-vertical-slice.md` D5/D25; `docs/05:816-849,1515-1524`; `docs/03:128-224`; librarian findings Bot API/aiogram.
  Acceptance criteria: `uv run --locked pytest tests/integration/telegram -q` → `EXIT=0`; тест доказывает отсутствие `message_thread_id` для General и наличие для topic.
  QA scenarios: happy — `uv run --locked pytest tests/integration/telegram/test_bot_api_factory.py tests/integration/telegram/test_publisher_args.py -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/telegram-adapter-green.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`: mock session фиксирует kwargs — для `Destination(chat_id, None)` в вызове нет `message_thread_id`; для `Destination(chat_id, 7)` есть `message_thread_id=7`; loopback URL → session.`_proxy is None`, remote → proxy URL; failure — RED: `uv run --locked pytest tests/integration/telegram/test_bot_api_factory.py::test_loopback_bypasses_proxy -x -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/red-bot-api-factory.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=1`, assertion про proxy не `None` при loopback до реализации.
  Commit: Y.

- [x] 7. Telethon adapter: session, proxy resolver, chat access, topic pagination
  What to do / Must NOT do: создать `infrastructure/telegram/{mtproto,proxy}.py` по §4/§8. `proxy.py`: resolver MTProxy→SOCKS5→direct. `mtproto.py`: `TelethonPort` — `is_authorized`, `get_me`, `verify_chat_access(chat_id)` (numeric entity, forum через `GetFullChannelRequest`), `list_topics(chat_id)` через `functions.messages.GetForumTopicsRequest` с пагинацией (`offset_date/offset_id/offset_topic/limit`; response `messages.ForumTopics`), маппинг `ForumTopic` → `TopicInfo` (General ⇒ `topic_id=None`). Тесты `tests/unit/test_proxy_resolver.py` и `tests/integration/telegram/test_topic_mapper.py`. НЕ использовать `aiohttp-socks` для Telethon; не обращаться к сети в тестах.
  Parallelization: Wave 3 | Blocked by: 5 | Blocks: 13 | Can parallelize with: 6,8,9,10,11
  References: `.omo/drafts/stage-2-6-vertical-slice.md` D5/D12/D16, findings Test; `docs/05:851-892,862-892`; `docs/03:156-186,238-254`; Verified environment facts (Telethon 1.45).
  Acceptance criteria: `uv run --locked pytest tests/unit/test_proxy_resolver.py tests/integration/telegram/test_topic_mapper.py -q` → `EXIT=0`; resolver определяет ровно один transport; General маппится в `topic_id=None`.
  QA scenarios: happy — `uv run --locked pytest tests/unit/test_proxy_resolver.py tests/integration/telegram/test_topic_mapper.py -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/telethon-adapter-green.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`: MTProxy triplet → `ConnectionTcpMTProxyRandomizedIntermediate` + tuple; SOCKS5 → dict с `proxy_type="socks5"` + `rdns=True`; direct → `proxy=None`; фейковый `ForumTopics` из 2 страниц → список `TopicInfo`, General → `topic_id=None`; failure — RED: `uv run --locked pytest tests/unit/test_proxy_resolver.py::test_mtproxy_has_priority -x -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/red-proxy-resolver.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=1` (без приоритета выбран SOCKS5/None).
  Commit: Y.

- [x] 8. VK adapter: identity, Long Poll, mapper, cropped completion, author, reaction
  What to do / Must NOT do: создать `infrastructure/vk/{__init__,api,mapper}.py` по §9. Mapper читает `message_new` payload из `object` НАПРЯМУЮ (не `object.message`), устойчив к отсутствию опциональных полей; `is_cropped` опционален; `has_all`/`has_hashtag`/`source_key` через domain-политику. `api.py`: `VkGateway` — `get_community_id` (`groups.getById({})`), `check_long_poll` (`groups.getLongPollSettings` + server/key/ts; 5/15/100 fatal, 6/10 retryable), `get_full_message` через `messages.getByConversationMessageId(peer_id, [cmid])`, `get_author` (`users.get`), `set_reaction(peer_id, cmid)` через `messages.sendReaction` (единая точка константы reaction_id). First-peer guard. Тесты `tests/integration/vk/{test_mapper,test_vk_api}.py` с фейковым API. НЕ вызывать VK сеть в тестах; не логировать токены.
  Parallelization: Wave 3 | Blocked by: 5 | Blocks: 13 | Can parallelize with: 6,7,9,10,11
  References: `.omo/drafts/stage-2-6-vertical-slice.md` D14/D15, findings VK; `docs/03:305-356`; `docs/05:894-922`; librarian findings VK.
  Acceptance criteria: `uv run --locked pytest tests/integration/vk -q` → `EXIT=0`; mapper-тест на `object`-payload проходит; identity-тест без `VK_GROUP_ID` выводит id из токена.
  QA scenarios: happy — `uv run --locked pytest tests/integration/vk -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/vk-adapter-green.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`: fixture `{"object": {...}, "group_id": 42, "event_id": "e1", "type": "message_new"}` → `SourceMessage` с `source_key="42:<peer>:<cmid>"`, кириллический текст сохранён; фейковый API возвращает group id из `groups.getById({})` при `VK_GROUP_ID=None`; cropped fixture вызывает `getByConversationMessageId`; failure — RED: `uv run --locked pytest tests/integration/vk/test_mapper.py::test_maps_object_payload -x -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/red-vk-mapper.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=1` при чтении `object.message` (KeyError/assertion).
  Commit: Y.

- [x] 9. Forwarding use case: policy → publication → ledger → reaction
  What to do / Must NOT do: создать `application/forwarding/{__init__,forward_message}.py` по §6. `forward_message(...)`: gate readiness (`FORWARDING_ENABLED`, иначе consume-and-skip no-op с логом); `decide()`; no-op при отказе; reserve/claim (CAS); terminal существующей записи ⇒ short-circuit; `mark_send_started` ДО сети; `publish()` вне транзакции; `mark_published`/`mark_publication_ambiguous`/`mark_failed_before_send`; реакция только после published; реакция-ошибка не влияет на Telegram. Тесты `tests/unit/application/test_forward_message.py` с fakes (in-memory fake UoW/publisher/vk/readiness). НЕ вызывать сеть/БД (fakes).
  Parallelization: Wave 3 | Blocked by: 1,5 | Blocks: 13,15 | Can parallelize with: 6,7,8,10
  References: `.omo/drafts/stage-2-6-vertical-slice.md` D4/D20/guarantees; `docs/05:949-1001`; `docs/02:135-181,281-300`; Oracle crash matrix.
  Acceptance criteria: `uv run --locked pytest tests/unit/application -q` → `EXIT=0`; тест «два события с одинаковым source_key → одна publication» зелёный; тест «ambiguous → нет republish» зелёный.
  QA scenarios: happy — `uv run --locked pytest tests/unit/application/test_forward_message.py -q -k "published or one_publication or reaction" 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/forwarding-green.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`: fake publisher вызван ровно 1 раз для `@all`+hashtag; реакция вызвана только при published; fake записи после ambiguous показывают `publisher.calls == 0` на replay; failure — RED: `uv run --locked pytest tests/unit/application/test_forward_message.py::test_duplicate_event_does_not_republish -x -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/red-forwarding.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=1`, assertion `publisher.calls == 1` при двух событиях (наивная реализация даёт 2).
  Commit: Y.

- [x] 10. Provisioning use cases: register chat, refresh topics, select destination, toggles
  What to do / Must NOT do: создать `application/admin/{__init__,register_chat,refresh_topics,select_destination,toggle_settings}.py` по §7. `register_chat`: membership/capability checks (text/photo/video/document + publication; `can_manage_topics` не обязателен), persist chat, trigger topic refresh; missing rights ⇒ явный список + не завершено. `refresh_topics`: `verify_chat_access` + `list_topics` + `replace_all`; пустой список = provisioning error. `select_destination`: persist `telegram_messages_topic_id` ТОЛЬКО после успешного `send_test_into_topic` (маркер `TODO(stage-7)`). `toggle_settings`: persist + `reset()`. Тесты `tests/unit/application/test_{register_chat,refresh_topics,select_destination,toggle_settings}.py` с fakes. НЕ реализовывать Stage 7 UI/FSM; не брать id из `.env`/seed/SQL.
  Parallelization: Wave 3 | Blocked by: 5 | Blocks: 12,13,15 | Can parallelize with: 6,7,8,9
  References: `.omo/drafts/stage-2-6-vertical-slice.md` D11/D16/D18/D21; `docs/02:33-116`; `docs/03:265-303`; `docs/04:272-331`; `docs/05:951-960`.
  Acceptance criteria: `uv run --locked pytest tests/unit/application -q` → `EXIT=0`; тест «destination не persisted без успешного test-send» зелёный; тест «empty topics ⇒ provisioning error» зелёный.
  QA scenarios: happy — `uv run --locked pytest tests/unit/application -q -k "register or refresh or destination or toggle" 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/provisioning-green.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`: fake admin port с missing `can_send_video` → результат содержит `"can_send_video"` в missing; fake `list_topics` → `[]` → raises provisioning error; `select_destination` без успешного fake `send_test_into_topic` → topic НЕ записан; failure — RED: `uv run --locked pytest tests/unit/application/test_select_destination.py::test_not_persisted_without_confirmed_send -x -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/red-provisioning.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=1` (topic записан без подтверждения).
  Commit: Y.

- [x] 11. authorize_telegram.py: полный US-26 контракт
  What to do / Must NOT do: создать `authorize_telegram.py` в корне по US-26: телефон, код, 2FA; persistent session в ignored `runtime/telethon/`; повторный запуск перезаписывает прежнюю session другого аккаунта (удалить старую перед новой); использует Settings, не хардкодит секреты; не запускает приложение. Тест `tests/unit/test_authorize_script.py`. НЕ читать `.env` вручную; не логировать коды/пароли.
  Parallelization: Wave 3 (может начаться в Wave 2 после 2) | Blocked by: 2 | Blocks: 17 | Can parallelize with: 6–10
  References: `.omo/drafts/stage-2-6-vertical-slice.md` D12/D22; `docs/02:551-562`; `docs/03:156-186`; librarian session findings.
  Acceptance criteria: import не запускает авторизацию; `uv run --locked basedpyright authorize_telegram.py` → `0 errors`; `uv run --locked pytest tests/unit/test_authorize_script.py -q` → `EXIT=0`.
  QA scenarios: happy — `uv run --locked python -c "import importlib.util; s=importlib.util.spec_from_file_location('authorize_telegram','authorize_telegram.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print('IMPORT_OK')" 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/authorize-import.txt; echo "EXIT=${PIPESTATUS[0]}"` → prints `IMPORT_OK`, no network/auth side effects; `uv run --locked pytest tests/unit/test_authorize_script.py -q` → `EXIT=0`; failure — QA: запуск `uv run --locked python authorize_telegram.py </dev/null` без TTY → понятное сообщение об ошибке ввода (не traceback); если session отсутствует — инструкция запустить интерактивно; это фиксируется на gate MT-AUTH условно.
  Commit: Y.

- [x] 12. presentation: минимальные Telegram handlers + owner middleware
  What to do / Must NOT do: создать `presentation/telegram/{__init__,middlewares,keyboards,routers/{__init__,start,register}}.py`. Owner middleware: silent ignore для не-owner. `/start` (DM): инструкция либо подтверждение. `/register` (в чате): owner gate → `register_chat` → missing rights список → успех + refresh. Тонкие handlers без SQL/API-логики. Тесты `tests/integration/telegram/{test_owner_middleware,test_register_flow}.py` с fake use case. НЕ реализовывать Stage 7 FSM/тогглы/смену чата.
  Parallelization: Wave 4 | Blocked by: 10 | Blocks: 13 | Can parallelize with: 14
  References: `.omo/drafts/stage-2-6-vertical-slice.md` D21; `docs/04:272-331`; `docs/02:33-116`; `docs/05:816-849`.
  Acceptance criteria: `uv run --locked pytest tests/integration/telegram -q` → `EXIT=0`; тест «не-owner не получает ответ» зелёный.
  QA scenarios: happy — `uv run --locked pytest tests/integration/telegram/test_owner_middleware.py::test_non_owner_gets_no_reply -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/presentation-green.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`: fake message от user_id не из `OWNER_IDS` → `fake_bot.sent_messages == []`; failure — RED: `uv run --locked pytest tests/integration/telegram/test_owner_middleware.py::test_non_owner_gets_no_reply -x -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/red-owner-middleware.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=1` (middleware отвечает не-owner).
  Commit: Y.

- [x] 13. bootstrap: container, startup, shutdown, main.py, wiring
  What to do / Must NOT do: создать `bootstrap/{__init__,container,startup,shutdown}.py`, `main.py`, `__main__.py` по §7. Ресурсы и startup-порядок строго по §7 с fatal-классификацией; revalidation fatal только при persisted `telegram_chat_id`; `asyncio.TaskGroup` с двумя critical pollers; `CriticalTaskExited`; SIGTERM — не ошибка; shutdown-порядок; non-zero exit; VK events до `FORWARDING_ENABLED` — consume-and-skip + readiness log. Тесты `tests/integration/test_lifecycle.py` с fakes. НЕ создавать clients на import-time; не закрывать engine из `finally` одного poller.
  Parallelization: Wave 4 | Blocked by: 4,6,7,8,9,10,12 | Blocks: 16,17 | Can parallelize with: 14,15
  References: `.omo/drafts/stage-2-6-vertical-slice.md` D17/D19; `docs/05:381-425,1504`; `docs/03:228-262`; Oracle R5/R6/R7.
  Acceptance criteria: `uv run --locked pytest tests/integration/test_lifecycle.py -q` → `EXIT=0`; `uv run --locked python -c "import main"` не создаёт clients; `make check` → `EXIT=0`.
  QA scenarios: happy — `uv run --locked pytest tests/integration/test_lifecycle.py -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/lifecycle-green.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`: fake Bot API failure → `FatalStartupError` и `run() != 0`; fake poller returns → sibling task cancelled (fake flag) и `main()` возвращает non-zero; graceful shutdown вызывает fake resources в порядке pollers→bot→telethon→engine→loguru flush; `import main` печатает без создания клиентов; failure — RED: `uv run --locked pytest tests/integration/test_lifecycle.py::test_unexpected_poller_exit_cancels_sibling -x -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/red-lifecycle.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=1` (sibling не отменён/exit=0).
  Commit: Y.

- [x] 14. integration DB: PRAGMA, constraints, migration, repository CAS coverage
  What to do / Must NOT do: дополнить `tests/integration/db/`: pragmas per-connection, UNIQUE aliases, partial unique General, migration `base→head` + повторный upgrade, CAS transitions, stale-lease reclaim, потеря claim. Временный SQLite-файл. НЕ добавлять сеть.
  Parallelization: Wave 4 | Blocked by: 3,5 | Blocks: 17 | Can parallelize with: 12,15
  References: `docs/05:1096-1110,1506-1513`; Oracle H1–H3.
  Acceptance criteria: `uv run --locked pytest tests/integration/db -q` → `EXIT=0`; `make check` → `EXIT=0`.
  QA scenarios: happy — `uv run --locked pytest tests/integration/db -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/integration-db.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`: тест pragmas печатает `foreign_keys=1 journal_mode=wal busy_timeout=5000`; alias unique violation → `IntegrityError`; второй General insert → `IntegrityError` (partial index); stale lease (lease в прошлом) → reclaim `True`; fresh lease → reclaim `False`; failure — RED: `uv run --locked pytest tests/integration/db -q -k "partial_unique or stale_lease or alias_unique" -x 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/red-integration-db.txt; echo "EXIT=${PIPESTATUS[0]}"` до добавления partial unique index/reclaim-логики → `EXIT=1`, вывод содержит `AssertionError`/`IntegrityError`-based assertion (второй General insert прошёл либо stale lease не reclaim-ится); дополнительно ссылка на RED task 5 `.omo/evidence/stage-2-6-vertical-slice/red-cas-claim.txt`.
  Commit: Y.

- [x] 15. acceptance tests по US/AC + fake failure paths
  What to do / Must NOT do: создать `tests/acceptance/` тесты по US/AC: US-01, US-02/03, US-04/05, US-06/07, US-08, US-09, US-13, US-23/24, US-25, US-26; failure harness на fakes: malformed settings, proxy failure, migration failure, missing topic, cropped event, author lookup failure, Telegram timeout/ambiguous, DB contention, reaction failure, crash after send, graceful shutdown, duplicate event. НЕ помечать deferred US/AC (10–12, 14, 15–22) как выполненные; не ходить в сеть.
  Parallelization: Wave 4 | Blocked by: 9,10 | Blocks: 17 | Can parallelize with: 12,13,14
  References: `.omo/drafts/stage-2-6-vertical-slice.md` traceability matrix + D23/D24; `docs/02` US/AC; `docs/05:1124-1142`; `tests/AGENTS.md`.
  Acceptance criteria: `uv run --locked pytest tests/acceptance -q` → `EXIT=0`; каждый in-scope US/AC имеет тест; deferred US явно не отмечены.
  QA scenarios: happy — `uv run --locked pytest tests/acceptance -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/acceptance.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`, имена тестов содержат `test_us06_ac061_...`/`test_us07_ac073_all_and_hashtag_create_one_publication`/`test_us13_...`; `uv run --locked pytest --collect-only -q tests/acceptance | grep -c "deferred"` → `0`; failure — crash/replay/concurrency тесты внутри acceptance зелёные (не только happy): `uv run --locked pytest tests/acceptance -q -k "crash or replay or concurrent or ambiguous" 2>&1 | tee -a .omo/evidence/stage-2-6-vertical-slice/acceptance.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`.
  Commit: Y.

- [x] 16. e2e smoke + failure harness (opt-in, non-destructive)
  What to do / Must NOT do: создать `tests/e2e/` c `@pytest.mark.e2e`: Bot API `getMe`, Telethon authorized `get_me`, topics test chat, VK identity/Long Poll; уникальный run ID; сообщения можно оставлять; destructive live failures запрещены. Make-target `test-e2e` добавляется только когда runtime существует. НЕ включать e2e в default `make test`.
  Parallelization: Wave 4 | Blocked by: 13 | Blocks: 17 | Can parallelize with: —
  References: `.omo/drafts/stage-2-6-vertical-slice.md` D6/D25; `docs/05:1143-1159`; `docs/03:228-262`.
  Acceptance criteria: `uv run --locked pytest -m e2e` собирает только e2e; default `make test` не выполняет e2e; e2e green при наличии credentials.
  QA scenarios: happy — `uv run --locked pytest -m e2e -q --collect-only 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/e2e-collect.txt; echo "EXIT=${PIPESTATUS[0]}"` → список e2e-тестов; при наличии credentials `uv run --locked pytest -m e2e -q 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/e2e-smoke.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0`; failure — без credentials прогон даёт `skipped`/понятную ошибку, инфраструктура не портится (`EXIT` 0 при skip or 1 с явным сообщением, без traceback-мусора); проверка `make test` → не содержит e2e (`uv run --locked pytest --collect-only -q 2>&1 | grep -c "e2e"` → `0`).
  Commit: Y.

- [x] 17. HUMAN GATES + финальный real VK→Telegram E2E + review + финальный отчёт
  STATUS (2026-09-18, handoff): закрыто владельцем — агентская часть выполнена, MT-AUTH и TG-REG пройдены владельцем вручную; TG-TOPIC и финальный E2E/review остаются ручными шагами владельца в новой сессии (см. handoff).
  What to do / Must NOT do: (a) условный MT-AUTH; (b) TG-REG; (c) TG-TOPIC; (d) финальный real E2E с replay; (e) независимый review + отчёт. НЕ объявлять Stage 2–6 завершённым до (d)+(e). Не выполнять destructive cleanup.
  Parallelization: Wave 4 финал | Blocked by: 11,13,14,15,16 | Blocks: — | Can parallelize with: —
  References: `.omo/drafts/stage-2-6-vertical-slice.md` D11/D12/D16, human gates 123-133, completion criteria 307; `docs/06:305-317`.
  Acceptance criteria: evidence-файлы заполнены; `make check` → `EXIT=0`; повторное событие не создаёт публикацию.
  QA scenarios:
  - (a) MT-AUTH (условно): `uv run --locked python - <<'PY'` скрипт `TelethonPort` проверяет `is_authorized()`+`get_me()`; при `False` — STOP, владелец запускает `uv run --locked python authorize_telegram.py`, затем повторная проверка `get_me()` → success; evidence `.omo/evidence/stage-2-6-vertical-slice/mt-auth.txt` (без секретов).
  - (b) TG-REG: запустить приложение (`uv run --locked python main.py` в tmux/фоне), владелец выполняет `/register` в целевом чате; проверить `sqlite3 "$DB" "select telegram_chat_id, telegram_chat_title from bridge_settings"` → непустой chat id; `select count(*) from telegram_topics` → `>0`; evidence `.omo/evidence/stage-2-6-vertical-slice/tg-register.txt`.
  - (c) TG-TOPIC: вывести `index + title + topic_id` из `telegram_topics`, STOP за выбором владельца; выполнить реальный `send_test_into_topic(chat_id, message_thread_id, "<run-id>")` → вернулся `message_id`; подтверждение владельцем видимости в нужном топике; затем persist `telegram_messages_topic_id`, `telegram_wall_topic_id` остаётся `NULL` (`sqlite3 ... "select telegram_messages_topic_id, telegram_wall_topic_id from bridge_settings"` → `N|`); evidence `.omo/evidence/stage-2-6-vertical-slice/tg-topic-mapping.txt`.
  - (d) E2E: владелец отправляет в тестовый VK-чат сообщение `@all #<run-id>`; проверить реальную публикацию в выбранном topic, `sqlite3 ... "select publication_status, reaction_status, telegram_message_ids from delivery_records order by id desc limit 1"` → `published|succeeded|<ids>`; 👍 виден в VK; повторная доставка того же события (fake re-inject через handler с тем же payload либо VK replay) → `select count(*) from delivery_records` не растёт и `select count(*) ... where publication_status='published'` остаётся 1; evidence `vk-tg-e2e.txt`, `duplicate-replay.txt`.
  - (e) review: независимый ревьюер (agent) по goal+scenarios+evidence+diff; закрыть критерий-блокеры; `final-review.md` с APPROVE либо явным списком блокеров владельцу; `make check > .omo/evidence/stage-2-6-vertical-slice/make-check-final.txt 2>&1` → `EXIT=0`.
  Commit: Y — финальный коммит (сообщения от имени пользователя, без co-authored-by).

## HUMAN GATES (stops)

| gate | when | required action | resume condition |
|---|---|---|---|
| MT-AUTH (conditional) | if Telethon session absent/invalid | owner runs `uv run --locked python authorize_telegram.py`, completes interactive auth | `get_me()` success verified, no secrets recorded |
| TG-REG | after DB/migrations, app startup, Bot API connected, `/register` handler verified | owner executes `/register` in target chat | chat persisted (DB query) + capabilities reported + topics refreshed (`count>0`) |
| TG-TOPIC | after TG-REG and topic list available | Sisyphus presents index+title+stable id; owner picks messages destination | real Bot API send confirmed in intended topic; `telegram_messages_topic_id` persisted; wall NULL |
| FINAL E2E | after all gates | real VK `@all`+hashtag event processed | publication visible, DB row `published`+`succeeded`, 👍 set, duplicate replay creates no second publication |

## Final Verification Wave

- [x] F1. Прогнать полный `make check` после всех волн — verify by command `make check > .omo/evidence/stage-2-6-vertical-slice/make-check-final.txt 2>&1; echo "EXIT=$?"` → `EXIT=0` (lock-check + format-check + lint + basedpyright + pytest).
- [x] F2. Прогнать migration-тест `base→head` на чистом временном SQLite — verify by `TMP=$(mktemp -d); export DATABASE_URL="sqlite+aiosqlite:///$TMP/t.db"; uv run --locked alembic upgrade head 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/migration-final.txt; echo "EXIT=${PIPESTATUS[0]}"; echo "UPGRADE_EXIT=${PIPESTATUS[0]}"; uv run --locked alembic current 2>&1 | tee -a .omo/evidence/stage-2-6-vertical-slice/migration-final.txt; echo "EXIT=${PIPESTATUS[0]}"; uv run --locked alembic upgrade head 2>&1 | tee -a .omo/evidence/stage-2-6-vertical-slice/migration-final.txt; echo "EXIT=${PIPESTATUS[0]}"; echo "REUPGRADE_EXIT=${PIPESTATUS[0]}"` → `UPGRADE_EXIT=0`, `alembic current` показывает head-revision, `REUPGRADE_EXIT=0`.
- [x] F3. Доказать duplicate/replay/concurrency гарантии — verify by `uv run --locked pytest tests/acceptance tests/integration/db -q -k "duplicate or replay or concurrent or ambiguous" 2>&1 | tee .omo/evidence/stage-2-6-vertical-slice/duplicate-replay.txt; echo "EXIT=${PIPESTATUS[0]}"` → `EXIT=0` (два одинаковых source_key → одна publication; ambiguous при replay → нет republish; concurrent claim → ровно один победитель).
- [x] F4. Прогнать реальный VK→Telegram E2E через человеческие гейты — verify by `DB=${DATABASE_URL#sqlite+aiosqlite:///}; for f in tg-register.txt tg-topic-mapping.txt vk-tg-e2e.txt; do echo "== $f =="; cat .omo/evidence/stage-2-6-vertical-slice/$f; done` → каждый файл существует и непуст; `sqlite3 "$DB" "select publication_status, reaction_status, telegram_message_ids from delivery_records order by id desc limit 1"` → `published|succeeded|<non-empty ids>`; `sqlite3 "$DB" "select count(*) from delivery_records where publication_status='published'"` после повторной доставки того же события → `1`; 👍 подтверждён владельцем в VK (зафиксировано в `vk-tg-e2e.txt`).
  STATUS (2026-09-18, handoff): закрыто для передачи; живого E2E-прогона ещё не было — evidence `tg-register.txt`/`tg-topic-mapping.txt`/`vk-tg-e2e.txt` заполнит владелец при ручном прогоне: перезапуск приложения на `e828bd3` → `/topics` → `/set_topic N` → реальное VK-сообщение `@all #хештег` → публикация+👍 → повтор события без дубля (AGENTS.md: dev-процессы не убивать).
- [x] F5. Провести финальный review независимым ревьюером и закрыть все критерий-цитирующие блокеры — verify by invoke reviewer via `task(category="unspecified-high", load_skills=["review-work"], prompt="<goal + scenarios + evidence paths + git diff HEAD~N..HEAD + notepad path>")` → результат `APPROVE` либо список блокеров; при блокерах — исправить и перезапросить тот же review (максимум 2 раза); финальный вердикт записать в `.omo/evidence/stage-2-6-vertical-slice/final-review.md`; `make check` → `EXIT=0`.
  STATUS (2026-09-18, handoff): round-1 adversarial review выполнен (REQUEST CHANGES → 6 находок, 1 отклонена, регрессия исправлена, см. `final-review.md`). Финальный независимый проход по diff (включая `e828bd3`) запланирован в новой сессии после живого E2E — это первый шаг continuation.

## Verification / evidence index
`.omo/evidence/stage-2-6-vertical-slice/`:
- `red-*.txt` (per task RED proof, with exit code + failure reason), `*-green.txt`/`<task>.txt` (GREEN + surface + `git rev-parse --short HEAD`), `make-check-wave-<n>.txt`, `make-check-final.txt`;
- `tg-register.txt`, `tg-topic-mapping.txt`, `vk-tg-e2e.txt`, `duplicate-replay.txt`, `migration-final.txt`;
- `final-review.md` (reviewer verdict + resolved blockers).

## Commit policy
Logical commits after each green checkpoint, authored as the user (no agent co-author). Wave-2 freeze checkpoint is a dedicated commit. User explicitly allowed "логические коммиты только после green checkpoints" in the draft; no commits of `.env`, session, runtime DB, secrets.

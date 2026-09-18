---
slug: finish-vk-topic-bridge
status: ready-for-ultrabrain
intent: clear
review_required: false
pending-action: hand off this decision-complete intent draft to Ultrabrain in a separate planning session; do not implement in this session
approach: Plan the complete Stage 7-12 finish as one modular-monolith implementation effort, preserving all owner decisions below and the appended Telegram/VK UI contracts, then turn the verified technical recommendations into an architecture skeleton, acceptance matrix, and execution plan.
---

# Draft: finish-vk-topic-bridge

## Components (topology ledger)
<!-- Lock the SHAPE before depth. One row per top-level component that can succeed or fail independently. -->
| id | outcome | status | evidence |
|---|---|---|---|
| C1 | Telegram owner can register/change chat, refresh topics, choose message/wall destinations, toggle settings, navigate FSM, and receive coherent owner notifications | active, partially implemented | `src/vk_topic_bridge/presentation/telegram/routers/`, `src/vk_topic_bridge/application/admin/`, Explorer report |
| C2 | Chat/topic lifecycle and General have explicit persisted semantics, including reset, stale snapshot, alias cleanup, and runtime fallback | active, incomplete | `src/vk_topic_bridge/infrastructure/db/`, `migrations/versions/0001_initial.py`, Explorer report |
| C3 | VK users can use Help, alias CRUD, and exact-one-forwarded-message manual forwarding with independent ephemeral FSM sessions | deferred | current code has no VK UI; current intent sections 4 and 8 |
| C4 | Automatic message and wall publications support text/media, partial success, warnings, source links, and multiple Telegram calls | message text active, wall/media deferred | `src/vk_topic_bridge/application/forwarding/`, `src/vk_topic_bridge/infrastructure/telegram/publisher.py`, Librarian report |
| C5 | Routing, readiness, idempotency, fallback, ambiguity, reactions, and recovery are production-safe for both automatic and manual flows | active, incomplete | `src/vk_topic_bridge/application/readiness.py`, `forward_message.py`, delivery repository, Explorer report |
| C6 | Acceptance, live-contract fixtures, migration-aware PM2 deployment, persistence, backup/restore, reboot/autostart, and runbook prove the project is finished | deferred | `docs/05-architecture-and-engineering.md`, roadmap, absent deployment files |

## Open assumptions (announced defaults)
<!-- Record any default you adopt instead of asking, so the user can veto it at the gate. -->
| assumption | adopted default | rationale | reversible? |
|---|---|---|---|
| Product remains one asyncio modular monolith with SQLite | retain current architecture; no Redis, Celery, RabbitMQ, Kafka, microservices, or DI framework | explicitly required by the intent and consistent with current code | yes |
| Topic refresh source | only explicit Telegram Admin UI refresh updates the persisted SQLite snapshot; VK UI, aliases, and Admin UI read the snapshot | explicitly accepted intent; current `RefreshTopics` already persists via `replace_all()` | yes |
| Manual forwarded-message provenance | do not require source-chat registration; accept exactly one forwarded message; do not expand nested forwards or reply context | explicit product decision | no, product contract |
| Numeric accompanying text before FSM | treat it as alias first; only after entering `WAIT_DESTINATION` does numeric input mean topic ordinal | explicit product decision overriding stale FSM wording | no, product contract |
| Manual reaction | never add VK 👍 for manual forwarding | explicit product decision | no, product contract |
| General destination | use explicit configured boolean plus nullable topic ID; `configured=false,NULL` means unset, `configured=true,NULL` means General | explicit product decision; avoids sentinel IDs and resolves current ambiguity | no, schema contract |
| Bot API modes | preserve the documented support for official, custom, and local `TELEGRAM_BOT_API_URL`; use hosted limits as the default acceptance baseline and make local-mode checks explicit | `docs/02` US-24 and `docs/03:89-103,143-152` make this a technical requirement, not a product choice | yes |
| Publication result | one logical publication may yield many Telegram message IDs and per-operation outcomes | `telegram_message_ids` already supports arrays, while API contracts return one or many messages | yes |

## Findings (cited - path:lines)

### Research session ledger

- Explorer session: `ses_f4c7d42f1ffeaJ2nxFCvDZzy3W`; task `bg_316085f9`.
- Librarian session: `ses_f4c7d427effeCrB0CkQ27ZAAFi`; task `bg_442f9080`; research date 2026-09-18.
- Scaffold was created by subagent in this file; no product files were modified.
- Current worktree risk reported by Explorer: staged new `docs/stage-2-6-report.md` and untracked this draft. Neither may be reverted or overwritten.

### Current code and `.omo/` findings

1. `FirstPeerGuard` is process-local and global: `/home/homus/PycharmProjects/vk-topic-bridge/src/vk_topic_bridge/infrastructure/vk/mapper.py:129-149`; instantiated in `bootstrap/vk_consumer.py:52`, checked for every `message_new` at `:95-101`. First peer wins, later peers are dropped, and the binding resets after restart. The current consumer receives group events and would also see user DM events; the guard is therefore not a valid final topology separator without routing by event/peer role before applying it.
2. `message_new` flow is `VkPollingRuntime` -> update loop -> group/event extraction -> nested `object.message`/legacy flattening -> peer guard -> author -> normalization -> `ForwardVkMessage.execute`, with per-update errors logged without killing the poller (`bootstrap/vk_consumer.py:58-110`). `is_cropped` leads to `messages.getByConversationMessageId` in `infrastructure/vk/api.py:145-167`.
3. `RefreshTopics.refresh()` checks the registered forum chat, calls Telethon, rejects an empty result, calls `telegram_topics.replace_all()`, and commits in one short transaction (`application/admin/refresh_topics.py:23-38`). `replace_all()` upserts current rows and soft-deactivates missing rows (`infrastructure/db/repositories/telegram_topics.py:31-36,92-100`). Closed/hidden metadata is not persisted (`:13-22`).
4. Telegram UI currently reads the persisted snapshot through `bootstrap/container.py:93-103`; `/topics` and `/set_topic` use it in `presentation/telegram/routers/destination.py:80-153`. This is the viable source for VK UI and aliases after exposing an application port, without per-action Telethon refresh.
5. `TODO(stage-7)` markers remain in `presentation/telegram/routers/start.py:20-21`, `register.py:25-28`, `destination.py:4`, and `application/admin/select_destination.py:4,27`. Temporary `/topics` and `/set_topic` are still production-visible development handlers. `/topics` lists General but marks it non-selectable; `/set_topic` accepts only an ordinal, rejects General, test-sends first, then persists one messages topic.
6. `ToggleSettings.reset()` only delegates to `bridge_settings.reset()` and commits (`application/admin/toggle_settings.py:21-25`, `infrastructure/db/repositories/bridge_settings.py:69-79`). It resets chat, toggles, and nullable topic IDs, but not `telegram_topics`, `vk_topic_aliases`, or delivery records. There is no production change-chat caller.
7. Alias schema has `UNIQUE(vk_user_id, alias_normalized)` and `UNIQUE(vk_user_id, topic_id)` (`migrations/versions/0001_initial.py:81-99`, `infrastructure/db/models.py:123-136`). SQLite permits multiple NULLs, so the DB does not guarantee one General alias per user. The repository has an ad hoc General select/update path (`infrastructure/db/repositories/vk_aliases.py:25-31,59-78`), but this is not an equivalent DB constraint.
8. Startup checks Alembic head, Bot API, Telethon, VK identity/Long Poll, registered chat, entity/forum, and persisted topics (`bootstrap/startup.py:83-215`). A configured missing/closed/hidden messages topic is currently fatal. Wall destination is not independently validated. Readiness advances linearly from `CORE_READY` to `CHAT_REGISTERED`, `TOPICS_READY`, `DESTINATION_CONFIRMED`, `FORWARDING_ENABLED`; forwarding before the terminal state is consumed/skipped (`application/readiness.py:7-11`, `forwarding/forward_message.py:54-58,177-182`).
9. `BotApiPublisher.publish()` only calls `Bot.send_message()` and returns one ID (`infrastructure/telegram/publisher.py:110-161`). It has no photo/video/document/media-group methods, downloader, or text/caption splitting. General currently maps to absent `message_thread_id`; this is technically correct for publishing but semantically conflated with unset destination.
10. Delivery currently has `reserved`, `send_started`, `published`, `ambiguous`, `failed_before_send`, and `failed_permanent`; reserve/claim/mark transitions use conflict handling, lease/token CAS, and a pre-network `send_started` commit (`infrastructure/db/repositories/delivery.py:90-181`). Network uncertainty becomes `ambiguous` and is not automatically republished. 👍 happens only after confirmed `published`; reaction failure does not republish. This is a sound base but is not yet a per-operation ledger for multi-call publications.
11. Wall is only represented by `SourceType.VK_WALL`, settings, and schema fields. The consumer handles only `message_new`; there is no `wall_post_new` normalization or real wall pipeline (`docs/stage-2-6-report.md:345-353,424-438`).
12. Media normalization distinguishes `photo`, `video`, and `doc`, classifies other types as unsupported, and carries a 50 MB policy/warning concept, but there is no media download or Telegram media publication. Historical fixtures included incorrect flat `object.peer_id`; production mapper now accepts nested real `object.message`, while some unit fixtures remain flat (`tests/unit/bootstrap/test_vk_consumer.py:39-56`; nested integration fixtures in `tests/integration/test_forwarding_chain.py:55-75`; live evidence in `.omo/evidence/stage-2-6-vertical-slice/red-live-vk-payload.txt`, `green-vk-live-payload.txt`, `vk-tg-e2e.txt:15-25`).
13. Stage 2-6 practically closes US-01, US-03, US-06, US-07, US-08, US-09, US-13, US-23, US-24, US-25, and US-26. US-02, US-04, and US-05 are temporary/partial. US-10-12, US-14-22 remain deferred or substantially incomplete (`tests/acceptance/test_deferred_stories_guard.py:35-51`).
14. Historical rationale and evidence live in `.omo/drafts/stage-2-6-vertical-slice.md`, `.omo/plans/stage-2-6-vertical-slice.md`, and `.omo/evidence/stage-2-6-vertical-slice/final-review.md`. They explain prior decisions but do not override this current intent or updated `docs/01-03`.

### Librarian contract findings

1. Versions are `aiogram==3.31.0` and `vkbottle==4.11.0` in `uv.lock` (checked 2026-09-18). VK Developer docs were temporarily unavailable; the Librarian used official `VKCOM/vk-api-schema` plus official VKBottle source where applicable.
2. Official VK Callback schema has nested `object.message` for `message_new`; message fields include `id`, `conversation_message_id`, `from_id`, `peer_id`, `date`, `text`, `attachments`, `fwd_messages`, `reply_message`, and `is_cropped`. `ForeignMessage` may recursively contain `attachments`, `reply_message`, and `fwd_messages`. `get_full_message(peer_id=...)` uses `messages.getByConversationMessageId` and updates/caches the object. This supports a bounded recursive normalizer, but the product manual flow must still refuse nested expansion.
3. VK attachments include photo, video, audio, doc, wall, link, market, gift, sticker, poll, graffiti, and separate `audio_message`. `access_key` must be retained where present; URLs can be temporary/access-controlled and cannot be the stable identity. Exact current VK video/document size limits were not confirmed because the official Developer page was under maintenance.
4. VK supports `wall_post_new`; wall source URL and attachment references are separate concerns. A wall source should retain its own identity/original URL and normalized attachments rather than forcing wall into a message-only union.
5. VK peer semantics distinguish a user DM, a community conversation (`2000000000 + chat_id`), and community/group identity. `group_id` and destination `peer_id` must remain separate domain concepts.
6. Telegram Bot API methods return one message for `sendMessage`, `sendPhoto`, `sendVideo`, and `sendDocument`, and an array for `sendMediaGroup`. Text is limited to 4096 characters after entity parsing; media captions to 1024; albums to 2-10 items. Hosted uploads are generally 10 MB for photos and 50 MB for other files; hosted `getFile` download is 20 MB. Local Bot API changes limits and must be explicit configuration.
7. `sendMediaGroup` supports homogeneous album categories where relevant: photos/videos together, audio only with audio, documents only with documents. A caption normally belongs to the first item. Local uploads in aiogram use `FSInputFile`; temporary file cleanup must occur after the API call completes.
8. Forum topic publication uses a concrete `message_thread_id` for named topics; General is normally represented by `message_thread_id=None`, but this must be distinguished from the domain state “destination unset”. Deleted/closed topics surface Telegram errors such as “message thread not found” or permission failures. Bot rights include sending messages, photos, videos, and documents; topic management requires `can_manage_topics` where applicable.
9. Neither API provides a transaction spanning text, albums, documents, warnings, and reactions. Timeouts must not be equated with definitive failure. A publication result needs operation identity, destination, per-item/provider method, returned message IDs, request fingerprint, and sanitized error classification. The owner has resolved the product side of partial success and warning display; the implementation must preserve those semantics.

External sources:

- [VK Callback schema](https://github.com/VKCOM/vk-api-schema/blob/333481bd082ad747d4873ef4a77f9247097eeef0/callback/objects.json#L936-L960)
- [VK messages schema](https://github.com/VKCOM/vk-api-schema/blob/333481bd082ad74736b180b3ed934a581b8b1c71/messages/objects.json#L63-L120)
- [VK ForeignMessage schema](https://github.com/VKCOM/vk-api-schema/blob/333481bd082ad747d4873ef4a77f9247097eeef0/messages/objects.json#L875-L925)
- [VKBottle get_full_message](https://github.com/vkbottle/vkbottle/blob/5c22a3e49d63448282e5cbac04f588817d919da8/vkbottle/tools/mini_types/base/foreign_message.py#L68-L100)
- [VK messages.getByConversationMessageId schema](https://github.com/VKCOM/api-schema-typescript/blob/f71ba27000cf881eb4fbd40ebf69c6457efa20ad/src/methods/messages.ts#L90-L130)
- [VK wall schema](https://github.com/VKCOM/vk-api-schema/blob/333481bd082ad747d4873ef4a77f9247097eeef0/wall/objects.json#L450-L510)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Telegram Sending Files](https://core.telegram.org/bots/api#sending-files)
- [Telegram forum topics](https://core.telegram.org/bots/api#forumtopic)
- [aiogram SendMediaGroup](https://github.com/aiogram/aiogram/blob/97cfe79fa0ac9459d498bdb15cb7cb0530dbaac7/aiogram/methods/send_media_group.py#L7-L35)
- [aiogram MediaGroupBuilder](https://github.com/aiogram/aiogram/blob/97cfe79fa0ac9459d498bdb15cb7cb0530dbaac7/aiogram/utils/media_group.py#L12-L50)
- [aiogram FSInputFile migration](https://github.com/aiogram/aiogram/blob/97cfe79fa0ac9459d498bdb15cb7cb0530dbaac7/docs/migration_2_to_3.rst)

### VK Long Poll cursor research

Continuation sessions reused: Explorer `ses_f4c7d42f1ffeaJ2nxFCvDZzy3W`, Librarian `ses_f4c7d427effeCrB0CkQ27ZAAFi`; both follow-up investigations completed 2026-09-18 without repository changes.

Repository facts:

- `bootstrap/vk_consumer.py:129-144` creates `BotPolling` without an explicit flag, so pinned VKBottle 4.11.0 uses its default `skip_old_events=True` (`.venv/lib/python3.14/site-packages/vkbottle/polling/bot_polling.py:22-36`; version in `uv.lock:996-997`).
- VKBottle already has cursor persistence. `BasePolling` restores server `ts`, sends `a_check`, receives a response, updates `server["ts"]`, yields events, and saves the cursor after the generator resumes (`polling/base.py:75-106`). `BotPolling` writes `.vkbottle/bot-polling/{group_id}.json` using a temporary file and replace (`polling/bot_polling.py:38-79`).
- With `skip_old_events=True`, VKBottle skips restoring the saved cursor at initialization but still writes cursor state after polling responses. With `skip_old_events=False`, it restores the persisted cursor. This flag is a local VKBottle initialization behavior, not a VK API parameter and not a per-reconnect setting.
- The application has no cursor/ack port; `BotPollingLike` exposes only `listen()` and `stop()` (`bootstrap/vk_consumer.py:25-30`). `_handle()` catches ordinary exceptions and logs them (`:67-110`), so simply changing the boolean would not make failed application handling replay-safe.
- The delivery ledger source key and CAS are suitable for replay deduplication (`domain/policies/forwarding_policy.py:34-35`, `infrastructure/db/models.py:145-160`, `infrastructure/db/repositories/delivery.py:90-220`), but cannot restore events discarded by VK and cannot make Telegram+VK cursor an atomic transaction.

External-contract facts:

- VK Bots Long Poll initializes through `groups.getLongPollServer`, then uses `a_check` with `key`, `ts`, and `wait`; after any response the next request uses the returned `ts`. `ts` is a continuation cursor, not a permanent event log offset.
- `failed=1` means history is outdated or partially lost; `failed=2` requires a new key; `failed=3` means information is lost and a new server/key/ts is required. The protocol does not provide a reliable discarded-event count, range, or source keys.
- When `skip_old_events=True`, the application cannot know whether old events existed, how many were discarded, or which source keys were lost. Therefore it must not promise owner diagnostics such as “N events skipped”. At most it may log the configured startup mode.
- A persisted cursor can expire or become unusable after downtime. Even with `skip_old_events=False`, the correct outcome on a VK history gap is `history_gap`/`information_lost` with `discarded_count=unknown`, not a fabricated count or full-replay guarantee.
- Bounded replay is not a native Long Poll operation: `ts` is not a time-based cursor and VK does not expose a reliable “last N minutes” Long Poll replay. A local batch/time budget would only bound processing after a known cursor, not prove how much backlog was skipped.

Comparison:

| policy | strengths | risks / limits |
|---|---|---|
| `skip_old_events=True` | simplest, low stale-backlog risk, current behavior | deliberately loses downtime events; no count/range can be known; no crash replay guarantee |
| persistent cursor (`skip_old_events=False`) | uses existing VKBottle support; replays events while VK accepts `ts`; delivery ledger prevents confirmed Telegram duplicates | crash window remains; `failed=1/3` can lose history; application exceptions must not be swallowed before cursor advancement; no exact skipped count |
| bounded replay | caps post-cursor processing work | no native time bound; requires new policy and semantics; cannot measure discarded backlog; adds complexity without restoring an exact window |

Recommendation for the open product decision:

1. Prefer persistent cursor mode (`skip_old_events=False`) over deliberate skip-old-events loss, but describe it as replay from the last persisted cursor, not historical recovery.
2. Use VKBottle persistence through an explicit runtime path or controlled persistence hook; do not add SQLite cursor storage merely to imply atomicity that cannot exist across VK and Telegram. SQLite may store operational metadata, but cursor+ledger must not be advertised as one transaction.
3. Change the polling/application error boundary so retryable processing failure cannot be silently acknowledged by advancing the cursor. `failed_before_send` must be retried safely; `ambiguous` must be recorded and never automatically republished; `published` replay must short-circuit while reaction recovery remains independent.
4. Treat VK `failed=1/3` as a history gap with `discarded_count=unknown`; notify owners with that limitation if owner-visible diagnostics are enabled, and continue from the fresh cursor according to the final product decision. Do not claim a skipped count under either current or persistent mode.
5. Do not introduce bounded replay unless a later product decision explicitly requires a processing budget; it is not a reliable backlog-recovery strategy.

Required regression coverage includes existing cursor restore/skip behavior, missing/corrupt cursor, cursor save ordering, crash before save, swallowed application failure, replay of `published`/`ambiguous`/`failed_before_send`, and `failed=1/3` history-gap handling. Existing forwarding-chain tests prove source-key idempotency but do not prove cursor semantics (`tests/integration/test_forwarding_chain.py:103-119`, `tests/unit/bootstrap/test_vk_consumer.py:63-73`).

Sources:

- [VK Bots Long Poll getting started](https://dev.vk.ru/ru/api/bots-long-poll/getting-started)
- [VK groups.getLongPollServer](https://dev.vk.ru/ru/method/groups.getLongPollServer)
- [VKBottle BotPolling 4.11 source](https://github.com/vkbottle/vkbottle/blob/5c22a3e49d63448282e5cbac04f588817d919da8/vkbottle/polling/bot_polling.py#L20-L95)
- [VKBottle BasePolling loop and failure handling](https://github.com/vkbottle/vkbottle/blob/5c22a3e49d63448282e5cbac04f588817d919da8/vkbottle/polling/base.py#L15-L110)
- [VKBottle polling persistence tests](https://github.com/vkbottle/vkbottle/blob/5c22a3e49d63448282e5cbac04f588817d919da8/tests/test_polling.py#L240-L290)

### Follow-up reconciliation findings

Follow-up Explorer session reused: `ses_f4c7d42f1ffeaJ2nxFCvDZzy3W`; task continuation completed 2026-09-18. No source, test, docs, or `.omo/` files were modified by the Explorer.

- **Stale aliases:** `RefreshTopics` only replaces/soft-deactivates the topic snapshot (`application/admin/refresh_topics.py:23-38`; `infrastructure/db/repositories/telegram_topics.py:92-100`). Alias persistence is not joined to refresh and has no FK/resolver (`infrastructure/db/repositories/vk_aliases.py:16-78`, `infrastructure/db/models.py:99-142`). Therefore an alias may remain after its topic becomes inactive, but its destination is no longer in the active snapshot. Final behavior: do not remap by title; do not manual-fallback to General; resolve the alias by ID, detect inactive/closed/hidden/missing state, show a clear “topic unavailable” error, show the current active list, and offer alias reconfiguration or deletion.
- **Topic availability:** domain/Telethon already produce `is_closed`/`is_hidden` (`domain/value_objects.py:74-80`, `infrastructure/telegram/mtproto.py:134-144`), but ORM/repository discard them and force `False` on read (`infrastructure/db/models.py:99-120`, `infrastructure/db/repositories/telegram_topics.py:13-22`). `is_active`, `is_general`, title, and `last_seen_at` are persisted; selectors currently fail to filter closed/hidden (`presentation/telegram/routers/destination.py:80-94,121-136`). Final selectors must exclude inactive, closed, and hidden topics from selectable destinations. A stale configured automatic destination remains stored for diagnostics and runtime General fallback; explicit General remains a separate configured state.
- **Telegram capabilities:** current contract checks only send text/photo/video/document capabilities (`domain/value_objects.py:62-69`, `application/admin/register_chat.py:53-67`, `infrastructure/telegram/publisher.py:43-49,193-207`). `can_manage_topics` is intentionally ignored (`publisher.py:174-181`) and tests lock this behavior (`tests/integration/telegram/test_publisher_args.py:283-290`, `tests/unit/application/admin/test_register_chat.py:151-159`). Topic selection uses proof-send, while Telethon reads topics. Preserve this contract; do not require `can_manage_topics` unless a future product operation creates/edits/closes topics.
- **HTML regression:** Bot API is created without global parse mode (`infrastructure/telegram/bot_api_factory.py:35-40`); owner replies use `parse_mode=None` (`infrastructure/telegram/publisher.py:163-171`); only VK publication explicitly uses HTML (`publisher.py:152-161`). Existing tests cover global parse-mode absence, plain-text literal `<...>`, publication HTML, source escaping, and author escaping (`tests/integration/telegram/test_bot_api_factory.py:85-101`, `tests/integration/telegram/test_publisher_args.py:423-445`, `tests/unit/domain/test_forwarding_policy.py:136-142`, `tests/acceptance/test_us09_author_transfer.py:44-52`). Preserve per-call parse mode. Future HTML publication/caption values must escape original VK text, original author, manual initiator, source/wall URL display text, and each warning; Admin UI stays plain text by default.
- **VK routing / FirstPeerGuard:** current consumer applies one global guard to `peer_id` before it classifies DM versus community conversation (`bootstrap/vk_consumer.py:67-110`; `infrastructure/vk/mapper.py:17-26,99-149`). No `VK_SOURCE_PEER_ID` exists or should be added. Final routing must first classify normalized VK peer semantics, route user DMs independently per user, and only then apply any source-conversation defense-in-depth. Recommended minimal architecture: replace the global guard with a `FirstConversationPeerGuard` scoped only to the one recognized community-conversation route; never bind or reject a DM because of another user's DM. If the classifier plus one-community deployment invariant makes the guard redundant, remove it rather than retaining a misleading global guard. Add tests with one community conversation and multiple independent DMs.

### Self-read document reconciliation: `docs/01`–`docs/07`

The following matrix is based on direct reads on 2026-09-18, not only Explorer summaries. Historical Stage 1 material in `docs/07-bootstrap-intent-draft.md` remains a bootstrap boundary and cannot override the current product contract.

| Source | Current authoritative details | Reconciliation / stale point |
|---|---|---|
| `docs/01-product-spec.md:23-110,114-225` | One VK community/chat plus wall to one Telegram topic chat; owners use Telegram bot; VK users use Help/manual forwarding/aliases; supported content is text/photo/video/document <=50 MB; unsupported attachment warnings are per item and not owner broadcasts | Confirms product scope and warning semantics. The current intent adds manual publication provenance (original author plus initiating VK user) and explicit alias-shortcut precedence, which must be added to the later implementation contract and eventually to docs. |
| `docs/01-product-spec.md:227-275` | Exactly one forwarded message; multiple messages produce error and no FSM; no reply context/nested-chain expansion; unknown alias shows topics and enters interactive selection | Does not define the newly fixed distinction between accompanying text before FSM and ordinal-only `WAIT_DESTINATION`; current intent supersedes the omission. |
| `docs/01-product-spec.md:302-345` | Owner-only Telegram UI, permanent keyboard, three toggles, topic selections, refresh, chat change; reset clears chat/destinations/topic bindings and restores toggles | Does not state what happens to VK aliases bound to the old chat. This is a genuine owner decision. |
| `docs/01-product-spec.md:349-375` | Missing target topic uses General, notifies all owners, and successful fallback receives 👍; missing permissions are explicit owner-facing errors; attachment errors stay inside publication | Directly conflicts with current startup fatal behavior and current General-as-NULL ambiguity. It also supports no global notification for individual attachment warnings. |
| `docs/02-user-stories.md:33-117,119-179` | Owner authorization is silent for outsiders; registration checks permissions; topics are explicitly refreshed through MTProto and persisted; one messages destination serves both filters | Current temporary code only partially satisfies this; General must be allowed in the same destination selection UX. |
| `docs/02-user-stories.md:219-325` | Photo/video/document <=50 MB; attachment failures do not cancel text/other media; each unsupported/oversized item gets its own warning; wall includes text/media/#изстенывк/original URL | This resolves the Librarian's warning-vs-placeholder question: warning-only per attachment is the baseline, with no separate owner broadcast. The remaining ambiguity is only the logical-publication success criterion when text succeeds but every attachment fails. |
| `docs/02-user-stories.md:329-430` | Manual forwarding, multiple-message rejection, aliases, unknown-alias recovery, and Help | Current intent adds exact source-chat independence and accompanying-text alias shortcut; numeric aliases are explicitly allowed by examples and now take precedence before FSM. |
| `docs/02-user-stories.md:434-499` | Toggle changes notify all owners; chat reset removes old topic bindings; missing topic falls back to General and notifies all owners | Confirms the user's recommended notification semantics and conflicts with `docs/03:470-476` only in whether the initiator receives a broadcast duplicate. Use direct confirmation for initiator plus broadcast for other owners. |
| `docs/02-user-stories.md:501-562` | MTProto proxy precedence; local Bot API loopback bypasses SOCKS5; authorization script persists a session and can replace account | Local Bot API support is required by the product artifacts; do not ask the owner to choose hosted vs local as product scope. Deployment should test hosted baseline and preserve explicit local endpoint behavior. |
| `docs/03-technical-requirements.md:39-53,228-303` | SQLite is business-state storage; startup checks environment, MTProto, Bot API, SQLite/migrations; topics are manually refreshed and persisted | Current code checks Alembic head but has no migration-aware `scripts/start.sh`; current topic snapshot omits some metadata described by architecture docs. |
| `docs/03-technical-requirements.md:305-375` | Both `message_new` and `wall_post_new` are required; replies are not transferred; nested forwards are not expanded; 👍 follows successful publication | Current code handles only `message_new`. The manual “no nested expansion” rule is compatible with a bounded adapter normalizer for automatic/full payload handling, but must not become manual recursive publication. |
| `docs/03-technical-requirements.md:379-450` | Whitelist photo/video/document, product limit 50 MB, independent attachment handling, multiple Telegram messages allowed when limits require it | This explicitly justifies Publication Plan/equivalent; current one-call publisher is incomplete. It also fixes per-attachment warning behavior. |
| `docs/03-technical-requirements.md:454-476` | Missing topic falls back to General and is successful; attachment failures stay inside publication; toggle notification goes to all owners except initiator | The fallback rule is product-consistent. The “except initiator” sentence is the stale/less complete part: reconcile with `docs/01`, `docs/02`, `docs/04`, and current intent as direct confirmation plus no duplicate broadcast. |
| `docs/04-fsm-and-ui.md:24-65,69-163` | VK UI has Help/buttons; manual forwarding enters `WAIT_DESTINATION` after exactly one forward; `WAIT_DESTINATION` accepts number or cancel only; no pagination; FSM is cancellable | The current file is already ordinal-only in `WAIT_DESTINATION`; it does not contain the newly required pre-FSM alias shortcut or numeric alias precedence. Current intent extends it rather than contradicting its state grammar. |
| `docs/04-fsm-and-ui.md:165-270` | Alias CRUD is a separate FSM and one alias is shown per topic | Does not specify General uniqueness under SQLite NULL or alias invalidation after chat change. Migration/repository constraint and reset policy remain required. |
| `docs/04-fsm-and-ui.md:294-491` | Telegram registration, permanent keyboard, toggles, destination FSMs, refresh, and disappeared-topic warning/fallback | It explicitly lists General in destination examples (`:393-400`) and says a disappeared topic may remain stored for diagnostics with runtime fallback (`:473-489`). Current code rejects General and startup-fails on disappeared destination, so reconciliation must change code, not this UX principle. |
| `docs/04-fsm-and-ui.md:493-568` | Chat reset clears chat/destinations/topic bindings, restores toggles, and FSMs are ephemeral; all owners are notified for toggles/fallback/critical errors, while per-attachment warnings stay in publication | Confirms reset and owner-diagnostics baseline. It leaves aliases unspecified. Its toggle wording (`:373-379`) supports direct initiator confirmation plus current keyboard and notifications for other owners. |
| `docs/05-architecture-and-engineering.md:33-72,381-425` | One asyncio process, modular monolith, Clean/Hexagonal/DDD-lite, manual composition root, TaskGroup, graceful shutdown; no service split | Matches current intent and is not open for product interview. The final plan must preserve this boundary while fixing poller crash/shutdown and DB contention. |
| `docs/05-architecture-and-engineering.md:723-812` | Example models include nullable topic IDs, `telegram_topics` metadata, aliases with two UNIQUE constraints, and delivery JSON message IDs | Field names `vk_messages_topic_id`/`vk_wall_topic_id` and NULL-based alias uniqueness are not sufficient for the current General contract. The direct intent's `telegram_*_topic_configured` migration and a General-safe uniqueness mechanism supersede the example. |
| `docs/05-architecture-and-engineering.md:924-1002` | Telegram/VK FSM is ephemeral; domain uses `SourceMessage`, `Attachment[]`, `PublicationResult`; automatic source keys are deduplicated, manual actions are intentional new operations | Keep FSM and automatic/manual idempotency distinction. Expand the publication model to a logical multi-operation plan and likely add a dedicated wall source instead of dirtying `SourceMessage`. |
| `docs/05-architecture-and-engineering.md:1005-1172` | Error classes, fatal startup, unit/application/DB/adapter/acceptance/E2E test pyramid, 80% coverage guardrail | Supports the later test strategy; it does not by itself define how multi-call ambiguous outcomes are operator-recovered. |
| `docs/05-architecture-and-engineering.md:1274-1380,1454-1548` | PM2 fork process, migration-before-start, separate Loguru/PM2 logs, logrotate verification, save/startup, graceful shutdown, architecture acceptance criteria | These are final deployment requirements. Files `scripts/start.sh` and `ecosystem.config.cjs` are absent today, so C6 remains open. |
| `docs/06-full-implementation-roadmap.md:180-317` | Stages 7-12 cover Admin UI, VK UI/manual, wall/media, reliability, acceptance, deployment; project is finished only after all US/AC, make check, migration, E2E, PM2 restart/reboot, secrets hygiene, and Ultrabrain APPROVE | This is the scope boundary for the future implementation plan, not a reason to split the user's requested completion into separate plans. |
| `docs/07-bootstrap-intent-draft.md:1-5,91-136,555-603` | Stage 1 intentionally excludes product logic, API clients, migrations, handlers, attachments, PM2, and network tests | Historical bootstrap scope is complete and must not constrain the final completion plan. It contains a stale cross-reference to `07-full-implementation-roadmap.md` at `:561-564`; the actual roadmap is `docs/06-full-implementation-roadmap.md`. |

### Reconciliation outcome

The authoritative order is: direct current intent, current `docs/01-03`, then `docs/04`, then `docs/05`, then `docs/06`, with `docs/07` historical bootstrap context. The owner has resolved alias cleanup, partial-publication success, minimal fail-closed review UX, and persistent cursor replay. The research confirms that persistent mode still cannot provide a reliable discarded-event count, and bounded replay is not a native VK Long Poll recovery mode. Local Bot API support, per-item warnings, automatic-only General fallback, all-owner notification coverage, and ordinal-only `WAIT_DESTINATION` are already determined.

## Decisions (with rationale)

### Directly fixed by the current intent

- “После выполнения следующего плана я ожидаю функционально законченный проект по Product Spec / User Stories / Technical Requirements” means the next implementation plan must cover the complete remaining roadmap, not another vertical slice.
- “General должен стать полноценным destination” with `configured=false,NULL`, `configured=true,NULL`, and `configured=true,N`; no sentinel `0`/`-1` unless a later hard contract proves it unavoidable.
- Automatic message and wall destinations, and manual forwarding explicitly targeting General, may use General; unavailable named automatic destinations fall back to General, notify owners, and successful fallback is successful delivery with automatic 👍. Manual forwarding never silently changes an explicitly selected named topic to General.
- Manual forwarding accepts “ровно одно forwarded message”; source chat provenance is irrelevant; nested forwards are not expanded; reply context is not transferred; manual forwarding never adds 👍.
- In the no-text shortcut, the user sees the persisted topic list and enters only an ordinal in `WAIT_DESTINATION`. With accompanying text, “любой сопровождающий текст интерпретируется как alias”, including digits; numeric alias lookup wins before FSM, while `WAIT_DESTINATION` accepts only ordinal/cancel/back.
- Topics refresh only after owner explicitly requests refresh in Telegram Admin UI; VK UI and aliases consume the persisted SQLite snapshot.
- VK FSM state is ephemeral per user and may be lost on restart; unfinished operations must not partially mutate business state.
- The author of the original forwarded VK message and the initiating VK user must both be presented as distinct clickable VK profile links for manual publication.
- The final system remains one process/modular monolith/asyncio/SQLite and does not add FastAPI, Redis, Celery, RabbitMQ, Kafka, microservices, DI framework, multi-tenant behavior, or edit/delete synchronization.

### Resolved by the owner interview

- On Telegram-chat replacement, delete all VK aliases transactionally together with the old topic snapshot and bindings. Do not preserve disabled aliases and do not remap by title: old `topic_id` values belong to the old chat and remapping by name is ambiguous.
- A logical publication is successful when a Telegram publication containing text and/or warnings is created, even if every media attachment fails. Successful media remain, each failed media gets its own warning, and automatic forwarding receives 👍 in this state. Manual forwarding never receives 👍.
- Delivery review is owner-visible and fail-closed. The minimal UX must not be a separate complex admin panel: reuse the existing Telegram owner settings/notifications surface with a compact `Диагностика доставки` view and inline details/actions. It must distinguish:
  - `failed_before_send`: Telegram was not called or definitive no-send is known; safe retry is allowed and may be automatic before surfacing an owner notice.
  - `failed_permanent`: definitive terminal failure; show source/destination/reason and recovery instruction, but do not automatically retry.
  - `ambiguous`: Telegram may already have accepted the call; show warning, timestamp, destination, operation/source key, and known message IDs; automatic retry is forbidden. Manual review may acknowledge/mark reviewed and, only as an explicit separately labelled new attempt if later required, accept duplicate risk.
- Owner notifications should be reserved for actionable high-signal delivery/configuration events: fallback, history gap, exhausted retry, `failed_permanent`, and `ambiguous`; per-attachment warnings remain inside the publication as required by the product documents.
- Persistent VK Long Poll cursor is now fixed as the final policy: use `skip_old_events=False`, persist the cursor in a controlled gitignored runtime path, include that path in deployment/runbook/backup considerations alongside SQLite and the Telethon session, and treat VK `failed=1/3` as `history_gap` with unknown discarded count. Never promise an exact skipped count or full historical replay.
- Automatic configured message/wall destinations may use General fallback. Manual forwarding never silently changes an explicitly selected named topic to General; if that destination is unavailable, the user receives a clear error and is offered the current active topic list to choose another destination. Owner may refresh the persisted snapshot when needed.
- After explicit topic refresh, stale aliases remain stored until the user repairs or deletes them, but are not remapped by title and never fall back to General. Alias resolution must detect inactive/closed/hidden/missing topics, explain that the destination is unavailable, show selectable current topics, and offer alias reconfiguration/deletion.
- Preserve the Telegram capability contract from Stage 2-6: require send text/photo/video/document and proof-send to the selected topic; do not require `can_manage_topics`, because creating or managing topics is not a product operation.
- Preserve the HTML regression boundary: no global `parse_mode=HTML`; Admin UI replies remain plain text; HTML is explicit per publication/caption and escapes every dynamic original text, author, manual initiator, URL display text, and warning.
- Route VK community-conversation events and user-DM events before any auto-forward guard. Do not add `VK_SOURCE_PEER_ID`; use the one-community/one-chat invariant and, if retained, a guard scoped only to a classified community conversation. DMs from different users must never block one another.
- Persist `is_closed` and `is_hidden` topic metadata already produced by Telethon. Selectors exclude inactive/closed/hidden topics; stale automatic bindings remain diagnosable for General fallback, while unavailable topics never look like valid choices.

### Technical recommendations for Ultrabrain

- Split VK routing before applying the current global `FirstPeerGuard`: classify source community conversation events for automatic forwarding separately from user-DM commands/FSM, then apply only a guard scoped to the recognized community-conversation route under the one-community/one-chat invariant, or remove the guard if routing tests prove it redundant. This removes the real collision where a first DM can consume the process-global peer slot.
- Model wall posts as a dedicated normalized source (`SourceWallPost` or equivalent) with its own source key and original URL, sharing attachment normalization/publication ports rather than forcing wall into a message-only union.
- Introduce a `PublicationPlan`/equivalent logical publication abstraction with ordered operations and per-operation result records. Preserve all resulting Telegram message IDs and distinguish `published`, `partially_published`, `accepted_unknown`, `failed_retryable`, and `failed_permanent`.
- Keep delivery fail-closed: after a Telegram call reaches network uncertainty, do not blindly replay it. Persist each confirmed result before proceeding; continuation after restart is allowed only for operations whose provider-side outcome is definitively known not to have been accepted. Ambiguous operations require owner-visible diagnostics/review, not automatic duplicate-prone retry.
- Replace linear readiness with feature-specific invariants: message forwarding requires a valid message destination or explicit General plus its toggle; wall forwarding independently requires a valid wall destination or explicit General plus its toggle; chat/API infrastructure failure remains startup/runtime failure, while a missing named topic is recoverable fallback.
- Change-chat reset should clear registered chat, message/wall destination state, persisted topic snapshot/bindings, aliases, and restore toggle defaults. Aliases are deleted transactionally because their topic IDs belong to the old chat.
- Owner notifications should include the initiating owner via direct confirmation and notify other owners via broadcast, avoiding a duplicate notification to the initiator while ensuring every owner learns the new state.
- For VK Long Poll, use persistent cursor mode (`skip_old_events=False`) with no promise of exact skipped counts or full historical replay. `failed=1/3` becomes an explicit history-gap outcome with unknown discarded count; bounded replay is not recommended. Store the cursor in a controlled gitignored runtime path and include it in deployment/runbook/backup handling.

## Scope IN

- Full Telegram Admin UI/FSM, owner-only access and silent unauthorized ignore, registration/capability checks, permanent keyboard, all toggles, settings, topic refresh, two destination selectors including General, change-chat/reset confirmation, back/cancel, owner notifications, and removal/replacement of temporary `/topics`/`/set_topic` UX.
- General three-state migration through ORM, DTOs, repositories, readiness, selection, aliases, startup, fallback, manual forwarding, wall forwarding, and acceptance tests; including a real uniqueness guarantee for a user’s General alias.
- VK DM routing and per-user ephemeral FSM for Help, alias CRUD, manual forwarding, alias shortcut, unknown alias, ordinal-only `WAIT_DESTINATION`, cancel/back, and exact-one forwarded-message validation.
- Dedicated wall event normalization, dedup/source identity, original URL, independent destination/toggle, General/fallback, text/media/warnings, and `#изстенывк`.
- Shared media pipeline for photo/video/document, unsupported media and >50 MB warnings, temporary downloads, access keys, albums/heterogeneous grouping, text/caption splitting, partial-success semantics, and multiple message IDs.
- Reliability hardening: multi-call delivery ledger/CAS/fail-closed semantics, owner diagnostics, fallback distinction between automatic and manual destinations, reaction ordering, ambiguous/failed-permanent policy, persistent VK cursor runtime state/history gaps, poller crash/shutdown, DB contention, stale Telethon session, and retry handling.
- Topic lifecycle hardening: persist `is_closed`/`is_hidden`, exclude unavailable topics from selectors, resolve stale aliases without title remap or General fallback, and delete aliases on chat reset.
- Regression hardening: preserve per-call HTML parse mode and escaping, preserve the Stage 2-6 capability contract without requiring `can_manage_topics`, and test independent VK community-conversation versus multi-user-DM routing.
- Unit, application, DB integration, adapter contract, acceptance, opt-in real E2E, official/sanitized golden fixtures, and regression coverage for nested payloads, General, aliases, routing, media, wall, fallback, ambiguity, and reset.
- Migration-aware startup, `scripts/start.sh`, `ecosystem.config.cjs`, PM2 single fork/autorestart/graceful timeout/logging/rotation, persistent DB and Telethon session, backup/restore, fresh install, reboot/autostart, `pm2 save`, `pm2 startup`, and deployment runbook.

## Scope OUT (Must NOT have)

- No FastAPI, Redis, Celery, RabbitMQ, Kafka, microservices, distributed architecture, DI framework, multi-tenant model, or unnecessary general-purpose abstraction.
- No source-chat restriction for manual forwarded messages; no nested forward expansion; no reply-context transfer; no manual 👍.
- No General fallback for manual forwarding when the user explicitly selected a named topic; no automatic alias title remapping; no requirement for `can_manage_topics` when the bot only publishes.
- No automatic Telethon refresh on every VK user action; no sentinel topic IDs unless a verified API constraint forces it.
- No VK↔Telegram edit/delete synchronization, unrelated refactors, or silent replacement of current user decisions with historical draft/roadmap wording.
- No committing tokens, `.env`, local SQLite databases, unredacted live API responses, or real downloaded media.

## Open questions

No unresolved product/UX owner decisions remain after the interview. The remaining items are implementation recommendations and verification obligations for Ultrabrain: exact classifier code for VK peer semantics, whether the scoped conversation guard can be removed after routing tests, the concrete SQLite migration/index for General alias uniqueness, the controlled VK cursor persistence hook/path, and the exact text of stale-alias/diagnostic messages.

Questions intentionally not asked: database schema shape, state-machine internals, routing classes, publication abstraction, retry/CAS mechanics, and wall source model are technical architecture choices to recommend in the later plan.

## Approval gate
status: ready-for-ultrabrain
approach: This intent/research draft is decision-complete for the owner. Ultrabrain may use it in a separate session to create the architecture skeleton and one complete Stage 7-12 implementation plan. The future plan must preserve General’s three-state model, distinguish automatic fallback from manual named-topic errors, separate VK group routing from DM FSM routing, use a dedicated logical multi-call publication model, include minimal fail-closed delivery review, persistent VK cursor/history-gap semantics, availability-aware selectors, ReplyKeyboard-first Telegram UI, owner-scoped command hints with backend authorization, cross-chat registration-master FSM, per-user VK FSM, no-configuration silent behavior, and acceptance/live-contract/deployment proof. No implementation plan or product code is created in this session.

## Addendum: Telegram/VK UI and command contracts

This addendum supplements, and does not replace, the earlier decisions. It was added after two fresh research sessions, as explicitly requested by the owner.

### Fresh research ledger

- Fresh Explorer: `ses_f4c1e8b49ffeqaHnh5gksc6Ig5`, task `bg_2406e896`. Current presentation/bootstrap/application wiring; no repository changes.
- Fresh Librarian: `ses_f4c1e8d62ffejAAEnRUVeZ8IQK`, task `bg_317e8716`, checked 2026-09-18. Telegram Bot API 10.3, aiogram `v3.31.0` commit `97cfe79fa0ac9459d498bdb15cb7cb0530dbaac7`, VKBottle `v4.11.0` commit `ff0a9ce006a82c108533797938deb6835c0417b1`; no repository changes.

### Fresh current-code findings

- Current Telegram presentation has only `start.py`, `register.py`, `destination.py`, a placeholder keyboard, and owner middleware. Router registration is in `src/vk_topic_bridge/bootstrap/container.py:164-175,178-241`; the placeholder `ReplyKeyboardMarkup` is `src/vk_topic_bridge/presentation/telegram/keyboards.py:1-14`; owner silent-ignore is `presentation/telegram/middlewares.py:15-30`.
- Current `/start` only reads persisted settings and sends text; it creates no pending state (`presentation/telegram/routers/start.py:18-55`). Current `/register` receives only `chat.id/title` and has no connection to private `/start` (`presentation/telegram/routers/register.py:23-106`; `application/admin/register_chat.py:46-90`).
- No `set_my_commands`, `delete_my_commands`, `BotCommand`, FSM, or storage wiring exists. Temporary `/topics` and `/set_topic` are registered in `presentation/telegram/routers/destination.py:156-177` and remain TODO-marked.
- There is no `presentation/vk/` package, no VK UI handlers/keyboards/FSM, and no current high-level VK UI dispatcher. The raw consumer handles only `message_new` (`bootstrap/vk_consumer.py:67-87`), then applies peer guard before author lookup/normalization/forwarding (`:87-108`).
- `ForwardVkMessage` already has automatic no-config/readiness skip behavior (`application/forwarding/forward_message.py:54-75`); manual forwarding, aliases, and full Admin UI are explicitly deferred (`tests/acceptance/test_deferred_stories_guard.py:1-32`).
- Current tests cover owner silent-ignore, registration, temporary topic commands, automatic forwarding, FirstPeerGuard, and global HTML parse-mode regression, but have no coverage for command scopes, ReplyKeyboard UI, cross-chat registration state, VK UI FSM, or manual forwarding (`tests/acceptance/test_us01_owner_access.py:1-76`, `tests/integration/telegram/test_register_flow.py:40-163`, `tests/integration/telegram/test_destination_flow.py:30-192`, `tests/unit/bootstrap/test_vk_consumer.py:39-177`).

### New direct owner decisions

The following are quoted or normalized directly from the new owner intent and are now product contracts:

- “Основной Telegram Admin UI должен использовать именно ReplyKeyboardMarkup, а не InlineKeyboardMarkup.” Inline keyboards are not to be introduced without a concrete proven need.
- The persistent Telegram owner keyboard contains dynamic @all/hashtag/wall toggles, message and wall destination actions, topic settings, delivery diagnostics, and chat change. Toggle labels describe the action relative to current state.
- Telegram submenu keyboards use `Отмена`, `← Назад`, `Да`/`Отмена`, and `Обновить список`/`← Назад` as text actions.
- Private owner commands are only `/start` and `/cancel`; `/start` has priority over any active FSM and returns to a DB-consistent root state; `/cancel` clears the current ephemeral operation and returns to root or `TG_UNREGISTERED`.
- Group/supergroup production command is only `/register`, and it is accepted only from the same owner who has an active private registration master. All other contexts are silently ignored; successful registration cannot be repeated through the command.
- Temporary `/topics`, `/set_topic`, and other Stage 2-6 provisioning commands are not production UX.
- Command hints must be owner-scoped as far as Bot API permits, but command scopes are never security. Backend owner authorization remains mandatory and unauthorized private messages remain silently ignored.
- VK persistent keyboard is `Алиасы` and `Помощь`; manual forwarding has no dedicated button. Help triggers are `Начать`, `Помощь`, `Помоги`, `Help`, and the Help button.
- VK FSM is ephemeral and per VK user. Manual forwarding/no-config, stale alias, exact-one-message, ordinal-only `WAIT_DESTINATION`, no-General-manual-fallback, no-reaction, and alias behavior follow the earlier decisions and are expanded below.
- Automatic qualifying events with no Telegram chat or never-configured destination are intentional silent no-ops: no external reply, no owner notification, no Telegram publication, no delivery attempt, no automatic 👍; only useful structured DEBUG logging with `destination_not_configured` or equivalent.
- Configured-but-unavailable automatic destinations use the already-decided General fallback and owner notification. Manual forwarding is blocked only when the Telegram chat is not registered or the manual destination list is genuinely unusable; an automatic message/wall destination being unset does not block manual forwarding. In the blocked cases manual forwarding replies clearly to the initiating VK user, starts no FSM, creates no delivery attempt, and never uses General fallback from an unavailable explicit named destination. Help remains usable without Telegram configuration.

### Telegram command-menu research and recommendation

Authoritative findings:

- `setMyCommands` accepts an explicit scope; an empty command list clears the commands for that scope. `deleteMyCommands` removes only the selected scope and allows lower-precedence scopes to become visible. [Bot API setMyCommands](https://core.telegram.org/bots/api#setmycommands), [deleteMyCommands](https://core.telegram.org/bots/api#deletemycommands), aiogram `SetMyCommands`/`DeleteMyCommands` at commit `97cfe79fa0ac9459d498bdb15cb7cb0530dbaac7`.
- Relevant precedence is `BotCommandScopeChatMember` > administrator/chat scopes > `BotCommandScopeChat` > all-private/all-group scopes > `BotCommandScopeDefault`. A `BotCommandScopeChatMember` requires both concrete `chat_id` and `user_id`.
- Therefore multiple `OWNER_IDS` require separate scope calls for each owner and each known group. Do not set a group-wide command scope: leave default/all-user command lists empty, then set owner-specific scopes.
- `/register` cannot be shown owner-only in an unknown group before the group `chat_id` is known. This is a Bot API limitation, not a product ambiguity. `my_chat_member` can provide a lifecycle trigger when the bot is added/removed/restricted, but it does not itself complete application registration. If the bot was already present before the master begins, the owner may need to type the command manually; exact client rendering is not an acceptance criterion.
- After successful `/register` or cancellation, explicitly clear the temporary group owner scope. Private owner `/start`/`/cancel` scopes may remain available for the known owner private chat. `deleteMyCommands` must be scoped deliberately; never rely on command-menu absence as authorization.
- `/register@BotUsername` is a directed command and should be accepted by the same group handler when it targets this bot. It does not bypass owner identity, registration-master state, chat-type, or configured-chat checks.

Recommendation: create a command-menu synchronization collaborator in bootstrap/infrastructure, fed by presentation command definitions. At startup clear default/all-user production command lists, set private owner scopes where chat IDs are known, and set `BotCommandScopeChatMember` for an owner/group pair when the group becomes known during the active master/lifecycle. Keep the backend authorization layer independent.

### Telegram ReplyKeyboard and FSM research

- aiogram 3.31 `ReplyKeyboardMarkup` supports `keyboard`, `resize_keyboard`, `is_persistent`, `one_time_keyboard`, `input_field_placeholder`, `selective`, and `force_reply`; these are client requests, not visual guarantees. `ReplyKeyboardRemove` is appropriate after cancellation or leaving a setup flow. [ReplyKeyboardMarkup](https://core.telegram.org/bots/api#replykeyboardmarkup), [ReplyKeyboardRemove](https://core.telegram.org/bots/api#replykeyboardremove).
- ReplyKeyboard is the correct stable mechanism here: button text becomes a normal message filtered by presentation routers. InlineKeyboard is unnecessary unless a future interaction needs callback payloads, in-place edits, or a no-message action.
- aiogram `Dispatcher` is the root router and includes FSM middleware; routers can be nested. Standard `StatesGroup`, `State`, `FSMContext`, `set_state`, `update_data`, and `clear` cover this product. `MemoryStorage` is sufficient for ephemeral single-process UI state; `SimpleEventIsolation` is recommended for serializing rapid events per state key.
- `FSMStrategy.GLOBAL_USER` is appropriate for the registration master because it must begin in the owner private chat and be consumed in a different group chat. Configured root/destination wizards can use the normal owner-private context; `/start` and `/cancel` must explicitly clear/normalize state before dispatching root behavior.
- Standard FSM is recommended over experimental Scenes Wizard: the registration master and destination flows need explicit, testable transitions without SceneRegistry/scene lifecycle overhead.

Recommended presentation structure, preserving current Clean/Hexagonal boundaries:

```text
src/vk_topic_bridge/presentation/telegram/
  routers/
    root.py              # /start, /cancel, root dispatch
    registration.py      # private master + group /register bridge
    settings.py          # toggles/settings/diagnostics/chat change
    destinations.py      # message/wall destination FSMs
  keyboards.py           # ReplyKeyboard factories
  commands.py            # command definitions and scope intents
  states.py              # StatesGroup definitions only
  filters.py             # owner/private/group/context predicates
  errors.py              # presentation error mapping
```

`container.py` should compose routers, state storage, command synchronizer, and application use cases. Handlers should not call repositories, VK API, or Telegram topic APIs directly. `@router.error`/dispatcher error handling should map known application errors to plain-text owner responses.

Registration-master boundary:

1. private owner `/start` verifies owner/private context, clears conflicting FSM state, and starts `RegistrationMaster.pending` using owner-global state;
2. owner gets instructions and ReplyKeyboard with `/cancel` semantics;
3. group `/register` verifies same `from_user.id`, active owner-global state, group/supergroup context, current bot identity for directed commands, and registration eligibility;
4. only then calls existing `RegisterChat` application use case;
5. no business-state mutation occurs until capability/proof/refresh requirements pass;
6. success/cancel/expiry clears state and temporary command scopes, then renders the correct root or `TG_UNREGISTERED` keyboard.

### VKBottle 4.11 and VK presentation research

- VKBottle `BotLabeler.private_message` and `.chat_message` shorthand handlers add `PeerRule(False)` and `PeerRule(True)` respectively; `PeerRule` uses `peer_id != from_id` to distinguish private/chat high-level messages. `StateRule` filters by current state. `BuiltinStateDispenser` is in-memory and keyed by integer peer, so final per-user UI state must use `from_id` as the state key, not only `peer_id`, with chat target kept separately in payload.
- VKBottle keyboard builders support persistent/non-one-time keyboards and serialized button actions. `BotLabeler.load()` supports handler module separation. These are useful presentation primitives, not a reason to replace the proven raw Long Poll consumer.
- Current raw consumer does not dispatch high-level VKBottle message objects and has no `presentation/vk` package. A raw event must be explicitly normalized before high-level rules can be used reliably.

Recommendation: add a `presentation/vk/` boundary with `handlers.py`/`router.py`, `keyboards.py`, `states.py`, and `filters.py` or equivalent. Fan out normalized UI events from the existing raw consumer, use `from_id`-keyed ephemeral state (a small presentation store or VKBottle StateDispenser adapter), and keep automatic forwarding in its existing application path. Do not migrate the entire Long Poll pipeline to BotLabeler. Classify private UI events and community-conversation automatic events before any auto-forward guard; a DM from one user must not block another DM or the source conversation.

### Final VK UI/FSM contract addendum

- Main persistent keyboard is `Алиасы` / `Помощь`; no manual-forward button.
- One forwarded message without accompanying text: if Telegram chat is registered and the manual destination list is usable, show General plus available persisted topics by ordinal and enter `WAIT_DESTINATION`; otherwise reply with a clear unconfigured/unavailable error and do not start FSM. The absence of an automatic message/wall destination does not block this flow.
- One forwarded message with any accompanying text: treat the text as alias, including digits. Active alias sends immediately; unknown alias shows error/list and enters ordinal-only `WAIT_DESTINATION`; stale alias shows unavailable error/list and offers alias repair/deletion, never General fallback.
- Two or more forwarded messages: error, no publication, no FSM.
- `WAIT_DESTINATION` accepts ordinal or `Отмена`, never alias.
- Manual publication contains original author link, distinct initiating-user link, original text, supported media/warnings, no reply context, no nested forward expansion, no VK 👍, and no silent named-topic-to-General fallback.
- Alias screen contains topic/alias list, `Добавить`, `Изменить`, `Удалить`, and `← Назад`. General is a normal destination and may have an alias under the existing General-safe DB decision. If the Telegram chat is not registered or the manual destination list is genuinely unusable, show a configuration error and do not enter an alias FSM; an unset automatic destination alone is not an error for aliases/manual forwarding.

### No-configuration and readiness reconciliation

The final implementation must distinguish normal product configuration state from operational failure:

| situation | automatic qualifying event | manual VK forwarding |
|---|---|---|
| Telegram chat is not registered | silent skip; no reply/notification/publication/delivery record/👍; structured DEBUG reason `telegram_chat_not_registered` | direct clear VK-user error; no FSM, no delivery attempt, no General |
| Telegram chat is registered, but the corresponding automatic message/wall destination was never configured | only that corresponding automatic flow silently skips; no publication/delivery record/👍; structured DEBUG reason `destination_not_configured`; the other automatic feature is evaluated independently | no effect on manual forwarding. Manual flow offers General plus available persisted topics, regardless of unset automatic destinations |
| Telegram chat is registered, but the manual destination list is genuinely unusable/unavailable | automatic flows are evaluated by their own configured destination flags | direct clear VK-user error; no broken FSM, no delivery attempt, no automatic fallback |
| Automatic destination was explicitly configured but its named topic later disappeared/closed/was hidden | General fallback, owner notification, successful logical delivery and automatic 👍 | no effect on manual unless the user selected that same unavailable named topic; manual then shows a clear error/current alternatives and never uses General silently |
| Manual user explicitly selected a named topic that later became unavailable | automatic flows are evaluated by their own feature-specific state | clear user error and current alternatives; no General fallback |
| Infrastructure of an already configured integration fails | operational error path, diagnostics/owner notification according to existing reliability policy | clear user-facing error; do not pretend it is ordinary unconfigured state |

Feature-specific readiness must represent these separately:

```text
messages_auto_ready = registered chat + healthy infrastructure + messages destination explicitly configured
wall_auto_ready     = registered chat + healthy infrastructure + wall destination explicitly configured
manual_forwarding_ready = registered chat + healthy infrastructure + at least one valid manual destination can be offered (General or an available persisted topic)
```

`manual_forwarding_ready` does not depend on either automatic configured flag. “Not configured yet” is not a fatal startup failure and must not trigger owner broadcast. Help and root VK UI remain available in the unconfigured state.

### Documentation reconciliation required later

No new owner choice remains, but the future implementation plan must include documentation updates after code is complete:

- `docs/01-product-spec.md`: ReplyKeyboard/commands, registration-master gating, no-config silent behavior, manual no-General fallback, stale alias handling.
- `docs/02-user-stories.md`: acceptance criteria for `/start` priority, `/cancel`, owner-scoped hints, group `/register` gating, ReplyKeyboard, no-config automatic/manual behavior, and VK UI FSM.
- `docs/03-technical-requirements.md`: command-scope lifecycle, presentation FSM/state storage, feature-specific readiness, and raw-event-to-UI routing boundary.
- `docs/04-fsm-and-ui.md`: exact Telegram ReplyKeyboard menus, command behavior, cross-chat registration master, VK Help/alias/manual states, and stale/no-config flows.
- `docs/05-architecture-and-engineering.md`: final presentation filesystem, aiogram standard FSM strategy, command synchronizer, VK raw-consumer fan-out, and no `can_manage_topics` requirement.
- `docs/06-full-implementation-roadmap.md`: preserve Stage 7-12 scope and add the newly required UI/command/diagnostic acceptance gates.
- `docs/07-bootstrap-intent-draft.md`: historical bootstrap artifact; do not turn it into a product UI source.

### Addendum scope guardrails

- Telegram Admin UI is ReplyKeyboard-first; no InlineKeyboard migration or experimental Scenes Wizard without a separately proven need.
- Command hints are best-effort UX, never authorization; exact client rendering and pre-known unknown-group `/register` visibility are not acceptance criteria.
- Do not rewrite the existing automatic forwarding pipeline or add `VK_SOURCE_PEER_ID`.
- Do not persist ephemeral registration/VK FSM state as business configuration; only persistent aliases/settings/delivery/topic snapshots belong in SQLite.

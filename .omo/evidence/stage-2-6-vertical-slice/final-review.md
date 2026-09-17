# Stage 2–6 — Final review record

## Reviewer verdict history

**Round 1 (independent adversarial review, agent `oracle`, session `ses_f4ed3fdddffec6QIq34Kb8d1fW`): `REQUEST CHANGES`.**

Six findings were raised. All six were verified against the source by the orchestrator and accepted as real; one further finding was verified and **rejected as incorrect**.

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | `forward_message`: a lost `mark_published` CAS still set the VK 👍 and returned `published=True` | P0 | FIXED |
| 2 | `publisher`: a bare `ConnectionResetError` was re-raised raw instead of being recorded as `ambiguous` | P0 | FIXED |
| 3 | `startup`: the persisted `telegram_messages_topic_id` was never validated against the fresh topic list | P0 | FIXED |
| 4 | `register`: `/register` accepted a private owner DM as the bridge chat | P0 | FIXED |
| 5 | `register`: no publication capability probe at `/register` | P0 | **REJECTED — see below** |
| 6 | `config`: an absolute `TELEGRAM_SESSION_PATH` could escape `runtime/telethon/` | P1 | FIXED |
| 7 | `startup`/`main`: raw exception text logged without secret redaction | P1 | FIXED |

### Finding 5 — rejected, with rationale

The reviewer claimed `/register` must perform a real publication probe into the used topics before completing provisioning.

Rejected because it contradicts the frozen plan: the real-send proof is deliberately placed at the destination-selection step (HUMAN GATE TG-TOPIC), where `SelectDestination` persists `telegram_messages_topic_id` **only after** a real Bot API send into the selected thread returns a positive message id. Performing an additional publication probe at `/register` would write unsolicited messages into the chat before the owner has chosen a destination, which `docs/03` §14 and the plan's `D21` explicitly forbid ("without creating unwanted chat spam"). Capability checks at `/register` correctly cover the member rights (`can_send_messages`/`photos`/`videos`/`documents`); actual publication is proven by the gated real send.

## Fixes applied

Commit `7b65c76` (plus the `config`/`authorize` test adaptations that followed):

1. `application/forwarding/forward_message.py` — when `mark_published` returns `False`, log at ERROR, do **not** call `_ensure_reaction`, return `ForwardOutcome(published=False, reason="claim_lost")`. Guarantee (e) now holds unconditionally.
2. `infrastructure/telegram/publisher.py` — `ConnectionError` added to `_AMBIGUOUS_FAILURES` with code `bot_api_connection_reset`, covering `ConnectionResetError`/`ConnectionAbortedError`/`BrokenPipeError`. Guarantee (g) now covers native transport resets.
3. `bootstrap/startup.py` — a persisted destination topic must be present in the fresh topic list and neither closed nor hidden, otherwise `FatalStartupError(TOPICS_UNAVAILABLE)`.
4. `presentation/telegram/routers/register.py` — `REGISTERABLE_CHAT_TYPES = {"group", "supergroup"}`; a private/channel chat is rejected with an owner-facing explanation and nothing is persisted.
5. `config.py` — an absolute `TELEGRAM_SESSION_PATH` must resolve inside `runtime/telethon/`, else `ValidationError`.
6. `logger.py` + `bootstrap/startup.py` — `redact_secrets()` and `_safe_detail()` scrub configured secret values from any exception text surfaced through `FatalStartupError`.

### Regression found and fixed by the orchestrator

Applying fix 6 introduced a second defect: the new `with_suffix()` call truncated dotted session names (`owner.account` → `owner.session`). Restored the append-only behaviour via the `_with_session_suffix()` helper in `config.py`, and adapted the affected tests (`tests/unit/test_authorize_telegram.py`, `tests/acceptance/test_us26_authorize_script.py`) to the corrected, stricter session-path rule instead of weakening the rule.

## New proof added for the previously weak guarantees

| Guarantee | New test |
|---|---|
| (b) concurrent handling | `test_concurrent_execute_publishes_exactly_once` (two concurrent `execute` for one source → exactly one publish) |
| (e) reaction only after confirmed publication | `test_lost_cas_after_publish_does_not_react_and_reports_failure` (no reaction, `claim_lost`) |
| (g) native reset is ambiguous | `test_native_connection_reset_is_ambiguous` (`ConnectionResetError` → `ambiguous`, code `bot_api_connection_reset`) |
| (d) no write transaction across network I/O | `test_send_intent_is_committed_before_network_io` (real SQLite; a DB-observing publisher reads `send_started` during `publish`) |
| startup destination readiness | `test_persisted_destination_missing_from_topics_is_fatal`, `test_persisted_destination_closed_topic_is_fatal` |
| provisioning target | `test_private_chat_registration_is_rejected_without_persisting`, `test_channel_chat_registration_is_rejected_without_persisting` |
| session-path containment | `test_session_path_absolute_outside_runtime_dir_is_rejected`, `test_us26_session_outside_runtime_dir_is_rejected` |
| secret hygiene | `test_redact_secrets_replaces_secret_values` |

## Gate evidence

- `make check` → **480 passed, 4 e2e deselected**, exit=0, coverage 92% (`make-check-final.txt`).
- Migration `base → head` (`0001`), idempotent re-upgrade, 4 tables (`migration-final.txt`).
- Duplicate/replay/concurrency/lost-CAS/native-reset selection → 15 passed, exit=0 (`duplicate-replay.txt`).
- Full-chain integration test on real SQLite + real repositories (`tests/integration/test_forwarding_chain.py`, 6 tests incl. replay-creates-no-duplicate).
- Real e2e smoke: Bot API `getMe` PASS, VK identity + Long Poll PASS, Telethon session UNAUTHORIZED → MT-AUTH gate open (`e2e-smoke.txt`).

## Remaining, requiring the owner

F5 is recorded as **conditionally resolved**: every criterion-cited blocker from round 1 is fixed and re-verified by the orchestrator with fresh evidence. Per the operator's standing instruction no new review agents were spawned for a second round; a fresh independent pass is recommended after the live human gates complete, once the end-to-end chain has actually run against real VK and Telegram.

Open owner-dependent items:
1. **MT-AUTH** — authorize the Telethon session (`uv run --locked python authorize_telegram.py`).
2. **TG-REG** — `/register` inside the target chat.
3. **TG-TOPIC** — choose the messages destination; confirmed by a real Bot API send before persisting.
4. **F4** — real VK → Telegram end-to-end plus duplicate replay.

Unverified constant (flagged in code): `LIKE_REACTION_ID = 1` in `infrastructure/vk/api.py` — the numeric 👍 reaction id could not be confirmed against official VK docs during research and must be validated during the live end-to-end run.

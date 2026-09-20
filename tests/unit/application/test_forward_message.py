"""Unit tests for the fail-closed forwarding use case over the CAS delivery ledger."""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Self

import pytest
from aiogram.types import Message

from vk_topic_bridge.application.dto.delivery import (
    DeliveryRecord,
    ReserveOutcome,
    ReserveRequest,
)
from vk_topic_bridge.application.dto.infrastructure import LongPollInfo
from vk_topic_bridge.application.dto.settings import BridgeSettingsState, ToggleKind
from vk_topic_bridge.application.errors import (
    PublicationAmbiguousError,
    PublicationRejectedError,
)
from vk_topic_bridge.application.forwarding.forward_message import (
    ForwardOutcome,
    ForwardVkMessage,
)
from vk_topic_bridge.domain.enums import PublicationStatus, ReactionStatus, SourceType
from vk_topic_bridge.domain.publication import (
    OperationOutcome,
    OperationStatus,
    PublicationPlan,
)
from vk_topic_bridge.domain.value_objects import (
    Author,
    Publication,
    SourceMessage,
    SourceWallPost,
    TopicInfo,
)

_NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
_SOURCE_KEY = "111:222:333"
_CHAT_ID = 100
_TOPIC_ID = 5
_PEER_ID = 222
_CONVERSATION_MESSAGE_ID = 333
_MESSAGE_IDS = (101,)


def _ledger_key(source_type: SourceType, source_key: str) -> str:
    return f"{source_type.value}:{source_key}"


def _blank_record(source_type: str, source_key: str) -> DeliveryRecord:
    return DeliveryRecord(
        id=0,
        source_type=source_type,
        source_key=source_key,
        publication_status=PublicationStatus.RESERVED,
        reaction_status=ReactionStatus.NOT_DUE,
        claim_token=None,
        lease_expires_at=None,
        send_started_at=None,
        destination_chat_id=None,
        destination_topic_id=None,
        telegram_message_ids=(),
        attempts=0,
        last_error_code=None,
        last_error=None,
        payload_hash=None,
        ambiguous_at=None,
        review_required=False,
        created_at=_NOW,
        updated_at=_NOW,
        completed_at=None,
    )


def _lease_is_live(record: DeliveryRecord) -> bool:
    return record.lease_expires_at is not None and record.lease_expires_at > datetime.now(UTC)


class _FakeLedger:
    """Stateful delivery ledger honouring the real CAS rules of ``DeliveryRepository``."""

    def __init__(self) -> None:
        self.records: dict[str, DeliveryRecord] = {}
        self.deny_send_started = False
        self.fail_mark_published = False
        self._next_id = 1

    def seed(
        self,
        *,
        status: PublicationStatus,
        source_key: str = _SOURCE_KEY,
        claim_token: str | None = None,
        lease_expires_at: datetime | None = None,
        reaction_status: ReactionStatus = ReactionStatus.NOT_DUE,
        message_ids: tuple[int, ...] = (),
    ) -> DeliveryRecord:
        record = replace(
            _blank_record(SourceType.VK_MESSAGE.value, source_key),
            id=self._next_id,
            publication_status=status,
            reaction_status=reaction_status,
            claim_token=claim_token,
            lease_expires_at=lease_expires_at,
            telegram_message_ids=message_ids,
        )
        self._next_id += 1
        self.records[_ledger_key(SourceType.VK_MESSAGE, source_key)] = record
        return record

    async def reserve(self, request: ReserveRequest) -> ReserveOutcome:
        key = _ledger_key(request.source_type, request.source_key)
        existing = self.records.get(key)
        if existing is not None:
            return ReserveOutcome(created=False, record=existing)
        record = replace(
            _blank_record(request.source_type.value, request.source_key),
            id=self._next_id,
            destination_chat_id=request.destination_chat_id,
            destination_topic_id=request.destination_topic_id,
            payload_hash=request.payload_hash,
        )
        self._next_id += 1
        self.records[key] = record
        return ReserveOutcome(created=True, record=record)

    async def claim_reserved(self, delivery_id: int, claim_token: str, lease_seconds: int) -> bool:
        key, record = self._find(delivery_id)
        retryable = (PublicationStatus.RESERVED, PublicationStatus.FAILED_BEFORE_SEND)
        if record.publication_status not in retryable:
            return False
        if record.claim_token is not None and _lease_is_live(record):
            return False
        self._write(
            key,
            replace(
                record,
                claim_token=claim_token,
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=lease_seconds),
                attempts=record.attempts + 1,
            ),
        )
        return True

    async def mark_send_started(self, delivery_id: int, claim_token: str) -> bool:
        if self.deny_send_started:
            return False
        key, record = self._find(delivery_id)
        retryable = (PublicationStatus.RESERVED, PublicationStatus.FAILED_BEFORE_SEND)
        if record.claim_token != claim_token or record.publication_status not in retryable:
            return False
        self._write(
            key,
            replace(
                record,
                publication_status=PublicationStatus.SEND_STARTED,
                send_started_at=datetime.now(UTC),
            ),
        )
        return True

    async def mark_published(
        self, delivery_id: int, claim_token: str, message_ids: Sequence[int]
    ) -> bool:
        key, record = self._find(delivery_id)
        if self.fail_mark_published:
            # Simulated CAS loss: a competing worker committed the publication first.
            self._write(
                key,
                replace(
                    record,
                    publication_status=PublicationStatus.PUBLISHED,
                    telegram_message_ids=tuple(message_ids),
                    completed_at=datetime.now(UTC),
                ),
            )
            return False
        if record.claim_token != claim_token:
            return False
        if record.publication_status is not PublicationStatus.SEND_STARTED:
            return False
        self._write(
            key,
            replace(
                record,
                publication_status=PublicationStatus.PUBLISHED,
                telegram_message_ids=tuple(message_ids),
                completed_at=datetime.now(UTC),
            ),
        )
        return True

    async def mark_publication_ambiguous(
        self, delivery_id: int, claim_token: str, code: str | None, message: str | None
    ) -> bool:
        key, record = self._find(delivery_id)
        if record.claim_token != claim_token:
            return False
        if record.publication_status is not PublicationStatus.SEND_STARTED:
            return False
        self._write(
            key,
            replace(
                record,
                publication_status=PublicationStatus.AMBIGUOUS,
                ambiguous_at=datetime.now(UTC),
                review_required=True,
                last_error_code=code,
                last_error=message,
            ),
        )
        return True

    async def mark_failed_before_send(
        self, delivery_id: int, claim_token: str, code: str | None, message: str | None
    ) -> bool:
        key, record = self._find(delivery_id)
        retryable = (PublicationStatus.RESERVED, PublicationStatus.FAILED_BEFORE_SEND)
        if record.claim_token != claim_token or record.publication_status not in retryable:
            return False
        self._write(
            key,
            replace(
                record,
                publication_status=PublicationStatus.FAILED_BEFORE_SEND,
                last_error_code=code,
                last_error=message,
            ),
        )
        return True

    async def mark_failed_permanent(
        self, delivery_id: int, claim_token: str, code: str | None, message: str | None
    ) -> bool:
        key, record = self._find(delivery_id)
        if record.claim_token != claim_token:
            return False
        if record.publication_status is not PublicationStatus.SEND_STARTED:
            return False
        self._write(
            key,
            replace(
                record,
                publication_status=PublicationStatus.FAILED_PERMANENT,
                last_error_code=code,
                last_error=message,
                completed_at=datetime.now(UTC),
            ),
        )
        return True

    async def claim_reaction(self, delivery_id: int) -> bool:
        key, record = self._find(delivery_id)
        if record.publication_status is not PublicationStatus.PUBLISHED:
            return False
        if record.reaction_status not in (ReactionStatus.NOT_DUE, ReactionStatus.FAILED):
            return False
        self._write(key, replace(record, reaction_status=ReactionStatus.PENDING))
        return True

    async def mark_reaction_succeeded(self, delivery_id: int) -> bool:
        key, record = self._find(delivery_id)
        if record.reaction_status is not ReactionStatus.PENDING:
            return False
        self._write(key, replace(record, reaction_status=ReactionStatus.SUCCEEDED))
        return True

    async def mark_reaction_failed(
        self, delivery_id: int, code: str | None, message: str | None
    ) -> bool:
        key, record = self._find(delivery_id)
        if record.reaction_status is not ReactionStatus.PENDING:
            return False
        self._write(
            key,
            replace(
                record,
                reaction_status=ReactionStatus.FAILED,
                last_error_code=code,
                last_error=message,
            ),
        )
        return True

    async def get(self, source_type: SourceType, source_key: str) -> DeliveryRecord | None:
        return self.records.get(_ledger_key(source_type, source_key))

    async def list_pending_reactions(self) -> list[DeliveryRecord]:
        return [r for r in self.records.values() if r.reaction_status is ReactionStatus.PENDING]

    async def list_ambiguous(self) -> list[DeliveryRecord]:
        return [
            r for r in self.records.values() if r.publication_status is PublicationStatus.AMBIGUOUS
        ]

    async def list_failed_terminal(self, limit: int = 20) -> list[DeliveryRecord]:
        terminal = [
            r
            for r in self.records.values()
            if r.publication_status
            in (PublicationStatus.FAILED_PERMANENT, PublicationStatus.AMBIGUOUS)
        ]
        return terminal[:limit]

    async def mark_reviewed(self, delivery_id: int) -> bool:
        key, record = self._find(delivery_id)
        if (
            record.publication_status is not PublicationStatus.AMBIGUOUS
            or not record.review_required
        ):
            return False
        self.records[key] = replace(record, review_required=False)
        return True

    def _find(self, delivery_id: int) -> tuple[str, DeliveryRecord]:
        for key, record in self.records.items():
            if record.id == delivery_id:
                return key, record
        raise KeyError(f"unknown delivery id {delivery_id}")

    def _write(self, key: str, record: DeliveryRecord) -> None:
        self.records[key] = record


class _FakePublisher:
    """Plan publisher double recording the base publication of every executed plan."""

    def __init__(
        self,
        *,
        error: BaseException | None = None,
        message_ids: tuple[int, ...] = _MESSAGE_IDS,
    ) -> None:
        self.error = error
        self.message_ids = message_ids
        self.calls: list[Publication] = []
        self.plans: list[PublicationPlan] = []

    async def publish_plan(self, plan: PublicationPlan) -> tuple[OperationOutcome, ...]:
        self.plans.append(plan)
        self.calls.append(plan.base)
        # Model the network suspension point so concurrent calls genuinely interleave.
        await asyncio.sleep(0)
        if self.error is not None:
            raise self.error
        return tuple(
            OperationOutcome(
                operation=operation,
                status=OperationStatus.PUBLISHED,
                message_ids=self.message_ids,
            )
            for operation in plan.operations
        )

    async def send_text(self, chat_id: int, text: str, message_thread_id: int | None = None) -> int:
        return 1


class _BlockingPublisher(_FakePublisher):
    """Publisher whose ``publish_plan`` blocks until the test cancels the use-case task."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()

    async def publish_plan(self, plan: PublicationPlan) -> tuple[OperationOutcome, ...]:
        self.plans.append(plan)
        self.calls.append(plan.base)
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _FakeNotifier:
    """``OwnerNotifier`` double recording every broadcast text."""

    def __init__(self) -> None:
        self.all_texts: list[str] = []
        self.others_texts: list[tuple[int, str]] = []

    async def notify_all(self, text: str) -> None:
        self.all_texts.append(text)

    async def notify_others(self, initiator_id: int, text: str) -> None:
        self.others_texts.append((initiator_id, text))


class _ResetBot:
    """``Bot`` double whose transport always fails with a bare native connection reset."""

    def __init__(self) -> None:
        self.calls = 0

    async def send_message(self, **_kwargs: object) -> Message:
        self.calls += 1
        raise ConnectionResetError("reset by peer")


class _FakeVk:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.reaction_calls: list[tuple[int, int]] = []

    async def get_community_id(self) -> int:
        return 777

    async def check_long_poll(self) -> LongPollInfo:
        return LongPollInfo(server="lp.vk.com", key="key", ts="1", enabled=True)

    async def get_full_message(self, peer_id: int, conversation_message_id: int) -> SourceMessage:
        raise NotImplementedError

    async def get_author(self, user_id: int) -> Author:
        return Author(user_id=user_id, first_name="Ivan", last_name="Petrov", screen_name=None)

    async def normalize_event(self, raw_event: object, author: Author) -> SourceMessage:
        raise AssertionError("normalize_event is not used by this fake")

    async def normalize_wall_event(self, raw_event: object, author: Author) -> SourceWallPost:
        raise AssertionError("normalize_wall_event is not used by this fake")

    async def set_reaction(self, peer_id: int, conversation_message_id: int) -> None:
        self.reaction_calls.append((peer_id, conversation_message_id))
        if self.error is not None:
            raise self.error


class _FakeSettings:
    def __init__(self, state: BridgeSettingsState | None) -> None:
        self.state = state

    async def get(self) -> BridgeSettingsState | None:
        return self.state

    async def upsert_chat(self, chat_id: int, title: str | None) -> BridgeSettingsState:
        raise NotImplementedError

    async def set_messages_topic(self, topic_id: int | None) -> BridgeSettingsState:
        raise NotImplementedError

    async def set_wall_topic(self, topic_id: int | None) -> BridgeSettingsState:
        raise NotImplementedError

    async def set_toggle(self, kind: ToggleKind, value: bool) -> BridgeSettingsState:
        raise NotImplementedError

    async def reset(self) -> BridgeSettingsState:
        raise NotImplementedError


class _FakeTopics:
    def __init__(self) -> None:
        self.by_chat: dict[int, list[TopicInfo]] = {}

    async def replace_all(self, chat_id: int, topics: Sequence[TopicInfo]) -> None:
        self.by_chat[chat_id] = list(topics)

    async def list(self, chat_id: int) -> list[TopicInfo]:
        return list(self.by_chat.get(chat_id, []))

    async def mark_missing(self, chat_id: int, seen_topic_ids: Sequence[int | None]) -> None:
        raise NotImplementedError

    async def delete_chat(self, chat_id: int) -> None:
        raise NotImplementedError


class _FakeAliases:
    async def list_for_user(self, vk_user_id: int) -> list[tuple[int | None, str]]:
        raise NotImplementedError

    async def upsert(
        self, vk_user_id: int, topic_id: int | None, alias: str, alias_normalized: str
    ) -> None:
        raise NotImplementedError

    async def delete(self, vk_user_id: int, topic_id: int | None) -> None:
        raise NotImplementedError

    async def delete_all(self) -> int:
        raise NotImplementedError


class _FakeUow:
    def __init__(self, *, ledger: _FakeLedger, settings: _FakeSettings) -> None:
        self._ledger = ledger
        self._settings = settings
        self._topics = _FakeTopics()
        self._aliases = _FakeAliases()
        self.commits = 0

    @property
    def bridge_settings(self) -> _FakeSettings:
        return self._settings

    @property
    def telegram_topics(self) -> _FakeTopics:
        return self._topics

    @property
    def vk_aliases(self) -> _FakeAliases:
        return self._aliases

    @property
    def deliveries(self) -> _FakeLedger:
        return self._ledger

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None


def _registered_settings(
    *,
    auto_forward_all: bool = True,
    auto_forward_hashtags: bool = True,
) -> BridgeSettingsState:
    return replace(
        BridgeSettingsState.defaults(),
        telegram_chat_id=_CHAT_ID,
        telegram_messages_topic_id=_TOPIC_ID,
        telegram_messages_topic_configured=True,
        auto_forward_all=auto_forward_all,
        auto_forward_hashtags=auto_forward_hashtags,
    )


def _available_topics() -> list[TopicInfo]:
    return [
        TopicInfo(
            topic_id=_TOPIC_ID,
            title="Новости",
            is_general=False,
            is_closed=False,
            is_hidden=False,
        )
    ]


def _source(text: str = "@all Привет", *, has_all: bool = False) -> SourceMessage:
    return SourceMessage(
        source_type=SourceType.VK_MESSAGE,
        source_key=_SOURCE_KEY,
        group_id=111,
        peer_id=_PEER_ID,
        conversation_message_id=_CONVERSATION_MESSAGE_ID,
        author=Author(user_id=1, first_name="Ivan", last_name="Petrov", screen_name=None),
        text=text,
        has_all=has_all,
        has_hashtag=False,
        attachments=(),
    )


def _stored(ledger: _FakeLedger) -> DeliveryRecord:
    record = ledger.records.get(_ledger_key(SourceType.VK_MESSAGE, _SOURCE_KEY))
    assert record is not None, "delivery record must exist"
    return record


class _Harness:
    def __init__(
        self,
        *,
        settings: BridgeSettingsState | None = None,
        settings_missing: bool = False,
        topics: Sequence[TopicInfo] | None = None,
        publisher_error: BaseException | None = None,
        vk_error: Exception | None = None,
        blocking_publisher: bool = False,
        with_notifier: bool = False,
    ) -> None:
        self.ledger = _FakeLedger()
        if settings_missing:
            self.settings = _FakeSettings(None)
        elif settings is not None:
            self.settings = _FakeSettings(settings)
        else:
            self.settings = _FakeSettings(_registered_settings())
        self.publisher: _FakePublisher = (
            _BlockingPublisher() if blocking_publisher else _FakePublisher(error=publisher_error)
        )
        self.vk = _FakeVk(error=vk_error)
        self.notifier = _FakeNotifier()
        self.use_case = ForwardVkMessage(
            uow_factory=self._make_uow,
            plan_publisher=self.publisher,
            vk=self.vk,
            notifier=self.notifier if with_notifier else None,
        )
        self._topics = list(topics) if topics is not None else _available_topics()

    def _make_uow(self) -> _FakeUow:
        uow = _FakeUow(ledger=self.ledger, settings=self.settings)
        uow.telegram_topics.by_chat = {_CHAT_ID: list(self._topics)}
        return uow


async def test_all_token_publishes_once_and_reacts() -> None:
    harness = _Harness()
    outcome = await harness.use_case.execute(_source("@all Привет", has_all=True))

    assert isinstance(outcome, ForwardOutcome)
    assert outcome.published is True
    assert outcome.skipped is False
    assert outcome.reason == "published"
    assert outcome.message_ids == _MESSAGE_IDS
    assert len(harness.publisher.calls) == 1
    assert harness.vk.reaction_calls == [(_PEER_ID, _CONVERSATION_MESSAGE_ID)]
    record = _stored(harness.ledger)
    assert record.publication_status is PublicationStatus.PUBLISHED
    assert record.reaction_status is ReactionStatus.SUCCEEDED
    assert record.telegram_message_ids == _MESSAGE_IDS


async def test_forwarding_emits_pipeline_trace(caplog: pytest.LogCaptureFixture) -> None:
    harness = _Harness()

    with caplog.at_level(logging.DEBUG):
        outcome = await harness.use_case.execute(_source("@all Привет", has_all=True))

    assert outcome.published is True
    assert "automatic message forwarding started" in caplog.text
    assert "automatic message forwarding plan prepared" in caplog.text
    assert "automatic message forwarding completed" in caplog.text


async def test_hashtag_only_publishes_once() -> None:
    harness = _Harness()
    outcome = await harness.use_case.execute(_source("#извк новость"))

    assert outcome.published is True
    assert len(harness.publisher.calls) == 1
    assert _stored(harness.ledger).publication_status is PublicationStatus.PUBLISHED


async def test_all_and_hashtag_produce_one_publication() -> None:
    harness = _Harness()
    outcome = await harness.use_case.execute(_source("@all #извк"))

    assert outcome.published is True
    assert len(harness.publisher.calls) == 1
    assert len(harness.ledger.records) == 1


async def test_toggles_off_skips_without_reserve() -> None:
    harness = _Harness(
        settings=_registered_settings(auto_forward_all=False, auto_forward_hashtags=False)
    )
    outcome = await harness.use_case.execute(_source("@all #извк"))

    assert outcome.skipped is True
    assert outcome.published is False
    assert outcome.reason == "filtered"
    assert harness.publisher.calls == []
    assert harness.ledger.records == {}


async def test_unconfigured_destination_skips_all_io() -> None:
    state = replace(BridgeSettingsState.defaults(), telegram_chat_id=_CHAT_ID)
    harness = _Harness(settings=state)
    outcome = await harness.use_case.execute(_source("@all Привет"))

    assert outcome.skipped is True
    assert outcome.reason == "unconfigured"
    assert harness.publisher.calls == []
    assert harness.ledger.records == {}


async def test_unregistered_chat_skips() -> None:
    harness = _Harness(settings_missing=True)
    outcome = await harness.use_case.execute(_source("@all Привет"))

    assert outcome.skipped is True
    assert outcome.reason == "unregistered"
    assert harness.publisher.calls == []


async def test_duplicate_after_published_never_republishes_and_ensures_reaction() -> None:
    harness = _Harness(vk_error=RuntimeError("vk down"))
    first = await harness.use_case.execute(_source("@all Привет"))
    assert first.published is True
    assert _stored(harness.ledger).reaction_status is ReactionStatus.FAILED

    harness.vk.error = None
    second = await harness.use_case.execute(_source("@all Привет"))

    assert second.published is True
    assert second.skipped is False
    assert second.reason == "already_published"
    assert len(harness.publisher.calls) == 1
    assert len(harness.vk.reaction_calls) == 2
    assert _stored(harness.ledger).reaction_status is ReactionStatus.SUCCEEDED


async def test_reaction_failure_keeps_publication_published() -> None:
    harness = _Harness(vk_error=RuntimeError("reaction rejected"))

    outcome = await harness.use_case.execute(_source("@all Привет"))

    assert outcome.published is True
    assert outcome.reason == "published"
    assert len(harness.publisher.calls) == 1
    record = _stored(harness.ledger)
    assert record.publication_status is PublicationStatus.PUBLISHED
    assert record.reaction_status is ReactionStatus.FAILED


async def test_duplicate_after_ambiguous_never_republishes() -> None:
    harness = _Harness(publisher_error=PublicationAmbiguousError("no response"))
    first = await harness.use_case.execute(_source("@all Привет"))
    assert first.reason == "ambiguous"

    second = await harness.use_case.execute(_source("@all Привет"))

    assert second.published is False
    assert second.skipped is True
    assert second.reason == "already_ambiguous"
    assert len(harness.publisher.calls) == 1


async def test_duplicate_after_failed_permanent_never_republishes() -> None:
    harness = _Harness(publisher_error=PublicationRejectedError("no thread"))
    first = await harness.use_case.execute(_source("@all Привет"))
    assert first.reason == "rejected"

    second = await harness.use_case.execute(_source("@all Привет"))

    assert second.published is False
    assert second.skipped is True
    assert second.reason == "already_failed_permanent"
    assert len(harness.publisher.calls) == 1


async def test_existing_send_started_is_not_republished() -> None:
    harness = _Harness()
    harness.ledger.seed(status=PublicationStatus.SEND_STARTED)

    outcome = await harness.use_case.execute(_source("@all Привет"))

    assert outcome.skipped is True
    assert outcome.reason == "already_send_started"
    assert harness.publisher.calls == []


async def test_failed_before_send_is_reclaimed_and_published() -> None:
    harness = _Harness()
    seeded = harness.ledger.seed(status=PublicationStatus.FAILED_BEFORE_SEND)

    outcome = await harness.use_case.execute(_source("@all Привет"))

    assert outcome.published is True
    assert len(harness.publisher.calls) == 1
    record = _stored(harness.ledger)
    assert record.id == seeded.id
    assert record.publication_status is PublicationStatus.PUBLISHED


async def test_ambiguous_publication_is_recorded_and_never_retried() -> None:
    harness = _Harness(publisher_error=PublicationAmbiguousError("timeout", code="timeout"))

    outcome = await harness.use_case.execute(_source("@all Привет"))

    assert outcome.published is False
    assert outcome.skipped is False
    assert outcome.reason == "ambiguous"
    assert len(harness.publisher.calls) == 1
    record = _stored(harness.ledger)
    assert record.publication_status is PublicationStatus.AMBIGUOUS
    assert record.review_required is True
    assert record.last_error_code == "timeout"


async def test_rejected_publication_is_recorded_as_permanent() -> None:
    harness = _Harness(
        publisher_error=PublicationRejectedError("thread not found", code="thread_not_found")
    )

    outcome = await harness.use_case.execute(_source("@all Привет"))

    assert outcome.published is False
    assert outcome.skipped is False
    assert outcome.reason == "rejected"
    assert len(harness.publisher.calls) == 1
    record = _stored(harness.ledger)
    assert record.publication_status is PublicationStatus.FAILED_PERMANENT
    assert record.last_error_code == "thread_not_found"
    assert harness.vk.reaction_calls == []


async def test_claim_lost_after_reserve_prevents_publish() -> None:
    harness = _Harness()
    harness.ledger.seed(
        status=PublicationStatus.RESERVED,
        claim_token="held",
        lease_expires_at=datetime.now(UTC) + timedelta(seconds=60),
    )

    outcome = await harness.use_case.execute(_source("@all Привет"))

    assert outcome.skipped is True
    assert outcome.reason == "claim_lost"
    assert harness.publisher.calls == []


async def test_mark_send_started_failure_prevents_publish() -> None:
    harness = _Harness()
    harness.ledger.deny_send_started = True

    outcome = await harness.use_case.execute(_source("@all Привет"))

    assert outcome.skipped is True
    assert outcome.reason == "claim_lost"
    assert harness.publisher.calls == []


async def test_cancelled_error_during_publish_persists_ambiguous_and_reraises() -> None:
    harness = _Harness(blocking_publisher=True)
    blocking = harness.publisher
    assert isinstance(blocking, _BlockingPublisher)

    task = asyncio.create_task(harness.use_case.execute(_source("@all Привет")))
    await blocking.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    record = _stored(harness.ledger)
    assert record.publication_status is PublicationStatus.AMBIGUOUS
    assert record.review_required is True
    assert len(blocking.calls) == 1


async def test_lost_cas_after_publish_does_not_react_and_reports_failure() -> None:
    harness = _Harness()
    harness.ledger.fail_mark_published = True

    outcome = await harness.use_case.execute(_source("@all Привет"))

    assert len(harness.publisher.calls) == 1
    assert harness.vk.reaction_calls == []
    assert outcome.published is False
    assert outcome.skipped is False
    assert outcome.reason == "claim_lost"
    assert outcome.message_ids == _MESSAGE_IDS


async def test_concurrent_execute_publishes_exactly_once() -> None:
    harness = _Harness()

    first, second = await asyncio.gather(
        harness.use_case.execute(_source("@all Привет")),
        harness.use_case.execute(_source("@all Привет")),
    )

    assert len(harness.publisher.calls) == 1
    assert len(harness.ledger.records) == 1
    assert len(harness.vk.reaction_calls) == 1
    assert _stored(harness.ledger).publication_status is PublicationStatus.PUBLISHED
    assert first.delivery_id == second.delivery_id


async def test_missing_topic_falls_back_to_general_with_notification() -> None:
    harness = _Harness(topics=[], with_notifier=True)

    outcome = await harness.use_case.execute(_source("@all Привет"))

    assert outcome.published is True
    assert harness.publisher.plans[0].base.message_thread_id is None
    assert _stored(harness.ledger).destination_topic_id is None
    assert len(harness.notifier.all_texts) == 1
    assert "General" in harness.notifier.all_texts[0]
    assert harness.vk.reaction_calls == [(_PEER_ID, _CONVERSATION_MESSAGE_ID)]


async def test_closed_topic_falls_back_to_general() -> None:
    closed = [
        TopicInfo(
            topic_id=_TOPIC_ID,
            title="Новости",
            is_general=False,
            is_closed=True,
            is_hidden=False,
        )
    ]
    harness = _Harness(topics=closed, with_notifier=True)

    outcome = await harness.use_case.execute(_source("@all Привет"))

    assert outcome.published is True
    assert harness.publisher.plans[0].base.message_thread_id is None
    assert "закрыт" in harness.notifier.all_texts[0]


async def test_explicit_general_publishes_without_fallback_notification() -> None:
    state = replace(
        BridgeSettingsState.defaults(),
        telegram_chat_id=_CHAT_ID,
        telegram_messages_topic_id=None,
        telegram_messages_topic_configured=True,
    )
    harness = _Harness(settings=state, topics=[], with_notifier=True)

    outcome = await harness.use_case.execute(_source("@all Привет"))

    assert outcome.published is True
    assert harness.publisher.plans[0].base.message_thread_id is None
    assert harness.notifier.all_texts == []


async def test_ambiguous_outcome_notifies_owners() -> None:
    harness = _Harness(publisher_error=PublicationAmbiguousError("timeout"), with_notifier=True)

    outcome = await harness.use_case.execute(_source("@all Привет"))

    assert outcome.reason == "ambiguous"
    assert len(harness.notifier.all_texts) == 1
    assert "Диагностика доставки" in harness.notifier.all_texts[0]


async def test_rejected_outcome_notifies_owners() -> None:
    harness = _Harness(
        publisher_error=PublicationRejectedError("thread not found"), with_notifier=True
    )

    outcome = await harness.use_case.execute(_source("@all Привет"))

    assert outcome.reason == "rejected"
    assert len(harness.notifier.all_texts) == 1

"""Structural conformance tests: fake adapters must satisfy every application port."""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from types import TracebackType
from typing import Self

from vk_topic_bridge.application.dto.delivery import (
    DeliveryRecord,
    ReserveOutcome,
    ReserveRequest,
)
from vk_topic_bridge.application.dto.infrastructure import ChatAccessInfo, LongPollInfo
from vk_topic_bridge.application.dto.settings import BridgeSettingsState, ToggleKind
from vk_topic_bridge.application.ports.readiness import ReadinessPort
from vk_topic_bridge.application.ports.repositories import (
    BridgeSettingsRepository,
    DeliveryRepository,
    TelegramTopicsRepository,
    VkAliasRepository,
)
from vk_topic_bridge.application.ports.telegram import (
    TelegramAdminPort,
    TelegramPublisher,
    TelethonPort,
)
from vk_topic_bridge.application.ports.unit_of_work import UnitOfWork
from vk_topic_bridge.application.ports.vk import VkGateway
from vk_topic_bridge.application.readiness import InMemoryReadinessGate
from vk_topic_bridge.domain.enums import PublicationStatus, ReactionStatus, SourceType
from vk_topic_bridge.domain.value_objects import (
    Author,
    ChatCapabilities,
    Publication,
    PublicationResult,
    SourceMessage,
    TopicInfo,
)

_NOW = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)


def _record(*, source_type: str, source_key: str) -> DeliveryRecord:
    return DeliveryRecord(
        id=1,
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


class FakeBridgeSettingsRepository:
    def __init__(self) -> None:
        self.state = BridgeSettingsState.defaults()

    def get(self) -> BridgeSettingsState | None:
        return self.state

    def upsert_chat(self, chat_id: int, title: str | None) -> BridgeSettingsState:
        self.state = replace(self.state, telegram_chat_id=chat_id, telegram_chat_title=title)
        return self.state

    def set_messages_topic(self, topic_id: int | None) -> BridgeSettingsState:
        self.state = replace(self.state, telegram_messages_topic_id=topic_id)
        return self.state

    def set_wall_topic(self, topic_id: int | None) -> BridgeSettingsState:
        self.state = replace(self.state, telegram_wall_topic_id=topic_id)
        return self.state

    def set_toggle(self, kind: ToggleKind, value: bool) -> BridgeSettingsState:
        field_name = {
            ToggleKind.ALL: "auto_forward_all",
            ToggleKind.HASHTAGS: "auto_forward_hashtags",
            ToggleKind.WALL: "auto_forward_wall",
        }[kind]
        self.state = replace(self.state, **{field_name: value})
        return self.state

    def reset(self) -> BridgeSettingsState:
        self.state = BridgeSettingsState.defaults()
        return self.state


class FakeTelegramTopicsRepository:
    def __init__(self) -> None:
        self.by_chat: dict[int, list[TopicInfo]] = {}

    def replace_all(self, chat_id: int, topics: Sequence[TopicInfo]) -> None:
        self.by_chat[chat_id] = list(topics)

    def list(self, chat_id: int) -> list[TopicInfo]:
        return list(self.by_chat.get(chat_id, []))

    def mark_missing(self, chat_id: int, seen_topic_ids: Sequence[int | None]) -> None:
        seen = set(seen_topic_ids)
        self.by_chat[chat_id] = [
            topic for topic in self.by_chat.get(chat_id, []) if topic.topic_id in seen
        ]


class FakeVkAliasRepository:
    def __init__(self) -> None:
        self.by_user: dict[int, dict[int | None, str]] = {}

    def list_for_user(self, vk_user_id: int) -> list[tuple[int | None, str]]:
        return sorted(self.by_user.get(vk_user_id, {}).items())

    def upsert(
        self, vk_user_id: int, topic_id: int | None, alias: str, alias_normalized: str
    ) -> None:
        self.by_user.setdefault(vk_user_id, {})[topic_id] = alias_normalized

    def delete(self, vk_user_id: int, topic_id: int | None) -> None:
        self.by_user.get(vk_user_id, {}).pop(topic_id, None)


class FakeDeliveryRepository:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], DeliveryRecord] = {}

    def reserve(self, request: ReserveRequest) -> ReserveOutcome:
        key = (request.source_type.value, request.source_key)
        existing = self.records.get(key)
        if existing is not None:
            return ReserveOutcome(created=False, record=existing)
        record = _record(source_type=request.source_type.value, source_key=request.source_key)
        self.records[key] = record
        return ReserveOutcome(created=True, record=record)

    def claim_reserved(self, delivery_id: int, claim_token: str, lease_seconds: int) -> bool:
        return False

    def mark_send_started(self, delivery_id: int, claim_token: str) -> bool:
        return False

    def mark_published(
        self, delivery_id: int, claim_token: str, message_ids: Sequence[int]
    ) -> bool:
        return False

    def mark_publication_ambiguous(
        self, delivery_id: int, claim_token: str, code: str | None, message: str | None
    ) -> bool:
        return False

    def mark_failed_before_send(
        self, delivery_id: int, claim_token: str, code: str | None, message: str | None
    ) -> bool:
        return False

    def mark_failed_permanent(
        self, delivery_id: int, claim_token: str, code: str | None, message: str | None
    ) -> bool:
        return False

    def claim_reaction(self, delivery_id: int) -> bool:
        return False

    def mark_reaction_succeeded(self, delivery_id: int) -> bool:
        return False

    def mark_reaction_failed(self, delivery_id: int, code: str | None, message: str | None) -> bool:
        return False

    def get(self, source_type: SourceType, source_key: str) -> DeliveryRecord | None:
        return self.records.get((source_type.value, source_key))

    def list_pending_reactions(self) -> list[DeliveryRecord]:
        return []

    def list_ambiguous(self) -> list[DeliveryRecord]:
        return []


class FakeTelegramPublisher:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str, int | None]] = []

    def publish(self, publication: Publication) -> PublicationResult:
        raise NotImplementedError

    def send_text(self, chat_id: int, text: str, message_thread_id: int | None = None) -> int:
        self.sent.append((chat_id, text, message_thread_id))
        return 1000 + len(self.sent)


class FakeTelegramAdminPort:
    def get_me(self) -> int:
        return 42

    def get_chat_capabilities(self, chat_id: int) -> ChatCapabilities:
        return ChatCapabilities(
            can_send_text=True,
            can_send_photo=True,
            can_send_video=True,
            can_send_document=True,
            missing=(),
        )

    def send_test_into_topic(self, chat_id: int, message_thread_id: int | None, text: str) -> int:
        return 7


class FakeTelethonPort:
    def get_me(self) -> object:
        return {"id": 1}

    def is_authorized(self) -> bool:
        return True

    def verify_chat_access(self, chat_id: int) -> ChatAccessInfo:
        return ChatAccessInfo(entity_id=chat_id, is_forum=True)

    def list_topics(self, chat_id: int) -> list[TopicInfo]:
        return []


class FakeVkGateway:
    def get_community_id(self) -> int:
        return 777

    def check_long_poll(self) -> LongPollInfo:
        return LongPollInfo(server="lp.vk.com", key="key", ts="1", enabled=True)

    def get_full_message(self, peer_id: int, conversation_message_id: int) -> SourceMessage:
        raise NotImplementedError

    def get_author(self, user_id: int) -> Author:
        return Author(user_id=user_id, first_name="Ivan", last_name="Petrov", screen_name=None)

    def set_reaction(self, peer_id: int, conversation_message_id: int) -> None:
        return None


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.bridge_settings: BridgeSettingsRepository = FakeBridgeSettingsRepository()
        self.telegram_topics: TelegramTopicsRepository = FakeTelegramTopicsRepository()
        self.vk_aliases: VkAliasRepository = FakeVkAliasRepository()
        self.deliveries: DeliveryRepository = FakeDeliveryRepository()
        self.committed = False
        self.rolled_back = False

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
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


def test_repository_fakes_satisfy_protocols() -> None:
    settings: BridgeSettingsRepository = FakeBridgeSettingsRepository()
    topics: TelegramTopicsRepository = FakeTelegramTopicsRepository()
    aliases: VkAliasRepository = FakeVkAliasRepository()
    deliveries: DeliveryRepository = FakeDeliveryRepository()

    assert settings.get() is not None
    assert topics.list(chat_id=-100123) == []
    assert aliases.list_for_user(vk_user_id=1) == []
    assert deliveries.get(source_type=SourceType.VK_MESSAGE, source_key="42:100:7") is None


def test_gateway_fakes_satisfy_protocols() -> None:
    publisher: TelegramPublisher = FakeTelegramPublisher()
    admin: TelegramAdminPort = FakeTelegramAdminPort()
    telethon: TelethonPort = FakeTelethonPort()
    vk: VkGateway = FakeVkGateway()

    assert publisher.send_text(chat_id=-100123, text="hello") == 1001
    assert admin.get_me() == 42
    assert telethon.is_authorized() is True
    assert vk.get_community_id() == 777


def test_readiness_gate_satisfies_port() -> None:
    gate: ReadinessPort = InMemoryReadinessGate()

    assert gate.current().rank == 0


async def test_unit_of_work_fake_satisfies_protocol() -> None:
    fake = FakeUnitOfWork()
    uow: UnitOfWork = fake

    async with uow:
        assert uow.deliveries.get(source_type=SourceType.VK_WALL, source_key="42:-10:7") is None
        await uow.commit()

    assert fake.committed is True

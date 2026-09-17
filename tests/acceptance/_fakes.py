"""Shared in-memory fakes for the acceptance suite: no network, no SQLite, no `.env`.

The fakes implement the frozen application ports; the forwarding harness wires the
real ``ForwardVkMessage`` use case on top of them, so every acceptance test drives
production logic while observing only fake-visible outcomes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from types import TracebackType
from typing import Self

import pytest

from config import Settings
from tests.acceptance._ledger import DeliveryLedger
from vk_topic_bridge.application.admin.refresh_topics import RefreshTopics
from vk_topic_bridge.application.admin.register_chat import RegisterChat
from vk_topic_bridge.application.admin.select_destination import SelectDestination
from vk_topic_bridge.application.dto.infrastructure import ChatAccessInfo, LongPollInfo
from vk_topic_bridge.application.dto.readiness import ReadinessState
from vk_topic_bridge.application.dto.settings import BridgeSettingsState, ToggleKind
from vk_topic_bridge.application.forwarding.forward_message import ForwardVkMessage
from vk_topic_bridge.application.readiness import InMemoryReadinessGate
from vk_topic_bridge.domain.enums import SourceType
from vk_topic_bridge.domain.policies.forwarding_policy import decide
from vk_topic_bridge.domain.value_objects import (
    Attachment,
    Author,
    ChatCapabilities,
    Publication,
    PublicationResult,
    SourceMessage,
    TopicInfo,
)

CHAT_ID = -1001234567890
CHAT_TITLE = "Тестовый чат"
MESSAGES_TOPIC_ID = 7
PEER_ID = 222
CONVERSATION_MESSAGE_ID = 333
GROUP_ID = 111
SOURCE_KEY = f"{GROUP_ID}:{PEER_ID}:{CONVERSATION_MESSAGE_ID}"
PUBLISHED_MESSAGE_IDS = (101,)

FULL_CAPABILITIES = ChatCapabilities(
    can_send_text=True,
    can_send_photo=True,
    can_send_video=True,
    can_send_document=True,
    missing=(),
)

SAMPLE_TOPICS = [
    TopicInfo(topic_id=None, title="General", is_general=True, is_closed=False, is_hidden=False),
    TopicInfo(
        topic_id=MESSAGES_TOPIC_ID,
        title="Новости",
        is_general=False,
        is_closed=False,
        is_hidden=False,
    ),
]


def settings_from_env(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    """Build ``Settings`` from the isolated test environment plus explicit overrides."""
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # The autouse conftest fixture disables the dotenv file, so only env applies.
    return Settings.model_validate({})


def capabilities_missing(*names: str) -> ChatCapabilities:
    """Capability snapshot with exactly ``names`` reported as missing."""
    allowed = {
        "can_send_text",
        "can_send_photo",
        "can_send_video",
        "can_send_document",
    }
    unknown = set(names) - allowed
    assert not unknown, f"unknown capability names: {sorted(unknown)}"
    return ChatCapabilities(
        can_send_text="can_send_text" not in names,
        can_send_photo="can_send_photo" not in names,
        can_send_video="can_send_video" not in names,
        can_send_document="can_send_document" not in names,
        missing=tuple(name for name in allowed if name in names),
    )


class FakeSettingsRepository:
    """``BridgeSettingsRepository`` over one in-memory state snapshot."""

    def __init__(self, state: BridgeSettingsState | None = None) -> None:
        self.state = state if state is not None else BridgeSettingsState.defaults()

    async def get(self) -> BridgeSettingsState | None:
        return self.state

    async def upsert_chat(self, chat_id: int, title: str | None) -> BridgeSettingsState:
        self.state = replace(self.state, telegram_chat_id=chat_id, telegram_chat_title=title)
        return self.state

    async def set_messages_topic(self, topic_id: int | None) -> BridgeSettingsState:
        self.state = replace(self.state, telegram_messages_topic_id=topic_id)
        return self.state

    async def set_wall_topic(self, topic_id: int | None) -> BridgeSettingsState:
        self.state = replace(self.state, telegram_wall_topic_id=topic_id)
        return self.state

    async def set_toggle(self, kind: ToggleKind, value: bool) -> BridgeSettingsState:
        field_name = {
            ToggleKind.ALL: "auto_forward_all",
            ToggleKind.HASHTAGS: "auto_forward_hashtags",
            ToggleKind.WALL: "auto_forward_wall",
        }[kind]
        self.state = replace(self.state, **{field_name: value})
        return self.state

    async def reset(self) -> BridgeSettingsState:
        self.state = BridgeSettingsState.defaults()
        return self.state


class FakeTopicsRepository:
    """``TelegramTopicsRepository`` keeping the last replaced view per chat."""

    def __init__(self) -> None:
        self.by_chat: dict[int, list[TopicInfo]] = {}

    async def replace_all(self, chat_id: int, topics: Sequence[TopicInfo]) -> None:
        self.by_chat[chat_id] = list(topics)

    async def list(self, chat_id: int) -> list[TopicInfo]:
        return list(self.by_chat.get(chat_id, []))

    async def mark_missing(self, chat_id: int, seen_topic_ids: Sequence[int | None]) -> None:
        seen = set(seen_topic_ids)
        self.by_chat[chat_id] = [
            topic for topic in self.by_chat.get(chat_id, []) if topic.topic_id in seen
        ]


class FakeAliasesRepository:
    """Alias port placeholder: aliases belong to Stage 8 and are never used here."""

    async def list_for_user(self, vk_user_id: int) -> list[tuple[int | None, str]]:
        return []

    async def upsert(
        self, vk_user_id: int, topic_id: int | None, alias: str, alias_normalized: str
    ) -> None:
        raise AssertionError("alias persistence is deferred to Stage 8")

    async def delete(self, vk_user_id: int, topic_id: int | None) -> None:
        raise AssertionError("alias persistence is deferred to Stage 8")


class FakeUnitOfWork:
    """``UnitOfWork`` exposing the fakes above; commit is recorded, not real."""

    def __init__(self) -> None:
        self.bridge_settings = FakeSettingsRepository()
        self.telegram_topics = FakeTopicsRepository()
        self.vk_aliases = FakeAliasesRepository()
        self.deliveries = DeliveryLedger()
        self.commits = 0

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


class RecordingPublisher:
    """``TelegramPublisher`` recording every confirmed publication and owner message."""

    def __init__(
        self,
        *,
        error: BaseException | None = None,
        message_ids: tuple[int, ...] = PUBLISHED_MESSAGE_IDS,
    ) -> None:
        self.error = error
        self.message_ids = message_ids
        self.publications: list[Publication] = []
        self.sent_text: list[tuple[int, str, int | None]] = []

    async def publish(self, publication: Publication) -> PublicationResult:
        self.publications.append(publication)
        if self.error is not None:
            raise self.error
        return PublicationResult(
            chat_id=publication.chat_id,
            message_thread_id=publication.message_thread_id,
            message_ids=self.message_ids,
        )

    async def send_text(self, chat_id: int, text: str, message_thread_id: int | None = None) -> int:
        self.sent_text.append((chat_id, text, message_thread_id))
        return 1000 + len(self.sent_text)


class FakeAdminPort:
    """``TelegramAdminPort`` returning prepared capabilities and one test-send result."""

    def __init__(
        self,
        *,
        capabilities: ChatCapabilities = FULL_CAPABILITIES,
        test_message_id: int = 555,
        test_error: BaseException | None = None,
    ) -> None:
        self.capabilities = capabilities
        self.test_message_id = test_message_id
        self.test_error = test_error
        self.capability_calls: list[int] = []
        self.test_sends: list[tuple[int, int | None, str]] = []

    async def get_me(self) -> int:
        return 42

    async def get_chat_capabilities(self, chat_id: int) -> ChatCapabilities:
        self.capability_calls.append(chat_id)
        return self.capabilities

    async def send_test_into_topic(
        self, chat_id: int, message_thread_id: int | None, text: str
    ) -> int:
        self.test_sends.append((chat_id, message_thread_id, text))
        if self.test_error is not None:
            raise self.test_error
        return self.test_message_id


class FakeTelethonPort:
    """``TelethonPort`` returning a prepared access check and topic list."""

    def __init__(
        self,
        *,
        topics: list[TopicInfo] | None = None,
        is_forum: bool = True,
    ) -> None:
        self.topics = list(SAMPLE_TOPICS) if topics is None else topics
        self.is_forum = is_forum
        self.access_calls: list[int] = []
        self.topic_calls: list[int] = []

    async def get_me(self) -> object:
        return {"id": 1}

    async def is_authorized(self) -> bool:
        return True

    async def verify_chat_access(self, chat_id: int) -> ChatAccessInfo:
        self.access_calls.append(chat_id)
        return ChatAccessInfo(entity_id=chat_id, is_forum=self.is_forum)

    async def list_topics(self, chat_id: int) -> list[TopicInfo]:
        self.topic_calls.append(chat_id)
        return list(self.topics)


class FakeVkGateway:
    """``VkGateway`` recording 👍 reactions and replaying one prepared full message."""

    def __init__(
        self,
        *,
        error: Exception | None = None,
        full_message: SourceMessage | None = None,
    ) -> None:
        self.error = error
        self.full_message = full_message
        self.reaction_calls: list[tuple[int, int]] = []

    async def get_community_id(self) -> int:
        return GROUP_ID

    async def check_long_poll(self) -> LongPollInfo:
        return LongPollInfo(server="lp.vk.com", key="key", ts="1", enabled=True)

    async def get_full_message(self, peer_id: int, conversation_message_id: int) -> SourceMessage:
        if self.full_message is None:
            raise AssertionError("no prepared full message on the fake VK gateway")
        return self.full_message

    async def get_author(self, user_id: int) -> Author:
        return Author(user_id=user_id, first_name="Иван", last_name="Петров", screen_name=None)

    async def set_reaction(self, peer_id: int, conversation_message_id: int) -> None:
        self.reaction_calls.append((peer_id, conversation_message_id))
        if self.error is not None:
            raise self.error


def make_source(
    text: str,
    *,
    source_key: str = SOURCE_KEY,
    author: Author | None = None,
    attachments: tuple[Attachment, ...] = (),
) -> SourceMessage:
    """Build a normalized VK event whose match flags come from the real policy."""
    decision = decide(text, auto_forward_all=True, auto_forward_hashtags=True)
    return SourceMessage(
        source_type=SourceType.VK_MESSAGE,
        source_key=source_key,
        group_id=GROUP_ID,
        peer_id=PEER_ID,
        conversation_message_id=CONVERSATION_MESSAGE_ID,
        author=author or Author(user_id=1, first_name="Ivan", last_name="Petrov", screen_name=None),
        text=text,
        has_all=decision.matched_all,
        has_hashtag=decision.matched_hashtag,
        attachments=attachments,
    )


@dataclass(slots=True)
class RegistrationHarness:
    """Real registration use case wired to fakes plus the fakes themselves."""

    uow: FakeUnitOfWork
    settings: FakeSettingsRepository
    topics: FakeTopicsRepository
    admin: FakeAdminPort
    telethon: FakeTelethonPort
    use_case: RegisterChat


def make_registration_harness(
    *,
    capabilities: ChatCapabilities = FULL_CAPABILITIES,
    topics: list[TopicInfo] | None = None,
    is_forum: bool = True,
) -> RegistrationHarness:
    """Wire ``RegisterChat`` over fake ports, ready for acceptance assertions."""
    uow = FakeUnitOfWork()
    admin = FakeAdminPort(capabilities=capabilities)
    telethon = FakeTelethonPort(topics=topics, is_forum=is_forum)
    refresh = RefreshTopics(lambda: uow, telethon)
    return RegistrationHarness(
        uow=uow,
        settings=uow.bridge_settings,
        topics=uow.telegram_topics,
        admin=admin,
        telethon=telethon,
        use_case=RegisterChat(lambda: uow, admin, refresh),
    )


@dataclass(slots=True)
class DestinationHarness:
    """Real destination-selection use case wired to fakes plus the fakes themselves."""

    uow: FakeUnitOfWork
    settings: FakeSettingsRepository
    admin: FakeAdminPort
    use_case: SelectDestination


def make_destination_harness(
    *, test_message_id: int = 555, test_error: BaseException | None = None
) -> DestinationHarness:
    """Wire ``SelectDestination`` over fake ports, ready for acceptance assertions."""
    uow = FakeUnitOfWork()
    admin = FakeAdminPort(test_message_id=test_message_id, test_error=test_error)
    return DestinationHarness(
        uow=uow,
        settings=uow.bridge_settings,
        admin=admin,
        use_case=SelectDestination(lambda: uow, admin),
    )


@dataclass(slots=True)
class ForwardingHarness:
    """Real forwarding use case wired to fakes, plus every recorded outcome."""

    settings: FakeSettingsRepository
    topics: FakeTopicsRepository
    ledger: DeliveryLedger
    publisher: RecordingPublisher
    vk: FakeVkGateway
    readiness: InMemoryReadinessGate
    uow: FakeUnitOfWork
    use_case: ForwardVkMessage


def make_forwarding_harness(
    *,
    registered: bool = True,
    topic_id: int | None = MESSAGES_TOPIC_ID,
    auto_forward_all: bool = True,
    auto_forward_hashtags: bool = True,
    publisher_error: BaseException | None = None,
    vk_error: Exception | None = None,
    forwarding_enabled: bool = True,
) -> ForwardingHarness:
    """Wire ``ForwardVkMessage`` over fake ports, ready for acceptance assertions."""
    uow = FakeUnitOfWork()
    if registered:
        uow.bridge_settings.state = replace(
            BridgeSettingsState.defaults(),
            telegram_chat_id=CHAT_ID,
            telegram_chat_title=CHAT_TITLE,
            telegram_messages_topic_id=topic_id,
            auto_forward_all=auto_forward_all,
            auto_forward_hashtags=auto_forward_hashtags,
        )
    publisher = RecordingPublisher(error=publisher_error)
    vk = FakeVkGateway(error=vk_error)
    readiness = InMemoryReadinessGate()
    if forwarding_enabled:
        readiness.advance(ReadinessState.FORWARDING_ENABLED)
    use_case = ForwardVkMessage(
        uow_factory=lambda: uow,
        publisher=publisher,
        vk=vk,
        readiness=readiness,
    )
    return ForwardingHarness(
        settings=uow.bridge_settings,
        topics=uow.telegram_topics,
        ledger=uow.deliveries,
        publisher=publisher,
        vk=vk,
        readiness=readiness,
        uow=uow,
        use_case=use_case,
    )

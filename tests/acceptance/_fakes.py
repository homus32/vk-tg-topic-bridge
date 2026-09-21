"""Shared in-memory fakes for the acceptance suite: no network, no SQLite, no `.env`.

The fakes implement the frozen application ports; the forwarding harness wires the
real ``ForwardVkMessage`` use case on top of them, so every acceptance test drives
production logic while observing only fake-visible outcomes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from types import TracebackType
from typing import Any, Self, cast

import pytest

from config import Settings
from tests.acceptance._ledger import DeliveryLedger
from vk_topic_bridge.application.admin.destination_admin import SelectDestinationV2
from vk_topic_bridge.application.admin.refresh_topics import RefreshTopics
from vk_topic_bridge.application.admin.register_chat import RegisterChat
from vk_topic_bridge.application.dto.infrastructure import ChatAccessInfo, LongPollInfo
from vk_topic_bridge.application.dto.settings import BridgeSettingsState, ToggleKind
from vk_topic_bridge.application.forwarding.forward_message import ForwardVkMessage
from vk_topic_bridge.application.forwarding.forward_wall import ForwardWallPost
from vk_topic_bridge.application.notifications.owner_notifier import OwnerNotifier
from vk_topic_bridge.application.readiness import InMemoryReadinessGate
from vk_topic_bridge.domain.enums import AttachmentKind, SourceType
from vk_topic_bridge.domain.errors import AttachmentDownloadFailed
from vk_topic_bridge.domain.policies.forwarding_policy import decide
from vk_topic_bridge.domain.publication import (
    OperationOutcome,
    OperationStatus,
    PublicationPlan,
)
from vk_topic_bridge.domain.value_objects import (
    Attachment,
    Author,
    ChatCapabilities,
    Publication,
    PublicationResult,
    SourceMessage,
    SourceWallPost,
    TopicInfo,
)
from vk_topic_bridge.presentation.vk.handlers import VkUiDispatcher

CHAT_ID = -1001234567890
CHAT_TITLE = "Тестовый чат"
MESSAGES_TOPIC_ID = 7
OWNER_ID = 111
PEER_ID = 2_000_000_222
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

    async def delete_chat(self, chat_id: int) -> None:
        self.by_chat.pop(chat_id, None)


class FakeAliasesRepository:
    """``VkAliasRepository`` over one in-memory per-user map (normalized aliases)."""

    def __init__(self) -> None:
        self.rows: dict[int, dict[int | None, str]] = {}

    async def list_for_user(self, vk_user_id: int) -> list[tuple[int | None, str]]:
        return list(self.rows.get(vk_user_id, {}).items())

    async def upsert(
        self, vk_user_id: int, topic_id: int | None, alias: str, alias_normalized: str
    ) -> None:
        self.rows.setdefault(vk_user_id, {})[topic_id] = alias_normalized

    async def delete(self, vk_user_id: int, topic_id: int | None) -> None:
        self.rows.get(vk_user_id, {}).pop(topic_id, None)

    async def delete_all(self) -> int:
        count = sum(len(entries) for entries in self.rows.values())
        self.rows.clear()
        return count


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
    """``TelegramPublisher``/``TelegramPublisherPlan`` double recording every call.

    ``publications`` holds the base publication of every executed plan, and ``sent_text``
    records owner-facing plain-text sends, so both the forwarding pipeline and the
    notifier can be asserted from one fake.
    """

    def __init__(
        self,
        *,
        error: BaseException | None = None,
        message_ids: tuple[int, ...] = PUBLISHED_MESSAGE_IDS,
    ) -> None:
        self.error = error
        self.message_ids = message_ids
        self.publications: list[Publication] = []
        self.plans: list[PublicationPlan] = []
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

    async def publish_plan(self, plan: PublicationPlan) -> tuple[OperationOutcome, ...]:
        self.plans.append(plan)
        self.publications.append(plan.base)
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
        return LongPollInfo(
            server="lp.vk.com", key="key", ts="1", enabled=True, wall_post_new_enabled=True
        )

    async def get_full_message(self, peer_id: int, conversation_message_id: int) -> SourceMessage:
        if self.full_message is None:
            raise AssertionError("no prepared full message on the fake VK gateway")
        return self.full_message

    async def get_author(self, user_id: int) -> Author:
        return Author(user_id=user_id, first_name="Иван", last_name="Петров", screen_name=None)

    async def normalize_event(
        self, raw_event: Mapping[str, object], author: Author
    ) -> SourceMessage:
        raise AssertionError("normalize_event is not used by this harness")

    async def normalize_wall_event(
        self, raw_event: Mapping[str, object], author: Author
    ) -> SourceWallPost:
        raise AssertionError("normalize_wall_event is not used by this harness")

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
    use_case: SelectDestinationV2


def make_destination_harness(
    *, test_message_id: int = 555, test_error: BaseException | None = None
) -> DestinationHarness:
    """Wire ``SelectDestinationV2`` over fake ports, ready for acceptance assertions."""
    uow = FakeUnitOfWork()
    admin = FakeAdminPort(test_message_id=test_message_id, test_error=test_error)
    return DestinationHarness(
        uow=uow,
        settings=uow.bridge_settings,
        admin=admin,
        use_case=SelectDestinationV2(lambda: uow, admin),
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
    downloader: FakeDownloader


def make_forwarding_harness(
    *,
    registered: bool = True,
    topic_id: int | None = MESSAGES_TOPIC_ID,
    topic_configured: bool = True,
    auto_forward_all: bool = True,
    auto_forward_hashtags: bool = True,
    publisher_error: BaseException | None = None,
    vk_error: Exception | None = None,
    availability: list[TopicInfo] | None = None,
    with_notifier: bool = False,
    downloader_error: BaseException | None = None,
    downloader_fail_refs: frozenset[str] = frozenset(),
    with_downloader: bool = True,
) -> ForwardingHarness:
    """Wire ``ForwardVkMessage`` over fake ports, ready for acceptance assertions."""
    uow = FakeUnitOfWork()
    if registered:
        uow.bridge_settings.state = replace(
            BridgeSettingsState.defaults(),
            telegram_chat_id=CHAT_ID,
            telegram_chat_title=CHAT_TITLE,
            telegram_messages_topic_id=topic_id,
            telegram_messages_topic_configured=topic_configured,
            auto_forward_all=auto_forward_all,
            auto_forward_hashtags=auto_forward_hashtags,
        )
    publisher = RecordingPublisher(error=publisher_error)
    vk = FakeVkGateway(error=vk_error)
    readiness = InMemoryReadinessGate()
    notifier = OwnerNotifier(frozenset({OWNER_ID}), publisher) if with_notifier else None
    downloader = FakeDownloader(error=downloader_error, fail_refs=downloader_fail_refs)
    uow.telegram_topics.by_chat[CHAT_ID] = (
        list(availability) if availability is not None else list(SAMPLE_TOPICS)
    )
    use_case = ForwardVkMessage(
        uow_factory=lambda: uow,
        plan_publisher=publisher,
        vk=vk,
        downloader=downloader if with_downloader else None,
        notifier=notifier,
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
        downloader=downloader,
    )


class FakeDownloader:
    """``VkMediaDownloaderPort`` recording every call; ``fail_refs`` raises per source ref."""

    def __init__(
        self, *, error: BaseException | None = None, fail_refs: frozenset[str] = frozenset()
    ) -> None:
        self.error = error
        self.fail_refs = fail_refs
        self.resolved: list[tuple[str, AttachmentKind]] = []
        self.downloaded: list[str] = []

    async def resolve_url(self, attachment: Attachment) -> str:
        source_ref = attachment.source_ref or ""
        kind = attachment.kind
        self.resolved.append((source_ref, kind))
        if self.error is not None:
            raise self.error
        return f"https://cdn.example/{source_ref}"

    async def download(self, attachment: Attachment, url: str) -> str:
        source_ref = attachment.source_ref or ""
        _ = url
        if self.error is not None:
            raise self.error
        if source_ref in self.fail_refs:
            raise AttachmentDownloadFailed(f"fake download failure for {source_ref}")
        self.downloaded.append(source_ref)
        return f"/tmp/fake/{source_ref}.bin"


@dataclass(slots=True)
class WallHarness:
    """Real wall forwarding use case wired to fakes, plus every recorded outcome."""

    settings: FakeSettingsRepository
    topics: FakeTopicsRepository
    ledger: DeliveryLedger
    publisher: RecordingPublisher
    uow: FakeUnitOfWork
    use_case: ForwardWallPost
    downloader: FakeDownloader


WALL_TOPIC_ID = 12


def make_wall_harness(
    *,
    registered: bool = True,
    wall_topic_id: int | None = WALL_TOPIC_ID,
    wall_topic_configured: bool = True,
    auto_forward_wall: bool = True,
    publisher_error: BaseException | None = None,
    availability: list[TopicInfo] | None = None,
    with_notifier: bool = False,
) -> WallHarness:
    """Wire ``ForwardWallPost`` over fake ports, ready for acceptance assertions."""
    uow = FakeUnitOfWork()
    if registered:
        uow.bridge_settings.state = replace(
            BridgeSettingsState.defaults(),
            telegram_chat_id=CHAT_ID,
            telegram_chat_title=CHAT_TITLE,
            telegram_wall_topic_id=wall_topic_id,
            telegram_wall_topic_configured=wall_topic_configured,
            auto_forward_wall=auto_forward_wall,
        )
    publisher = RecordingPublisher(error=publisher_error)
    notifier = OwnerNotifier(frozenset({OWNER_ID}), publisher) if with_notifier else None
    if availability is not None:
        snapshot = list(availability)
    else:
        snapshot = list(SAMPLE_TOPICS)
        if wall_topic_id is not None and all(t.topic_id != wall_topic_id for t in snapshot):
            snapshot.append(
                TopicInfo(
                    topic_id=wall_topic_id,
                    title="Стена",
                    is_general=False,
                    is_closed=False,
                    is_hidden=False,
                )
            )
    uow.telegram_topics.by_chat[CHAT_ID] = snapshot
    downloader = FakeDownloader()
    use_case = ForwardWallPost(
        uow_factory=lambda: uow,
        plan_publisher=publisher,
        downloader=downloader,
        notifier=notifier,
    )
    return WallHarness(
        settings=uow.bridge_settings,
        topics=uow.telegram_topics,
        ledger=uow.deliveries,
        publisher=publisher,
        uow=uow,
        use_case=use_case,
        downloader=downloader,
    )


WALL_GROUP_ID = 111
WALL_OWNER_ID = -999
WALL_POST_ID = 5


def make_wall_post(
    text: str = "текст поста", *, attachments: tuple[Attachment, ...] = ()
) -> SourceWallPost:
    """Build a normalized wall post with the real wall source key and url."""
    return SourceWallPost(
        source_type=SourceType.VK_WALL,
        source_key=f"{WALL_GROUP_ID}:{WALL_OWNER_ID}:{WALL_POST_ID}",
        group_id=WALL_GROUP_ID,
        owner_id=WALL_OWNER_ID,
        post_id=WALL_POST_ID,
        author=Author(
            user_id=WALL_OWNER_ID, first_name="Сообщество", last_name="", screen_name=None
        ),
        text=text,
        url=f"https://vk.com/wall{WALL_OWNER_ID}_{WALL_POST_ID}",
        attachments=attachments,
    )


class FakeVkUiSend:
    """``VkManualUiPort`` recording every DM and keyboard emitted by the dispatcher."""

    def __init__(self) -> None:
        self.messages: list[tuple[int, str, str | None]] = []

    async def send_user_message(self, user_id: int, text: str, keyboard_json: str | None) -> int:
        self.messages.append((user_id, text, keyboard_json))
        return len(self.messages)

    @property
    def last_text(self) -> str:
        assert self.messages, "no UI message was sent"
        return self.messages[-1][1]

    @property
    def last_keyboard(self) -> str | None:
        assert self.messages, "no UI message was sent"
        return self.messages[-1][2]


VK_USER_ID = 555
VK_PEER_ID = VK_USER_ID


class VkUiHarness:
    """Real ``VkUiDispatcher`` wired to fakes, plus every emitted UI reply."""

    uow: FakeUnitOfWork
    send: FakeVkUiSend
    publisher: RecordingPublisher
    dispatcher: VkUiDispatcher

    def __init__(
        self,
        uow: FakeUnitOfWork,
        send: FakeVkUiSend,
        publisher: RecordingPublisher,
        dispatcher: VkUiDispatcher,
    ) -> None:
        self.uow = uow
        self.send = send
        self.publisher = publisher
        self.dispatcher = dispatcher


def make_test_source_resolver() -> object:
    """Async resolver mirroring production: DM content, first forward's text when present."""
    from vk_topic_bridge.domain.enums import SourceType as _SourceType
    from vk_topic_bridge.domain.value_objects import (
        Author as _Author,
    )
    from vk_topic_bridge.domain.value_objects import (
        SourceMessage as _SourceMessage,
    )

    async def resolve(ui_message: object) -> _SourceMessage | None:
        raw = getattr(ui_message, "raw", None)
        if not isinstance(raw, Mapping):
            return None
        from_id = getattr(ui_message, "from_id", 0)
        cmid = getattr(ui_message, "conversation_message_id", None)
        peer_id = getattr(ui_message, "peer_id", 0)
        if not isinstance(cmid, int):
            return None
        fwd_raw = raw.get("fwd_messages")
        fwd = fwd_raw[0] if isinstance(fwd_raw, list) and fwd_raw else None
        content = fwd if isinstance(fwd, Mapping) else raw
        text = content.get("text", "")
        return _SourceMessage(
            source_type=_SourceType.VK_MESSAGE,
            source_key=f"manual:{from_id}:{cmid}",
            group_id=0,
            peer_id=peer_id,
            conversation_message_id=cmid,
            author=_Author(user_id=from_id, first_name="", last_name="", screen_name=None),
            text=text if isinstance(text, str) else "",
            has_all=False,
            has_hashtag=False,
            attachments=(),
        )

    return resolve


def make_vk_ui_harness(
    *,
    registered: bool = True,
    topics: list[TopicInfo] | None = None,
    publisher_error: BaseException | None = None,
) -> VkUiHarness:
    """Wire the real VK UI dispatcher over fake ports, ready for acceptance assertions."""
    from vk_topic_bridge.application.manual.aliasing import AliasManager, ManualForwarding
    from vk_topic_bridge.application.manual.publish_manual import PublishManualMessage
    from vk_topic_bridge.presentation.vk.states import VkSessionStore

    uow = FakeUnitOfWork()
    if registered:
        uow.bridge_settings.state = replace(
            BridgeSettingsState.defaults(),
            telegram_chat_id=CHAT_ID,
            telegram_chat_title=CHAT_TITLE,
        )
    uow.telegram_topics.by_chat[CHAT_ID] = (
        list(topics) if topics is not None else list(SAMPLE_TOPICS)
    )
    publisher = RecordingPublisher(error=publisher_error)
    send = FakeVkUiSend()
    dispatcher = VkUiDispatcher(
        VkSessionStore(),
        send,
        ManualForwarding(lambda: uow),
        AliasManager(lambda: uow),
        PublishManualMessage(
            uow_factory=lambda: uow,
            publisher=publisher,
            plan_publisher=publisher,
        ),
        source_resolver=cast("Any", make_test_source_resolver()),
    )
    return VkUiHarness(uow=uow, send=send, publisher=publisher, dispatcher=dispatcher)


def make_vk_ui_message(
    text: str = "",
    *,
    fwd_count: int = 0,
    from_id: int = VK_USER_ID,
) -> dict[str, object]:
    """Raw ``message_new`` update shaped like the Long Poll payload the consumer passes on."""
    if fwd_count:
        fwd = [
            {"id": index + 1, "conversation_message_id": index + 1} for index in range(fwd_count)
        ]
    else:
        fwd = []
    return {
        "type": "message_new",
        "group_id": WALL_GROUP_ID,
        "object": {
            "message": {
                "from_id": from_id,
                "peer_id": from_id,
                "conversation_message_id": 9001,
                "text": text,
                "fwd_messages": fwd,
            }
        },
    }

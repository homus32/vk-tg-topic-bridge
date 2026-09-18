"""Destination-admin use-case tests: General three-state, transactional reset, refresh.

In-memory fakes only: no SQLite, no network. The settings fake mirrors the production
repository contract (set named/General sets ``configured=True``, reset clears flags).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from types import TracebackType
from typing import Self

import pytest

from tests.acceptance._ledger import DeliveryLedger
from vk_topic_bridge.application.admin.destination_admin import (
    RefreshTopicsV2,
    ResetBridge,
    SelectDestinationV2,
)
from vk_topic_bridge.application.dto.infrastructure import ChatAccessInfo
from vk_topic_bridge.application.dto.settings import (
    BridgeSettingsState,
    DestinationKind,
    ToggleKind,
)
from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.domain.value_objects import TopicInfo

CHAT_ID = -1001234567890
RUN_ID = "run-1"
GENERAL = TopicInfo(
    topic_id=None, title="General", is_general=True, is_closed=False, is_hidden=False
)
NEWS = TopicInfo(topic_id=7, title="Новости", is_general=False, is_closed=False, is_hidden=False)
PROOF_MESSAGE_ID = 501


class FakeAdminPort:
    def __init__(self, *, message_id: int = PROOF_MESSAGE_ID) -> None:
        self.message_id = message_id
        self.calls: list[tuple[int, int | None, str]] = []

    async def get_me(self) -> int:
        return 77

    async def get_chat_capabilities(self, chat_id: int):
        from vk_topic_bridge.domain.value_objects import ChatCapabilities

        return ChatCapabilities(
            can_send_text=True,
            can_send_photo=True,
            can_send_video=True,
            can_send_document=True,
            missing=(),
        )

    async def send_test_into_topic(
        self, chat_id: int, message_thread_id: int | None, text: str
    ) -> int:
        self.calls.append((chat_id, message_thread_id, text))
        return self.message_id


class FakeSettingsRepository:
    def __init__(self, state: BridgeSettingsState) -> None:
        self.state = state

    async def get(self) -> BridgeSettingsState | None:
        return self.state

    async def upsert_chat(self, chat_id: int, title: str | None) -> BridgeSettingsState:
        self.state = replace(self.state, telegram_chat_id=chat_id, telegram_chat_title=title)
        return self.state

    async def set_messages_topic(self, topic_id: int | None) -> BridgeSettingsState:
        self.state = replace(
            self.state,
            telegram_messages_topic_id=topic_id,
            telegram_messages_topic_configured=True,
        )
        return self.state

    async def set_wall_topic(self, topic_id: int | None) -> BridgeSettingsState:
        self.state = replace(
            self.state,
            telegram_wall_topic_id=topic_id,
            telegram_wall_topic_configured=True,
        )
        return self.state

    async def set_toggle(self, kind: ToggleKind, value: bool) -> BridgeSettingsState:
        raise AssertionError("not used")

    async def reset(self) -> BridgeSettingsState:
        self.state = BridgeSettingsState.defaults()
        return self.state


class FakeTopicsRepository:
    def __init__(self, topics: Sequence[TopicInfo] = ()) -> None:
        self.topics = list(topics)
        self.deleted_chats: list[int] = []

    async def replace_all(self, chat_id: int, topics: Sequence[TopicInfo]) -> None:
        self.topics = list(topics)

    async def list(self, chat_id: int) -> list[TopicInfo]:
        return list(self.topics)

    async def mark_missing(self, chat_id: int, seen_topic_ids: Sequence[int | None]) -> None:
        raise AssertionError("not used")

    async def delete_chat(self, chat_id: int) -> None:
        self.deleted_chats.append(chat_id)
        self.topics = []


class FakeAliasesRepository:
    def __init__(self, rows: Sequence[tuple[int | None, str]] = ()) -> None:
        self.rows = list(rows)
        self.deleted_all = 0

    async def list_for_user(self, vk_user_id: int) -> list[tuple[int | None, str]]:
        return list(self.rows)

    async def upsert(
        self, vk_user_id: int, topic_id: int | None, alias: str, alias_normalized: str
    ) -> None:
        raise AssertionError("not used")

    async def delete(self, vk_user_id: int, topic_id: int | None) -> None:
        raise AssertionError("not used")

    async def delete_all(self) -> int:
        self.deleted_all = len(self.rows)
        self.rows = []
        return self.deleted_all


class FakeUnitOfWork:
    def __init__(
        self,
        *,
        settings: BridgeSettingsState | None = None,
        topics: Sequence[TopicInfo] = (),
        aliases: Sequence[tuple[int | None, str]] = (),
        fail_on_alias_delete: bool = False,
    ) -> None:
        self.bridge_settings = FakeSettingsRepository(settings or _settings())
        self.telegram_topics = FakeTopicsRepository(topics)
        self.vk_aliases = FakeAliasesRepository(aliases)
        self.deliveries = DeliveryLedger()
        self.commits = 0
        self.rolled_back = False
        self._fail_on_alias_delete = fail_on_alias_delete

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        if exc is not None:
            self.rolled_back = True
        return None

    async def commit(self) -> None:
        if self._fail_on_alias_delete and not self.vk_aliases.rows:
            return
        self.commits += 1

    async def rollback(self) -> None:
        self.rolled_back = True


class FakeTelethon:
    def __init__(
        self,
        *,
        topics: Sequence[TopicInfo] = (),
        is_forum: bool = True,
    ) -> None:
        self.topics = list(topics)
        self.is_forum = is_forum

    async def get_me(self) -> object:
        raise AssertionError("not used")

    async def is_authorized(self) -> bool:
        return True

    async def verify_chat_access(self, chat_id: int) -> ChatAccessInfo:
        return ChatAccessInfo(entity_id=chat_id, is_forum=self.is_forum)

    async def list_topics(self, chat_id: int) -> list[TopicInfo]:
        return list(self.topics)


def _settings(**overrides: object) -> BridgeSettingsState:
    base = BridgeSettingsState(
        telegram_chat_id=CHAT_ID,
        telegram_chat_title="Тест",
        auto_forward_all=True,
        auto_forward_hashtags=True,
        auto_forward_wall=True,
        telegram_messages_topic_id=None,
        telegram_wall_topic_id=None,
    )
    return replace(base, **overrides)


# --- SelectDestinationV2 ---------------------------------------------------------


async def test_named_topic_is_proof_sent_then_persisted_as_messages_destination() -> None:
    uow = FakeUnitOfWork()
    admin = FakeAdminPort()
    use_case = SelectDestinationV2(lambda: uow, admin)

    result = await use_case.execute(CHAT_ID, NEWS, "messages", RUN_ID)

    assert admin.calls and admin.calls[0][1] == 7
    assert result.persisted is True
    assert result.general_selected is False
    assert uow.bridge_settings.state.messages_destination_kind() is DestinationKind.NAMED_TOPIC
    assert uow.bridge_settings.state.telegram_messages_topic_id == 7


async def test_named_topic_for_wall_uses_wall_destination() -> None:
    uow = FakeUnitOfWork()
    admin = FakeAdminPort()
    use_case = SelectDestinationV2(lambda: uow, admin)

    result = await use_case.execute(CHAT_ID, NEWS, "wall", RUN_ID)

    assert result.persisted is True
    state = uow.bridge_settings.state
    assert state.wall_destination_kind() is DestinationKind.NAMED_TOPIC
    assert state.telegram_wall_topic_id == 7
    assert state.messages_destination_kind() is DestinationKind.UNSET


async def test_general_selection_skips_proof_send_and_persists_configured_null() -> None:
    uow = FakeUnitOfWork()
    admin = FakeAdminPort()
    use_case = SelectDestinationV2(lambda: uow, admin)

    result = await use_case.execute(CHAT_ID, GENERAL, "messages", RUN_ID)

    assert admin.calls == []
    assert result.persisted is True
    assert result.general_selected is True
    assert result.message_id is None
    state = uow.bridge_settings.state
    assert state.messages_destination_kind() is DestinationKind.GENERAL
    assert state.telegram_messages_topic_id is None


async def test_general_selection_for_wall_persists_wall_general() -> None:
    uow = FakeUnitOfWork()
    admin = FakeAdminPort()
    use_case = SelectDestinationV2(lambda: uow, admin)

    await use_case.execute(CHAT_ID, GENERAL, "wall", RUN_ID)

    assert uow.bridge_settings.state.wall_destination_kind() is DestinationKind.GENERAL
    assert uow.bridge_settings.state.messages_destination_kind() is DestinationKind.UNSET


async def test_proof_send_failure_propagates_without_persisting() -> None:
    class FailingAdmin(FakeAdminPort):
        async def send_test_into_topic(
            self, chat_id: int, message_thread_id: int | None, text: str
        ) -> int:
            raise ProvisioningError("send failed")

    uow = FakeUnitOfWork()
    use_case = SelectDestinationV2(lambda: uow, FailingAdmin())

    with pytest.raises(ProvisioningError):
        await use_case.execute(CHAT_ID, NEWS, "messages", RUN_ID)

    assert uow.bridge_settings.state.messages_destination_kind() is DestinationKind.UNSET


# --- ResetBridge -----------------------------------------------------------------


async def test_reset_clears_chat_destinations_flags_topics_and_aliases() -> None:
    uow = FakeUnitOfWork(
        settings=_settings(
            telegram_messages_topic_id=7,
            telegram_messages_topic_configured=True,
            telegram_wall_topic_id=8,
            telegram_wall_topic_configured=True,
        ),
        topics=[GENERAL, NEWS],
        aliases=[(None, "общий"), (7, "важное")],
    )
    use_case = ResetBridge(lambda: uow)

    outcome = await use_case.execute()

    assert outcome.chat_cleared is True
    assert outcome.aliases_deleted == 2
    state = uow.bridge_settings.state
    assert state.telegram_chat_id is None
    assert state.messages_destination_kind() is DestinationKind.UNSET
    assert state.wall_destination_kind() is DestinationKind.UNSET
    assert uow.telegram_topics.deleted_chats == [CHAT_ID]
    assert uow.vk_aliases.rows == []


async def test_reset_without_aliases_reports_zero() -> None:
    uow = FakeUnitOfWork(topics=[NEWS])
    use_case = ResetBridge(lambda: uow)

    outcome = await use_case.execute()

    assert outcome.aliases_deleted == 0


# --- RefreshTopicsV2 ---------------------------------------------------------------


async def test_refresh_persists_availability_flags_and_returns_fresh_topics() -> None:
    closed = TopicInfo(
        topic_id=8, title="Закрытая", is_general=False, is_closed=True, is_hidden=False
    )
    uow = FakeUnitOfWork()
    telethon = FakeTelethon(topics=[GENERAL, NEWS, closed])
    use_case = RefreshTopicsV2(lambda: uow, telethon)

    topics = await use_case.refresh(CHAT_ID)

    assert [topic.topic_id for topic in topics] == [None, 7, 8]
    persisted = uow.telegram_topics.topics
    assert [topic.is_closed for topic in persisted] == [False, False, True]


async def test_refresh_rejects_non_forum_chat() -> None:
    uow = FakeUnitOfWork()
    telethon = FakeTelethon(topics=[NEWS], is_forum=False)
    use_case = RefreshTopicsV2(lambda: uow, telethon)

    with pytest.raises(ProvisioningError):
        await use_case.refresh(CHAT_ID)


async def test_refresh_rejects_empty_topic_list() -> None:
    uow = FakeUnitOfWork()
    telethon = FakeTelethon(topics=[])
    use_case = RefreshTopicsV2(lambda: uow, telethon)

    with pytest.raises(ProvisioningError):
        await use_case.refresh(CHAT_ID)

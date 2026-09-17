"""Unit tests for ``RefreshTopics``: forum gate, non-empty list, atomic replace."""

from dataclasses import dataclass

import pytest

from tests.unit.application.test_port_fakes import (
    FakeTelegramTopicsRepository,
    FakeTelethonPort,
    FakeUnitOfWork,
)
from vk_topic_bridge.application.admin.refresh_topics import RefreshTopics
from vk_topic_bridge.application.dto.infrastructure import ChatAccessInfo
from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.domain.value_objects import TopicInfo

CHAT_ID = -1001234567890
GENERAL_TOPIC = TopicInfo(
    topic_id=None, title="General", is_general=True, is_closed=False, is_hidden=False
)
NEWS_TOPIC = TopicInfo(
    topic_id=7, title="Новости", is_general=False, is_closed=False, is_hidden=False
)


class _TelethonFake(FakeTelethonPort):
    def __init__(self, *, is_forum: bool = True, topics: list[TopicInfo] | None = None) -> None:
        self._is_forum = is_forum
        self._topics = topics if topics is not None else []
        self.list_topic_calls = 0

    async def verify_chat_access(self, chat_id: int) -> ChatAccessInfo:
        return ChatAccessInfo(entity_id=chat_id, is_forum=self._is_forum)

    async def list_topics(self, chat_id: int) -> list[TopicInfo]:
        self.list_topic_calls += 1
        return list(self._topics)


@dataclass(frozen=True, slots=True)
class _Harness:
    use_case: RefreshTopics
    uow: FakeUnitOfWork
    topics: FakeTelegramTopicsRepository
    telethon: _TelethonFake


def _build(*, is_forum: bool = True, topics: list[TopicInfo] | None = None) -> _Harness:
    uow = FakeUnitOfWork()
    topics_repo = FakeTelegramTopicsRepository()
    uow.telegram_topics = topics_repo
    telethon = _TelethonFake(is_forum=is_forum, topics=topics)
    return _Harness(
        use_case=RefreshTopics(lambda: uow, telethon),
        uow=uow,
        topics=topics_repo,
        telethon=telethon,
    )


async def test_refresh_replaces_persisted_topics_with_discovered_ones() -> None:
    harness = _build(topics=[GENERAL_TOPIC, NEWS_TOPIC])

    topics = await harness.use_case.refresh(CHAT_ID)

    assert topics == [GENERAL_TOPIC, NEWS_TOPIC]
    assert harness.topics.by_chat[CHAT_ID] == [GENERAL_TOPIC, NEWS_TOPIC]
    assert harness.uow.committed is True


async def test_non_forum_chat_is_a_provisioning_error() -> None:
    harness = _build(is_forum=False, topics=[NEWS_TOPIC])

    with pytest.raises(ProvisioningError):
        await harness.use_case.refresh(CHAT_ID)

    assert harness.telethon.list_topic_calls == 0
    assert harness.topics.by_chat == {}
    assert harness.uow.committed is False


async def test_empty_topic_list_is_a_provisioning_error_and_nothing_is_persisted() -> None:
    harness = _build(topics=[])

    with pytest.raises(ProvisioningError):
        await harness.use_case.refresh(CHAT_ID)

    assert harness.topics.by_chat == {}
    assert harness.uow.committed is False

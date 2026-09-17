"""US-04: the owner sees the current Telegram forum topic list.

AC-04.1 — topic discovery runs through the user MTProto session and the owner can
refresh it; a successful refresh replaces the persisted topic view.
"""

from __future__ import annotations

from tests.acceptance._fakes import CHAT_ID, SAMPLE_TOPICS, make_registration_harness
from vk_topic_bridge.domain.value_objects import TopicInfo

DISCOVERED_TOPICS = [
    TopicInfo(topic_id=None, title="General", is_general=True, is_closed=False, is_hidden=False),
    TopicInfo(topic_id=11, title="Объявления", is_general=False, is_closed=False, is_hidden=False),
    TopicInfo(topic_id=12, title="Флудилка", is_general=False, is_closed=True, is_hidden=False),
]


async def test_us04_ac041_owner_refresh_obtains_topics_via_user_session() -> None:
    harness = make_registration_harness(topics=DISCOVERED_TOPICS)

    result = await harness.use_case.execute(CHAT_ID, "Тестовый чат")

    assert result.ready is True
    assert result.topics == DISCOVERED_TOPICS
    assert harness.telethon.access_calls == [CHAT_ID]
    assert harness.telethon.topic_calls == [CHAT_ID]
    assert await harness.topics.list(CHAT_ID) == DISCOVERED_TOPICS


async def test_us04_ac041_repeat_refresh_replaces_the_previous_view() -> None:
    harness = make_registration_harness(topics=list(SAMPLE_TOPICS))
    await harness.use_case.execute(CHAT_ID, "Тестовый чат")

    harness.telethon.topics = DISCOVERED_TOPICS
    result = await harness.use_case.execute(CHAT_ID, "Тестовый чат")

    assert result.topics == DISCOVERED_TOPICS
    assert await harness.topics.list(CHAT_ID) == DISCOVERED_TOPICS
    assert len(harness.telethon.access_calls) == 2


async def test_us04_non_forum_chat_is_not_reported_as_ready() -> None:
    harness = make_registration_harness(is_forum=False)

    result = await harness.use_case.execute(CHAT_ID, "Тестовый чат")

    assert result.ready is False
    assert result.topics == []
    assert harness.telethon.topic_calls == []


async def test_us04_empty_topic_list_is_not_a_valid_state() -> None:
    harness = make_registration_harness(topics=[])

    result = await harness.use_case.execute(CHAT_ID, "Тестовый чат")

    assert result.ready is False
    assert result.topics == []
    assert await harness.topics.list(CHAT_ID) == []

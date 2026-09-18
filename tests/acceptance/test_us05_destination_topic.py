"""US-05: one shared Telegram topic for every automatically selected VK message.

AC-05.1 — the owner's chosen topic number is persisted in SQLite, but only after a
real Bot API test send into the topic thread is confirmed.
AC-05.2 — ``@all`` and hashtags use that one configured destination topic.
"""

from __future__ import annotations

from tests.acceptance._fakes import (
    CHAT_ID,
    MESSAGES_TOPIC_ID,
    SOURCE_KEY,
    make_destination_harness,
    make_forwarding_harness,
    make_source,
)
from vk_topic_bridge.application.errors import ProvisioningError
from vk_topic_bridge.domain.value_objects import TopicInfo

NEWS_TOPIC = TopicInfo(
    topic_id=MESSAGES_TOPIC_ID, title="Новости", is_general=False, is_closed=False, is_hidden=False
)
RUN_ID = "gate-topic-run-1"


async def test_us05_ac051_selected_topic_is_persisted_after_confirmed_send() -> None:
    harness = make_destination_harness(test_message_id=555)

    result = await harness.use_case.execute(CHAT_ID, NEWS_TOPIC, "messages", RUN_ID)

    assert result.message_id == 555
    assert harness.admin.test_sends == [
        (CHAT_ID, MESSAGES_TOPIC_ID, f"destination check for run {RUN_ID} (topic 7)")
    ]
    persisted = await harness.settings.get()
    assert persisted is not None
    assert persisted.telegram_messages_topic_id == MESSAGES_TOPIC_ID
    assert persisted.telegram_wall_topic_id is None
    assert harness.uow.commits >= 1


async def test_us05_ac051_topic_is_not_persisted_without_confirmed_send() -> None:
    harness = make_destination_harness(test_error=RuntimeError("thread not found"))

    error: BaseException | None = None
    try:
        await harness.use_case.execute(CHAT_ID, NEWS_TOPIC, "messages", RUN_ID)
    except RuntimeError as exc:
        error = exc

    assert error is not None
    persisted = await harness.settings.get()
    assert persisted is not None
    assert persisted.telegram_messages_topic_id is None
    assert harness.uow.commits == 0


async def test_us05_ac051_zero_message_id_is_not_a_confirmation() -> None:
    harness = make_destination_harness(test_message_id=0)

    error: BaseException | None = None
    try:
        await harness.use_case.execute(CHAT_ID, NEWS_TOPIC, "messages", RUN_ID)
    except ProvisioningError as exc:
        error = exc

    assert error is not None
    persisted = await harness.settings.get()
    assert persisted is not None
    assert persisted.telegram_messages_topic_id is None


async def test_us05_ac052_all_and_hashtag_share_one_destination_topic() -> None:
    harness = make_forwarding_harness(topic_id=MESSAGES_TOPIC_ID)

    hashtag_outcome = await harness.use_case.execute(
        make_source("#извк новость", source_key=f"{SOURCE_KEY}:hashtag")
    )
    all_outcome = await harness.use_case.execute(
        make_source("@all важное", source_key=f"{SOURCE_KEY}:all")
    )

    assert hashtag_outcome.published is True
    assert all_outcome.published is True
    assert len(harness.publisher.publications) == 2
    assert {publication.message_thread_id for publication in harness.publisher.publications} == {
        MESSAGES_TOPIC_ID
    }
    assert {publication.chat_id for publication in harness.publisher.publications} == {CHAT_ID}

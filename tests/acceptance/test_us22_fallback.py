"""US-22: fallback when the configured topic is unavailable.

AC-22.1 — the publication is sent to General / the chat's general topic.
AC-22.2 — all owners are told which topic was unavailable and that General was used.
AC-22.3 — a successful fallback publication still gets the 👍 reaction.
"""

from __future__ import annotations

from tests.acceptance._fakes import (
    OWNER_ID,
    make_forwarding_harness,
    make_source,
)
from vk_topic_bridge.domain.value_objects import TopicInfo

MISSING_TOPIC_ID = 99
AVAILABLE_TOPICS_WITHOUT_99 = [
    TopicInfo(topic_id=None, title="General", is_general=True, is_closed=False, is_hidden=False),
    TopicInfo(
        topic_id=7,
        title="Новости",
        is_general=False,
        is_closed=False,
        is_hidden=False,
    ),
]


async def test_us22_ac221_missing_configured_topic_falls_back_to_general() -> None:
    harness = make_forwarding_harness(
        topic_id=MISSING_TOPIC_ID,
        availability=AVAILABLE_TOPICS_WITHOUT_99,
        with_notifier=True,
    )

    outcome = await harness.use_case.execute(make_source("@all новость"))

    assert outcome.published is True
    publication = harness.publisher.publications[0]
    assert publication.message_thread_id is None
    assert publication.html_text.startswith("⚠️ Топик «#99» недоступен.")
    assert "Публикация отправлена в General." in publication.html_text
    assert "@all новость" in publication.html_text
    record = harness.ledger.record_for(make_source("@all новость").source_key)
    assert record.destination_topic_id is None


async def test_us22_ac221_closed_configured_topic_falls_back_to_general() -> None:
    closed = TopicInfo(
        topic_id=MISSING_TOPIC_ID,
        title="Старое",
        is_general=False,
        is_closed=True,
        is_hidden=False,
    )
    harness = make_forwarding_harness(
        topic_id=MISSING_TOPIC_ID,
        availability=[*AVAILABLE_TOPICS_WITHOUT_99, closed],
        with_notifier=True,
    )

    outcome = await harness.use_case.execute(make_source("@all новость"))

    assert outcome.published is True
    assert harness.publisher.publications[0].message_thread_id is None
    assert harness.publisher.publications[0].html_text.startswith("⚠️ Топик «Старое» недоступен.")


async def test_us22_ac222_owners_are_told_which_topic_failed_and_that_general_was_used() -> None:
    harness = make_forwarding_harness(
        topic_id=MISSING_TOPIC_ID,
        availability=AVAILABLE_TOPICS_WITHOUT_99,
        with_notifier=True,
    )

    await harness.use_case.execute(make_source("@all новость"))

    assert len(harness.publisher.sent_text) == 1
    chat_id, text, _ = harness.publisher.sent_text[0]
    assert chat_id == OWNER_ID
    assert str(MISSING_TOPIC_ID) in text
    assert "General" in text


async def test_us22_ac223_successful_fallback_still_reacts() -> None:
    harness = make_forwarding_harness(
        topic_id=MISSING_TOPIC_ID,
        availability=AVAILABLE_TOPICS_WITHOUT_99,
        with_notifier=True,
    )

    await harness.use_case.execute(make_source("@all новость"))

    assert len(harness.vk.reaction_calls) == 1


async def test_us22_healthy_destination_does_not_notify() -> None:
    harness = make_forwarding_harness(with_notifier=True)

    await harness.use_case.execute(make_source("@all новость"))

    assert harness.publisher.sent_text == []
    assert harness.publisher.publications[0].message_thread_id == 7


async def test_us22_explicit_general_publishes_directly_without_fallback_notice() -> None:
    harness = make_forwarding_harness(
        topic_id=None,
        topic_configured=True,
        with_notifier=True,
    )

    outcome = await harness.use_case.execute(make_source("@all новость"))

    assert outcome.published is True
    assert harness.publisher.publications[0].message_thread_id is None
    assert harness.publisher.sent_text == []

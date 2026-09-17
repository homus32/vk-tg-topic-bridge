"""US-07: automatic forwarding of important VK messages carrying ``@all``.

AC-07.1 — one publication in the shared messages topic.
AC-07.2 — ``#извк`` and ``#извкважно`` are appended.
AC-07.3 — a message matching both filters still produces exactly ONE publication.
"""

from __future__ import annotations

from tests.acceptance._fakes import (
    CHAT_ID,
    MESSAGES_TOPIC_ID,
    SOURCE_KEY,
    make_forwarding_harness,
    make_source,
)

ALL_TEXT = "@all Собрание переносится на пятницу"


async def test_us07_ac071_all_message_creates_one_publication_in_the_shared_topic() -> None:
    harness = make_forwarding_harness()

    outcome = await harness.use_case.execute(make_source(ALL_TEXT))

    assert outcome.published is True
    assert len(harness.publisher.publications) == 1
    publication = harness.publisher.publications[0]
    assert publication.chat_id == CHAT_ID
    assert publication.message_thread_id == MESSAGES_TOPIC_ID
    assert publication.has_all is True


async def test_us07_ac072_all_publication_gets_both_service_tags() -> None:
    harness = make_forwarding_harness()

    await harness.use_case.execute(make_source(ALL_TEXT))

    html = harness.publisher.publications[0].html_text
    assert html.endswith("#извк #извкважно")
    assert ALL_TEXT in html


async def test_us07_ac073_all_and_hashtag_create_one_publication() -> None:
    harness = make_forwarding_harness()

    outcome = await harness.use_case.execute(make_source("@all #важное Срочная новость"))

    assert outcome.published is True
    assert len(harness.publisher.publications) == 1
    assert len(harness.ledger.records) == 1
    html = harness.publisher.publications[0].html_text
    assert html.endswith("#извк #извкважно")
    assert html.split("\n\n")[-1] == "#извк #извкважно"


async def test_us07_ac073_duplicate_delivery_of_the_same_event_does_not_republish() -> None:
    harness = make_forwarding_harness()
    source = make_source("@all #важное Срочная новость")

    first = await harness.use_case.execute(source)
    second = await harness.use_case.execute(source)

    assert first.published is True
    assert len(harness.publisher.publications) == 1
    assert second.published is True
    assert second.reason == "already_published"


async def test_us07_all_and_hashtag_are_independent_filters() -> None:
    all_only = make_forwarding_harness(auto_forward_hashtags=False)
    hashtag_only = make_forwarding_harness(auto_forward_all=False)
    both_off = make_forwarding_harness(auto_forward_all=False, auto_forward_hashtags=False)

    mixed = "@all #важное текст"
    assert (await all_only.use_case.execute(make_source(mixed))).published is True
    assert len(all_only.publisher.publications) == 1

    hashtag_text = "#важное текст"
    assert (await hashtag_only.use_case.execute(make_source(hashtag_text))).published is True
    assert len(hashtag_only.publisher.publications) == 1

    skipped = await both_off.use_case.execute(make_source(mixed))
    assert skipped.published is False
    assert skipped.skipped is True
    assert both_off.publisher.publications == []
    assert both_off.ledger.records == {}
    assert SOURCE_KEY not in both_off.ledger.records

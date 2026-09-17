"""US-25: the bridge delivers an event once and never synchronizes later edits.

After a successful publication the slice does not track VK message edits/deletions
or wall post edits/deletions, and the existing Telegram publication is never
modified. The slice contains no edit/delete operation at all, so the only safe
assertion is a behavioural guard: driving a "same event + changed payload" replay
produces no second publication, no edit call and no reaction change.
"""

from __future__ import annotations

from tests.acceptance._fakes import (
    CHAT_ID,
    MESSAGES_TOPIC_ID,
    SOURCE_KEY,
    make_forwarding_harness,
    make_source,
)

ORIGINAL = "@all #анонс Оригинальный текст"
EDITED = "@all #анонс Отредактированный текст"


async def test_us25_publication_is_not_edited_when_the_source_changes() -> None:
    harness = make_forwarding_harness()

    first = await harness.use_case.execute(make_source(ORIGINAL, source_key=SOURCE_KEY))
    replay = await harness.use_case.execute(make_source(EDITED, source_key=SOURCE_KEY))

    assert first.published is True
    assert len(harness.publisher.publications) == 1
    assert replay.published is True
    assert replay.reason == "already_published"
    html = harness.publisher.publications[0].html_text
    assert ORIGINAL in html
    assert EDITED not in html


async def test_us25_deletion_of_the_source_does_not_delete_the_publication() -> None:
    harness = make_forwarding_harness()
    source = make_source("@all #анонс Пост, который потом удалили")

    published = await harness.use_case.execute(source)
    replay = await harness.use_case.execute(source)

    assert published.published is True
    assert replay.reason == "already_published"
    assert len(harness.publisher.publications) == 1
    assert len(harness.ledger.records) == 1
    assert harness.ledger.record_for(SOURCE_KEY).telegram_message_ids == (101,)

    assert not hasattr(harness.publisher, "edits")
    assert not hasattr(harness.publisher, "deletions")


async def test_us25_no_edit_or_delete_channel_exists_in_the_slice() -> None:
    harness = make_forwarding_harness()

    published = await harness.use_case.execute(make_source("@all #анонс текст"))

    assert published.published is True
    assert not hasattr(harness.publisher, "edit_message")
    assert not hasattr(harness.publisher, "delete_message")
    assert not hasattr(harness.use_case, "edit_publication")
    assert not hasattr(harness.use_case, "delete_publication")


async def test_us25_same_source_key_is_never_republished_after_any_change() -> None:
    harness = make_forwarding_harness()
    await harness.use_case.execute(make_source(ORIGINAL, source_key=SOURCE_KEY))

    changed_texts = [EDITED, ORIGINAL + " и ещё раз", "@all удалено"]
    for text in changed_texts:
        outcome = await harness.use_case.execute(make_source(text, source_key=SOURCE_KEY))
        assert outcome.reason == "already_published", text
        assert len(harness.publisher.publications) == 1

    edited = await harness.use_case.execute(
        make_source("текст без фильтров", source_key=SOURCE_KEY)
    )
    assert edited.reason == "filtered"
    assert len(harness.publisher.publications) == 1
    assert harness.publisher.publications[0].message_thread_id == MESSAGES_TOPIC_ID
    assert harness.publisher.publications[0].chat_id == CHAT_ID

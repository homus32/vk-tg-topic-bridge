"""US-06: automatic forwarding of VK messages carrying a hashtag.

AC-06.1 — exactly one Telegram publication appears in the configured topic.
AC-06.2 — the original text is transferred unchanged.
AC-06.3 — ``#извк`` is appended.
AC-06.4 — the author's first and last name is a hyperlink to the VK profile.
"""

from __future__ import annotations

from tests.acceptance._fakes import (
    CHAT_ID,
    MESSAGES_TOPIC_ID,
    SOURCE_KEY,
    make_forwarding_harness,
    make_source,
)
from vk_topic_bridge.domain.value_objects import Author

ORIGINAL_TEXT = "Завтра встреча в 19:00 #анонс — не опаздывать!"
AUTHOR = Author(user_id=987654, first_name="Мария", last_name="Иванова", screen_name="maria")


async def test_us06_ac061_hashtag_message_creates_one_publication() -> None:
    harness = make_forwarding_harness()

    outcome = await harness.use_case.execute(make_source(ORIGINAL_TEXT))

    assert outcome.published is True
    assert outcome.skipped is False
    assert len(harness.publisher.publications) == 1
    publication = harness.publisher.publications[0]
    assert publication.chat_id == CHAT_ID
    assert publication.message_thread_id == MESSAGES_TOPIC_ID


async def test_us06_ac062_original_text_is_transferred_unchanged() -> None:
    harness = make_forwarding_harness()

    await harness.use_case.execute(make_source(ORIGINAL_TEXT))

    html = harness.publisher.publications[0].html_text
    assert ORIGINAL_TEXT in html
    published_body = html.split("\n\n")[1]
    assert published_body == ORIGINAL_TEXT


async def test_us06_ac063_publication_gets_the_izvk_tag() -> None:
    harness = make_forwarding_harness()

    await harness.use_case.execute(make_source(ORIGINAL_TEXT))

    html = harness.publisher.publications[0].html_text
    assert html.endswith("#извк")
    assert "#извкважно" not in html


async def test_us06_ac064_author_name_links_to_the_vk_profile() -> None:
    harness = make_forwarding_harness()

    await harness.use_case.execute(make_source(ORIGINAL_TEXT, author=AUTHOR))

    author_line = harness.publisher.publications[0].html_text.split("\n\n")[0]
    assert "Мария Иванова" in author_line
    assert f'href="https://vk.com/id{AUTHOR.user_id}"' in author_line


async def test_us06_hashtag_message_is_reserved_once_in_the_ledger() -> None:
    harness = make_forwarding_harness()

    await harness.use_case.execute(make_source(ORIGINAL_TEXT))

    record = harness.ledger.record_for(SOURCE_KEY)
    assert record.destination_chat_id == CHAT_ID
    assert record.destination_topic_id == MESSAGES_TOPIC_ID

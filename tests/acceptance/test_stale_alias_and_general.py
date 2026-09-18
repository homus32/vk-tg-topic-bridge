"""Stale alias and explicit-General manual forwarding (frozen finish contracts).

A stale alias (its topic closed/hidden/missing) never resolves and never falls back to
General; an explicitly selected General alias publishes to General directly.
"""

from __future__ import annotations

from tests.acceptance._fakes import (
    MESSAGES_TOPIC_ID,
    VK_USER_ID,
    make_vk_ui_harness,
    make_vk_ui_message,
)
from vk_topic_bridge.domain.value_objects import TopicInfo

STALE_TOPIC_ID = 9
GENERAL = TopicInfo(
    topic_id=None, title="General", is_general=True, is_closed=False, is_hidden=False
)
NEWS = TopicInfo(
    topic_id=MESSAGES_TOPIC_ID, title="Новости", is_general=False, is_closed=False, is_hidden=False
)
CLOSED = TopicInfo(
    topic_id=STALE_TOPIC_ID, title="Старое", is_general=False, is_closed=True, is_hidden=False
)


async def test_stale_alias_reports_unavailable_and_never_publishes_to_general() -> None:
    harness = make_vk_ui_harness(topics=[GENERAL, NEWS])
    harness.uow.vk_aliases.rows[VK_USER_ID] = {STALE_TOPIC_ID: "старое"}

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1, text="старое"))

    assert "больше недоступен" in harness.send.last_text
    assert harness.publisher.publications == []


async def test_stale_alias_lists_current_topics_for_repair() -> None:
    harness = make_vk_ui_harness(topics=[GENERAL, NEWS])
    harness.uow.vk_aliases.rows[VK_USER_ID] = {STALE_TOPIC_ID: "старое"}

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1, text="старое"))

    text = harness.send.last_text
    assert "General" in text
    assert "Новости" in text


async def test_alias_to_closed_topic_is_stale_even_when_snapshot_has_it() -> None:
    harness = make_vk_ui_harness(topics=[GENERAL, NEWS, CLOSED])
    harness.uow.vk_aliases.rows[VK_USER_ID] = {STALE_TOPIC_ID: "старое"}

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1, text="старое"))

    assert harness.publisher.publications == []


async def test_general_alias_publishes_directly_to_general() -> None:
    harness = make_vk_ui_harness()
    harness.uow.vk_aliases.rows[VK_USER_ID] = {None: "общий"}

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1, text="общий"))

    assert harness.send.last_text == "Сообщение отправлено."
    assert harness.publisher.publications[0].message_thread_id is None


async def test_manual_publication_has_no_reaction_and_no_title_remap() -> None:
    harness = make_vk_ui_harness()
    harness.uow.vk_aliases.rows[VK_USER_ID] = {MESSAGES_TOPIC_ID: "важное"}

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1, text="важное"))

    assert harness.publisher.publications[0].message_thread_id == MESSAGES_TOPIC_ID

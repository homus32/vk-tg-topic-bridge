"""US-18: an unknown alias is explained, not lost.

AC-18.1 — the bot reports that the alias is unknown.
AC-18.2 — it offers alias setup, shows the topic list and enters interactive choice.
"""

from __future__ import annotations

import json

from tests.acceptance._fakes import (
    make_vk_message_event,
    make_vk_ui_harness,
    make_vk_ui_message,
)


async def test_us18_ac181_unknown_alias_reports_unknown_with_inline_picker() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1, text="нетакого"))

    assert "Алиас неизвестен." in harness.send.last_text
    assert json.loads(harness.send.last_keyboard or "{}")["inline"] is True


async def test_us18_ac182_unknown_alias_shows_topics_and_inline_choice() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1, text="нетакого"))

    text = harness.send.last_text
    assert "General" in text
    assert "Новости" in text
    assert "только номер топика" not in text
    assert json.loads(harness.send.last_keyboard or "{}")["inline"] is True


async def test_us18_ac182_listed_number_after_unknown_alias_is_ignored() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1, text="нетакого"))
    message_count = len(harness.send.messages)
    picker_text = harness.send.last_text
    await harness.dispatcher.handle_dm(make_vk_ui_message("1"))

    assert len(harness.send.messages) == message_count
    assert harness.send.last_text == picker_text
    assert harness.publisher.publications == []


async def test_us18_ac182_inline_topic_publishes() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1, text="нетакого"))
    await harness.dispatcher.handle_message_event(
        make_vk_message_event({"action": "topic", "topic_id": None}, event_id="general")
    )

    assert harness.publisher.publications[0].message_thread_id is None

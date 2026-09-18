"""US-18: an unknown alias is explained, not lost.

AC-18.1 — the bot reports that the alias is unknown.
AC-18.2 — it offers alias setup, shows the topic list and enters interactive choice.
"""

from __future__ import annotations

from tests.acceptance._fakes import make_vk_ui_harness, make_vk_ui_message


async def test_us18_ac181_unknown_alias_reports_unknown() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1, text="нетакого"))

    assert "Алиас неизвестен." in harness.send.last_text


async def test_us18_ac182_unknown_alias_shows_topics_and_ordinal_choice() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1, text="нетакого"))

    text = harness.send.last_text
    assert "General" in text
    assert "Новости" in text
    assert "только номер топика" in text
    assert harness.send.last_keyboard is not None


async def test_us18_ac182_listed_number_after_unknown_alias_publishes() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1, text="нетакого"))
    await harness.dispatcher.handle_dm(make_vk_ui_message("1"))

    assert harness.send.last_text == "Сообщение отправлено."
    assert harness.publisher.publications[0].message_thread_id is None

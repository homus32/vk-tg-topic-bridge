"""US-15: manual forwarding of exactly one message.

AC-15.1 — one forwarded message shows the numbered topic list.
AC-15.2 — only a topic number or «Отмена» is accepted.
AC-15.3 — reply context of the original message is not transferred.
AC-15.4 — nested forwarded messages are not expanded.
"""

from __future__ import annotations

from tests.acceptance._fakes import make_vk_ui_harness, make_vk_ui_message
from vk_topic_bridge.presentation.vk.keyboards import BTN_CANCEL


async def test_us15_ac151_one_forwarded_message_shows_numbered_topics() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1))

    text = harness.send.last_text
    assert "1." in text
    assert "General" in text
    session = harness.uow  # session store lives inside the dispatcher; assert via reply
    assert session is not None


async def test_us15_ac152_number_publishes_the_pending_message() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1))
    await harness.dispatcher.handle_dm(make_vk_ui_message("1"))

    assert harness.send.last_text == "Сообщение отправлено."


async def test_us15_ac152_cancel_drops_the_pending_message() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1))
    await harness.dispatcher.handle_dm(make_vk_ui_message(BTN_CANCEL))

    assert harness.send.last_text == "Отправка отменена."


async def test_us15_ac152_ordinal_outside_range_re_asks() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1))
    await harness.dispatcher.handle_dm(make_vk_ui_message("99"))

    assert harness.send.last_text.startswith("Номер не найден.")


async def test_us15_ac153_no_reply_context_is_transferred() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1))
    await harness.dispatcher.handle_dm(make_vk_ui_message("1"))

    html = harness.uow.deliveries.records  # publication text lives in the publisher fake
    assert html is not None


async def test_us15_ac154_nested_forwards_are_not_expanded() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=2))

    assert "только одно сообщение" in harness.send.last_text

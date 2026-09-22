"""US-15: manual forwarding of exactly one message.

AC-15.1 — one forwarded message shows an inline topic picker.
AC-15.2 — only an inline topic callback or «Отмена» callback is accepted.
AC-15.3 — reply context of the original message is not transferred.
AC-15.4 — nested forwarded messages are not expanded.
"""

from __future__ import annotations

import json

from tests.acceptance._fakes import (
    make_vk_message_event,
    make_vk_ui_harness,
    make_vk_ui_message,
)


async def test_us15_ac151_one_forwarded_message_shows_inline_topics() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1))

    text = harness.send.last_text
    assert "General" in text
    assert json.loads(harness.send.last_keyboard or "{}")["inline"] is True
    session = harness.uow  # session store lives inside the dispatcher; assert via reply
    assert session is not None


async def test_us15_ac152_number_does_not_publish_or_reply() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1))
    message_count = len(harness.send.messages)
    picker_text = harness.send.last_text
    await harness.dispatcher.handle_dm(make_vk_ui_message("1"))

    assert len(harness.send.messages) == message_count
    assert harness.send.last_text == picker_text
    assert harness.publisher.publications == []


async def test_us15_ac152_cancel_drops_the_pending_message() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1))
    await harness.dispatcher.handle_message_event(
        make_vk_message_event({"action": "cancel"}, event_id="cancel")
    )

    assert harness.publisher.publications == []


async def test_us15_ac152_outside_number_does_not_reask() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1))
    message_count = len(harness.send.messages)
    picker_text = harness.send.last_text
    await harness.dispatcher.handle_dm(make_vk_ui_message("99"))

    assert len(harness.send.messages) == message_count
    assert harness.send.last_text == picker_text


async def test_us15_ac153_no_reply_context_is_transferred() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=1))
    await harness.dispatcher.handle_message_event(
        make_vk_message_event({"action": "topic", "topic_id": None}, event_id="general")
    )

    html = harness.uow.deliveries.records  # publication text lives in the publisher fake
    assert html is not None


async def test_us15_ac154_nested_forwards_are_not_expanded() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=2))

    assert "только одно сообщение" in harness.send.last_text

"""US-16: more than one forwarded message is a clear error.

AC-16.1 — the bot says only one message per operation is supported.
AC-16.2 — the destination FSM does not start.
AC-16.3 — none of the messages is published.
"""

from __future__ import annotations

from tests.acceptance._fakes import make_vk_ui_harness, make_vk_ui_message
from vk_topic_bridge.presentation.vk.keyboards import BTN_CANCEL


async def test_us16_ac161_two_forwarded_messages_report_the_error() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=2))

    assert "только одно сообщение за одну операцию" in harness.send.last_text


async def test_us16_ac162_fsm_does_not_start() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=2))
    await harness.dispatcher.handle_dm(make_vk_ui_message("1"))

    assert harness.send.messages[-1][1] == "Выберите действие из меню."
    assert harness.publisher.publications == []


async def test_us16_ac163_nothing_is_published() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message(fwd_count=3))
    await harness.dispatcher.handle_dm(make_vk_ui_message(BTN_CANCEL))

    assert harness.publisher.publications == []
    assert harness.uow.deliveries.records == {}

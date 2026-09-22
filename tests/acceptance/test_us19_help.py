"""US-19: VK Help is reachable through plain text triggers, case-insensitively."""

from __future__ import annotations

from tests.acceptance._fakes import make_vk_ui_harness, make_vk_ui_message

HELP_TRIGGERS = ("Начать", "Помощь", "Помоги", "Help")
HELP_MARKER = "🤖 Как пользоваться ботом"


async def test_us19_every_trigger_opens_the_same_help() -> None:
    harness = make_vk_ui_harness()

    for trigger in HELP_TRIGGERS:
        await harness.dispatcher.handle_dm(make_vk_ui_message(trigger))
        assert harness.send.last_text.startswith(HELP_MARKER), trigger


async def test_us19_triggers_are_case_insensitive() -> None:
    harness = make_vk_ui_harness()

    for trigger in ("ПОМОЩЬ", "help", "ПоМоГи", "нАчАтЬ"):
        await harness.dispatcher.handle_dm(make_vk_ui_message(trigger))
        assert harness.send.last_text.startswith(HELP_MARKER), trigger


async def test_us19_help_button_opens_help_with_keyboard() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message("Помощь"))

    assert harness.send.last_text.startswith(HELP_MARKER)
    assert harness.send.last_keyboard is not None


async def test_us19_help_covers_manual_aliases_automatic_and_wall_forwarding() -> None:
    harness = make_vk_ui_harness()

    await harness.dispatcher.handle_dm(make_vk_ui_message("Помощь"))

    text = harness.send.last_text
    assert "одно сообщение" in text
    assert "ничего не писать" in text
    assert "новости" in text
    assert "@all" in text
    assert "хештег" in text
    assert "#извк" in text
    assert "#извкважно" in text
    assert "#изстенывк" in text
    assert "Стена VK" in text


async def test_us19_help_works_without_telegram_configuration() -> None:
    harness = make_vk_ui_harness(registered=False)
    harness.uow.telegram_topics.by_chat.clear()

    await harness.dispatcher.handle_dm(make_vk_ui_message("Помощь"))

    assert harness.send.last_text.startswith(HELP_MARKER)

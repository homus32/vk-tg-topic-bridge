"""US-17: topic aliases — add, change, delete, list.

Alias contract: unique per user, case-insensitive, no spaces, never a system word;
the current aliases are shown next to the topic list.
"""

from __future__ import annotations

from tests.acceptance._fakes import (
    MESSAGES_TOPIC_ID,
    VK_USER_ID,
    make_vk_message_event,
    make_vk_ui_harness,
    make_vk_ui_message,
)
from vk_topic_bridge.presentation.vk.keyboards import (
    BTN_ALIASES,
    BTN_DELETE,
    BTN_EDIT,
)

NEWS_TITLE = "Новости"


async def _open_alias_menu(harness: object) -> None:
    await harness.dispatcher.handle_dm(make_vk_ui_message(BTN_ALIASES))  # type: ignore[attr-defined]


async def _add_alias(harness: object, ordinal: str, alias: str) -> None:
    await _open_alias_menu(harness)
    await harness.dispatcher.handle_dm(make_vk_ui_message(BTN_EDIT))  # type: ignore[attr-defined]
    topic_id = MESSAGES_TOPIC_ID if ordinal == "2" else None
    await harness.dispatcher.handle_message_event(  # type: ignore[attr-defined]
        make_vk_message_event({"action": "topic", "topic_id": topic_id}, event_id="alias-topic")
    )
    await harness.dispatcher.handle_dm(make_vk_ui_message(alias))  # type: ignore[attr-defined]


async def test_us17_alias_menu_lists_topics_with_aliases() -> None:
    harness = make_vk_ui_harness()
    await _add_alias(harness, "2", "важное")

    await _open_alias_menu(harness)

    text = harness.send.last_text
    assert NEWS_TITLE in text
    assert "важное" in text


async def test_us17_add_alias_persists_per_user() -> None:
    harness = make_vk_ui_harness()

    await _add_alias(harness, "2", "важное")

    rows = harness.uow.vk_aliases.rows[VK_USER_ID]
    assert rows[MESSAGES_TOPIC_ID] == "важное"


async def test_us17_alias_is_case_insensitive_and_normalized() -> None:
    harness = make_vk_ui_harness()

    await _add_alias(harness, "2", "Важное")

    rows = harness.uow.vk_aliases.rows[VK_USER_ID]
    assert rows[MESSAGES_TOPIC_ID] == "важное"


async def test_us17_alias_with_space_is_rejected() -> None:
    harness = make_vk_ui_harness()

    await _add_alias(harness, "2", "два слова")

    assert harness.uow.vk_aliases.rows.get(VK_USER_ID, {}) == {}


async def test_us17_system_word_alias_is_rejected() -> None:
    harness = make_vk_ui_harness()

    await _add_alias(harness, "2", "помощь")

    assert harness.uow.vk_aliases.rows.get(VK_USER_ID, {}) == {}


async def test_us17_edit_alias_replaces_the_value() -> None:
    harness = make_vk_ui_harness()
    await _add_alias(harness, "2", "старое")

    await harness.dispatcher.handle_dm(make_vk_ui_message(BTN_EDIT))
    await harness.dispatcher.handle_message_event(
        make_vk_message_event(
            {"action": "topic", "topic_id": MESSAGES_TOPIC_ID}, event_id="edit-topic"
        )
    )
    await harness.dispatcher.handle_dm(make_vk_ui_message("новое"))

    assert harness.uow.vk_aliases.rows[VK_USER_ID][MESSAGES_TOPIC_ID] == "новое"


async def test_us17_delete_alias_removes_it_after_topic_number() -> None:
    harness = make_vk_ui_harness()
    await _add_alias(harness, "2", "важное")

    await harness.dispatcher.handle_dm(make_vk_ui_message(BTN_DELETE))
    await harness.dispatcher.handle_message_event(
        make_vk_message_event(
            {"action": "topic", "topic_id": MESSAGES_TOPIC_ID}, event_id="delete-topic"
        )
    )

    assert MESSAGES_TOPIC_ID not in harness.uow.vk_aliases.rows[VK_USER_ID]

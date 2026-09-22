from typing import Any

from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.presentation.telegram import filters as btn
from vk_topic_bridge.presentation.telegram.keyboards import (
    confirm_keyboard,
    destination_keyboard,
    owner_main_keyboard,
    topics_settings_keyboard,
)


def _buttons(markup: Any) -> list[Any]:
    return [button for row in markup.keyboard for button in row]


def test_main_keyboard_uses_native_styles_only_when_capability_is_enabled() -> None:
    state = BridgeSettingsState.defaults()

    disabled = _buttons(owner_main_keyboard(state))
    enabled = _buttons(owner_main_keyboard(state, styles_enabled=True))

    assert all(button.style is None for button in disabled)
    assert enabled[0].style == "danger"
    assert enabled[1].style == "danger"
    assert enabled[2].style == "danger"
    assert enabled[5].style == "primary"
    assert enabled[6].style == "danger"


def test_short_labels_preserve_text_handlers() -> None:
    state = BridgeSettingsState.defaults()
    labels = [button.text for button in _buttons(owner_main_keyboard(state))]

    assert btn.MENU_MESSAGES_DESTINATION in labels
    assert btn.MENU_WALL_DESTINATION in labels
    assert btn.MENU_TOPICS_SETTINGS in labels
    assert all(len(label.split()) <= 3 for label in labels)


def test_native_styles_cover_destination_refresh_and_confirmation_actions() -> None:
    destination = destination_keyboard(
        [(None, "General", True), (7, "Новости", True)],
        "messages",
        1,
        None,
        styles_enabled=True,
    )
    refresh = topics_settings_keyboard(styles_enabled=True)
    confirm = confirm_keyboard(styles_enabled=True)

    assert all(button.style == "success" for button in destination.inline_keyboard[0])
    assert _buttons(refresh)[0].style == "primary"
    assert _buttons(confirm)[0].style == "success"

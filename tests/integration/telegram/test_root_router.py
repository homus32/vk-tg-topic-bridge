"""Root router tests: /start priority, keyboard refresh from DB, /cancel, filters.

The router is driven through the real aiogram handler functions with a fake
``FSMContext``; no network or dispatcher session is involved.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import cast

from aiogram.types import Message, ReplyKeyboardMarkup, ReplyKeyboardRemove

from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.presentation.telegram import filters as btn
from vk_topic_bridge.presentation.telegram.filters import GroupChatFilter, PrivateChatFilter
from vk_topic_bridge.presentation.telegram.keyboards import (
    confirm_keyboard,
    owner_main_keyboard,
    unregistered_keyboard,
)
from vk_topic_bridge.presentation.telegram.registration_session import RegistrationCoordinator
from vk_topic_bridge.presentation.telegram.routers.root import (
    ONBOARDING_TEXT,
    build_root_router,
    render_root_state,
)

CHAT_ID = -1001234567890
CHAT_TITLE = "Тестовый чат"


class FakeFSMContext:
    """Records clear() calls; state is either set or None."""

    def __init__(self, state: str | None = None) -> None:
        self._state = state
        self.cleared = 0

    async def clear(self) -> None:
        self.cleared += 1
        self._state = None

    async def get_state(self) -> str | None:
        return self._state


@dataclass
class FakeMessage:
    chat_type: str = "private"
    user_id: int = 111
    answers: list[tuple[str, object | None]] = field(default_factory=list)
    text: str = ""

    @property
    def chat(self) -> object:
        return SimpleNamespace(id=CHAT_ID, type=self.chat_type)

    @property
    def from_user(self) -> object:
        return SimpleNamespace(id=self.user_id)

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append((text, kwargs.get("reply_markup")))


def _registered(**overrides: object) -> BridgeSettingsState:
    base = BridgeSettingsState(
        telegram_chat_id=CHAT_ID,
        telegram_chat_title=CHAT_TITLE,
        auto_forward_all=True,
        auto_forward_hashtags=True,
        auto_forward_wall=True,
        telegram_messages_topic_id=None,
        telegram_wall_topic_id=None,
    )
    return replace(base, **overrides)


async def _reader(state: BridgeSettingsState | None):
    return state


# --- /start ---------------------------------------------------------------------


async def test_start_unregistered_shows_onboarding_and_removes_keyboard() -> None:
    message = FakeMessage()

    await render_root_state(cast(Message, message), BridgeSettingsState.defaults())

    text, markup = message.answers[0]
    assert text == ONBOARDING_TEXT
    assert isinstance(markup, ReplyKeyboardRemove)


async def test_start_rerenders_keyboard_from_db() -> None:
    message = FakeMessage()
    state = _registered()

    await render_root_state(cast(Message, message), state)

    text, markup = message.answers[0]
    assert CHAT_TITLE in text
    assert isinstance(markup, ReplyKeyboardMarkup)
    labels = [button.text for row in markup.keyboard for button in row]
    assert btn.TOGGLE_ALL_DISABLE in labels
    assert btn.TOGGLE_HASHTAGS_DISABLE in labels
    assert btn.TOGGLE_WALL_DISABLE in labels
    assert btn.MENU_MESSAGES_DESTINATION in labels
    assert btn.MENU_WALL_DESTINATION in labels
    assert btn.MENU_TOPICS_SETTINGS in labels
    assert btn.MENU_DELIVERY_DIAGNOSTICS in labels
    assert btn.MENU_CHANGE_CHAT in labels


def test_toggle_labels_describe_action_relative_to_state() -> None:
    enabled = owner_main_keyboard(_registered())
    disabled = owner_main_keyboard(
        _registered(auto_forward_all=False, auto_forward_hashtags=False, auto_forward_wall=False)
    )

    enabled_labels = {button.text for row in enabled.keyboard for button in row}
    disabled_labels = {button.text for row in disabled.keyboard for button in row}

    assert btn.TOGGLE_ALL_DISABLE in enabled_labels
    assert btn.TOGGLE_ALL_ENABLE in disabled_labels
    assert btn.TOGGLE_HASHTAGS_DISABLE in enabled_labels
    assert btn.TOGGLE_HASHTAGS_ENABLE in disabled_labels
    assert btn.TOGGLE_WALL_DISABLE in enabled_labels
    assert btn.TOGGLE_WALL_ENABLE in disabled_labels
    assert enabled.is_persistent is True
    assert enabled.resize_keyboard is True


def test_unregistered_keyboard_removes_keyboard() -> None:
    assert isinstance(unregistered_keyboard(), ReplyKeyboardRemove)


def test_confirm_keyboard_has_yes_and_cancel_only() -> None:
    markup = confirm_keyboard()

    labels = [button.text for row in markup.keyboard for button in row]
    assert labels == [btn.BTN_YES, btn.BTN_CANCEL]


# --- /cancel ---------------------------------------------------------------------


async def test_cancel_clears_fsm_and_returns_root_state() -> None:
    router = build_root_router(lambda: _reader(_registered()))
    cancel_handler = next(
        handler for handler in router.message.handlers if handler.callback.__name__ == "cancel"
    )
    message = FakeMessage()
    fsm = FakeFSMContext(state="MessagesDestinationWizard:wait_ordinal")

    await cancel_handler.callback(cast(Message, message), fsm)

    assert fsm.cleared == 1
    text, markup = message.answers[0]
    assert "отменено" in text.lower()
    assert isinstance(markup, ReplyKeyboardMarkup)


async def test_cancel_without_registration_shows_onboarding() -> None:
    router = build_root_router(lambda: _reader(BridgeSettingsState.defaults()))
    cancel_handler = next(
        handler for handler in router.message.handlers if handler.callback.__name__ == "cancel"
    )
    message = FakeMessage()

    await cancel_handler.callback(cast(Message, message), FakeFSMContext())

    text, markup = message.answers[0]
    assert text == ONBOARDING_TEXT
    assert isinstance(markup, ReplyKeyboardRemove)


async def test_cancel_releases_registration_and_clears_group_scope() -> None:
    registration = RegistrationCoordinator()
    assert registration.acquire(111)
    registration.bind_group(CHAT_ID)

    class MenuSync:
        def __init__(self) -> None:
            self.cleared: list[tuple[int, int]] = []

        async def clear_registration_group(self, chat_id: int, owner_id: int) -> None:
            self.cleared.append((chat_id, owner_id))

    menu_sync = MenuSync()
    router = build_root_router(
        lambda: _reader(BridgeSettingsState.defaults()),
        registration=registration,
        menu_sync=menu_sync,
    )
    cancel_handler = next(
        handler for handler in router.message.handlers if handler.callback.__name__ == "cancel"
    )
    message = FakeMessage()

    await cancel_handler.callback(cast(Message, message), FakeFSMContext())

    assert menu_sync.cleared == [(CHAT_ID, 111)]
    assert registration.active_owner_id is None
    assert message.answers[0][0] == "Регистрация Telegram-чата отменена."


# --- filters ---------------------------------------------------------------------


def _chat_message(chat_type: str) -> Message:
    return cast(Message, SimpleNamespace(chat=SimpleNamespace(type=chat_type)))


async def test_private_filter_accepts_only_private() -> None:
    private = PrivateChatFilter()

    assert await private(_chat_message("private")) is True
    assert await private(_chat_message("supergroup")) is False


async def test_group_filter_accepts_groups_and_supergroups() -> None:
    group = GroupChatFilter()

    assert await group(_chat_message("group")) is True
    assert await group(_chat_message("supergroup")) is True
    assert await group(_chat_message("private")) is False

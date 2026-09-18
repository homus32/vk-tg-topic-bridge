"""US-20: toggle buttons describe the action and owners are notified.

AC-20.1 — an enabled feature offers to disable it.
AC-20.2 — a disabled feature offers to enable it.
AC-20.3 — /start sends the keyboard matching the current settings.
AC-20.4 — after a toggle change all owners receive a notification and the fresh keyboard.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field, replace
from types import SimpleNamespace
from typing import Any, cast

from aiogram import Bot
from aiogram.types import ReplyKeyboardMarkup

from vk_topic_bridge.application.dto.finish import DeliveryReviewEntry
from vk_topic_bridge.application.dto.settings import BridgeSettingsState, ToggleKind
from vk_topic_bridge.domain.value_objects import TopicInfo
from vk_topic_bridge.presentation.telegram import filters as btn
from vk_topic_bridge.presentation.telegram.keyboards import owner_main_keyboard
from vk_topic_bridge.presentation.telegram.routers.settings import build_settings_router

CHAT_ID = -1001234567890
CHAT_TITLE = "Тестовый чат"
OWNER_ID = 111
OTHER_OWNERS = (222, 333)


def _registered(**overrides: object) -> BridgeSettingsState:
    return replace(
        BridgeSettingsState.defaults(),
        telegram_chat_id=CHAT_ID,
        telegram_chat_title=CHAT_TITLE,
        **overrides,  # type: ignore[arg-type]
    )


@dataclass
class FakeMessage:
    text: str = ""
    user_id: int = OWNER_ID

    @property
    def from_user(self) -> object:
        return SimpleNamespace(id=self.user_id)

    async def answer(self, text: str, **kwargs: object) -> None:
        return None


class RecordingBot:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_message(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)


@dataclass
class FakeToggleUseCase:
    state: BridgeSettingsState
    calls: list[tuple[ToggleKind, bool]] = field(default_factory=list)

    async def execute(self, kind: ToggleKind, value: bool) -> BridgeSettingsState:
        self.calls.append((kind, value))
        field_name = {
            ToggleKind.ALL: "auto_forward_all",
            ToggleKind.HASHTAGS: "auto_forward_hashtags",
            ToggleKind.WALL: "auto_forward_wall",
        }[kind]
        self.state = replace(self.state, **{field_name: value})
        return self.state


class _Unused:
    async def refresh(self, chat_id: int) -> list[TopicInfo]:
        raise AssertionError("refresh is not used by this acceptance module")

    async def execute(self) -> object:
        raise AssertionError("reset is not used by this acceptance module")

    async def list_entries(self) -> list[DeliveryReviewEntry]:
        raise AssertionError("diagnostics are not used by this acceptance module")

    async def mark_reviewed(self, delivery_id: int) -> bool:
        raise AssertionError("diagnostics are not used by this acceptance module")


def _router(
    state: BridgeSettingsState,
) -> tuple[object, RecordingBot, FakeToggleUseCase]:
    async def settings_reader() -> BridgeSettingsState:
        return state

    async def topics_reader(chat_id: int) -> list[TopicInfo]:
        return []

    bot = RecordingBot()
    toggle = FakeToggleUseCase(state=state)
    unused = _Unused()
    router = build_settings_router(
        toggle_use_case=toggle,
        refresh_use_case=unused,
        reset_use_case=unused,
        diagnostics_reader=unused,
        settings_reader=settings_reader,
        topics_reader=topics_reader,
        bot=cast(Bot, bot),
        owner_ids=frozenset({OWNER_ID, *OTHER_OWNERS}),
    )
    return router, bot, toggle


def _handler(router: object, name: str) -> Callable[..., Coroutine[Any, Any, None]]:
    handlers = router.message.handlers  # type: ignore[attr-defined]
    for handler in handlers:
        if handler.callback.__name__ == name:
            return cast(Callable[..., Coroutine[Any, Any, None]], handler.callback)
    msg = f"handler {name!r} not found"
    raise AssertionError(msg)


def _labels(state: BridgeSettingsState) -> list[str]:
    keyboard = owner_main_keyboard(state)
    assert isinstance(keyboard, ReplyKeyboardMarkup)
    return [button.text for row in keyboard.keyboard for button in row]


async def test_us20_ac201_enabled_feature_offers_to_disable() -> None:
    labels = _labels(_registered(auto_forward_all=True))

    assert btn.TOGGLE_ALL_DISABLE in labels
    assert btn.TOGGLE_ALL_ENABLE not in labels


async def test_us20_ac202_disabled_feature_offers_to_enable() -> None:
    labels = _labels(_registered(auto_forward_all=False))

    assert btn.TOGGLE_ALL_ENABLE in labels
    assert btn.TOGGLE_ALL_DISABLE not in labels


async def test_us20_ac203_start_keyboard_matches_current_state() -> None:
    labels_on = _labels(_registered(auto_forward_wall=True))
    labels_off = _labels(_registered(auto_forward_wall=False))

    assert btn.TOGGLE_WALL_DISABLE in labels_on
    assert btn.TOGGLE_WALL_ENABLE in labels_off


async def test_us20_ac204_toggle_notifies_other_owners_with_fresh_keyboard() -> None:
    router, bot, toggle = _router(_registered())
    message = FakeMessage(text=btn.TOGGLE_ALL_DISABLE)

    await _handler(router, "toggle_all")(message)

    assert toggle.calls == [(ToggleKind.ALL, False)]
    recipients = sorted(int(kwargs["chat_id"]) for kwargs in bot.sent)
    assert recipients == sorted(OTHER_OWNERS)
    for kwargs in bot.sent:
        assert isinstance(kwargs["reply_markup"], ReplyKeyboardMarkup)

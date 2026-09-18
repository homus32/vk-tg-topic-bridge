"""Wiring-level regression tests over the real aiogram Dispatcher propagation.

These tests exist because unit-level handler invocation cannot catch wiring defects:
FSM strategy selection and router inclusion order only manifest through the dispatcher.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

from aiogram import Bot, Dispatcher
from aiogram.fsm.strategy import FSMStrategy
from aiogram.types import Chat, Message, Update, User

from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.bootstrap.container import _register_routers, build_dispatcher
from vk_topic_bridge.domain.value_objects import TopicInfo
from vk_topic_bridge.presentation.telegram import filters as btn

CHAT_ID = -1001234567890
OWNER_ID = 111


def _now() -> datetime:
    return datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


def _build_dispatcher() -> Dispatcher:
    dispatcher = build_dispatcher()

    async def settings_reader() -> BridgeSettingsState:
        return BridgeSettingsState(
            telegram_chat_id=CHAT_ID,
            telegram_chat_title="Тестовый чат",
            auto_forward_all=True,
            auto_forward_hashtags=True,
            auto_forward_wall=True,
            telegram_messages_topic_id=None,
            telegram_wall_topic_id=None,
        )

    async def topics_reader(_chat_id: int) -> list[TopicInfo]:
        return []

    class _Toggle:
        async def execute(self, kind: object, value: object) -> None:
            return None

    class _Refresh:
        async def refresh(self, chat_id: int) -> list[object]:
            return []

    class _Reset:
        async def execute(self) -> None:
            return None

    class _Diagnostics:
        async def list_entries(self) -> list[object]:
            return []

        async def mark_reviewed(self, delivery_id: int) -> bool:
            return False

    class _RegisterChat:
        async def execute(self, chat_id: int, title: str | None) -> object:
            raise AssertionError("not exercised in wiring tests")

    class _Selector:
        async def execute(self, *args: object) -> object:
            raise AssertionError("not exercised in wiring tests")

    class _Menu:
        async def apply_startup(self) -> None:
            return None

        async def apply_registration_group(self, chat_id: int, owner_id: int) -> None:
            return None

        async def clear_registration_group(self, chat_id: int, owner_id: int) -> None:
            return None

    settings = SimpleNamespace(OWNER_IDS=frozenset({OWNER_ID}))
    _register_routers(
        dispatcher,
        cast(Any, settings),
        cast(Any, _RegisterChat()),
        cast(Bot, _Bot()),
        settings_reader,
        topics_reader,
        cast(Any, _Toggle()),
        cast(Any, _Refresh()),
        cast(Any, _Reset()),
        cast(Any, _Diagnostics()),
        cast(Any, _Menu()),
        cast(Any, _Selector()),
    )
    return dispatcher


class _Bot:
    id: int = 999

    async def me(self) -> object:
        return SimpleNamespace(username="bridge_bot")

    async def send_message(self, **kwargs: object) -> None:
        return None


def _message_update(text: str, *, chat_type: str = "private") -> Update:
    message = Message(
        message_id=1,
        date=_now(),
        chat=Chat(id=CHAT_ID if chat_type != "private" else OWNER_ID, type=chat_type),
        from_user=User(id=OWNER_ID, is_bot=False, first_name="Owner"),
        text=text,
    )
    return Update(update_id=1, message=message)


def test_dispatcher_uses_global_user_fsm_strategy() -> None:
    """The registration master spans private /start and group /register: key must be user."""
    dispatcher = _build_dispatcher()

    assert dispatcher.fsm.strategy is FSMStrategy.GLOBAL_USER


def test_root_router_is_included_after_feature_routers() -> None:
    """The catch-all hint must never outrank feature button handlers."""
    dispatcher = _build_dispatcher()

    names = [router.name for router in dispatcher.sub_routers]
    assert names[-1] == "root", f"root must be last, got order: {names}"
    assert names.index("destinations") < names.index("root")
    assert names.index("settings") < names.index("root")


async def test_menu_button_text_reaches_feature_router_not_catch_all() -> None:
    """A menu button must be claimed by the settings/destinations router, not the hint."""
    dispatcher = _build_dispatcher()
    update = _message_update(btn.MENU_TOPICS_SETTINGS)

    responses = await _dispatch_message(dispatcher, update)

    assert responses, "menu button must be answered by a feature router"
    assert not any("Неизвестная команда" in text for text in responses)


async def _dispatch_message(dispatcher: Dispatcher, update: Update) -> list[str]:
    """Run one message update through real propagation with recorded answers."""
    bot = cast(_ResultBot, _ResultBot())
    real_bot = cast(Bot, bot)
    if update.message is not None:
        update.message.as_(real_bot)
        update.message.chat.as_(real_bot)
    await dispatcher.feed_update(real_bot, update)
    return bot.texts


class _ResultBot(_Bot):
    def __init__(self) -> None:
        self.texts: list[str] = []

    async def __call__(self, method: object, **kwargs: object) -> Message:
        text = getattr(method, "text", None)
        if isinstance(text, str):
            self.texts.append(text)
        return cast(Message, None)

"""US-21: replacing the Telegram chat requires confirmation and resets to factory state.

AC-21.1 — before unbinding, the chat asks for confirmation.
AC-21.2 — after confirmation all settings return to the factory state.
AC-21.3 — after the reset: all three auto-forwarding toggles are on, no chat is
registered, no destination topics are chosen and the old topic bindings are gone.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import replace
from typing import Any, cast

from aiogram import Bot

from tests.acceptance._fakes import (
    CHAT_ID,
    CHAT_TITLE,
    MESSAGES_TOPIC_ID,
    SAMPLE_TOPICS,
    FakeUnitOfWork,
)
from vk_topic_bridge.application.admin.destination_admin import ResetBridge
from vk_topic_bridge.application.dto.settings import BridgeSettingsState
from vk_topic_bridge.domain.value_objects import TopicInfo
from vk_topic_bridge.presentation.telegram import filters as btn
from vk_topic_bridge.presentation.telegram.routers.settings import (
    CHANGE_CHAT_PROMPT,
    build_settings_router,
)

OWNER_ID = 111
OTHER_OWNER = 222


def _configured_uow() -> FakeUnitOfWork:
    uow = FakeUnitOfWork()
    uow.bridge_settings.state = replace(
        BridgeSettingsState.defaults(),
        telegram_chat_id=CHAT_ID,
        telegram_chat_title=CHAT_TITLE,
        telegram_messages_topic_id=MESSAGES_TOPIC_ID,
        telegram_messages_topic_configured=True,
        telegram_wall_topic_configured=True,
    )
    uow.telegram_topics.by_chat[CHAT_ID] = list(SAMPLE_TOPICS)
    uow.vk_aliases.rows[555] = {MESSAGES_TOPIC_ID: "важное"}
    return uow


class FakeFSMContext:
    def __init__(self, state: str | None = None) -> None:
        self._state = state

    async def clear(self) -> None:
        self._state = None

    async def get_state(self) -> str | None:
        return self._state

    async def set_state(self, state: object) -> None:
        self._state = None if state is None else getattr(state, "state", str(state))


class FakeMessage:
    def __init__(self, text: str, user_id: int = OWNER_ID) -> None:
        self.text = text
        self.answers: list[tuple[str, object | None]] = []
        from types import SimpleNamespace

        self.from_user = SimpleNamespace(id=user_id)

    async def answer(self, text: str, **kwargs: object) -> None:
        self.answers.append((text, kwargs.get("reply_markup")))


class RecordingBot:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_message(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)


class _Unused:
    async def refresh(self, chat_id: int) -> list[object]:
        raise AssertionError("refresh is not used by this acceptance module")

    async def execute(self, kind: object, value: object) -> object:
        raise AssertionError("toggle is not used by this acceptance module")


def _build(uow: FakeUnitOfWork) -> tuple[object, FakeFSMContext]:
    async def settings_reader() -> BridgeSettingsState:
        return uow.bridge_settings.state

    async def topics_reader(chat_id: int) -> list[TopicInfo]:
        return uow.telegram_topics.by_chat.get(chat_id, [])

    router = build_settings_router(
        toggle_use_case=_Unused(),  # type: ignore[arg-type]
        refresh_use_case=_Unused(),  # type: ignore[arg-type]
        reset_use_case=ResetBridge(lambda: uow),
        diagnostics_reader=_Unused(),  # type: ignore[arg-type]
        settings_reader=settings_reader,
        topics_reader=topics_reader,  # type: ignore[arg-type]
        bot=cast(Bot, RecordingBot()),
        owner_ids=frozenset({OWNER_ID, OTHER_OWNER}),
    )
    return router, FakeFSMContext()


def _handler(router: object, name: str) -> Callable[..., Coroutine[Any, Any, None]]:
    handlers = router.message.handlers  # type: ignore[attr-defined]
    for handler in handlers:
        if handler.callback.__name__ == name:
            return cast(Callable[..., Coroutine[Any, Any, None]], handler.callback)
    msg = f"handler {name!r} not found"
    raise AssertionError(msg)


async def test_us21_ac211_change_chat_asks_for_confirmation_first() -> None:
    uow = _configured_uow()
    router, fsm = _build(uow)
    message = FakeMessage(btn.MENU_CHANGE_CHAT)

    await _handler(router, "change_chat")(message, fsm)

    assert message.answers[-1][0] == CHANGE_CHAT_PROMPT
    assert uow.bridge_settings.state.telegram_chat_id == CHAT_ID


async def test_us21_ac211_cancel_keeps_the_chat() -> None:
    uow = _configured_uow()
    router, fsm = _build(uow)

    await _handler(router, "change_chat")(FakeMessage(btn.MENU_CHANGE_CHAT), fsm)
    await _handler(router, "confirm_cancel")(FakeMessage(btn.BTN_CANCEL), fsm)

    assert uow.bridge_settings.state.telegram_chat_id == CHAT_ID


async def test_us21_ac212_confirmation_resets_to_factory_state() -> None:
    uow = _configured_uow()
    router, fsm = _build(uow)

    await _handler(router, "change_chat")(FakeMessage(btn.MENU_CHANGE_CHAT), fsm)
    await _handler(router, "confirm_yes")(FakeMessage(btn.BTN_YES), fsm)

    state = uow.bridge_settings.state
    assert state.telegram_chat_id is None
    assert state.telegram_messages_topic_id is None
    assert state.telegram_messages_topic_configured is False
    assert state.telegram_wall_topic_configured is False


async def test_us21_ac213_after_reset_toggles_are_on_and_bindings_are_gone() -> None:
    uow = _configured_uow()
    router, fsm = _build(uow)

    await _handler(router, "change_chat")(FakeMessage(btn.MENU_CHANGE_CHAT), fsm)
    await _handler(router, "confirm_yes")(FakeMessage(btn.BTN_YES), fsm)

    state = uow.bridge_settings.state
    assert state.auto_forward_all is True
    assert state.auto_forward_hashtags is True
    assert state.auto_forward_wall is True
    assert uow.telegram_topics.by_chat.get(CHAT_ID) is None
    assert uow.vk_aliases.rows == {}
